import Foundation
import Security

/// Resolves the Keychain access group the two targets share.
///
/// The value carries the team prefix (`<team>.io.rovia.shared`), which the
/// source cannot know, so it is probed from the Keychain itself: a throwaway
/// item is written, its stamped access group is read back, and the probe is
/// deleted before returning. On a build without the shared-access-group
/// entitlement the probe reports the app's own default group, and callers
/// treat "no shared group" as "no sharing", which is the honest answer for
/// unsigned simulator runs.
public enum KeychainAccessGroup {
    private static let probeAccount = "io.rovia.probe.access-group"

    /// The access group the Keychain stamps onto a probe item, or nil when the
    /// probe cannot run at all (no usable keychain in this process).
    public static func resolve() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: probeAccount,
            kSecAttrAccount as String: probeAccount,
            kSecValueData as String: Data([0]),
            kSecReturnAttributes as String: true,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]

        // A leftover probe from a crashed run would shadow the write, so the
        // write path is delete-then-add rather than add-or-update.
        var item: CFTypeRef?
        let addStatus = SecItemAdd(query as CFDictionary, &item)
        if addStatus == errSecDuplicateItem {
            SecItemDelete(baseQuery)
            let retry = SecItemAdd(query as CFDictionary, &item)
            guard retry == errSecSuccess else { return nil }
        } else if addStatus != errSecSuccess {
            return nil
        }
        defer { SecItemDelete(baseQuery) }

        guard let attributes = item as? [String: Any],
              let group = attributes[kSecAttrAccessGroup as String] as? String,
              !group.isEmpty
        else {
            return nil
        }
        return group
    }

    private static var baseQuery: CFDictionary {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: probeAccount,
            kSecAttrAccount as String: probeAccount
        ] as CFDictionary
    }
}
