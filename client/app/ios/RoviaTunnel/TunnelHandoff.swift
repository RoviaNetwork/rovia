import Foundation
import RoviaConfig
import RoviaEngineAPI

/// The durable hand-off between the app and the tunnel extension, living in
/// the shared App Group container.
///
/// What is stored here and what is not: the canonical configuration carries
/// server endpoints and routing, never credentials — a credential is a
/// `SecretReference` key, resolved by the extension from the shared Keychain
/// access group at start time. The settings carry the kill-switch flag.
/// Everything is written atomically with `completeFileProtectionUnlessOpen`,
/// so the hand-off is readable on a locked device only while it is already
/// open — a tunnel start from the lock screen keeps working, a first start
/// after reboot does not read stale bytes.
public struct TunnelHandoff: Sendable {
    public static let canonicalConfigPath = "tunnel/canonical-config.json"
    public static let settingsPath = "tunnel/settings.json"

    public let container: URL

    public init(appGroup: String = "group.io.rovia.shared") throws {
        guard let container = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroup
        ) else {
            throw TunnelHandoffError.unavailableContainer
        }
        self.init(container: container)
    }

    /// A direct container URL — the seam tests use to stay out of the real
    /// App Group.
    public init(container: URL) {
        self.container = container
    }

    public enum TunnelHandoffError: Error, Equatable {
        case unavailableContainer
        case configurationMissing
        case settingsMalformed
    }

    // MARK: - App side: write

    public func writeCanonicalConfiguration(_ configuration: CanonicalTunnelConfiguration) throws {
        let data = try JSONEncoder.rovia.encode(configuration)
        try write(data, named: Self.canonicalConfigPath)
    }

    public func writeSettings(_ settings: TunnelSettings) throws {
        let data = try JSONEncoder.rovia.encode(settings)
        try write(data, named: Self.settingsPath)
    }

    // MARK: - Extension side: read

    public func readCanonicalConfiguration() throws -> CanonicalTunnelConfiguration {
        guard let data = try? read(named: Self.canonicalConfigPath) else {
            throw TunnelHandoffError.configurationMissing
        }
        return try JSONDecoder().decode(CanonicalTunnelConfiguration.self, from: data)
    }

    /// A missing or unreadable settings file means the safe default: the kill
    /// switch is off and the app never silently opted the user into a
    /// blackhole-on-failure posture they did not choose.
    public func readSettings() -> TunnelSettings {
        guard let data = try? read(named: Self.settingsPath),
              let settings = try? JSONDecoder().decode(TunnelSettings.self, from: data)
        else {
            return TunnelSettings()
        }
        return TunnelSettings(killSwitch: settings.killSwitch)
    }

    private func write(_ data: Data, named name: String) throws {
        let url = container.appendingPathComponent(name)
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try data.write(to: url, options: [.atomic, .completeFileProtectionUnlessOpen])
    }

    private func read(named name: String) throws -> Data {
        try Data(contentsOf: container.appendingPathComponent(name))
    }
}

/// The user-facing tunnel settings the extension needs at start time.
public struct TunnelSettings: Codable, Equatable, Sendable {
    /// When on, the installed profile asks iOS to drop all traffic whenever
    /// the tunnel is not running (`includeAllNetworks` plus always-connect
    /// on-demand rules), and the extension cancels itself on an engine failure
    /// rather than letting traffic leak past a dead engine.
    public var killSwitch: Bool

    public init(killSwitch: Bool = false) {
        self.killSwitch = killSwitch
    }
}

private extension JSONEncoder {
    static let rovia: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }()
}
