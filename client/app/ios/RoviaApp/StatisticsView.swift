import SwiftUI

/// What the engine itself reports, read through the provider channel — never
/// synthesized by the app. A tunnel that has never answered shows "No report",
/// not a fabricated zero.
struct StatisticsView: View {
    let model: AppModel

    var body: some View {
        RoviaScreen {
            RoviaScreenHeader(
                title: "Statistics",
                subtitle: "What the extension reports through the provider channel: the lifecycle state it is in, the engine it runs, and the datagrams the pump dropped under pressure.",
                identifier: AppAccessibilityIdentifier.statisticsScreen
            )

            SectionCard(title: "Connection", systemImage: "shield") {
                VStack(alignment: .leading, spacing: 12) {
                    InfoRow(
                        label: "Tunnel",
                        value: model.snapshot.engine.statusText,
                        identifier: AppAccessibilityIdentifier.statisticsTunnelState
                    )
                    InfoRow(
                        label: "Engine report",
                        value: model.snapshot.engineReport?.state ?? "No report yet",
                        identifier: AppAccessibilityIdentifier.statisticsEngineState
                    )
                    if let version = model.snapshot.engineReport?.engineVersion {
                        InfoRow(
                            label: "Engine",
                            value: version,
                            identifier: AppAccessibilityIdentifier.statisticsEngineVersion
                        )
                    }
                }
            }

            SectionCard(title: "Pump drops", systemImage: "arrow.down.circle") {
                VStack(alignment: .leading, spacing: 12) {
                    InfoRow(
                        label: "Outbound dropped",
                        value: model.snapshot.engineReport.map { String($0.droppedOutbound) } ?? "—",
                        identifier: AppAccessibilityIdentifier.statisticsDroppedOutbound,
                        tabular: true
                    )
                    InfoRow(
                        label: "Inbound dropped",
                        value: model.snapshot.engineReport.map { String($0.droppedInbound) } ?? "—",
                        identifier: AppAccessibilityIdentifier.statisticsDroppedInbound,
                        tabular: true
                    )
                    Text("Drops are the backpressure policy working: a datagram that could not be written in time is dropped and counted, never queued. Payloads are never counted here — or anywhere.")
                        .font(.footnote)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Button {
                Task { _ = await model.refreshStatistics() }
            } label: {
                Label("Refresh statistics", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .tint(ScopeTheme.phosphor)
            .controlSize(.large)
            .disabled(model.snapshot.system != .ready)
            .accessibilityHint("Asks the extension for its current report over the provider channel.")
            .accessibilityIdentifier(AppAccessibilityIdentifier.statisticsRefresh)
        }
        .task {
            _ = await model.refreshStatistics()
        }
    }
}
