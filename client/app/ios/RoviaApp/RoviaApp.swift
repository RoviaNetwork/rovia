import RoviaApplePlatform
import RoviaSubscription
import SwiftUI

/// The compile-time identity of this build, so any screen can label the
/// UI-only variant without re-deriving it — and cannot get it wrong in one
/// place and right in another.
enum BuildVariant {
    /// True only in the RoviaFreeDev target: the UI-only Personal Team build
    /// with no Packet Tunnel extension embedded and no Network Extension
    /// entitlement.
    static let isUIOnly: Bool = {
        #if ROVIA_UI_ONLY
            return true
        #else
            return false
        #endif
    }()
}

@main
struct RoviaApp: App {
    @State private var model = RoviaApp.makeModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
        }
    }

    private static func makeModel() -> AppModel {
        let coordinator = makeSubscriptionCoordinator()
        let handoff = try? TunnelHandoff()
        return AppModel(
            tunnel: makeTunnelController(),
            subscriptions: coordinator,
            configWriter: handoff.map {
                TunnelHandoffWriter(coordinator: coordinator, handoff: $0)
            },
            settingsStore: handoff.map(HandoffTunnelSettingsStore.init(handoff:))
        )
    }

    /// Which tunnel controller the build gets is a compile-time property of
    /// the target, not a runtime switch. The UI-only FreeDev target is built
    /// without the Network Extension entitlement and embeds no extension, so
    /// constructing a real controller there would promise a capability the
    /// binary cannot have; the unavailable controller keeps Connect disabled
    /// and says why.
    private static func makeTunnelController() -> any TunnelControlling {
        #if ROVIA_UI_ONLY
            UnavailableTunnelController()
        #else
            NETunnelController()
        #endif
    }

    /// Production subscription stack: file store in the shared app-group
    /// container (so the tunnel extension can read server lists later),
    /// secrets in the Keychain, and the streaming production fetcher (byte
    /// cap during the read, redirect delegate) — passed explicitly, never
    /// inferred.
    private static func makeSubscriptionCoordinator() -> SubscriptionCoordinator {
        let directory: URL
        if let container = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: "group.io.rovia.shared"
        ) {
            directory = container.appendingPathComponent("subscriptions", isDirectory: true)
        } else {
            directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Rovia/subscriptions", isDirectory: true)
        }
        return SubscriptionCoordinator(
            store: SubscriptionStore(directory: directory),
            secrets: KeychainSecretStore(service: "io.rovia.client", accessGroup: KeychainAccessGroup.resolve()),
            fetcher: SubscriptionFetcher.production()
        )
    }
}
