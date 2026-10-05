import SwiftUI

enum AppRoute: String, CaseIterable, Identifiable, Hashable {
    case overview
    case servers
    case statistics
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview:
            "Overview"
        case .servers:
            "Servers"
        case .statistics:
            "Statistics"
        case .settings:
            "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .overview:
            "scope"
        case .servers:
            "server.rack"
        case .statistics:
            "chart.bar.xaxis"
        case .settings:
            "gearshape"
        }
    }

    var accessibilityIdentifier: String {
        AppAccessibilityIdentifier.tabRoute(rawValue)
    }
}

/// The developer-facing instruments, reachable from Settings → Tools rather
/// than the tab bar: a working client shows four tabs, not seven.
enum ToolRoute: String, CaseIterable, Identifiable, Hashable {
    case routing
    case routingDebugger
    case subscription

    var id: String { rawValue }

    var title: String {
        switch self {
        case .routing:
            "Routing"
        case .routingDebugger:
            "Routing Debugger"
        case .subscription:
            "Subscriptions"
        }
    }

    var systemImage: String {
        switch self {
        case .routing:
            "arrow.triangle.branch"
        case .routingDebugger:
            "ladybug"
        case .subscription:
            "doc.text.magnifyingglass"
        }
    }

    var accessibilityIdentifier: String {
        "rovia.settings.tools.\(rawValue)"
    }
}

struct RootView: View {
    let model: AppModel

    var body: some View {
        TabView {
            ForEach(AppRoute.allCases) { route in
                NavigationStack {
                    detail(for: route)
                }
                .tabItem {
                    Label(route.title, systemImage: route.systemImage)
                }
                .accessibilityIdentifier(route.accessibilityIdentifier)
                .tag(route)
            }
        }
        .tint(ScopeTheme.phosphor)
        .background(ScopeTheme.ground.ignoresSafeArea())
    }

    @ViewBuilder
    private func detail(for route: AppRoute) -> some View {
        switch route {
        case .overview:
            OverviewView(model: model)
        case .servers:
            ServersView(model: model)
        case .statistics:
            StatisticsView(model: model)
        case .settings:
            SettingsView(model: model)
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
        .background(ScopeTheme.ground)
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
                    .foregroundStyle(ScopeTheme.ink)
                Text(subtitle)
                    .font(.body)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
        .accessibilityIdentifier(identifier)
    }
}

/// An instrument panel: the housing ground and an etched edge. One idea per
/// panel; nothing here is a card stack.
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
                    .foregroundStyle(ScopeTheme.ink)
            } icon: {
                if let systemImage {
                    Image(systemName: systemImage)
                        .foregroundStyle(ScopeTheme.inkSecondary)
                }
            }
            .accessibilityAddTraits(.isHeader)
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ScopeTheme.housing, in: RoundedRectangle(cornerRadius: 16))
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(ScopeTheme.etched.opacity(0.6), lineWidth: 1)
        )
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
    /// Measurements (ms, counters) read tabular, so a rerank never makes the
    /// line jump.
    var tabular: Bool = false

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(label)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                Spacer(minLength: 12)
                Text(value)
                    .font(tabular ? ScopeTheme.measurement(.body) : .body)
                    .multilineTextAlignment(.trailing)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .foregroundStyle(ScopeTheme.inkSecondary)
                Text(value)
                    .font(tabular ? ScopeTheme.measurement(.body) : .body)
            }
        }
        .font(.body)
        .foregroundStyle(ScopeTheme.ink)
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
        ScopeTheme.qualityTint(latency.quality)
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
        // Health reads quiet until evidence exists: an unknown confidence
        // earns no color, a measured one earns the state's tint.
        let tint: Color = switch confidence {
        case .unknown:
            ScopeTheme.inkSecondary
        case .low:
            ScopeTheme.alarm
        case .medium:
            ScopeTheme.warn
        case .high:
            ScopeTheme.phosphor
        }
        StatusBadge(
            text: "Health \(confidence.summary) · \(evidence.displayText)",
            systemImage: "heart.text.square",
            tint: tint
        )
    }
}

struct SampleDataNotice: View {
    let identifier: String
    var text = "Sample data from the offline fixture environment. No network request, tunnel, or profile is created."

    var body: some View {
        Label(text, systemImage: "shippingbox")
            .font(.footnote)
            .foregroundStyle(ScopeTheme.inkSecondary)
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
                .foregroundStyle(ScopeTheme.alarm)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(error.userMessage)
                    .font(.subheadline)
                    .foregroundStyle(ScopeTheme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier(messageIdentifier)
                Text(error.code)
                    .font(ScopeTheme.measurement(.caption))
                    .foregroundStyle(ScopeTheme.inkSecondary)
            }
            Spacer(minLength: 8)
            Button(action: dismiss) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(ScopeTheme.inkSecondary)
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss message")
            .accessibilityIdentifier(dismissIdentifier)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(ScopeTheme.alarm.opacity(0.12), in: RoundedRectangle(cornerRadius: 16))
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(ScopeTheme.alarm.opacity(0.35), lineWidth: 1)
        )
    }
}
