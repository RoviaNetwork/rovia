import SwiftUI

/// The tunnel's operational settings. Honest about scope: the kill switch is
/// a property of the installed profile and the extension's failure handling,
/// applied on the next start — the label says so rather than implying a
/// mid-flight switch.
struct SettingsView: View {
    let model: AppModel

    var body: some View {
        RoviaScreen {
            RoviaScreenHeader(
                title: "Settings",
                subtitle: "Tunnel behaviour and appearance. Network-level protection is a property of the installed profile, applied when the tunnel starts.",
                identifier: AppAccessibilityIdentifier.settingsScreen
            )

            SectionCard(
                title: "Appearance",
                systemImage: "circle.lefthalf.filled",
                identifier: nil
            ) {
                VStack(alignment: .leading, spacing: 12) {
                    Picker(
                        "Appearance",
                        selection: Binding(
                            get: { model.snapshot.appearance },
                            set: { preference in
                                Task { _ = await model.setAppearance(preference) }
                            }
                        )
                    ) {
                        ForEach(AppearancePreference.allCases) { preference in
                            Text(preference.title).tag(preference)
                        }
                    }
                    .pickerStyle(.segmented)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.settingsAppearance)

                    Text("System follows the device. Light and Dark pin the app to that scheme regardless of the device setting.")
                        .font(.footnote)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            SectionCard(
                title: "Kill switch",
                systemImage: "shield.lefthalf.filled",
                identifier: nil
            ) {
                VStack(alignment: .leading, spacing: 12) {
                    Toggle(
                        "Block traffic when the tunnel drops",
                        isOn: Binding(
                            get: { model.snapshot.killSwitch },
                            set: { enabled in
                                Task { _ = await model.setKillSwitch(enabled) }
                            }
                        )
                    )
                    .tint(ScopeTheme.phosphor)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.settingsKillSwitch)

                    Text(
                        "When on, the installed profile asks iOS to drop all traffic whenever the tunnel is not running, and the extension tears the tunnel down if the engine fails. When off, a stopped tunnel leaves traffic on the normal route. Applies on the next start."
                    )
                    .font(.footnote)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier(AppAccessibilityIdentifier.settingsKillSwitchNote)
                }
            }

            SectionCard(
                title: "Tools",
                systemImage: "wrench.and.screwdriver",
                identifier: nil
            ) {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(ToolRoute.allCases) { tool in
                        NavigationLink {
                            toolDestination(tool)
                        } label: {
                            HStack {
                                Label(tool.title, systemImage: tool.systemImage)
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .font(.footnote.weight(.semibold))
                                    .foregroundStyle(ScopeTheme.inkSecondary)
                                    .accessibilityHidden(true)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 8)
                            .contentShape(Rectangle())
                        }
                        .foregroundStyle(ScopeTheme.ink)
                        .accessibilityIdentifier(tool.accessibilityIdentifier)
                        if tool.id != ToolRoute.allCases.last?.id {
                            Divider()
                                .overlay(ScopeTheme.etched.opacity(0.6))
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func toolDestination(_ tool: ToolRoute) -> some View {
        switch tool {
        case .routing:
            RoutingView(model: model)
        case .routingDebugger:
            RoutingDebuggerView(model: model)
        case .subscription:
            SubscriptionInspectorView(model: model)
        }
    }
}
