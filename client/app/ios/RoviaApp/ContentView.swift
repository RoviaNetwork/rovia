import SwiftUI

struct ContentView: View {
    let model: AppModel

    var body: some View {
        RootView(model: model)
            .task {
                _ = await model.bootstrap()
            }
    }
}
