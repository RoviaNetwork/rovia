import SwiftUI

struct RoutingView: View {
    let model: AppModel

    var body: some View {
        Group {
            if model.snapshot.content.routeRules.isEmpty {
                ContentUnavailableView(
                    "No routing rules",
                    systemImage: "arrow.triangle.branch",
                    description: Text("Routing rules appear once a local configuration with rules is loaded.")
                )
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.routingEmpty
                ))
            } else {
                RoviaScreen {
                    RoviaScreenHeader(
                        title: "Routing",
                        subtitle: "Rules are read-only in this build. The first matching enabled rule decides the route.",
                        identifier: AppAccessibilityIdentifier.routingScreen
                    )
                    summaryCard
                    rulesCard
                    privacyCard
                    SampleDataNotice(identifier: AppAccessibilityIdentifier.routingScreen + ".notice")
                }
            }
        }
        .navigationTitle(ToolRoute.routing.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var summaryCard: some View {
        SectionCard(title: "Rule set", systemImage: "list.number") {
            VStack(alignment: .leading, spacing: 12) {
                InfoRow(
                    label: "Rules",
                    value: "\(model.snapshot.content.enabledRuleCount) enabled of \(model.snapshot.content.routeRules.count)",
                    identifier: AppAccessibilityIdentifier.routingSummary
                )
                Label {
                    Text("Default action: \(model.snapshot.content.defaultRoute.label(using: model.snapshot.content))")
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                } icon: {
                    Image(systemName: model.snapshot.content.defaultRoute.systemImage)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier(AppAccessibilityIdentifier.routingDefaultAction)
            }
        }
    }

    private var rulesCard: some View {
        SectionCard(
            title: "Rules in order",
            systemImage: "arrow.down.right.circle",
            identifier: AppAccessibilityIdentifier.routingRules
        ) {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(model.snapshot.content.routeRules) { rule in
                    ruleRow(rule)
                }
            }
        }
    }

    private func ruleRow(_ rule: RouteRuleSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text("Rule \(rule.index + 1)")
                        .font(.subheadline.weight(.semibold))
                    Text(rule.action.label(using: model.snapshot.content))
                        .font(.subheadline)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                    Spacer(minLength: 12)
                    ruleStateBadge(rule)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("Rule \(rule.index + 1)")
                        .font(.subheadline.weight(.semibold))
                    Text(rule.action.label(using: model.snapshot.content))
                        .font(.subheadline)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                    ruleStateBadge(rule)
                }
            }

            ForEach(rule.matchers) { matcher in
                Label(matcher.summaryText, systemImage: "line.3.horizontal.decrease.circle")
                    .font(.footnote)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let note = rule.note {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ScopeTheme.housing, in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Rule \(rule.index + 1), \(rule.isEnabled ? "enabled" : "disabled"), \(rule.action.label(using: model.snapshot.content))")
        .accessibilityValue(rule.matchers.map(\.summaryText).joined(separator: ", "))
        .accessibilityIdentifier(AppAccessibilityIdentifier.routingRulePrefix + String(rule.index))
    }

    private func ruleStateBadge(_ rule: RouteRuleSummary) -> some View {
        StatusBadge(
            text: rule.isEnabled ? "Enabled" : "Disabled",
            systemImage: rule.isEnabled ? "checkmark.circle" : "pause.circle",
            tint: rule.isEnabled ? .green : .secondary
        )
    }

    private var privacyCard: some View {
        SectionCard(
            title: "Privacy policy",
            systemImage: "hand.raised",
            identifier: AppAccessibilityIdentifier.routingPrivacy
        ) {
            VStack(alignment: .leading, spacing: 12) {
                InfoRow(label: "Telemetry", value: "Disabled", identifier: AppAccessibilityIdentifier.routingPrivacy + ".telemetry")
                InfoRow(label: "Traffic logging", value: "Disabled", identifier: AppAccessibilityIdentifier.routingPrivacy + ".traffic")
                InfoRow(label: "Browsing history", value: "Not collected", identifier: AppAccessibilityIdentifier.routingPrivacy + ".history")
                InfoRow(label: "Diagnostics", value: "Held in memory only", identifier: AppAccessibilityIdentifier.routingPrivacy + ".retention")
                InfoRow(label: "Server addresses", value: "Redacted by default", identifier: AppAccessibilityIdentifier.routingPrivacy + ".addresses")
                InfoRow(label: "Credentials", value: "Never displayed", identifier: AppAccessibilityIdentifier.routingPrivacy + ".credentials")
            }
        }
    }
}
