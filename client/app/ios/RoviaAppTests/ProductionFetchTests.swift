import Foundation
import Network
import RoviaApplePlatform
import RoviaConfig
import RoviaSubscription
import XCTest

// MARK: - Local HTTP server

/// Minimal loopback HTTP server for production-composition fetch tests.
/// The whole-body stub path never sees sockets, so redirect chains,
/// lengthless bodies, stalls, and cancellation are exercised here against
/// `SubscriptionFetcher.production()` through a real coordinator.
private final class LocalHTTPServer: Sendable {
    struct Route: Sendable {
        var status: Int
        var headers: [String: String]
        var body: Data
        var omitContentLength: Bool
        var headerDelayNanoseconds: UInt64
        var bodyDelayNanoseconds: UInt64
    }

    private let listener: NWListener
    private let routes: [String: Route]

    init(routes: [String: Route]) throws {
        let listener = try NWListener(using: .tcp, on: 0)
        let box = RouteBox(routes: routes)
        self.routes = routes
        self.listener = listener
        listener.newConnectionHandler = { connection in
            connection.start(queue: .global())
            Self.serve(connection, routes: box)
        }
    }

    var port: Int { Int(listener.port?.rawValue ?? 0) }

    func start() async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            let flag = ReadyFlag()
            listener.stateUpdateHandler = { state in
                if case .ready = state, !flag.done {
                    flag.done = true
                    continuation.resume()
                }
            }
            listener.start(queue: .global())
        }
    }

    func stop() { listener.cancel() }

    func url(_ path: String) -> URL {
        URL(string: "http://127.0.0.1:\(port)\(path)")!
    }

    private static func serve(_ connection: NWConnection, routes: RouteBox) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { data, _, _, _ in
            guard let data,
                  let request = String(data: data, encoding: .utf8),
                  let path = request.split(separator: " ").dropFirst().first.map(String.init)
            else {
                connection.cancel()
                return
            }
            let clean = String(path.split(separator: "?").first ?? "?")
            guard let route = routes.routes[clean] else {
                send(connection, status: 404, headers: [:], body: Data("no route".utf8))
                return
            }
            Task {
                if route.headerDelayNanoseconds > 0 {
                    try? await Task.sleep(nanoseconds: route.headerDelayNanoseconds)
                }
                var headers = route.headers
                if !route.omitContentLength {
                    headers["Content-Length"] = "\(route.body.count)"
                }
                headers["Connection"] = "close"
                sendHeaders(connection, status: route.status, headers: headers) {
                    if route.bodyDelayNanoseconds > 0 {
                        Task {
                            try? await Task.sleep(nanoseconds: route.bodyDelayNanoseconds)
                            connection.send(content: route.body, completion: .contentProcessed { _ in connection.cancel() })
                        }
                    } else {
                        connection.send(content: route.body, completion: .contentProcessed { _ in connection.cancel() })
                    }
                }
            }
        }
    }

    private static func send(_ connection: NWConnection, status: Int, headers: [String: String], body: Data) {
        var all = headers
        all["Content-Length"] = "\(body.count)"
        all["Connection"] = "close"
        sendHeaders(connection, status: status, headers: all) {
            connection.send(content: body, completion: .contentProcessed { _ in connection.cancel() })
        }
    }

    private static func sendHeaders(
        _ connection: NWConnection, status: Int, headers: [String: String],
        done: @Sendable @escaping () -> Void
    ) {
        var text = "HTTP/1.1 \(status) \(status == 200 ? "OK" : status == 302 ? "Found" : "Status")\r\n"
        for (key, value) in headers.sorted(by: { $0.key < $1.key }) {
            text += "\(key): \(value)\r\n"
        }
        text += "\r\n"
        connection.send(content: Data(text.utf8), completion: .contentProcessed { _ in done() })
    }
}

private final class RouteBox: Sendable {
    let routes: [String: LocalHTTPServer.Route]
    init(routes: [String: LocalHTTPServer.Route]) { self.routes = routes }
}

private final class ReadyFlag: @unchecked Sendable {
    var done = false
}

// MARK: - Secret tracker

/// Wraps a real store and records every key ever saved, so tests can prove
/// a cancelled or failed import left no orphans behind.
private final class TrackingSecretStore: SecretStore, @unchecked Sendable {
    private let inner = InMemorySecretStore()
    private let lock = NSLock()
    private var savedKeys: [String] = []

    var everSaved: [String] {
        lock.lock()
        defer { lock.unlock() }
        return savedKeys
    }

    func save(_ value: Data, for key: String) throws {
        try inner.save(value, for: key)
        lock.lock()
        savedKeys.append(key)
        lock.unlock()
    }

    func read(for key: String) throws -> Data? {
        try inner.read(for: key)
    }

    func delete(for key: String) throws {
        try inner.delete(for: key)
    }

    func liveKeys() -> [String] {
        lock.lock()
        let keys = savedKeys
        lock.unlock()
        return keys.filter { (try? inner.read(for: $0)) != nil }
    }
}

/// Injects a mid-import save failure after a fixed number of successful
/// saves, so rollback tests don't depend on timing. The URL secret is the
/// first save of `add(url:)`; server secrets follow.
private struct InjectedSaveFailure: Error {}

private final class FailingSecretStore: SecretStore, @unchecked Sendable {
    private let wrapping: TrackingSecretStore
    private let lock = NSLock()
    private var saves = 0
    private let failAfterSaves: Int

    init(wrapping: TrackingSecretStore, failAfterSaves: Int) {
        self.wrapping = wrapping
        self.failAfterSaves = failAfterSaves
    }

    func save(_ value: Data, for key: String) throws {
        lock.lock()
        saves += 1
        let count = saves
        lock.unlock()
        if count > failAfterSaves {
            throw InjectedSaveFailure()
        }
        try wrapping.save(value, for: key)
    }

    func read(for key: String) throws -> Data? {
        try wrapping.read(for: key)
    }

    func delete(for key: String) throws {
        try wrapping.delete(for: key)
    }
}

// MARK: - Production composition tests

/// These tests run a real `SubscriptionCoordinator` with
/// `SubscriptionFetcher.production()`. The redirect-chain tests are the
/// tripwire for the old whole-body path: `URLSession.shared` follows the
/// chain to success, while the production delegate refuses past five hops
/// (or to a non-HTTP target) with `redirectBlocked`.
@MainActor
final class ProductionFetchTests: XCTestCase {
    private func makeProductionCoordinator(
        fetchPolicy: SubscriptionFetchPolicy = SubscriptionFetchPolicy(allowInsecureHTTP: true),
        secrets: TrackingSecretStore? = nil
    ) -> (SubscriptionCoordinator, SubscriptionStore, TrackingSecretStore, URL) {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = SubscriptionStore(directory: dir)
        let tracker = secrets ?? TrackingSecretStore()
        let coordinator = SubscriptionCoordinator(
            store: store,
            secrets: tracker,
            fetcher: SubscriptionFetcher.production(),
            fetchPolicy: fetchPolicy
        )
        return (coordinator, store, tracker, dir)
    }

    func testLongRedirectChainIsBlocked() async throws {
        var routes: [String: LocalHTTPServer.Route] = [:]
        for index in 0..<7 {
            routes["/r\(index)"] = .init(
                status: 302, headers: ["Location": "/r\(index + 1)"],
                body: Data(), omitContentLength: false,
                headerDelayNanoseconds: 0, bodyDelayNanoseconds: 0
            )
        }
        routes["/r7"] = .init(
            status: 200, headers: [:], body: Data("done".utf8),
            omitContentLength: false, headerDelayNanoseconds: 0, bodyDelayNanoseconds: 0
        )
        let server = try LocalHTTPServer(routes: routes)
        await server.start()
        defer { server.stop() }
        let (coordinator, _, _, _) = makeProductionCoordinator()
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(url: server.url("/r0"), name: "Chain", allowInsecure: true)
            XCTFail("expected redirectBlocked: the shared-session whole-body path would have followed this chain")
        } catch let error as SubscriptionCoordinatorError {
            XCTAssertEqual(error, .fetchFailed(.redirectBlocked))
        }
    }

    func testNonHTTPRedirectTargetIsBlocked() async throws {
        let server = try LocalHTTPServer(routes: [
            "/start": .init(
                status: 302, headers: ["Location": "ftp://127.0.0.1/x"],
                body: Data(), omitContentLength: false,
                headerDelayNanoseconds: 0, bodyDelayNanoseconds: 0
            ),
        ])
        await server.start()
        defer { server.stop() }
        let (coordinator, _, _, _) = makeProductionCoordinator()
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(url: server.url("/start"), name: "Odd", allowInsecure: true)
            XCTFail("expected redirectBlocked")
        } catch let error as SubscriptionCoordinatorError {
            XCTAssertEqual(error, .fetchFailed(.redirectBlocked))
        }
    }

    func testOversizedStreamWithoutLengthIsRejected() async throws {
        let server = try LocalHTTPServer(routes: [
            "/big": .init(
                status: 200, headers: [:], body: Data(repeating: 0x61, count: 4096),
                omitContentLength: true, headerDelayNanoseconds: 0, bodyDelayNanoseconds: 0
            ),
        ])
        await server.start()
        defer { server.stop() }
        // No Content-Length on the wire: the cap must come from counting
        // actual bytes, never from the header.
        let policy = SubscriptionFetchPolicy(allowInsecureHTTP: true, maximumBytes: 128)
        let (coordinator, _, _, _) = makeProductionCoordinator(fetchPolicy: policy)
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(url: server.url("/big"), name: "Big", allowInsecure: true)
            XCTFail("expected tooLarge")
        } catch let error as SubscriptionCoordinatorError {
            XCTAssertEqual(error, .fetchFailed(.tooLarge))
        }
    }

    func testStalledBodyTimesOut() async throws {
        let server = try LocalHTTPServer(routes: [
            "/stall": .init(
                status: 200, headers: [:], body: Data("late".utf8),
                omitContentLength: true, headerDelayNanoseconds: 0, bodyDelayNanoseconds: 5_000_000_000
            ),
        ])
        await server.start()
        defer { server.stop() }
        let policy = SubscriptionFetchPolicy(allowInsecureHTTP: true, timeout: 2)
        let (coordinator, _, _, _) = makeProductionCoordinator(fetchPolicy: policy)
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(url: server.url("/stall"), name: "Stall", allowInsecure: true)
            XCTFail("expected timedOut")
        } catch let error as SubscriptionCoordinatorError {
            XCTAssertEqual(error, .fetchFailed(.timedOut))
        }
    }

    func testCancelledProductionImportLeavesNothingBehind() async throws {
        let lines = (1...6000).map { index in
            "vless://00000000-0000-0000-0000-\(String(format: "%012X", index))@h\(index).example:443?encryption=none&security=tls&type=tcp"
        }.joined(separator: "\n")
        let server = try LocalHTTPServer(routes: [
            "/big": .init(
                status: 200, headers: [:], body: Data(lines.utf8),
                omitContentLength: true, headerDelayNanoseconds: 0, bodyDelayNanoseconds: 0
            ),
        ])
        await server.start()
        defer { server.stop() }
        let tracker = TrackingSecretStore()
        let (coordinator, store, _, _) = makeProductionCoordinator(secrets: tracker)
        try await coordinator.loadPersisted()
        // The URL secret is saved after a successful fetch but before the
        // chunked import below: cancelling mid-import must remove it with
        // everything else the import saved.
        let task = Task { try await coordinator.add(url: server.url("/big"), name: "Big", allowInsecure: true) }
        try? await Task.sleep(nanoseconds: 200_000_000)
        task.cancel()
        do {
            _ = try await task.value
        } catch is CancellationError {
            // Expected: the raw cancellation survives the transaction.
        } catch let error as SubscriptionCoordinatorError {
            if error != .fetchFailed(.cancelled) {
                throw error
            }
        }
        let cancelledRecords = await store.subscriptions()
        XCTAssertTrue(cancelledRecords.isEmpty)
        XCTAssertTrue(tracker.liveKeys().isEmpty)
    }
}

// MARK: - Import transaction tests (stub transport)

@MainActor
final class ImportTransactionTests: XCTestCase {
    private func goodLink(host index: Int) -> String {
        "vless://00000000-0000-0000-0000-\(String(format: "%012d", index))@h\(index).example:443?encryption=none&security=tls&type=tcp"
    }

    func testRejectedLinesCarryDocumentNumbers() async throws {
        // Garbage at document lines 1, 256, and 300: across the 256-line
        // chunk boundary. A chunk-relative index would report 1, 256, 44.
        var lines: [String] = []
        for index in 1...300 {
            if index == 1 || index == 256 || index == 300 {
                lines.append("not-a-share-link-\(index)")
            } else {
                lines.append(goodLink(host: index))
            }
        }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let coordinator = SubscriptionCoordinator(
            store: SubscriptionStore(directory: dir),
            secrets: InMemorySecretStore(),
            session: StubTextSession(text: lines.joined(separator: "\n"))
        )
        try await coordinator.loadPersisted()
        let summary = try await coordinator.addPastedText(lines.joined(separator: "\n"), name: "Numbered")
        XCTAssertEqual(summary.accepted, 297)
        XCTAssertEqual(summary.rejected.map(\.index), [1, 256, 300])
    }

    func testCancelledFirstImportDeletesURLSecret() async throws {
        // Immediate cancel of a 6k-link import: the fetch returns instantly
        // while the chunked import takes measurably longer, so the cancel
        // lands mid-import, after the subscription URL secret was saved.
        // The raw CancellationError must propagate (not wrapped), the store
        // must stay empty, and every saved key — URL included — deleted.
        let lines = (1...6000).map { goodLink(host: $0) }.joined(separator: "\n")
        let tracker = TrackingSecretStore()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let coordinator = SubscriptionCoordinator(
            store: SubscriptionStore(directory: dir),
            secrets: tracker,
            session: StubTextSession(text: lines)
        )
        try await coordinator.loadPersisted()
        let task = Task {
            try await coordinator.add(
                url: URL(string: "https://provider.example/sub")!, name: "Slow", allowInsecure: false
            )
        }
        task.cancel()
        do {
            _ = try await task.value
            // Extremely unlikely (6k-link import beat the cancel): nothing
            // to roll back, but the commit itself must then be complete.
            let committed = await coordinator.subscriptions()
            XCTAssertEqual(committed.count, 1)
            return
        } catch is CancellationError {
        } catch let error as SubscriptionCoordinatorError {
            if error != .fetchFailed(.cancelled) {
                throw error
            }
        }
        let store = SubscriptionStore(directory: dir)
        try await store.load()
        let freshRecords = await store.subscriptions()
        XCTAssertTrue(freshRecords.isEmpty)
        XCTAssertTrue(tracker.liveKeys().isEmpty)
    }

    func testMidImportFailureRollsBackURLAndServerSecrets() async throws {
        // Deterministic mid-import failure: the store throws on the 3rd
        // save (URL secret + 2 server secrets succeed first). The unified
        // transaction must remove all three; the store must stay empty.
        // No timing involved — the failure is injected, not raced.
        let lines = (1...600).map { goodLink(host: $0) }.joined(separator: "\n")
        let tracker = TrackingSecretStore()
        let failing = FailingSecretStore(wrapping: tracker, failAfterSaves: 3)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let coordinator = SubscriptionCoordinator(
            store: SubscriptionStore(directory: dir),
            secrets: failing,
            session: StubTextSession(text: lines)
        )
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(
                url: URL(string: "https://provider.example/sub")!, name: "Fragile", allowInsecure: false
            )
            XCTFail("expected the injected save failure to abort the import")
        } catch is CancellationError {
            XCTFail("a save failure must not surface as cancellation")
        } catch {
            // Any non-cancellation error: the rollback is what matters.
        }
        XCTAssertEqual(tracker.everSaved.count, 3)
        let store = SubscriptionStore(directory: dir)
        try await store.load()
        let freshRecords = await store.subscriptions()
        XCTAssertTrue(freshRecords.isEmpty)
        XCTAssertTrue(tracker.liveKeys().isEmpty)
    }

    func testRefreshRemapsRotatedIDsAndStampsSchema() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let secrets = InMemorySecretStore()
        let seeding = SubscriptionStore(directory: dir)
        try await seeding.load()
        // A v1-style record: same endpoint as the fixture link below, but a
        // random server UUID (as if hashed from the raw, uncanonicalized line).
        let legacyServerID = UUID()
        let record = StoredSubscription(
            name: "Legacy",
            source: SubscriptionSource(
                kind: .url,
                displayValue: "https://provider.example/sub?token=t",
                secretReference: SecretReference(key: "subscription/legacy-url")
            ),
            servers: [Server(
                id: legacyServerID,
                name: "VLESS server",
                protocolKind: .vless,
                endpoint: Endpoint(host: "synthetic.example", port: 443),
                credential: SecretReference(key: "subscription/legacy-cred"),
                transport: TransportOptions(kind: "tcp"),
                tls: TLSOptions(serverName: "synthetic.example"),
                tags: []
            )],
            acceptedCount: 1,
            rejectedCount: 0,
            updatedAt: Date(timeIntervalSince1970: 1_700_000_000),
            schemaVersion: 1
        )
        try await seeding.upsert(record)
        try secrets.save(Data("https://provider.example/sub".utf8), for: "subscription/\(record.id.uuidString.lowercased())/url")
        let link = "vless://00000000-0000-0000-0000-000000000001@synthetic.example:443?encryption=none&security=tls&type=tcp"
        let coordinator = SubscriptionCoordinator(
            store: SubscriptionStore(directory: dir),
            secrets: secrets,
            session: StubTextSession(text: link)
        )
        try await coordinator.loadPersisted()
        let oldSummaryID = SubscriptionCoordinator.summaryID(subscriptionID: record.id, serverID: legacyServerID)
        // Select and favorite under the legacy ID, then refresh.
        let model = AppModel(
            tunnel: StubTunnelController(),
            fixtures: CountingFixtureProvider(content: .empty),
            subscriptions: coordinator
        )
        _ = await model.bootstrap()
        let selected = await model.selectServer(oldSummaryID)
        XCTAssertTrue(selected)
        let favorited = await model.toggleFavorite(oldSummaryID)
        XCTAssertTrue(favorited)
        let refreshed = await model.refreshSubscription(record.id)
        XCTAssertTrue(refreshed)
        let snapshot = model.snapshot
        XCTAssertEqual(snapshot.content.servers.count, 1)
        let newID = snapshot.content.servers[0].id
        XCTAssertNotEqual(newID, oldSummaryID)
        XCTAssertEqual(snapshot.selection.server, newID)
        XCTAssertTrue(model.isFavorite(newID))
        XCTAssertFalse(model.isFavorite(oldSummaryID))
        let stored = await coordinator.subscriptions()
        XCTAssertEqual(stored.first?.schemaVersion, StoredSubscription.currentSchemaVersion)
    }
}

private struct StubTextSession: SubscriptionHTTPSession {
    let text: String
    let delayNanoseconds: UInt64 = 0

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        if delayNanoseconds > 0 {
            try await Task.sleep(nanoseconds: delayNanoseconds)
        }
        guard let url = request.url else { throw URLError(.badURL) }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
        return (Data(text.utf8), response)
    }
}
