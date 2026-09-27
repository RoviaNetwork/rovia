import Foundation
import Security

public enum SecretStoreError: Error, Equatable, Sendable {
    case keychain(OSStatus)
    case invalidKey
}

public protocol SecretStore: Sendable {
    func save(_ value: Data, for key: String) throws
    func read(for key: String) throws -> Data?
    func delete(for key: String) throws
}

public final class InMemorySecretStore: SecretStore, @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: Data] = [:]

    public init() {}

    public func save(_ value: Data, for key: String) throws {
        guard !key.isEmpty else { throw SecretStoreError.invalidKey }
        lock.lock()
        values[key] = value
        lock.unlock()
    }

    public func read(for key: String) throws -> Data? {
        guard !key.isEmpty else { throw SecretStoreError.invalidKey }
        lock.lock()
        let value = values[key]
        lock.unlock()
        return value
    }

    public func delete(for key: String) throws {
        guard !key.isEmpty else { throw SecretStoreError.invalidKey }
        lock.lock()
        values.removeValue(forKey: key)
        lock.unlock()
    }
}

public final class KeychainSecretStore: SecretStore, @unchecked Sendable {
    private let service: String
    private let accessGroup: String?

    public init(service: String, accessGroup: String? = nil) {
        self.service = service
        self.accessGroup = accessGroup
    }

    public func save(_ value: Data, for key: String) throws {
        guard !key.isEmpty else { throw SecretStoreError.invalidKey }
        var query = baseQuery(for: key)
        query[kSecValueData as String] = value
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

        let status = SecItemAdd(query as CFDictionary, nil)
        if status == errSecDuplicateItem {
            let update: [String: Any] = [kSecValueData as String: value]
            let updateStatus = SecItemUpdate(baseQuery(for: key) as CFDictionary, update as CFDictionary)
            guard updateStatus == errSecSuccess else { throw SecretStoreError.keychain(updateStatus) }
        } else if status != errSecSuccess {
            throw SecretStoreError.keychain(status)
        }
    }

    public func read(for key: String) throws -> Data? {
        guard !key.isEmpty else { throw SecretStoreError.invalidKey }
        var query = baseQuery(for: key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw SecretStoreError.keychain(status) }
        return result as? Data
    }

    public func delete(for key: String) throws {
        guard !key.isEmpty else { throw SecretStoreError.invalidKey }
        let status = SecItemDelete(baseQuery(for: key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw SecretStoreError.keychain(status)
        }
    }

    private func baseQuery(for key: String) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
        if let accessGroup {
            query[kSecAttrAccessGroup as String] = accessGroup
        }
        return query
    }
}

public enum AppGroupStoreError: Error, Equatable, Sendable {
    case invalidIdentifier
    case invalidPath
    case unavailableContainer
}

public struct AppGroupStore: Sendable {
    public let identifier: String

    public init(identifier: String) {
        self.identifier = identifier
    }

    public func containerURL() throws -> URL {
        guard !identifier.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw AppGroupStoreError.invalidIdentifier
        }
        guard let url = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: identifier) else {
            throw AppGroupStoreError.unavailableContainer
        }
        return url
    }

    public func write(_ data: Data, to relativePath: String) throws {
        let url = try fileURL(for: relativePath)
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: url, options: [.atomic, .completeFileProtectionUnlessOpen])
    }

    public func read(from relativePath: String) throws -> Data {
        try Data(contentsOf: fileURL(for: relativePath))
    }

    public func delete(_ relativePath: String) throws {
        let url = try fileURL(for: relativePath)
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try FileManager.default.removeItem(at: url)
    }

    private func fileURL(for relativePath: String) throws -> URL {
        guard !relativePath.isEmpty, !relativePath.hasPrefix("/") else {
            throw AppGroupStoreError.invalidPath
        }
        let components = relativePath.split(separator: "/")
        guard !components.contains("..") else { throw AppGroupStoreError.invalidPath }
        return try containerURL().appendingPathComponent(relativePath)
    }
}

public protocol TunnelProfileManaging: Sendable {
    func installProfile() async throws
    func removeProfile() async throws
    func start() async throws
    func stop() async
}
