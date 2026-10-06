import SwiftUI

struct OverviewView: View {
    let model: AppModel

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
                subtitle: "The scope is the tunnel: the sweep runs only while the engine does, and every contact is a real server.",
                identifier: AppAccessibilityIdentifier.overviewScreen,
                showsLogo: true
            )

            if BuildVariant.isUIOnly {
                Label(
                    "UI-only development build: no VPN extension is embedded in this target, so Connect stays disabled. This is what a free Personal Team signature can install.",
                    systemImage: "hammer"
                )
                .font(.footnote)
                .foregroundStyle(ScopeTheme.warn)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityElement(children: .combine)
            }

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
                scopeCard
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

    /// The instrument cluster: the scope with the connect control at its
    /// center, the state annunciator beneath, and the refresh alongside —
    /// the three things a person opens a VPN client to read, ahead of
    /// everything else.
    private var scopeCard: some View {
        VStack(spacing: 16) {
            ScopeView(
                engine: model.snapshot.engine,
                contacts: scopeContacts,
                selectedServer: model.snapshot.selection.server,
                actionEnabled: model.snapshot.isPrimaryActionEnabled,
                action: { Task { await runPrimaryAction() } },
                identifier: AppAccessibilityIdentifier.overviewPrimaryAction,
                actionLabel: model.snapshot.connectActionTitle,
                actionHint: model.snapshot.primaryActionHint
            )

            VStack(spacing: 6) {
                Text(model.snapshot.engineStatusText)
                    .font(.headline)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewEngineStatus)

                if let connectedSinceText = model.snapshot.connectedSinceText {
                    Text(connectedSinceText)
                        .font(ScopeTheme.measurement(.subheadline))
                        .foregroundStyle(ScopeTheme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier(AppAccessibilityIdentifier.overviewConnectedSince)
                }

                Text(model.snapshot.systemStatusText)
                    .font(.footnote)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewSystemStatus)
            }

            Button {
                Task { await model.refreshStatus() }
            } label: {
                Label("Refresh tunnel status", systemImage: "arrow.clockwise")
                    .font(.subheadline)
            }
            .buttonStyle(.plain)
            .foregroundStyle(ScopeTheme.inkSecondary)
            .disabled(model.snapshot.system != .ready)
            .accessibilityHint("Re-reads the engine status. Only a confirmed engine status can report a running tunnel.")
            .accessibilityIdentifier(AppAccessibilityIdentifier.overviewRefreshAction)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 20)
        .animation(ScopeTheme.stateChange, value: model.snapshot.engine)
    }

    /// The fastest members of the fleet, up to six: close contacts are fast
    /// servers. Sorted by measurement so a fresh probe reranks them in place.
    private var scopeContacts: [ServerSummary] {
        model.snapshot.content.servers
            .sorted {
                ($0.latency.milliseconds ?? .max) < ($1.latency.milliseconds ?? .max)
            }
            .prefix(6)
            .map { $0 }
    }

    private var selectionCard: some View {
        SectionCard(title: "Locked contact", systemImage: "scope") {
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
                    identifier: AppAccessibilityIdentifier.overviewLatency,
                    tabular: true
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
        SectionCard(title: "Fleet", systemImage: "server.rack") {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(model.snapshot.content.servers.prefix(3).enumerated()), id: \.element.id) { index, server in
                    if index > 0 {
                        Divider()
                            .overlay(ScopeTheme.etched.opacity(0.6))
                            .padding(.vertical, 4)
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        Text(server.name)
                            .font(.subheadline.weight(.semibold))
                        Text("\(server.protocolLabel) · \(server.locationLabel)")
                            .font(.footnote)
                            .foregroundStyle(ScopeTheme.inkSecondary)
                        HStack(spacing: 8) {
                            QualityBadge(latency: server.latency)
                            ConfidenceBadge(confidence: server.healthConfidence, evidence: server.health)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
                    .accessibilityElement(children: .combine)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.overviewServerRowPrefix + server.id)
                }
                Text("Open the Servers tab to lock a different contact.")
                    .font(.footnote)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .padding(.top, 8)
            }
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
