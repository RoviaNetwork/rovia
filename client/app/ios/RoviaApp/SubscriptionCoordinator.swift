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
    private let session: any SubscriptionHTTPSession
    private var refreshing: Set<UUID> = []

    init(
        store: SubscriptionStore,
        secrets: any SecretStore,
        session: any SubscriptionHTTPSession = URLSession.shared
    ) {
        self.store = store
        self.secrets = secrets
        self.session = session
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
        let fetcher = SubscriptionFetcher(
            session: session,
            policy: SubscriptionFetchPolicy(allowInsecureHTTP: allowInsecure)
        )
        do {
            return try await fetcher.fetch(url)
        } catch let error as SubscriptionFetchError {
            throw SubscriptionCoordinatorError.fetchFailed(error)
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
        // Cancellation checkpoints around every stage: a cancelled import
        // stops within one chunk and never reaches the store, even if the
        // last chunk finished in the same instant.
        try Task.checkCancellation()
        // Ordered dedup first (cheap), then bounded chunks off the MainActor.
        var seen: Set<String> = []
        var unique: [String] = []
        unique.reserveCapacity(lines.count)
        for rawLine in lines {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            guard !line.isEmpty else { continue }
            if seen.insert(SubscriptionImporter.canonicalLine(line)).inserted {
                unique.append(line)
            }
        }
        let saved = SavedKeys()
        var accepted: [ParsedShareLink] = []
        var rejected: [RejectedSubscriptionLine] = []
        do {
            for chunk in unique.chunked(into: 256) {
                try Task.checkCancellation()
                // The sink is built inside the detached closure from Sendable
                // captures only (secret store, subscription id, key tracker), so
                // no unchecked boundary is needed to cross threads here.
                let chunkResult = try await background { [secrets] in
                    SubscriptionImporter.importLines(chunk) { serverID, secret in
                        let key = SecretKeys.serverCredential(subscriptionID: record.id, serverID: serverID)
                        try secrets.save(secret, for: key)
                        saved.append(key)
                        return SecretReference(key: key)
                    }
                }
                accepted.append(contentsOf: chunkResult.accepted)
                rejected.append(contentsOf: chunkResult.rejected)
            }
        } catch {
            // Cancellation included: nothing reached the store, and nothing
            // saved may stay behind.
            await rollbackSecrets(saved)
            throw error
        }
        guard !accepted.isEmpty else {
            await rollbackSecrets(saved)
            if isFirstImport {
                var empty = record
                empty.servers = []
                empty.acceptedCount = 0
                empty.rejectedCount = rejected.count
                try? await store.upsert(empty)
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
        // Vanished servers leave orphaned Keychain entries behind unless
        // someone deletes them: the old record's keys minus the new ones.
        // Computed before the store swap, deleted after it succeeds.
        let staleKeys: Set<String> = {
            guard !isFirstImport else { return [] }
            let oldKeys = Set(record.servers.compactMap { $0.credential?.key })
            let newKeys = Set(updated.servers.compactMap { $0.credential?.key })
            return oldKeys.subtracting(newKeys)
        }()
        do {
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
        } catch {
            await rollbackSecrets(saved)
            if isFirstImport, let urlKey = record.source.secretReference?.key {
                // The record never reached the store, so its URL secret
                // would be an orphan: remove it with the server secrets.
                try? secrets.delete(for: urlKey)
            }
            throw SubscriptionCoordinatorError.persistenceFailed
        }
        for key in staleKeys {
            try? secrets.delete(for: key)
        }
        return SubscriptionImportSummary(
            subscriptionID: record.id,
            accepted: accepted.count,
            rejected: rejected
        )
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
