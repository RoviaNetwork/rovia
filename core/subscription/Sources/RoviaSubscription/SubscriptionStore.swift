import Foundation
import RoviaConfig

public enum SubscriptionStoreError: Error, Equatable, Sendable {
    case unknownSubscription
    case persistenceFailed
}

/// One persisted subscription: redacted metadata plus the last working
/// server list. Secrets are never stored here — the import credential sink
/// writes them to the Keychain (`KeychainSecretStore`), keyed per server.
public struct StoredSubscription: Codable, Equatable, Sendable, Identifiable {
    public let id: UUID
    public var name: String
    public var source: SubscriptionSource
    public var servers: [Server]
    public var acceptedCount: Int
    public var rejectedCount: Int
    public var updatedAt: Date

    public init(
        id: UUID = UUID(),
        name: String,
        source: SubscriptionSource,
        servers: [Server] = [],
        acceptedCount: Int = 0,
        rejectedCount: Int = 0,
        updatedAt: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.source = source
        self.servers = servers
        self.acceptedCount = acceptedCount
        self.rejectedCount = rejectedCount
        self.updatedAt = updatedAt
    }
}

/// File-backed subscription list. Refresh is atomic by construction: a
/// failed download or an empty import throws before `replaceServers` runs,
/// so the last working server list (and the selected server, via stable
/// importer IDs) always survives.
public actor SubscriptionStore {
    private let fileURL: URL
    private var records: [StoredSubscription] = []
    private var loaded = false

    public init(directory: URL, fileName: String = "subscriptions.json") {
        self.fileURL = directory.appendingPathComponent(fileName)
    }

    public func load() throws {
        guard !loaded else { return }
        loaded = true
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            records = []
            return
        }
        do {
            let data = try Data(contentsOf: fileURL)
            records = try JSONDecoder().decode([StoredSubscription].self, from: data)
        } catch {
            throw SubscriptionStoreError.persistenceFailed
        }
    }

    public func subscriptions() -> [StoredSubscription] {
        records
    }

    public func upsert(_ record: StoredSubscription) throws {
        if let index = records.firstIndex(where: { $0.id == record.id }) {
            records[index] = record
        } else {
            records.append(record)
        }
        try persist()
    }

    public func rename(id: UUID, name: String) throws {
        guard let index = records.firstIndex(where: { $0.id == id }) else {
            throw SubscriptionStoreError.unknownSubscription
        }
        records[index].name = name
        try persist()
    }

    public func remove(id: UUID) throws {
        guard let index = records.firstIndex(where: { $0.id == id }) else {
            throw SubscriptionStoreError.unknownSubscription
        }
        records.remove(at: index)
        try persist()
    }

    /// Atomic refresh update. Call only after a successful import; network
    /// and decode failures never reach this method, which is what keeps the
    /// last working version on disk.
    public func replaceServers(
        id: UUID,
        servers: [Server],
        acceptedCount: Int,
        rejectedCount: Int,
        updatedAt: Date = Date()
    ) throws {
        guard let index = records.firstIndex(where: { $0.id == id }) else {
            throw SubscriptionStoreError.unknownSubscription
        }
        records[index].servers = servers
        records[index].acceptedCount = acceptedCount
        records[index].rejectedCount = rejectedCount
        records[index].updatedAt = updatedAt
        try persist()
    }

    private func persist() throws {
        do {
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let data = try JSONEncoder().encode(records)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            throw SubscriptionStoreError.persistenceFailed
        }
    }
}
