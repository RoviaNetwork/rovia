import RoviaApplePlatform
import RoviaSubscription
import SwiftUI

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
            tunnel: NETunnelController(),
            subscriptions: coordinator,
            configWriter: handoff.map {
                TunnelHandoffWriter(coordinator: coordinator, handoff: $0)
            },
            settingsStore: handoff.map(HandoffTunnelSettingsStore.init(handoff:))
        )
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
