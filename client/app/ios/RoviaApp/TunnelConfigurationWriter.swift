import Foundation
import RoviaConfig
import RoviaEngineAPI

/// Builds the canonical configuration for the selected server and writes it
/// to the App Group hand-off the extension reads at start time.
///
/// The written configuration never carries a credential: every server's
/// `credential` is a `SecretReference` key, and the extension resolves it
/// from the shared Keychain. What crosses the process boundary here is
/// endpoints and routing, atomically written, so the extension never reads a
/// half-written config.
protocol TunnelConfigWriting: Sendable {
    func writeConfiguration(serverID: ServerID, killSwitch: Bool) async throws
}

struct TunnelHandoffWriter: TunnelConfigWriting {
    let coordinator: SubscriptionCoordinator
    let handoff: TunnelHandoff

    enum WriterError: Error, Equatable {
        /// The selected summary ID maps to no stored canonical server — the
        /// store and the model disagree, which is a bug, so the failure is
        /// loud rather than a silent no-op.
        case unknownServer
    }

    func writeConfiguration(serverID: ServerID, killSwitch: Bool) async throws {
        guard let server = await coordinator.canonicalServer(summaryID: serverID) else {
            throw WriterError.unknownServer
        }
        // The default route needs a group: the canonical model resolves
        // `defaultAction: .group` against the group list, so a single-server
        // tunnel is a one-member manual group named for what it is.
        let group = ServerGroup(
            id: UUID(),
            name: "Selected server",
            mode: .manual,
            members: [server.id],
            selectionPolicy: .manual
        )
        let configuration = CanonicalTunnelConfiguration(
            schemaVersion: 1,
            appConfig: AppConfig(
                schemaVersion: 1,
                subscriptions: [],
                groups: [group],
                routing: RouteSet(rules: [], defaultAction: .group(group.id)),
                dns: DNSPolicy(mode: .system),
                privacy: PrivacyPolicy(),
                servers: [server]
            )
        )
        try handoff.writeCanonicalConfiguration(configuration)
        try handoff.writeSettings(TunnelSettings(killSwitch: killSwitch))
    }
}
