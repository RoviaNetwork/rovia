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

/// An import job that may cross to a detached task. Unchecked because
/// `ShareLinkCredentialSink` is not marked `@Sendable` (marking the
/// package-wide typealias would break every existing call site that captures
/// test recorders); the concrete closures built by `credentialSink` capture
/// only the `Sendable` secret store and a UUID, so no shared mutable state
/// crosses here.
private struct DetachedImport: @unchecked Sendable {
    let lines: [String]
    let sink: ShareLinkCredentialSink
}

private enum SecretKeys {    static func subscriptionURL(_ id: UUID) -> String {
        "subscription/\(id.uuidString.lowercased())/url"
    }

    /// Deterministic per secret bytes: the same credential reuses one
    /// Keychain entry across refreshes, and two servers sharing a password
    /// honestly share it. FNV-1a/64, hex — printable ASCII, 16 chars.
    static func credential(subscriptionID: UUID, secret: Data) -> String {
        var hash = UInt64(0xCBF29CE484222325)
        for byte in secret {
            hash ^= UInt64(byte)
            hash &*= 0x100000001B3
        }
        return "subscription/\(subscriptionID.uuidString.lowercased())/credential/\(String(format: "%016llx", hash))"
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
        let raw = try await fetch(url: url, allowInsecure: allowInsecure)
        let document = try decode(raw)
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
            allowInsecure: allowInsecure
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
        let document = try decode(data)
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
        let document = try decode(raw)
        return try await importAndStore(lines: document.lines, record: record, isFirstImport: false)
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

    /// Non-secret endpoints for latency probing, keyed by the summary ID
    /// (`ServerSummary.id`). Hosts and ports are not secrets — the redacted
    /// display values already carry the port — but credentials never leave
    /// the Keychain through here.
    func endpoints() async -> [String: (host: String, port: Int)] {
        var result: [String: (host: String, port: Int)] = [:]
        for record in await store.subscriptions() {
            for server in record.servers {
                result[server.id.uuidString.lowercased()] = (server.endpoint.host, server.endpoint.port)
            }
        }
        return result
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
            let serverIDs = record.servers.map { $0.id.uuidString.lowercased() }
            content.profiles.append(ProfileSummary(
                id: groupID,
                name: record.name,
                sourceKindLabel: "Subscription",
                serverIDs: serverIDs
            ))
            content.servers.append(contentsOf: record.servers.map { serverSummary($0, groupID: groupID) })
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

    private func fetch(url: URL, allowInsecure: Bool) async throws -> Data {
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

    private func decode(_ data: Data) throws -> SubscriptionDocument {
        do {
            return try SubscriptionDocumentDecoder.decode(data)
        } catch let error as SubscriptionDocumentError {
            throw SubscriptionCoordinatorError.decodeFailed(error)
        } catch {
            throw SubscriptionCoordinatorError.decodeFailed(.invalidBase64)
        }
    }

    private func credentialSink(subscriptionID: UUID) -> ShareLinkCredentialSink {
        { [secrets] secret in
            let key = SecretKeys.credential(subscriptionID: subscriptionID, secret: secret)
            try secrets.save(secret, for: key)
            return SecretReference(key: key)
        }
    }

    private func importAndStore(
        lines: [String],
        record: StoredSubscription,
        isFirstImport: Bool
    ) async throws -> SubscriptionImportSummary {
        // Parsing thousands of links costs ~2s per 5000 on an i3 and must
        // never run on the MainActor: the importer is pure, so it runs
        // detached. The sink only captures the thread-safe secret store and
        // a UUID, which is what makes the unchecked boundary below honest —
        // and it is the only unchecked boundary in this file.
        let sink = credentialSink(subscriptionID: record.id)
        let job = DetachedImport(lines: lines, sink: sink)
        let result = await Task.detached(priority: .userInitiated) {
            SubscriptionImporter.importLines(job.lines, credentialSink: job.sink)
        }.value
        guard !result.accepted.isEmpty else {
            if isFirstImport {
                var empty = record
                empty.servers = []
                empty.acceptedCount = 0
                empty.rejectedCount = result.rejected.count
                try? await store.upsert(empty)
            }
            throw SubscriptionCoordinatorError.nothingAccepted(
                accepted: 0,
                rejected: result.rejected
            )
        }
        var updated = record
        updated.servers = result.accepted.map(\.server)
        updated.acceptedCount = result.accepted.count
        updated.rejectedCount = result.rejected.count
        updated.updatedAt = Date()
        do {
            if isFirstImport {
                try await store.upsert(updated)
            } else {
                try await store.replaceServers(
                    id: record.id,
                    servers: updated.servers,
                    acceptedCount: updated.acceptedCount,
                    rejectedCount: updated.rejectedCount,
                    updatedAt: updated.updatedAt
                )
            }
        } catch {
            throw SubscriptionCoordinatorError.persistenceFailed
        }
        return SubscriptionImportSummary(
            subscriptionID: record.id,
            accepted: result.accepted.count,
            rejected: result.rejected
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

    private func serverSummary(_ server: Server, groupID: String) -> ServerSummary {
        let protocolLabel: String
        switch server.protocolKind {
        case .vless: protocolLabel = "VLESS"
        case .trojan: protocolLabel = "Trojan"
        case .shadowsocks: protocolLabel = "Shadowsocks"
        case .vmess: protocolLabel = "VMess"
        }
        return ServerSummary(
            id: server.id.uuidString.lowercased(),
            name: "\(protocolLabel) · \(server.endpoint.port)",
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
                    id: server.id.uuidString.lowercased(),
                    displayName: "\(record.name) · \(protocolLabel)",
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
