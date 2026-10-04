import Foundation
import NetworkExtension

/// The real tunnel controller: the host app's handle on the Packet Tunnel
/// extension through `NETunnelProviderManager`.
///
/// What it does, in order: loads or creates the manager for the extension's
/// bundle identifier, applies the profile the current settings require
/// (kill-switch drives `includeAllNetworks` and the on-demand rules), saves,
/// and starts the tunnel. The engine itself is the extension's business; this
/// controller never sees a credential or a config payload.
final class NETunnelController: TunnelControlling {
    private let providerBundleIdentifier = "io.rovia.client.tunnel"
    private let managerProvider: @Sendable () async throws -> NETunnelProviderManager
    private let settingsProvider: @Sendable () -> TunnelSettings

    init(
        managerProvider: @escaping @Sendable () async throws -> NETunnelProviderManager = {
            try await NETunnelController.loadManager(bundleID: "io.rovia.client.tunnel")
        },
        settingsProvider: @escaping @Sendable () -> TunnelSettings = {
            (try? TunnelHandoff())?.readSettings() ?? TunnelSettings()
        }
    ) {
        self.managerProvider = managerProvider
        self.settingsProvider = settingsProvider
    }

    private static func loadManager(bundleID: String) async throws -> NETunnelProviderManager {
        let managers = try await NETunnelProviderManager.loadAllFromPreferences()
        let manager = managers.first(where: {
            ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == bundleID
        }) ?? NETunnelProviderManager()

        let proto = NETunnelProviderProtocol()
        proto.providerBundleIdentifier = bundleID
        // The display name iOS shows in Settings > VPN. No address is invented:
        // the real endpoint comes from the stored configuration.
        proto.serverAddress = "Rovia"
        return manager.withProtocol(proto)
    }

    func engineAvailability() async -> EngineAvailability {
        .available
    }

    func requestStart() async throws {
        let settings = settingsProvider()
        let manager = try await managerProvider()
        manager.isEnabled = true
        manager.isOnDemandEnabled = settings.killSwitch
        manager.onDemandRules = settings.killSwitch ? [NEOnDemandRuleConnect()] : []
        if let proto = manager.protocolConfiguration as? NETunnelProviderProtocol {
            // Kill switch, platform level: with includeAllNetworks, iOS drops
            // traffic whenever the tunnel is not running, and the on-demand
            // rule above restarts it.
            proto.includeAllNetworks = settings.killSwitch
            proto.excludeLocalNetworks = false
        }
        try await manager.saveToPreferences()
        try await manager.loadFromPreferences()

        do {
            try manager.connection.startVPNTunnel()
        } catch let error as NEVPNError {
            throw Self.mapStart(error)
        }
    }

    func requestStop() async throws {
        let manager = try await managerProvider()
        manager.connection.stopVPNTunnel()
    }

    func currentStatus() async -> TunnelStatus {
        guard let manager = try? await managerProvider() else {
            return .engineUnavailable(.platformUnsupported)
        }
        switch manager.connection.status {
        case .invalid, .disconnected:
            return .disconnected
        case .connecting:
            return .connecting
        case .connected:
            return .connected
        case .reasserting:
            return .reasserting
        case .disconnecting:
            return .disconnecting
        @unknown default:
            return .disconnected
        }
    }

    private static func mapStart(_ error: NEVPNError) -> TunnelControlFailure {
        switch error.code {
        case .configurationInvalid, .configurationDisabled, .configurationReadWriteFailed:
            return .configurationRejected
        default:
            return .unknown
        }
    }
}

private extension NETunnelProviderManager {
    func withProtocol(_ proto: NETunnelProviderProtocol) -> NETunnelProviderManager {
        protocolConfiguration = proto
        isEnabled = true
        return self
    }
}
