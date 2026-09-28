import SwiftUI

struct SubscriptionInspectorView: View {
    let model: AppModel

    var body: some View {
        Group {
            if model.snapshot.content.subscription == nil {
                ContentUnavailableView {
                    Label {
                        Text("No subscription loaded")
                    } icon: {
                        RoviaLogoView(.emptyState)
                    }
                } description: {
                    Text("Rovia does not fetch subscriptions in this build. Load a local configuration to inspect parsed results offline.")
                }
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.subscriptionEmpty
                ))
            } else {
                RoviaScreen {
                    RoviaScreenHeader(
                        title: "Subscription Inspector",
                        subtitle: "Local parse results with every endpoint redacted. No network request is made in this build.",
                        identifier: AppAccessibilityIdentifier.subscriptionScreen
                    )
                    summaryCard
                    entriesCard
                    redactionNotice
                    SampleDataNotice(identifier: AppAccessibilityIdentifier.subscriptionScreen + ".notice")
                }
            }
        }
        .navigationTitle(AppRoute.subscription.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var summaryCard: some View {
        SectionCard(title: "Source", systemImage: "link") {
            if let subscription = model.snapshot.content.subscription {
                VStack(alignment: .leading, spacing: 12) {
                    InfoRow(
                        label: "Name",
                        value: subscription.name,
                        identifier: AppAccessibilityIdentifier.subscriptionSummary + ".name"
                    )
                    InfoRow(
                        label: "Source kind",
                        value: subscription.sourceKindLabel,
                        identifier: AppAccessibilityIdentifier.subscriptionSummary + ".kind"
                    )
                    InfoRow(
                        label: "Source value",
                        value: subscription.sourceDisplayValue,
                        identifier: AppAccessibilityIdentifier.subscriptionSummary + ".value"
                    )
                    InfoRow(
                        label: "Accepted entries",
                        value: "\(subscription.acceptedCount)",
                        identifier: AppAccessibilityIdentifier.subscriptionSummary + ".accepted"
                    )
                    InfoRow(
                        label: "Rejected entries",
                        value: "\(subscription.rejectedCount)",
                        identifier: AppAccessibilityIdentifier.subscriptionSummary + ".rejected"
                    )
                }
            }
        }
    }

    private var entriesCard: some View {
        SectionCard(
            title: "Parsed entries",
            systemImage: "list.bullet.rectangle",
            identifier: AppAccessibilityIdentifier.subscriptionEntries
        ) {
            VStack(alignment: .leading, spacing: 12) {
                if let subscription = model.snapshot.content.subscription {
                    ForEach(subscription.entries) { entry in
                        entryRow(entry)
                    }
                }
            }
        }
    }

    private func entryRow(_ entry: SubscriptionEntrySummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(entry.displayName)
                        .font(.subheadline.weight(.semibold))
                    Spacer(minLength: 12)
                    statusBadge(entry)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(entry.displayName)
                        .font(.subheadline.weight(.semibold))
                    statusBadge(entry)
                }
            }
            Text("\(entry.protocolLabel) · \(entry.redactedEndpointLabel)")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.25), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityLabel(entry.displayName)
        .accessibilityValue("\(entry.statusLabel), \(entry.protocolLabel), \(entry.redactedEndpointLabel)")
        .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionEntryPrefix + entry.id)
    }

    private func statusBadge(_ entry: SubscriptionEntrySummary) -> some View {
        StatusBadge(
            text: entry.statusLabel,
            systemImage: entry.isAccepted ? "checkmark.circle" : "xmark.circle",
            tint: entry.isAccepted ? .green : .orange
        )
    }

    private var redactionNotice: some View {
        Label(
            "Credentials are never shown. Server addresses are replaced with a redacted placeholder, and nothing is written to disk.",
            systemImage: "eye.slash"
        )
        .font(.footnote)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(AppAccessibilityIdentifier.subscriptionRedaction)
    }
}
