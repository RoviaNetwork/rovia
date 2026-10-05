import Foundation
import NetworkExtension

/// The profile operations the controller uses, abstracted so tests never
/// touch the system's real VPN preferences. The production implementation is
/// `NETunnelProviderManager` itself; the mock records the same calls.
protocol TunnelProfileManaging: AnyObject, Sendable {
    var isEnabled: Bool { get set }
    var isOnDemandEnabled: Bool { get set }
    // Optional because NetworkExtension's own property is optional; the
    // controller never reads it back, it only ever assigns a concrete list.
    var onDemandRules: [NEOnDemandRule]? { get set }
    var includeAllNetworks: Bool { get set }

    func save() async throws
    func reload() async throws
    func start() throws
    func stop()
    func status() -> TunnelStatus
    func sendStatusRequest(_ body: Data) async -> Data?
}

extension NETunnelProviderManager: TunnelProfileManaging {
    var includeAllNetworks: Bool {
        get { (protocolConfiguration as? NETunnelProviderProtocol)?.includeAllNetworks ?? false }
        set { (protocolConfiguration as? NETunnelProviderProtocol)?.includeAllNetworks = newValue }
    }

    func save() async throws {
        try await saveToPreferences()
    }

    func reload() async throws {
        try await loadFromPreferences()
    }

    func start() throws {
        try connection.startVPNTunnel()
    }

    func stop() {
        connection.stopVPNTunnel()
    }

    func status() -> TunnelStatus {
        switch connection.status {
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

    func sendStatusRequest(_ body: Data) async -> Data? {
        guard let session = connection as? NETunnelProviderSession else {
            return nil
        }
        return await withCheckedContinuation { continuation in
            do {
                try session.sendProviderMessage(body) { data in
                    continuation.resume(returning: data)
                }
            } catch {
                continuation.resume(returning: nil)
            }
        }
    }
}

/// The real tunnel controller: the host app's handle on the Packet Tunnel
/// extension through the profile store. The engine itself is the extension's
/// business; this controller never sees a credential or a config payload.
final class NETunnelController: TunnelControlling {
    private let providerBundleIdentifier = "io.rovia.client.tunnel"
    private let profileProvider: @Sendable () async throws -> any TunnelProfileManaging
    private let settingsProvider: @Sendable () -> TunnelSettings

    init(
        profileProvider: @escaping @Sendable () async throws -> any TunnelProfileManaging = {
            try await NETunnelController.loadManager(bundleID: "io.rovia.client.tunnel")
        },
        settingsProvider: @escaping @Sendable () -> TunnelSettings = {
            (try? TunnelHandoff())?.readSettings() ?? TunnelSettings()
        }
    ) {
        self.profileProvider = profileProvider
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
        manager.protocolConfiguration = proto
        manager.isEnabled = true
        return manager
    }

    func engineAvailability() async -> EngineAvailability {
        .available
    }

    func requestStart() async throws {
        let settings = settingsProvider()
        let profile = try await profileProvider()
        profile.isEnabled = true
        profile.isOnDemandEnabled = settings.killSwitch
        profile.onDemandRules = settings.killSwitch ? [NEOnDemandRuleConnect()] : []
        // Kill switch, platform level: with includeAllNetworks, iOS drops
        // traffic whenever the tunnel is not running, and the on-demand rule
        // above restarts it.
        profile.includeAllNetworks = settings.killSwitch
        try await profile.save()
        try await profile.reload()

        do {
            try profile.start()
        } catch let error as NEVPNError {
            throw Self.mapStart(error)
        }
    }

    func requestStop() async throws {
        let profile = try await profileProvider()
        // An always-connect on-demand rule restarts the tunnel the moment it
        // is stopped: the classic iOS footgun. Disarm it before stopping, or
        // "stop" is a rumor.
        if profile.isOnDemandEnabled {
            profile.isOnDemandEnabled = false
            profile.onDemandRules = []
            try await profile.save()
            try await profile.reload()
        }
        profile.stop()
    }

    func currentStatus() async -> TunnelStatus {
        guard let profile = try? await profileProvider() else {
            return .engineUnavailable(.platformUnsupported)
        }
        return profile.status()
    }

    /// Asks the extension for the engine's own report. A tunnel that is not
    /// running has nothing to ask, and a message the extension cannot answer
    /// is nil — the caller shows "no report", never a fabricated one.
    func statusReport() async -> TunnelStatusReport? {
        guard let profile = try? await profileProvider() else {
            return nil
        }
        let request: [String: Any] = [
            "apiVersion": 1,
            "requestID": UUID().uuidString,
            "method": "status.get",
            "payload": [:] as [String: Any]
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: request, options: [.sortedKeys]) else {
            return nil
        }
        guard let response = await profile.sendStatusRequest(body) else {
            return nil
        }
        guard let object = try? JSONSerialization.jsonObject(with: response),
              let envelope = object as? [String: Any],
              envelope["ok"] as? Bool == true,
              let result = envelope["result"] as? [String: Any],
              let state = result["state"] as? String
        else {
            return nil
        }
        return TunnelStatusReport(
            state: state,
            engineVersion: result["engineVersion"] as? String,
            droppedOutbound: (result["droppedOutbound"] as? NSNumber)?.uint64Value ?? 0,
            droppedInbound: (result["droppedInbound"] as? NSNumber)?.uint64Value ?? 0
        )
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
