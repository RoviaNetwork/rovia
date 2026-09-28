import SwiftUI

enum AppRoute: String, CaseIterable, Identifiable, Hashable {
    case overview
    case servers
    case routing
    case routingDebugger
    case subscription

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview:
            "Overview"
        case .servers:
            "Servers"
        case .routing:
            "Routing"
        case .routingDebugger:
            "Routing Debugger"
        case .subscription:
            "Subscriptions"
        }
    }

    var shortTitle: String {
        switch self {
        case .overview:
            "Overview"
        case .servers:
            "Servers"
        case .routing:
            "Routing"
        case .routingDebugger:
            "Debugger"
        case .subscription:
            "Subscription"
        }
    }

    var systemImage: String {
        switch self {
        case .overview:
            "gauge.with.dots.needle.33percent"
        case .servers:
            "server.rack"
        case .routing:
            "arrow.triangle.branch"
        case .routingDebugger:
            "ladybug"
        case .subscription:
            "doc.text.magnifyingglass"
        }
    }

    var accessibilityIdentifier: String {
        AppAccessibilityIdentifier.sidebarRoute(rawValue)
    }
}

struct RootView: View {
    let model: AppModel

    @State private var route: AppRoute? = .overview
    @State private var columnVisibility: NavigationSplitViewVisibility = .automatic

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 10) {
                    RoviaLogoView(.navigation)
                    Text("Rovia")
                        .font(.headline)
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                List(AppRoute.allCases, selection: $route) { destination in
                    Label(destination.title, systemImage: destination.systemImage)
                        .tag(destination)
                        .accessibilityIdentifier(destination.accessibilityIdentifier)
                }
                .listStyle(.sidebar)
            }
            .navigationTitle("Rovia")
        } detail: {
            detail
        }
        .navigationSplitViewStyle(.balanced)
    }

    @ViewBuilder
    private var detail: some View {
        switch route {
        case .overview:
            OverviewView(model: model)
        case .servers:
            ServersView(model: model)
        case .routing:
            RoutingView(model: model)
        case .routingDebugger:
            RoutingDebuggerView(model: model)
        case .subscription:
            SubscriptionInspectorView(model: model)
        case nil:
            ContentUnavailableView(
                "Choose a section",
                systemImage: "sidebar.left",
                description: Text("Open Overview, Servers, Routing, Routing Debugger, or Subscription Inspector from the sidebar.")
            )
            .modifier(ConditionalAccessibilityIdentifier(identifier: AppAccessibilityIdentifier.emptySelection))
        }
    }
}

struct RoviaScreen<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                content
            }
            .padding(20)
            .frame(maxWidth: 720, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct RoviaScreenHeader: View {
    let title: String
    let subtitle: String
    let identifier: String
    var showsLogo: Bool = false

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            if showsLogo {
                RoviaLogoView(.header)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.largeTitle.weight(.semibold))
                Text(subtitle)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
        .accessibilityIdentifier(identifier)
    }
}

struct SectionCard<Content: View>: View {
    let title: String
    var systemImage: String?
    var identifier: String?
    @ViewBuilder var content: Content

    init(
        title: String,
        systemImage: String? = nil,
        identifier: String? = nil,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.systemImage = systemImage
        self.identifier = identifier
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label {
                Text(title)
                    .font(.headline)
            } icon: {
                if let systemImage {
                    Image(systemName: systemImage)
                }
            }
            .accessibilityAddTraits(.isHeader)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 16))
        .modifier(ConditionalAccessibilityIdentifier(identifier: identifier))
    }
}

struct ConditionalAccessibilityIdentifier: ViewModifier {
    let identifier: String?

    func body(content: Content) -> some View {
        if let identifier {
            content
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier(identifier)
        } else {
            content
        }
    }
}

struct InfoRow: View {
    let label: String
    let value: String
    let identifier: String

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(label)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 12)
                Text(value)
                    .multilineTextAlignment(.trailing)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .foregroundStyle(.secondary)
                Text(value)
            }
        }
        .font(.body)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(identifier)
    }
}

struct StatusBadge: View {
    let text: String
    let systemImage: String
    let tint: Color

    var body: some View {
        Label(text, systemImage: systemImage)
            .font(.caption)
            .labelStyle(.titleAndIcon)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .foregroundStyle(tint)
            .background(tint.opacity(0.15), in: Capsule())
            .fixedSize(horizontal: false, vertical: true)
    }
}

struct QualityBadge: View {
    let latency: LatencyState

    private var tint: Color {
        switch latency.quality {
        case .unavailable:
            .secondary
        case .good:
            .green
        case .fair:
            .orange
        case .poor:
            .red
        }
    }

    private var systemImage: String {
        switch latency.quality {
        case .unavailable:
            "questionmark.circle"
        case .good:
            "bolt.horizontal.circle.fill"
        case .fair:
            "bolt.horizontal.circle"
        case .poor:
            "exclamationmark.triangle.fill"
        }
    }

    var body: some View {
        StatusBadge(text: "\(latency.displayText) · \(latency.quality.summary)", systemImage: systemImage, tint: tint)
    }
}

struct ConfidenceBadge: View {
    let confidence: HealthConfidence
    let evidence: HealthEvidence

    var body: some View {
        StatusBadge(
            text: "Health \(confidence.summary) · \(evidence.displayText)",
            systemImage: "heart.text.square",
            tint: .accentColor
        )
    }
}

struct SampleDataNotice: View {
    let identifier: String
    var text = "Sample data from the offline fixture environment. No network request, tunnel, or profile is created."

    var body: some View {
        Label(text, systemImage: "shippingbox")
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier(identifier)
    }
}

struct ErrorBanner: View {
    let error: AppError
    let messageIdentifier: String
    let dismissIdentifier: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(error.userMessage)
                    .font(.subheadline)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier(messageIdentifier)
                Text(error.code)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            Button(action: dismiss) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss message")
            .accessibilityIdentifier(dismissIdentifier)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 16))
    }
}
