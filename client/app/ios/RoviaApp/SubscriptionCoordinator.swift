import Foundation
import RoviaApplePlatform
import RoviaConfig
import RoviaSubscription

enum SubscriptionCoordinatorError: Error, Equatable {
    case fetchFailed(SubscriptionFetchError)
    case decodeFailed(SubscriptionDocumentError)
    case nothingAccepted(accepted: Int, rejected: [RejectedSubscriptionLine])
    case unknownSubscription
    case secretUnavailable
    case persistenceFailed
    case invalidInput
}

/// The result of one add/refresh, for honest UI counts.
struct SubscriptionImportSummary: Equatable, Sendable {
    let subscriptionID: UUID
    let accepted: Int
    let rejected: [RejectedSubscriptionLine]
    /// v1→v2 migration map: stored server IDs that changed identity across
    /// this import, matched unambiguously by (protocol, host, port).
    /// Empty for first imports and for refreshes with nothing to remap.
    /// The caller applies it to the selection and favorites; without this,
    /// an ID rotation would silently drop both.
    let remappedServerIDs: [UUID: UUID]

    init(
        subscriptionID: UUID,
        accepted: Int,
        rejected: [RejectedSubscriptionLine],
        remappedServerIDs: [UUID: UUID] = [:]
    ) {
        self.subscriptionID = subscriptionID
        self.accepted = accepted
        self.rejected = rejected
        self.remappedServerIDs = remappedServerIDs
    }
}

/// Fetch transport, chosen explicitly at composition — never inferred from
/// the dependency's type. Production passes the streaming fetcher (byte cap
/// during the read, hop-by-hop redirect control); tests pass a stub.
/// A coordinator built with the wrong transport fetches with the wrong
/// guarantees, so there is no default that could silently pick one.
///
/// The second parameter is named `fetchPolicy` on purpose: `SubscriptionFetcher`
/// also has a `fetch(_:policy:)` overload, and `policy:` inside the conformance
/// would recurse into itself forever. The label disambiguates.
protocol SubscriptionFetchClient: Sendable {
    func fetch(_ url: URL, fetchPolicy: SubscriptionFetchPolicy) async throws -> SubscriptionFetchResult
}

extension SubscriptionFetcher: SubscriptionFetchClient {
    func fetch(_ url: URL, fetchPolicy: SubscriptionFetchPolicy) async throws -> SubscriptionFetchResult {
        try await fetch(url, policy: fetchPolicy)
    }
}

/// Whole-body stub transport for tests. Production must never use this:
/// it loads the entire body before checking the size cap and follows
/// redirects with the shared session's defaults.
struct StubFetchClient: SubscriptionFetchClient {
    let session: any SubscriptionHTTPSession

    func fetch(_ url: URL, fetchPolicy: SubscriptionFetchPolicy) async throws -> SubscriptionFetchResult {
        try await SubscriptionFetcher(session: session, policy: fetchPolicy).fetch(url)
    }
}

private enum SecretKeys {
    static func subscriptionURL(_ id: UUID) -> String {
        "subscription/\(id.uuidString.lowercased())/url"
    }

    /// Opaque per-server key. The server UUID is stable (canonical import
    /// ID), so the same server reuses one entry across refreshes, and the
    /// record owns its keys explicitly: refresh replaces the list, remove
    /// deletes it, a failed import deletes what it saved.
    static func serverCredential(subscriptionID: UUID, serverID: UUID) -> String {
        "subscription/\(subscriptionID.uuidString.lowercased())/server/\(serverID.uuidString.lowercased())"
    }
}

/// Keychain keys saved during one import, for rollback on failure.
/// Unchecked because the compiler cannot see the lock; every access below
/// holds it, and the array never escapes except as a copy.
private final class SavedKeys: @unchecked Sendable {
    private let lock = NSLock()
    private var keys: [String] = []

    func append(_ key: String) {
        lock.lock()
        defer { lock.unlock() }
        keys.append(key)
    }

    func snapshot() -> [String] {
        lock.lock()
        defer { lock.unlock() }
        return keys
    }
}

/// First credential-sink failure of an import. The parser maps a sink
/// throw to the per-line rejection `.credentialSinkFailed` and keeps
/// going; the coordinator's transaction is all-or-nothing, so the real
/// error is captured here and rethrown to abort the import.
private final class SinkFailure: @unchecked Sendable {
    private let lock = NSLock()
    private var first: Error?

    func record(_ error: Error) {
        lock.lock()
        if first == nil { first = error }
        lock.unlock()
    }

    var error: Error? {
        lock.lock()
        defer { lock.unlock() }
        return first
    }
}

/// Owns the subscription lifecycle for the app: fetch → decode → import →
/// persist, and projects stored subscriptions into `AppContent`.
///
/// Secrets live in the `SecretStore` (Keychain in production); the file
/// store holds redacted metadata and the last working server lists only.
/// Refresh never overwrites on failure — a failed download, an undecodable
/// body, or an import with zero accepted servers throws before the record
/// is touched.
@MainActor
final class SubscriptionCoordinator {
    private let store: SubscriptionStore
    private let secrets: any SecretStore
    private let fetcher: any SubscriptionFetchClient
    private let fetchPolicy: SubscriptionFetchPolicy
    private var refreshing: Set<UUID> = []

    init(
        store: SubscriptionStore,
        secrets: any SecretStore,
        fetcher: any SubscriptionFetchClient,
        fetchPolicy: SubscriptionFetchPolicy = SubscriptionFetchPolicy()
    ) {
        self.store = store
        self.secrets = secrets
        self.fetcher = fetcher
        self.fetchPolicy = fetchPolicy
    }

    /// Test composition: whole-body stub session. Production must use
    /// `init(store:secrets:fetcher:)` with `SubscriptionFetcher.production()`.
    init(
        store: SubscriptionStore,
        secrets: any SecretStore,
        session: any SubscriptionHTTPSession,
        fetchPolicy: SubscriptionFetchPolicy = SubscriptionFetchPolicy()
    ) {
        self.store = store
        self.secrets = secrets
        self.fetcher = StubFetchClient(session: session)
        self.fetchPolicy = fetchPolicy
    }

    var isRefreshing: Set<UUID> { refreshing }

    func loadPersisted() async throws {
        do {
            try await store.load()
        } catch {
            throw SubscriptionCoordinatorError.persistenceFailed
        }
    }

    func subscriptions() async -> [StoredSubscription] {
        await store.subscriptions()
    }

    func add(url: URL, name: String, allowInsecure: Bool) async throws -> SubscriptionImportSummary {
        let id = UUID()
        let downloaded = try await fetch(url: url, allowInsecure: allowInsecure)
        let document = try await background { try Self.decode(downloaded.data) }
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty else { throw SubscriptionCoordinatorError.invalidInput }
        try secrets.save(Data(url.absoluteString.utf8), for: SecretKeys.subscriptionURL(id))
        let record = StoredSubscription(
            id: id,
            name: trimmedName,
            source: SubscriptionSource(
                kind: .url,
                displayValue: url.absoluteString,
                secretReference: SecretReference(key: SecretKeys.subscriptionURL(id))
            ),
            allowInsecure: allowInsecure,
            userInfo: downloaded.userInfo
        )
        return try await importAndStore(lines: document.lines, record: record, isFirstImport: true)
    }

    func addSingleLink(_ line: String, name: String) async throws -> SubscriptionImportSummary {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard SubscriptionInputClassifier.classify(trimmed) != nil else {
            throw SubscriptionCoordinatorError.invalidInput
        }
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty else { throw SubscriptionCoordinatorError.invalidInput }
        let record = StoredSubscription(
            id: UUID(),
            name: trimmedName,
            source: SubscriptionSource(kind: .pastedText, displayValue: "pasted text")
        )
        return try await importAndStore(lines: [trimmed], record: record, isFirstImport: true)
    }

    func addPastedText(_ text: String, name: String) async throws -> SubscriptionImportSummary {
        guard let data = text.data(using: .utf8) else {
            throw SubscriptionCoordinatorError.decodeFailed(.invalidUTF8)
        }
        let document = try await background { try Self.decode(data) }
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty else { throw SubscriptionCoordinatorError.invalidInput }
        let record = StoredSubscription(
            id: UUID(),
            name: trimmedName,
            source: SubscriptionSource(kind: .pastedText, displayValue: "pasted text")
        )
        return try await importAndStore(lines: document.lines, record: record, isFirstImport: true)
    }

    func refresh(id: UUID) async throws -> SubscriptionImportSummary {
        guard refreshing.insert(id).inserted else { return try await currentSummary(id: id) }
        defer { refreshing.remove(id) }
        let records = await store.subscriptions()
        guard let record = records.first(where: { $0.id == id }) else {
            throw SubscriptionCoordinatorError.unknownSubscription
        }
        guard record.source.kind == .url else {
            // Pasted/single-link subscriptions have no URL to re-fetch.
            // Re-import is a no-op that reports current counts.
            return try await currentSummary(id: id)
        }
        guard let urlData = try secrets.read(for: SecretKeys.subscriptionURL(id)),
              let urlString = String(data: urlData, encoding: .utf8),
              let url = URL(string: urlString)
        else {
            throw SubscriptionCoordinatorError.secretUnavailable
        }
        let raw = try await fetch(url: url, allowInsecure: record.allowInsecure)
        let document = try await background { try Self.decode(raw.data) }
        var refreshRecord = record
        refreshRecord.userInfo = raw.userInfo
        return try await importAndStore(lines: document.lines, record: refreshRecord, isFirstImport: false)
    }

    func rename(id: UUID, name: String) async throws {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw SubscriptionCoordinatorError.invalidInput }
        do {
            try await store.rename(id: id, name: trimmed)
        } catch SubscriptionStoreError.unknownSubscription {
            throw SubscriptionCoordinatorError.unknownSubscription
        } catch {
            throw SubscriptionCoordinatorError.persistenceFailed
        }
    }

    func remove(id: UUID) async throws {
        let records = await store.subscriptions()
        guard let record = records.first(where: { $0.id == id }) else {
            throw SubscriptionCoordinatorError.unknownSubscription
        }
        do {
            try await store.remove(id: id)
        } catch {
            throw SubscriptionCoordinatorError.persistenceFailed
        }
        // Best-effort secret cleanup; the record is already gone.
        try? secrets.delete(for: SecretKeys.subscriptionURL(id))
        for server in record.servers {
            if let credential = server.credential {
                try? secrets.delete(for: credential.key)
            }
        }
    }

    /// Summary identity: `subscriptionUUID/serverUUID`, both lowercased.
    /// Stable across refreshes (both sides are stable), unique across
    /// subscriptions, opaque to every consumer below this file.
    static func summaryID(subscriptionID: UUID, serverID: UUID) -> String {
        "\(subscriptionID.uuidString.lowercased())/\(serverID.uuidString.lowercased())"
    }

    /// Non-secret endpoints for latency probing, keyed by the summary ID
    /// (`ServerSummary.id`). Hosts and ports are not secrets — the redacted
    /// display values already carry the port — but credentials never leave
    /// the Keychain through here.
    func endpoints() async -> [String: (host: String, port: Int)] {
        var result: [String: (host: String, port: Int)] = [:]
        for record in await store.subscriptions() {
            for server in record.servers {
                result[Self.summaryID(subscriptionID: record.id, serverID: server.id)] = (
                    server.endpoint.host, server.endpoint.port
                )
            }
        }
        return result
    }

    /// The canonical server behind a summary ID, for the tunnel hand-off.
    /// The returned model still holds a `SecretReference`, not a credential.
    func canonicalServer(summaryID: ServerID) async -> Server? {
        for record in await store.subscriptions() {
            for server in record.servers
            where Self.summaryID(subscriptionID: record.id, serverID: server.id) == summaryID {
                return server
            }
        }
        return nil
    }

    /// Parses an inbound `rovia://import?url=<subscription-url>&name=<optional>`
    /// deep link. Returns the raw text and display name — the caller runs it
    /// through the usual classifier, so subscription URLs, single share
    /// links, and multi-line/base64 containers all take their normal path.
    /// A single garbage line is rejected here (freeform paste belongs to the
    /// in-app paste UI, not to a link another app can fire); anything the
    /// import itself refuses later still fails loudly with reasons.
    nonisolated static func importTarget(from deepLink: URL) -> (text: String, name: String?)? {
        guard deepLink.scheme?.lowercased() == "rovia",
              deepLink.host?.lowercased() == "import",
              let components = URLComponents(url: deepLink, resolvingAgainstBaseURL: false),
              let encoded = components.queryItems?.first(where: { $0.name == "url" })?.value
        else {
            return nil
        }
        // URLComponents already percent-decoded the parameter once.
        let trimmed = encoded.trimmingCharacters(in: .whitespacesAndNewlines)
        switch SubscriptionInputClassifier.classify(trimmed) {
        case .subscriptionURL, .singleShareLink:
            break
        case .pastedText:
            // Containers travel by deep link too — but only containers, not
            // one meaningless line.
            guard let data = trimmed.data(using: .utf8),
                  let document = try? SubscriptionDocumentDecoder.decode(data),
                  document.lines.count > 1 || document.wasBase64
            else {
                return nil
            }
        case .none:
            return nil
        }
        let name = components.queryItems?.first(where: { $0.name == "name" })?.value?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return (trimmed, name?.isEmpty == true ? nil : name)
    }

    /// Projects every stored subscription into content the existing
    /// selection, group, and routing UI already understands: one profile
    /// and one group per subscription, servers with stable IDs.
    func syncToContent() async -> AppContent {
        let records = await store.subscriptions()
        var content = AppContent()
        content.isSampleData = false
        for record in records {
            let groupID = "sub/\(record.id.uuidString.lowercased())"
            // Namespaced summary IDs: the same link in two subscriptions is
            // two different servers with two different credential owners.
            // Sharing the canonical UUID here would merge them — and merging
            // would silently attribute one subscription's credentials to the
            // other — so the summary ID carries both sides.
            let serverIDs = record.servers.map {
                Self.summaryID(subscriptionID: record.id, serverID: $0.id)
            }
            content.profiles.append(ProfileSummary(
                id: groupID,
                name: record.name,
                sourceKindLabel: "Subscription",
                serverIDs: serverIDs
            ))
            content.servers.append(contentsOf: record.servers.map {
                serverSummary($0, groupID: groupID, summaryID: Self.summaryID(subscriptionID: record.id, serverID: $0.id))
            })
            content.groups.append(ServerGroupSummary(
                id: groupID,
                name: record.name,
                modeLabel: "Manual",
                policyLabel: "Manual selection",
                memberIDs: serverIDs
            ))
        }
        if let first = records.first {
            let groupID = "sub/\(first.id.uuidString.lowercased())"
            content.defaultProfileID = groupID
            content.defaultGroupID = groupID
        }
        content.subscription = aggregatedSummary(records: records)
        return content
    }

    // MARK: - Private

    private func fetch(url: URL, allowInsecure: Bool) async throws -> SubscriptionFetchResult {
        var policy = fetchPolicy
        policy.allowInsecureHTTP = allowInsecure
        do {
            return try await fetcher.fetch(url, fetchPolicy: policy)
        } catch let error as SubscriptionFetchError {
            throw SubscriptionCoordinatorError.fetchFailed(error)
        } catch is CancellationError {
            throw SubscriptionCoordinatorError.fetchFailed(.cancelled)
        } catch {
            throw SubscriptionCoordinatorError.fetchFailed(.networkError)
        }
    }

    private nonisolated static func decode(_ data: Data) throws -> SubscriptionDocument {
        do {
            return try SubscriptionDocumentDecoder.decode(data)
        } catch let error as SubscriptionDocumentError {
            throw SubscriptionCoordinatorError.decodeFailed(error)
        } catch {
            throw SubscriptionCoordinatorError.decodeFailed(.invalidBase64)
        }
    }

    /// Runs work off the MainActor with parent cancellation propagated: a
    /// detached task alone would keep importing (and storing) after the
    /// caller gave up. The work closure must capture only `Sendable` values.
    private func background<T: Sendable>(_ work: @Sendable @escaping () throws -> T) async throws -> T {
        let task = Task.detached(priority: .userInitiated, operation: work)
        return try await withTaskCancellationHandler {
            try await task.value
        } onCancel: {
            task.cancel()
        }
    }

    /// Deletes every key saved during a failed import except those still
    /// referenced by stored servers — a surviving entry is never collateral
    /// damage of another record's failure.
    private func rollbackSecrets(_ saved: SavedKeys) async {
        let savedKeys = Set(saved.snapshot())
        guard !savedKeys.isEmpty else { return }
        var referenced: Set<String> = []
        for record in await store.subscriptions() {
            if let urlKey = record.source.secretReference?.key {
                referenced.insert(urlKey)
            }
            for server in record.servers {
                if let key = server.credential?.key {
                    referenced.insert(key)
                }
            }
        }
        for key in savedKeys.subtracting(referenced) {
            try? secrets.delete(for: key)
        }
    }

    private func importAndStore(
        lines: [String],
        record: StoredSubscription,
        isFirstImport: Bool
    ) async throws -> SubscriptionImportSummary {
        // Document line numbers travel with the text through trimming, dedup,
        // and chunking: a rejection in document line 300 must not surface as
        // line 44 of some chunk. Numbers are 1-based document lines.
        var seen: Set<String> = []
        var unique: [(number: Int, line: String)] = []
        unique.reserveCapacity(lines.count)
        for (offset, rawLine) in lines.enumerated() {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            guard !line.isEmpty else { continue }
            if seen.insert(SubscriptionImporter.canonicalLine(line)).inserted {
                unique.append((offset + 1, line))
            }
        }
        let saved = SavedKeys()
        // The subscription URL secret (saved by add/refresh before this
        // runs) belongs to the same transaction as the server secrets:
        // a cancelled import or an injected save failure must roll it
        // back too, or it leaks into the Keychain. rollbackSecrets
        // skips keys still referenced by stored records, so a stored
        // record's URL key is never collateral.
        if case .url = record.source.kind, let urlKey = record.source.secretReference?.key {
            saved.append(urlKey)
        }
        var accepted: [ParsedShareLink] = []
        var rejected: [RejectedSubscriptionLine] = []
        // One transaction for the whole import. Every throw below — a sink
        // failure mid-chunk, cancellation at any checkpoint including the
        // final one, or a store failure — rolls back everything this import
        // saved. `stored` flips only after a record reaches the store; the
        // subscription URL key (saved by the caller before this runs) is
        // removed with the rest when nothing was stored. Cancellation is
        // rethrown as-is so callers can tell it apart from real failures.
        var stored = false
        do {
            // Cancellation checkpoints around every stage: a cancelled
            // import stops within one chunk and never reaches the store,
            // even if the last chunk finished in the same instant. This is
            // inside the transaction so its throw also rolls back the URL
            // key the caller saved before we were called.
            try Task.checkCancellation()
            for chunk in unique.chunked(into: 256) {
                try Task.checkCancellation()
                // The sink is built inside the detached closure from Sendable
                // captures only (secret store, subscription id, key tracker), so
                // no unchecked boundary is needed to cross threads here.
                let texts = chunk.map(\.line)
                let sinkFailure = SinkFailure()
                let chunkResult = try await background { [secrets] in
                    SubscriptionImporter.importLines(texts) { serverID, secret in
                        let key = SecretKeys.serverCredential(subscriptionID: record.id, serverID: serverID)
                        do {
                            try secrets.save(secret, for: key)
                        } catch {
                            sinkFailure.record(error)
                            throw error
                        }
                        saved.append(key)
                        return SecretReference(key: key)
                    }
                }
                // A failed secret save must abort the whole import, not
                // report one more rejected line — atomicity is promised by
                // the transaction around this loop.
                if let failure = sinkFailure.error {
                    throw failure
                }
                accepted.append(contentsOf: chunkResult.accepted)
                for entry in chunkResult.rejected {
                    // importLines numbers rejections 1-based within its
                    // input: translate back to the document line that
                    // produced this chunk element.
                    guard entry.index >= 1, entry.index <= chunk.count else { continue }
                    rejected.append(RejectedSubscriptionLine(
                        index: chunk[entry.index - 1].number,
                        reason: entry.reason
                    ))
                }
            }
            guard !accepted.isEmpty else {
                if isFirstImport {
                    var empty = record
                    empty.servers = []
                    empty.acceptedCount = 0
                    empty.rejectedCount = rejected.count
                    empty.updatedAt = Date()
                    empty.schemaVersion = StoredSubscription.currentSchemaVersion
                    try? await store.upsert(empty)
                    stored = true
                }
                throw SubscriptionCoordinatorError.nothingAccepted(
                    accepted: 0,
                    rejected: rejected
                )
            }
            try Task.checkCancellation()
            var updated = record
            updated.servers = accepted.map(\.server)
            updated.acceptedCount = accepted.count
            updated.rejectedCount = rejected.count
            updated.updatedAt = Date()
            updated.schemaVersion = StoredSubscription.currentSchemaVersion
            // v1→v2 migration map: a refresh regenerates IDs from canonical
            // lines, so a server whose ID rotated (remark added, query
            // reordered) is matched to its stored predecessor by
            // (protocol, host, port). Only unambiguous 1:1 matches remap;
            // anything ambiguous keeps working under its new ID without
            // stealing another server's selection or favorite.
            let remapped = isFirstImport ? [:] : Self.remapServerIDs(
                old: record.servers,
                new: updated.servers
            )
            // Vanished servers leave orphaned Keychain entries behind unless
            // someone deletes them: the old record's keys minus the new ones.
            // Computed before the store swap, deleted after it succeeds.
            let staleKeys: Set<String> = {
                guard !isFirstImport else { return [] }
                let oldKeys = Set(record.servers.compactMap { $0.credential?.key })
                let newKeys = Set(updated.servers.compactMap { $0.credential?.key })
                return oldKeys.subtracting(newKeys)
            }()
            if isFirstImport {
                try await store.upsert(updated)
            } else {
                try await store.replaceServers(
                    id: record.id,
                    servers: updated.servers,
                    acceptedCount: updated.acceptedCount,
                    rejectedCount: updated.rejectedCount,
                    updatedAt: updated.updatedAt,
                    userInfo: updated.userInfo
                )
            }
            stored = true
            for key in staleKeys {
                try? secrets.delete(for: key)
            }
            return SubscriptionImportSummary(
                subscriptionID: record.id,
                accepted: accepted.count,
                rejected: rejected,
                remappedServerIDs: remapped
            )
        } catch {
            await rollbackSecrets(saved)
            if isFirstImport, !stored, let urlKey = record.source.secretReference?.key {
                // The record never reached the store, so its URL secret
                // would be an orphan: remove it with the server secrets.
                try? secrets.delete(for: urlKey)
            }
            if error is CancellationError {
                throw error
            }
            if let coordinatorError = error as? SubscriptionCoordinatorError {
                throw coordinatorError
            }
            throw SubscriptionCoordinatorError.persistenceFailed
        }
    }

    /// Matches stored servers to freshly imported ones by (protocol, host,
    /// port): the identity fields that survive a v1→v2 ID rotation.
    /// Returns old→new ID pairs for unambiguous 1:1 matches only.
    private static func remapServerIDs(old: [Server], new: [Server]) -> [UUID: UUID] {
        struct Key: Hashable {
            let proto: ProxyProtocol
            let host: String
            let port: Int
        }
        var oldByKey: [Key: [Server]] = [:]
        for server in old {
            oldByKey[Key(proto: server.protocolKind, host: server.endpoint.host, port: server.endpoint.port), default: []].append(server)
        }
        var newByKey: [Key: [Server]] = [:]
        for server in new {
            newByKey[Key(proto: server.protocolKind, host: server.endpoint.host, port: server.endpoint.port), default: []].append(server)
        }
        var remapped: [UUID: UUID] = [:]
        for (key, olds) in oldByKey {
            guard olds.count == 1, let news = newByKey[key], news.count == 1 else { continue }
            let from = olds[0].id
            let to = news[0].id
            if from != to {
                remapped[from] = to
            }
        }
        return remapped
    }

    private func currentSummary(id: UUID) async throws -> SubscriptionImportSummary {
        let records = await store.subscriptions()
        guard let record = records.first(where: { $0.id == id }) else {
            throw SubscriptionCoordinatorError.unknownSubscription
        }
        return SubscriptionImportSummary(
            subscriptionID: id,
            accepted: record.acceptedCount,
            rejected: []
        )
    }

    private func serverSummary(_ server: Server, groupID: String, summaryID: String) -> ServerSummary {
        let protocolLabel: String
        switch server.protocolKind {
        case .vless: protocolLabel = "VLESS"
        case .trojan: protocolLabel = "Trojan"
        case .shadowsocks: protocolLabel = "Shadowsocks"
        case .vmess: protocolLabel = "VMess"
        }
        return ServerSummary(
            id: summaryID,
            name: server.name,
            protocolLabel: protocolLabel,
            locationLabel: "Endpoint hidden",
            latency: .notMeasured,
            health: .none,
            groupIDs: [groupID]
        )
    }

    private func aggregatedSummary(records: [StoredSubscription]) -> SubscriptionSummary? {
        guard !records.isEmpty else { return nil }
        let entries = records.flatMap { record -> [SubscriptionEntrySummary] in
            record.servers.map { server in
                let protocolLabel: String
                switch server.protocolKind {
                case .vless: protocolLabel = "VLESS"
                case .trojan: protocolLabel = "Trojan"
                case .shadowsocks: protocolLabel = "Shadowsocks"
                case .vmess: protocolLabel = "VMess"
                }
                return SubscriptionEntrySummary(
                    id: Self.summaryID(subscriptionID: record.id, serverID: server.id),
                    displayName: server.name,
                    protocolLabel: protocolLabel,
                    redactedEndpointLabel: "Host hidden · port \(server.endpoint.port)",
                    statusLabel: "Accepted"
                )
            }
        }
        return SubscriptionSummary(
            id: "subscriptions",
            name: records.count == 1 ? records[0].name : "\(records.count) subscriptions",
            sourceKindLabel: "Subscription",
            sourceDisplayValue: "stored subscriptions",
            acceptedCount: records.reduce(0) { $0 + $1.acceptedCount },
            rejectedCount: records.reduce(0) { $0 + $1.rejectedCount },
            isSampleData: false,
            entries: entries
        )
    }
}

private extension Array {
    func chunked(into size: Int) -> [[Element]] {
        guard size > 0 else { return [self] }
        return stride(from: 0, to: count, by: size).map { start in
            Array(self[start..<Swift.min(start + size, count)])
        }
    }
}
