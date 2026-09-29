import SwiftUI

struct ContentView: View {
    let model: AppModel

    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        RootView(model: model)
            .task {
                _ = await model.bootstrap()
            }
            .onChange(of: scenePhase) { _, phase in
                guard phase == .active else { return }
                Task {
                    await model.refreshStaleSubscriptions()
                }
            }
            .onOpenURL { url in
                guard let target = SubscriptionCoordinator.importTarget(from: url) else { return }
                Task {
                    await model.addSubscriptionText(target.text, name: target.name ?? "Imported subscription")
                }
            }
    }
}
