import SwiftUI

struct ContentView: View {
    let model: AppModel

    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        RootView(model: model)
            .preferredColorScheme(model.snapshot.appearance.colorScheme)
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
                // Queued, never acted on directly: the preview sheet asks
                // first, and a link that arrives mid-bootstrap waits for it.
                guard let target = SubscriptionCoordinator.importTarget(from: url) else { return }
                model.queueDeepLink(text: target.text, name: target.name)
            }
            .sheet(
                item: Binding(get: { model.pendingImport }, set: { model.pendingImport = $0 })
            ) { pending in
                ImportPreviewSheet(model: model, pending: pending)
            }
    }
}
