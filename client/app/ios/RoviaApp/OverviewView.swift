import SwiftUI

struct OverviewView: View {
    let model: AppModel

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            switch model.snapshot.system {
            case .idle, .preparing:
                preparingView
            case .failed:
                failedView
            case .ready:
                readyView
            }
        }
        .navigationTitle(AppRoute.overview.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var preparingView: some View {
        RoviaScreen {
            RoviaScreenHeader(
                title: "Overview",
                subtitle: "Preparing local data for this build.",
                identifier: AppAccessibilityIdentifier.overviewScreen
            )
            HStack(spacing: 12) {
                ProgressView()
                Text("Loading the offline fixture environment")
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier(AppAccessibilityIdentifier.overviewPreparing)
        }
    }

    private var failedView: some View {
        Group {
            if case let .failed(error) = model.snapshot.system {
                ContentUnavailableView {
                    Label("Local data unavailable", systemImage: "exclamationmark.triangle")
                } description: {
                    Text(error.userMessage)
                } actions: {
                    Button("Try again") {
                        Task { await model.bootstrap() }
                    }
                    .accessibilityHint("Re-runs local preparation. The previous failure is shown above the button.")
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewRetry)
                }
            }
        }
        .modifier(ConditionalAccessibilityIdentifier(identifier: AppAccessibilityIdentifier.overviewEmptyFailed))
    }

    private var readyView: some View {
        RoviaScreen {
            RoviaScreenHeader(
                title: "Overview",
                subtitle: "Local status only. This build ships no tunnel engine, so Rovia cannot establish a VPN connection.",
                identifier: AppAccessibilityIdentifier.overviewScreen,
                showsLogo: true
            )

            if !model.snapshot.hasContent {
                ContentUnavailableView {
                    Label("No configuration loaded", systemImage: "tray")
                } description: {
                    Text("Load a local configuration to inspect servers, routing rules, and subscription data offline.")
                } actions: {
                    Button("Load local data") {
                        Task { await model.bootstrap() }
                    }
                    .accessibilityHint("Re-runs local preparation to load the offline fixture environment.")
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewLoadConfiguration)
                }
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.overviewEmptyNoContent
                ))
            } else {
                heroCard
                actions
                if let error = model.snapshot.lastError {
                    ErrorBanner(
                        error: error,
                        messageIdentifier: AppAccessibilityIdentifier.overviewErrorMessage,
                        dismissIdentifier: AppAccessibilityIdentifier.overviewErrorDismiss,
                        dismiss: { model.clearError() }
                    )
                }
                selectionCard
                fleetCard
                SampleDataNotice(identifier: AppAccessibilityIdentifier.overviewSampleNotice)
            }
        }
    }

    /// The connect powerhouse: one big round action, honest engine state,
    /// and the time since the last confirmed connection — the three things
    /// a person opens a VPN client to see, ahead of everything else.
    private var heroCard: some View {
        VStack(spacing: 18) {
            Button {
                Task { await runPrimaryAction() }
            } label: {
                ZStack {
                    Circle()
                        .stroke(engineTint.opacity(0.18), lineWidth: 8)
                        .frame(width: 148, height: 148)
                    if case .connected = model.snapshot.engine, !reduceMotion {
                        Circle()
                            .trim(from: 0, to: 0.72)
                            .stroke(
                                engineTint,
                                style: StrokeStyle(lineWidth: 8, lineCap: .round)
                            )
                            .frame(width: 148, height: 148)
                            .rotationEffect(.degrees(-90))
                    }
                    Circle()
                        .fill(engineTint.opacity(0.10))
                        .frame(width: 120, height: 120)
                    Image(systemName: "power")
                        .font(.system(size: 44, weight: .semibold))
                        .foregroundStyle(engineTint)
                }
                .contentShape(Circle())
                .padding(8)
            }
            .buttonStyle(.plain)
            .disabled(!model.snapshot.isPrimaryActionEnabled)
            .accessibilityLabel(model.snapshot.connectActionTitle)
            .accessibilityHint(model.snapshot.primaryActionHint)
            .accessibilityIdentifier(AppAccessibilityIdentifier.overviewPrimaryAction)

            VStack(spacing: 6) {
                HStack(spacing: 8) {
                    Image(systemName: engineIcon)
                        .foregroundStyle(engineTint)
                        .accessibilityHidden(true)
                    Text(model.snapshot.engineStatusText)
                        .font(.headline)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier(AppAccessibilityIdentifier.overviewEngineStatus)

                if let connectedSinceText = model.snapshot.connectedSinceText {
                    Text(connectedSinceText)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier(AppAccessibilityIdentifier.overviewConnectedSince)
                }

                Text(model.snapshot.systemStatusText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewSystemStatus)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(20)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 20))
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.25), value: model.snapshot.engine)
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                Task { await model.refreshStatus() }
            } label: {
                Label("Refresh tunnel status", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .disabled(model.snapshot.system != .ready)
            .accessibilityHint("Re-reads the engine status. Only a confirmed engine status can report a running tunnel.")
            .accessibilityIdentifier(AppAccessibilityIdentifier.overviewRefreshAction)

            Text(model.snapshot.primaryActionHint)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var selectionCard: some View {
        SectionCard(title: "Selected profile and group", systemImage: "checklist") {
            VStack(alignment: .leading, spacing: 12) {
                InfoRow(
                    label: "Profile",
                    value: model.snapshot.selectedProfileName ?? "None selected",
                    identifier: AppAccessibilityIdentifier.overviewSelection + ".profile"
                )
                InfoRow(
                    label: "Group",
                    value: model.snapshot.selectedGroupName ?? "None selected",
                    identifier: AppAccessibilityIdentifier.overviewSelection + ".group"
                )
                InfoRow(
                    label: "Server",
                    value: model.snapshot.selectedServerName ?? "None selected",
                    identifier: AppAccessibilityIdentifier.overviewSelection + ".server"
                )
                InfoRow(
                    label: "Latency",
                    value: model.snapshot.latency.displayText,
                    identifier: AppAccessibilityIdentifier.overviewLatency
                )
                InfoRow(
                    label: "Health confidence",
                    value: "\(model.snapshot.health.summary) · \(model.snapshot.healthEvidence.displayText)",
                    identifier: AppAccessibilityIdentifier.overviewHealth
                )
            }
        }
    }

    private var fleetCard: some View {
        SectionCard(title: "Sample servers", systemImage: "server.rack") {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(model.snapshot.content.servers.prefix(3)) { server in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(server.name)
                            .font(.subheadline.weight(.semibold))
                        Text("\(server.protocolLabel) · \(server.locationLabel)")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        HStack(spacing: 8) {
                            QualityBadge(latency: server.latency)
                            ConfidenceBadge(confidence: server.healthConfidence, evidence: server.health)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewServerRowPrefix + server.id)
                }
                Text("Open the Servers section to pick a group and a server.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var engineIcon: String {
        switch model.snapshot.engine {
        case .unknown:
            "questionmark.circle"
        case .unavailable:
            "xmark.shield"
        case .idle:
            "shield"
        case .starting, .stopping:
            "clock.arrow.circlepath"
        case .connected:
            "checkmark.shield"
        case .failed:
            "exclamationmark.shield"
        }
    }

    private var engineTint: Color {
        switch model.snapshot.engine {
        case .connected:
            .green
        case .unavailable, .failed:
            .red
        case .starting, .stopping:
            .orange
        case .unknown, .idle:
            .secondary
        }
    }

    private func runPrimaryAction() async {
        switch model.snapshot.primaryTunnelAction {
        case .disconnect:
            _ = await model.disconnect()
        case .connect:
            _ = await model.connect()
        case .unavailable, .busy:
            break
        }
    }
}
