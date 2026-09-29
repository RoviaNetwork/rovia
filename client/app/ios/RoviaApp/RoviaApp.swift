import RoviaApplePlatform
import RoviaSubscription
import SwiftUI

@main
struct RoviaApp: App {
    @State private var model = AppModel(
        subscriptions: RoviaApp.makeSubscriptionCoordinator()
    )

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
        }
    }

    /// Production subscription stack: file store in the shared app-group
    /// container (so the tunnel extension can read server lists later),
    /// secrets in the Keychain, real network session.
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
            secrets: KeychainSecretStore(service: "io.rovia.client", accessGroup: "group.io.rovia.shared")
        )
    }
}
