import Foundation
import RoviaApplePlatform
import RoviaConfig
import RoviaSubscription
import XCTest

private let coordinatorVLESS =
    "vless://00000000-0000-0000-0000-000000000001@synthetic.example:443?encryption=none&security=tls&type=tcp"
private let coordinatorTrojan = "trojan://Coordinator-Password-1@synthetic.example:443?security=tls"

private struct CoordinatorStubSession: SubscriptionHTTPSession {
    let handler: @Sendable (URLRequest) throws -> (Data, URLResponse)

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try handler(request)
    }
}

private func coordinatorHTTPResponse(url: URL, status: Int) -> HTTPURLResponse {
    HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: nil)!
}

private final class CoordinatorBodyBox: @unchecked Sendable {
    var body: String
    var fail: Bool
    var headers: [String: String]?

    init(body: String, fail: Bool = false, headers: [String: String]? = nil) {
        self.body = body
        self.fail = fail
        self.headers = headers
    }
}

@MainActor
final class SubscriptionCoordinatorTests: XCTestCase {
    private func makeCoordinator(
        handler: @escaping @Sendable (URLRequest) throws -> (Data, URLResponse),
        directory: URL? = nil
    ) -> (SubscriptionCoordinator, SubscriptionStore, InMemorySecretStore, URL) {
        let dir = directory ?? FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let store = SubscriptionStore(directory: dir)
        let secrets = InMemorySecretStore()
        let coordinator = SubscriptionCoordinator(
            store: store,
            secrets: secrets,
            session: CoordinatorStubSession(handler: handler)
        )
        return (coordinator, store, secrets, dir)
    }

    private func okHandler(body: String) -> @Sendable (URLRequest) throws -> (Data, URLResponse) {
        { request in
            (Data(body.utf8), coordinatorHTTPResponse(url: request.url!, status: 200))
        }
    }

    func testAddURLStoresServersAndSecrets() async throws {
        let (coordinator, _, secrets, _) = makeCoordinator(handler: okHandler(body: "\(coordinatorVLESS)\n\(coordinatorTrojan)\n"))
        try await coordinator.loadPersisted()
        let summary = try await coordinator.add(
            url: URL(string: "https://provider.example/sub")!,
            name: "Provider",
            allowInsecure: false
        )
        XCTAssertEqual(summary.accepted, 2)
        XCTAssertTrue(summary.rejected.isEmpty)
        let records = await coordinator.subscriptions()
        XCTAssertEqual(records.count, 1)
        XCTAssertEqual(records[0].name, "Provider")
        XCTAssertEqual(records[0].servers.count, 2)
        XCTAssertEqual(records[0].source.displayValue, "https://provider.example/••••••••")
        XCTAssertNotNil(try secrets.read(for: "subscription/\(records[0].id.uuidString.lowercased())/url"))
        let content = await coordinator.syncToContent()
        XCTAssertEqual(content.servers.count, 2)
        XCTAssertEqual(content.groups.count, 1)
        XCTAssertEqual(content.profiles.count, 1)
        XCTAssertFalse(content.isSampleData)
    }

    func testAddSingleLink() async throws {
        let (coordinator, _, _, _) = makeCoordinator(handler: okHandler(body: ""))
        try await coordinator.loadPersisted()
        let summary = try await coordinator.addSingleLink(coordinatorTrojan, name: "Single")
        XCTAssertEqual(summary.accepted, 1)
        let records = await coordinator.subscriptions()
        XCTAssertEqual(records[0].source.kind, .pastedText)
    }

    func testPartialImportStoresAcceptedWithCounts() async throws {
        let (coordinator, _, _, _) = makeCoordinator(handler: okHandler(
            body: "\(coordinatorVLESS)\nvmess://eyJhZGRyZXNzIjoieCJ9\nnot a link\n"
        ))
        try await coordinator.loadPersisted()
        let summary = try await coordinator.add(
            url: URL(string: "https://provider.example/sub")!,
            name: "Partial",
            allowInsecure: false
        )
        XCTAssertEqual(summary.accepted, 1)
        XCTAssertEqual(summary.rejected.count, 2)
        let records = await coordinator.subscriptions()
        XCTAssertEqual(records[0].servers.count, 1)
        XCTAssertEqual(records[0].acceptedCount, 1)
        XCTAssertEqual(records[0].rejectedCount, 2)
    }

    func testAddWithNothingAcceptedThrowsAndStoresEmpty() async throws {
        let (coordinator, _, _, _) = makeCoordinator(handler: okHandler(body: "vmess://eyJhZGRyZXNzIjoieCJ9\n"))
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(
                url: URL(string: "https://provider.example/sub")!,
                name: "Empty",
                allowInsecure: false
            )
            XCTFail("expected nothingAccepted")
        } catch let error as SubscriptionCoordinatorError {
            guard case let .nothingAccepted(accepted, rejected) = error else {
                XCTFail("wrong error \(error)")
                return
            }
            XCTAssertEqual(accepted, 0)
            XCTAssertEqual(rejected.count, 1)
        }
        let records = await coordinator.subscriptions()
        XCTAssertEqual(records.count, 1)
        XCTAssertTrue(records[0].servers.isEmpty)
    }

    func testRefreshFailureKeepsLastWorkingList() async throws {
        let box = CoordinatorBodyBox(body: coordinatorVLESS)
        let (coordinator, _, _, _) = makeCoordinator(handler: { request in
            if box.fail { throw URLError(.notConnectedToInternet) }
            return (Data(box.body.utf8), coordinatorHTTPResponse(url: request.url!, status: 200))
        })
        try await coordinator.loadPersisted()
        let added = try await coordinator.add(
            url: URL(string: "https://provider.example/sub")!,
            name: "Provider",
            allowInsecure: false
        )
        box.fail = true
        do {
            _ = try await coordinator.refresh(id: added.subscriptionID)
            XCTFail("expected fetchFailed")
        } catch let error as SubscriptionCoordinatorError {
            guard case .fetchFailed = error else {
                XCTFail("wrong error \(error)")
                return
            }
        }
        let records = await coordinator.subscriptions()
        XCTAssertEqual(records[0].servers.count, 1)
    }

    func testRefreshWithZeroAcceptedKeepsOldServers() async throws {
        let box = CoordinatorBodyBox(body: coordinatorVLESS)
        let (coordinator, _, _, _) = makeCoordinator(handler: { request in
            (Data(box.body.utf8), coordinatorHTTPResponse(url: request.url!, status: 200))
        })
        try await coordinator.loadPersisted()
        let added = try await coordinator.add(
            url: URL(string: "https://provider.example/sub")!,
            name: "Provider",
            allowInsecure: false
        )
        box.body = "vmess://eyJhZGRyZXNzIjoieCJ9"
        do {
            _ = try await coordinator.refresh(id: added.subscriptionID)
            XCTFail("expected nothingAccepted")
        } catch let error as SubscriptionCoordinatorError {
            guard case .nothingAccepted = error else {
                XCTFail("wrong error \(error)")
                return
            }
        }
        let records = await coordinator.subscriptions()
        XCTAssertEqual(records[0].servers.count, 1)
    }

    func testStableIDsSurviveRefreshReorder() async throws {
        let box = CoordinatorBodyBox(body: "\(coordinatorVLESS)\n\(coordinatorTrojan)")
        let (coordinator, _, _, _) = makeCoordinator(handler: { request in
            (Data(box.body.utf8), coordinatorHTTPResponse(url: request.url!, status: 200))
        })
        try await coordinator.loadPersisted()
        let added = try await coordinator.add(
            url: URL(string: "https://provider.example/sub")!,
            name: "Provider",
            allowInsecure: false
        )
        let before = await coordinator.subscriptions()
        let beforeIDs = Set(before[0].servers.map(\.id))
        box.body = "\(coordinatorTrojan)\n\(coordinatorVLESS)"
        let summary = try await coordinator.refresh(id: added.subscriptionID)
        XCTAssertEqual(summary.accepted, 2)
        let after = await coordinator.subscriptions()
        XCTAssertEqual(Set(after[0].servers.map(\.id)), beforeIDs)
    }

    func testHTTPBlockedUnlessAllowed() async throws {
        let (coordinator, _, _, _) = makeCoordinator(handler: okHandler(body: coordinatorVLESS))
        try await coordinator.loadPersisted()
        do {
            _ = try await coordinator.add(
                url: URL(string: "http://provider.example/sub")!,
                name: "Insecure",
                allowInsecure: false
            )
            XCTFail("expected insecureSchemeBlocked")
        } catch let error as SubscriptionCoordinatorError {
            guard case let .fetchFailed(.insecureSchemeBlocked) = error else {
                XCTFail("wrong error \(error)")
                return
            }
        }
        let summary = try await coordinator.add(
            url: URL(string: "http://provider.example/sub")!,
            name: "Insecure",
            allowInsecure: true
        )
        XCTAssertEqual(summary.accepted, 1)
    }

    func testRenameRemoveAndSecretCleanup() async throws {
        let (coordinator, _, secrets, _) = makeCoordinator(handler: okHandler(body: coordinatorVLESS))
        try await coordinator.loadPersisted()
        let added = try await coordinator.add(
            url: URL(string: "https://provider.example/sub")!,
            name: "Provider",
            allowInsecure: false
        )
        try await coordinator.rename(id: added.subscriptionID, name: "Renamed")
        let renamed = await coordinator.subscriptions()
        XCTAssertEqual(renamed[0].name, "Renamed")
        let urlKey = "subscription/\(added.subscriptionID.uuidString.lowercased())/url"
        let storedURL = try secrets.read(for: urlKey)
        XCTAssertNotNil(storedURL)
        try await coordinator.remove(id: added.subscriptionID)
        let remaining = await coordinator.subscriptions()
        XCTAssertTrue(remaining.isEmpty)
        XCTAssertNil(try secrets.read(for: urlKey))
    }

    func testLegacyFileWithoutAllowInsecureLoads() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let legacy = """
        [{"id":"\(UUID().uuidString)","name":"Legacy","source":{"kind":"url","displayValue":"https://provider.example/••••••••","secretReference":{"kind":"keychain","key":"subscription/legacy"}},"servers":[],"acceptedCount":0,"rejectedCount":0,"updatedAt":789000000}]
        """
        try Data(legacy.utf8).write(to: dir.appendingPathComponent("subscriptions.json"))
        let store = SubscriptionStore(directory: dir)
        try await store.load()
        let records = await store.subscriptions()
        XCTAssertEqual(records.count, 1)
        XCTAssertFalse(records[0].allowInsecure)
    }
}

final class DeepLinkTests: XCTestCase {
    func testImportLinkParsesURLAndName() {
        let link = URL(string: "rovia://import?url=https%3A%2F%2Fprovider.example%2Fsub&name=Provider")!
        let target = SubscriptionCoordinator.importTarget(from: link)
        XCTAssertEqual(target?.text, "https://provider.example/sub")
        XCTAssertEqual(target?.name, "Provider")
    }

    func testImportLinkAcceptsSingleShareLink() {
        let single = "vless://00000000-0000-0000-0000-000000000001@synthetic.example:443?encryption=none&security=tls&type=tcp"
        var components = URLComponents(string: "rovia://import")!
        components.queryItems = [URLQueryItem(name: "url", value: single)]
        let target = SubscriptionCoordinator.importTarget(from: components.url!)
        XCTAssertEqual(target?.text, single)
        XCTAssertNil(target?.name)
    }

    func testImportLinkAcceptsBase64Container() {
        let container = Data(coordinatorVLESS.utf8).base64EncodedString()
        var components = URLComponents(string: "rovia://import")!
        components.queryItems = [URLQueryItem(name: "url", value: container)]
        let target = SubscriptionCoordinator.importTarget(from: components.url!)
        XCTAssertEqual(target?.text, container)
    }

    func testNonImportLinksAreRejected() {
        XCTAssertNil(SubscriptionCoordinator.importTarget(from: URL(string: "rovia://other?url=https://x.example/")!))
        XCTAssertNil(SubscriptionCoordinator.importTarget(from: URL(string: "https://provider.example/sub")!))
        XCTAssertNil(SubscriptionCoordinator.importTarget(from: URL(string: "rovia://import")!))
        XCTAssertNil(SubscriptionCoordinator.importTarget(from: URL(string: "rovia://import?url=not%20a%20link")!))
    }
}
