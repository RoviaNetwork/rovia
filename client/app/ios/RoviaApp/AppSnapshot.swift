import Foundation

typealias ProfileID = String
typealias ServerID = String
typealias ServerGroupID = String
typealias RouteRuleID = String
typealias DebugSampleID = String

enum AppAccessibilityIdentifier {
    static let emptySelection = "rovia.root.emptySelection"

    static let overviewScreen = "rovia.overview.screen"
    static let overviewEngineStatus = "rovia.overview.engineStatus"
    static let overviewConnectedSince = "rovia.overview.connectedSince"
    static let overviewSystemStatus = "rovia.overview.systemStatus"
    static let overviewSelection = "rovia.overview.selection"
    static let overviewLatency = "rovia.overview.latency"
    static let overviewHealth = "rovia.overview.health"
    static let overviewPrimaryAction = "rovia.overview.primaryAction"
    static let overviewRefreshAction = "rovia.overview.refreshStatus"
    static let overviewErrorMessage = "rovia.overview.errorMessage"
    static let overviewErrorDismiss = "rovia.overview.errorDismiss"
    static let overviewRetry = "rovia.overview.retry"
    static let overviewLoadConfiguration = "rovia.overview.loadConfiguration"
    static let overviewEmptyFailed = "rovia.overview.empty.failed"
    static let overviewEmptyNoContent = "rovia.overview.empty.noContent"
    static let overviewPreparing = "rovia.overview.preparing"
    static let overviewSampleNotice = "rovia.overview.sampleNotice"
    static let overviewServerRowPrefix = "rovia.overview.server."

    static let serversScreen = "rovia.servers.screen"
    static let serversProfileMenu = "rovia.servers.profileMenu"
    static let serversGroupMenu = "rovia.servers.groupMenu"
    static let serversList = "rovia.servers.list"
    static let serversRowPrefix = "rovia.servers.row."
    static let serversEmpty = "rovia.servers.empty"

    static let routingScreen = "rovia.routing.screen"
    static let routingSummary = "rovia.routing.summary"
    static let routingDefaultAction = "rovia.routing.defaultAction"
    static let routingRules = "rovia.routing.rules"
    static let routingRulePrefix = "rovia.routing.rule."
    static let routingPrivacy = "rovia.routing.privacy"
    static let routingEmpty = "rovia.routing.empty"

    static let routingDebuggerScreen = "rovia.routingDebugger.screen"
    static let routingDebuggerSampleMenu = "rovia.routingDebugger.sampleMenu"
    static let routingDebuggerExplain = "rovia.routingDebugger.explain"
    static let routingDebuggerDecision = "rovia.routingDebugger.decision"
    static let routingDebuggerSteps = "rovia.routingDebugger.steps"
    static let routingDebuggerStepPrefix = "rovia.routingDebugger.step."
    static let routingDebuggerRedaction = "rovia.routingDebugger.redaction"
    static let routingDebuggerEmpty = "rovia.routingDebugger.empty"

    static let subscriptionScreen = "rovia.subscription.screen"
    static let subscriptionSummary = "rovia.subscription.summary"
    static let subscriptionEntries = "rovia.subscription.entries"
    static let subscriptionEntryPrefix = "rovia.subscription.entry."
    static let subscriptionRedaction = "rovia.subscription.redaction"
    static let subscriptionEmpty = "rovia.subscription.empty"

    static func sidebarRoute(_ rawValue: String) -> String {
        "rovia.sidebar.\(rawValue)"
    }

    static let containerIdentifiers: [String] = [
        emptySelection,
        overviewEmptyFailed,
        overviewEmptyNoContent,
        serversList,
        serversEmpty,
        routingRules,
        routingPrivacy,
        routingEmpty,
        routingDebuggerSteps,
        routingDebuggerEmpty,
        subscriptionEntries,
        subscriptionEmpty
    ]

    static let elementIdentifiers: [String] = [
        overviewScreen,
        overviewEngineStatus,
        overviewConnectedSince,
        overviewSystemStatus,
        overviewSelection,
        overviewLatency,
        overviewHealth,
        overviewPrimaryAction,
        overviewRefreshAction,
        overviewErrorMessage,
        overviewErrorDismiss,
        overviewRetry,
        overviewLoadConfiguration,
        overviewPreparing,
        overviewSampleNotice,
        overviewServerRowPrefix,
        serversScreen,
        serversProfileMenu,
        serversGroupMenu,
        serversRowPrefix,
        routingScreen,
        routingSummary,
        routingDefaultAction,
        routingRulePrefix,
        routingDebuggerScreen,
        routingDebuggerSampleMenu,
        routingDebuggerExplain,
        routingDebuggerDecision,
        routingDebuggerStepPrefix,
        routingDebuggerRedaction,
        subscriptionScreen,
        subscriptionSummary,
        subscriptionEntryPrefix,
        subscriptionRedaction
    ]
}

enum SystemState: Equatable, Sendable {
    case idle
    case preparing
    case ready
    case failed(AppError)

    var statusText: String {
        switch self {
        case .idle:
            "Not prepared"
        case .preparing:
            "Preparing local data"
        case .ready:
            "Prepared"
        case let .failed(error):
            error.userMessage
        }
    }
}

enum EngineUnavailableReason: String, Equatable, Sendable, CaseIterable {
    case noEngineConfigured
    case engineBinaryMissing
    case engineSignatureUnverified
    case platformUnsupported

    var summary: String {
        switch self {
        case .noEngineConfigured:
            "No tunnel engine is bundled in this build."
        case .engineBinaryMissing:
            "The tunnel engine binary is missing from this build."
        case .engineSignatureUnverified:
            "The tunnel engine signature could not be verified."
        case .platformUnsupported:
            "Tunneling is not supported on this platform."
        }
    }
}

enum EngineAvailability: Equatable, Sendable {
    case available
    case unavailable(EngineUnavailableReason)
}

enum TunnelStatus: Equatable, Sendable {
    case engineUnavailable(EngineUnavailableReason)
    case disconnected
    case connecting
    case connected
    case disconnecting
    case reasserting
}

enum TunnelState: Equatable, Sendable {
    case unknown
    case unavailable(EngineUnavailableReason)
    case idle
    case starting
    case connected(since: Date)
    case stopping
    case failed(AppError)

    var isConnected: Bool {
        if case .connected = self { return true }
        return false
    }

    var isBusy: Bool {
        switch self {
        case .starting, .stopping:
            true
        case .unknown, .unavailable, .idle, .connected, .failed:
            false
        }
    }

    var allowsStart: Bool {
        switch self {
        case .unavailable, .connected, .stopping:
            false
        case .unknown, .idle, .starting, .failed:
            true
        }
    }

    var allowsStop: Bool {
        switch self {
        case .starting, .connected:
            true
        case .unknown, .unavailable, .idle, .stopping, .failed:
            false
        }
    }

    var unavailableReason: EngineUnavailableReason? {
        if case let .unavailable(reason) = self { return reason }
        return nil
    }

    var statusText: String {
        switch self {
        case .unknown:
            "Not checked yet"
        case let .unavailable(reason):
            "Unavailable — \(reason.summary)"
        case .idle:
            "Ready to start"
        case .starting:
            "Start requested — awaiting engine confirmation"
        case .connected:
            "Engine confirmed a running tunnel"
        case .stopping:
            "Stop requested"
        case let .failed(error):
            "Failed — \(error.userMessage)"
        }
    }
}

enum TunnelControlFailure: Error, Equatable, Sendable {
    case engineUnavailable
    case permissionDenied
    case configurationRejected
    case timedOut
    case unknown
}

enum AppOperation: String, Equatable, Sendable {
    case bootstrap
    case connect
    case disconnect
    case refreshStatus
}

enum AppError: Error, Equatable, Sendable, CustomStringConvertible {
    case engineUnavailable(reason: EngineUnavailableReason)
    case tunnelStartRejected(code: String)
    case tunnelStopRejected(code: String)
    case tunnelStatusRejected(code: String)
    case fixtureLoadFailed(code: String)
    case routeExplanationFailed(code: String)
    case unknown(code: String)

    static let engineUnavailableCode = "engine.unavailable"
    static let fixtureLoadFailedCode = "fixtures.load.failed"
    static let routeExplanationFailedCode = "route.explanation.failed"

    init(sanitizing underlying: some Error, operation: AppOperation) {
        if let failure = underlying as? TunnelControlFailure {
            switch (operation, failure) {
            case (_, .engineUnavailable):
                self = .engineUnavailable(reason: .noEngineConfigured)
            case (.connect, .permissionDenied):
                self = .tunnelStartRejected(code: "tunnel.start.permission-denied")
            case (.connect, .configurationRejected):
                self = .tunnelStartRejected(code: "tunnel.start.configuration-rejected")
            case (.connect, .timedOut):
                self = .tunnelStartRejected(code: "tunnel.start.timed-out")
            case (.connect, .unknown):
                self = .tunnelStartRejected(code: "tunnel.start.rejected")
            case (.disconnect, .permissionDenied):
                self = .tunnelStopRejected(code: "tunnel.stop.permission-denied")
            case (.disconnect, .configurationRejected):
                self = .tunnelStopRejected(code: "tunnel.stop.configuration-rejected")
            case (.disconnect, .timedOut):
                self = .tunnelStopRejected(code: "tunnel.stop.timed-out")
            case (.disconnect, .unknown):
                self = .tunnelStopRejected(code: "tunnel.stop.rejected")
            case (.refreshStatus, .permissionDenied):
                self = .tunnelStatusRejected(code: "tunnel.status.permission-denied")
            case (.refreshStatus, .configurationRejected):
                self = .tunnelStatusRejected(code: "tunnel.status.configuration-rejected")
            case (.refreshStatus, .timedOut):
                self = .tunnelStatusRejected(code: "tunnel.status.timed-out")
            case (.refreshStatus, .unknown):
                self = .tunnelStatusRejected(code: "tunnel.status.rejected")
            case (.bootstrap, _):
                self = .fixtureLoadFailed(code: Self.fixtureLoadFailedCode)
            }
            return
        }
        switch operation {
        case .bootstrap:
            self = .fixtureLoadFailed(code: Self.fixtureLoadFailedCode)
        case .connect, .disconnect, .refreshStatus:
            self = .unknown(code: "app.\(operation.rawValue).failed")
        }
    }

    var code: String {
        switch self {
        case .engineUnavailable:
            Self.engineUnavailableCode
        case let .tunnelStartRejected(code):
            code
        case let .tunnelStopRejected(code):
            code
        case let .tunnelStatusRejected(code):
            code
        case let .fixtureLoadFailed(code):
            code
        case let .routeExplanationFailed(code):
            code
        case let .unknown(code):
            code
        }
    }

    var userMessage: String {
        switch self {
        case .engineUnavailable:
            "The tunnel engine is not available in this build, so a VPN connection cannot be started."
        case let .tunnelStartRejected(code):
            switch code {
            case "tunnel.start.permission-denied":
                "System permission was refused, so no tunnel was started."
            case "tunnel.start.configuration-rejected":
                "The system rejected the VPN configuration, so no tunnel was started."
            case "tunnel.start.timed-out":
                "The engine did not accept the start request in time."
            default:
                "The system refused to start the tunnel."
            }
        case let .tunnelStopRejected(code):
            switch code {
            case "tunnel.stop.permission-denied":
                "System permission was refused, so the stop request was not sent."
            case "tunnel.stop.configuration-rejected":
                "The system rejected the stop request for the VPN configuration."
            case "tunnel.stop.timed-out":
                "The engine did not accept the stop request in time."
            default:
                "The system refused to stop the tunnel."
            }
        case let .tunnelStatusRejected(code):
            switch code {
            case "tunnel.status.permission-denied":
                "System permission was refused while reading the tunnel status."
            case "tunnel.status.configuration-rejected":
                "The system rejected the status request for the VPN configuration."
            case "tunnel.status.timed-out":
                "The engine did not report a tunnel status in time."
            default:
                "The tunnel status could not be read."
            }
        case .fixtureLoadFailed:
            "The local sample configuration could not be loaded."
        case .routeExplanationFailed:
            "The routing explanation could not be produced, because the routing policy could not be read in the form the route model requires."
        case .unknown:
            "The operation could not be completed."
        }
    }

    var description: String {
        "AppError(\(code))"
    }
}

struct SelectionState: Equatable, Sendable {
    var profile: ProfileID?
    var group: ServerGroupID?
    var server: ServerID?
    var debugSample: DebugSampleID?

    static let none = SelectionState()

    var isEmpty: Bool {
        profile == nil && group == nil && server == nil && debugSample == nil
    }
}

struct LatencyState: Equatable, Sendable {
    enum Quality: String, Equatable, Sendable, CaseIterable {
        case unavailable
        case good
        case fair
        case poor

        var summary: String {
            switch self {
            case .unavailable:
                "No measurement"
            case .good:
                "Good"
            case .fair:
                "Fair"
            case .poor:
                "Poor"
            }
        }
    }

    let milliseconds: Int?
    let observedAt: Date?

    init(milliseconds: Int?, observedAt: Date? = nil) {
        self.milliseconds = milliseconds
        self.observedAt = observedAt
    }

    var quality: Quality {
        guard let milliseconds, milliseconds >= 0 else { return .unavailable }
        switch milliseconds {
        case ..<150:
            return .good
        case ..<400:
            return .fair
        default:
            return .poor
        }
    }

    var displayText: String {
        guard let milliseconds else { return "Not measured" }
        return "\(milliseconds) ms"
    }

    static let notMeasured = LatencyState(milliseconds: nil)
}

enum HealthConfidence: String, Equatable, Sendable, CaseIterable {
    case unknown
    case low
    case medium
    case high

    var summary: String {
        switch self {
        case .unknown:
            "Unknown"
        case .low:
            "Low"
        case .medium:
            "Medium"
        case .high:
            "High"
        }
    }

    var detail: String {
        switch self {
        case .unknown:
            "No health samples have been collected."
        case .low:
            "Too few samples to trust a health verdict."
        case .medium:
            "A few samples are available."
        case .high:
            "Enough recent samples agree on this server."
        }
    }

    static func confidence(sampleCount: Int, successCount: Int) -> HealthConfidence {
        guard sampleCount > 0 else { return .unknown }
        switch sampleCount {
        case 1...2:
            return .low
        case 3...4:
            return .medium
        default:
            let successes = min(max(successCount, 0), sampleCount)
            return Double(successes) / Double(sampleCount) >= 0.75 ? .high : .low
        }
    }
}

struct HealthEvidence: Equatable, Sendable {
    let sampleCount: Int
    let successCount: Int

    init(sampleCount: Int, successCount: Int) {
        self.sampleCount = max(sampleCount, 0)
        self.successCount = min(max(successCount, 0), self.sampleCount)
    }

    var confidence: HealthConfidence {
        HealthConfidence.confidence(sampleCount: sampleCount, successCount: successCount)
    }

    var normalizedSuccessCount: Int {
        successCount
    }

    var displayText: String {
        guard sampleCount > 0 else { return "No samples" }
        return "\(successCount) of \(sampleCount) samples succeeded"
    }

    static let none = HealthEvidence(sampleCount: 0, successCount: 0)
}

struct ProfileSummary: Equatable, Sendable, Identifiable {
    let id: ProfileID
    let name: String
    let sourceKindLabel: String
    let serverIDs: [ServerID]
}

struct ServerSummary: Equatable, Sendable, Identifiable {
    let id: ServerID
    let name: String
    let protocolLabel: String
    let locationLabel: String
    let latency: LatencyState
    let health: HealthEvidence
    let groupIDs: [ServerGroupID]

    var healthConfidence: HealthConfidence {
        health.confidence
    }

    func withLatency(_ latency: LatencyState) -> ServerSummary {
        ServerSummary(
            id: id,
            name: name,
            protocolLabel: protocolLabel,
            locationLabel: locationLabel,
            latency: latency,
            health: health,
            groupIDs: groupIDs
        )
    }
}

struct ServerGroupSummary: Equatable, Sendable, Identifiable {
    let id: ServerGroupID
    let name: String
    let modeLabel: String
    let policyLabel: String
    let memberIDs: [ServerID]

    func contains(_ serverID: ServerID) -> Bool {
        memberIDs.contains(serverID)
    }
}

enum RouteOutcome: Equatable, Sendable {
    case direct
    case block
    case group(ServerGroupID)
    case unavailable

    var isResolved: Bool {
        if case .unavailable = self { return false }
        return true
    }

    var label: String {
        switch self {
        case .direct:
            "Direct"
        case .block:
            "Blocked"
        case .group:
            "Server group"
        case .unavailable:
            "Unavailable"
        }
    }

    var systemImage: String {
        switch self {
        case .direct:
            "arrow.right"
        case .block:
            "hand.raised.fill"
        case .group:
            "server.rack"
        case .unavailable:
            "questionmark.circle"
        }
    }

    func label(using content: AppContent) -> String {
        switch self {
        case let .group(id):
            content.group(id: id).map { "\($0.name)" } ?? "Unknown group"
        default:
            label
        }
    }

    var groupID: ServerGroupID? {
        if case let .group(id) = self { return id }
        return nil
    }
}

enum RouteMatcherKind: String, Equatable, Sendable, CaseIterable {
    case domain
    case domainSuffix
    case ipCIDR
    case port
    case portRange
    case network

    var summary: String {
        switch self {
        case .domain:
            "Domain"
        case .domainSuffix:
            "Domain suffix"
        case .ipCIDR:
            "IP range"
        case .port:
            "Port"
        case .portRange:
            "Port range"
        case .network:
            "Network"
        }
    }
}

struct DebugInput: Equatable, Sendable {
    var host: String?
    var ip: String?
    var port: Int?
    var network: String?

    init(host: String? = nil, ip: String? = nil, port: Int? = nil, network: String? = nil) {
        self.host = host
        self.ip = ip
        self.port = port
        self.network = network
    }
}

/// A matcher as the debugger lists it.
///
/// The values are display data. Nothing here decides whether a matcher matches:
/// `CanonicalRouteBridge` hands them to `RoviaRouting.RouteEvaluator`, and the
/// answer comes back as a canonical `RoutingDiagnostic`. An earlier version of
/// this file compared hosts, ports, and CIDR ranges itself, which was a second
/// implementation of the canonical evaluator that could disagree with it.
struct RouteMatcherSummary: Equatable, Sendable, Identifiable {
    let id: String
    let kind: RouteMatcherKind
    let value: String
    let upperValue: String?

    init(id: String, kind: RouteMatcherKind, value: String, upperValue: String? = nil) {
        self.id = id
        self.kind = kind
        self.value = value
        self.upperValue = upperValue
    }

    var valueLabel: String {
        switch kind {
        case .portRange:
            "\(value)–\(upperValue ?? value)"
        case .domain, .domainSuffix, .ipCIDR, .port, .network:
            value
        }
    }

    var summaryText: String {
        "\(kind.summary) \(valueLabel)"
    }
}

struct RouteRuleSummary: Equatable, Sendable, Identifiable {
    let id: RouteRuleID
    let index: Int
    let isEnabled: Bool
    let action: RouteOutcome
    let matchers: [RouteMatcherSummary]
    let note: String?
}

struct DebugSampleSummary: Equatable, Sendable, Identifiable {
    let id: DebugSampleID
    let label: String
    let detail: String
    let input: DebugInput
}

enum DebugReason: String, Equatable, Sendable, CaseIterable {
    case ruleDisabled
    case noMatcherMatched
    case applied
    case shadowed

    var summary: String {
        switch self {
        case .ruleDisabled:
            "Rule disabled"
        case .noMatcherMatched:
            "No matcher matched"
        case .applied:
            "Decided the route"
        case .shadowed:
            "Matched after the deciding rule"
        }
    }
}

struct DebugStep: Equatable, Sendable, Identifiable {
    let ruleIndex: Int
    let ruleID: RouteRuleID
    let isEnabled: Bool
    let matched: Bool
    let appliedMatcherIndex: Int?
    let evaluatedMatcherCount: Int
    let reason: DebugReason

    var id: Int { ruleIndex }
}

/// The debugger's rendering of one canonical `RoutingDiagnostic`.
///
/// Every field here is copied from the canonical diagnostic by
/// `CanonicalRouteBridge`. There is no second evaluation: the app does not decide
/// which rule matched, and it holds no destination at all. The debugger has no
/// text field — it evaluates one of the content's built-in samples — and the only
/// thing this model can say about an input is whether it was present.
struct DebugEvaluation: Equatable, Sendable {
    let sampleID: DebugSampleID
    let sampleLabel: String
    let inputPresence: String
    let decision: RouteOutcome
    let selectedGroupID: ServerGroupID?
    let appliedRuleIndex: Int?
    let steps: [DebugStep]
    let isSampleData: Bool

    init(
        sampleID: DebugSampleID,
        sampleLabel: String,
        inputPresence: String,
        decision: RouteOutcome,
        selectedGroupID: ServerGroupID?,
        appliedRuleIndex: Int?,
        steps: [DebugStep],
        isSampleData: Bool
    ) {
        self.sampleID = sampleID
        self.sampleLabel = sampleLabel
        self.inputPresence = inputPresence
        self.decision = decision
        self.selectedGroupID = selectedGroupID
        self.appliedRuleIndex = appliedRuleIndex
        self.steps = steps
        self.isSampleData = isSampleData
    }
}

struct SubscriptionEntrySummary: Equatable, Sendable, Identifiable {
    let id: ServerID
    let displayName: String
    let protocolLabel: String
    let redactedEndpointLabel: String
    let statusLabel: String

    var isAccepted: Bool {
        statusLabel == "Accepted"
    }
}

struct SubscriptionSummary: Equatable, Sendable, Identifiable {
    let id: ProfileID
    let name: String
    let sourceKindLabel: String
    let sourceDisplayValue: String
    let acceptedCount: Int
    let rejectedCount: Int
    let isSampleData: Bool
    let entries: [SubscriptionEntrySummary]

    var hasRejectedEntries: Bool {
        rejectedCount > 0
    }
}

struct AppContent: Equatable, Sendable {
    var profiles: [ProfileSummary] = []
    var servers: [ServerSummary] = []
    var groups: [ServerGroupSummary] = []
    var routeRules: [RouteRuleSummary] = []
    var defaultRoute: RouteOutcome = .unavailable
    var subscription: SubscriptionSummary?
    var debugSamples: [DebugSampleSummary] = []
    var defaultProfileID: ProfileID?
    var defaultGroupID: ServerGroupID?
    var defaultDebugSampleID: DebugSampleID?
    var isSampleData: Bool = true

    static let empty = AppContent()

    var isEmpty: Bool {
        profiles.isEmpty
            && servers.isEmpty
            && groups.isEmpty
            && routeRules.isEmpty
            && subscription == nil
            && debugSamples.isEmpty
    }

    func profile(id: ProfileID) -> ProfileSummary? {
        profiles.first { $0.id == id }
    }

    func isKnownProfile(_ id: ProfileID) -> Bool {
        guard !id.isEmpty else { return false }
        return profile(id: id) != nil
    }

    func server(id: ServerID) -> ServerSummary? {
        servers.first { $0.id == id }
    }

    func group(id: ServerGroupID) -> ServerGroupSummary? {
        groups.first { $0.id == id }
    }

    func debugSample(id: DebugSampleID) -> DebugSampleSummary? {
        debugSamples.first { $0.id == id }
    }

    var enabledRuleCount: Int {
        routeRules.filter(\.isEnabled).count
    }
}

extension AppContent {
    static let sample: AppContent = {
        let observedAt = Date(timeIntervalSince1970: 1_749_900_000)
        return AppContent(
            profiles: [
                ProfileSummary(
                    id: "profile-sample",
                    name: "Sample provider",
                    sourceKindLabel: "Local sample",
                    serverIDs: ["srv-fi-01", "srv-de-01", "srv-us-01", "srv-us-02"]
                ),
                ProfileSummary(
                    id: "profile-secondary",
                    name: "Sample provider EU",
                    sourceKindLabel: "Local sample",
                    serverIDs: ["srv-fi-01", "srv-de-01"]
                )
            ],
            servers: [
                ServerSummary(
                    id: "srv-fi-01",
                    name: "Helsinki relay",
                    protocolLabel: "VLESS",
                    locationLabel: "Finland",
                    latency: LatencyState(milliseconds: 84, observedAt: observedAt),
                    health: HealthEvidence(sampleCount: 6, successCount: 6),
                    groupIDs: ["00000000-0000-0000-0000-000000000201", "00000000-0000-0000-0000-000000000203"]
                ),
                ServerSummary(
                    id: "srv-de-01",
                    name: "Berlin relay",
                    protocolLabel: "Trojan",
                    locationLabel: "Germany",
                    latency: LatencyState(milliseconds: 460, observedAt: observedAt),
                    health: HealthEvidence(sampleCount: 6, successCount: 4),
                    groupIDs: ["00000000-0000-0000-0000-000000000201"]
                ),
                ServerSummary(
                    id: "srv-us-01",
                    name: "Ashburn relay",
                    protocolLabel: "VLESS",
                    locationLabel: "United States",
                    latency: LatencyState(milliseconds: 218, observedAt: observedAt),
                    health: HealthEvidence(sampleCount: 5, successCount: 5),
                    groupIDs: ["00000000-0000-0000-0000-000000000202"]
                ),
                ServerSummary(
                    id: "srv-us-02",
                    name: "Portland relay",
                    protocolLabel: "VMess",
                    locationLabel: "United States",
                    latency: LatencyState(milliseconds: 305, observedAt: observedAt),
                    health: HealthEvidence(sampleCount: 5, successCount: 2),
                    groupIDs: ["00000000-0000-0000-0000-000000000202"]
                ),
                ServerSummary(
                    id: "srv-no-01",
                    name: "Oslo relay",
                    protocolLabel: "Shadowsocks",
                    locationLabel: "Norway",
                    latency: LatencyState.notMeasured,
                    health: HealthEvidence.none,
                    groupIDs: []
                )
            ],
            groups: [
                ServerGroupSummary(
                    id: "00000000-0000-0000-0000-000000000201",
                    name: "Rovia EU",
                    modeLabel: "Manual",
                    policyLabel: "Manual selection",
                    memberIDs: ["srv-fi-01", "srv-de-01"]
                ),
                ServerGroupSummary(
                    id: "00000000-0000-0000-0000-000000000202",
                    name: "Rovia US",
                    modeLabel: "Lowest latency",
                    policyLabel: "Lowest latency",
                    memberIDs: ["srv-us-01", "srv-us-02"]
                ),
                ServerGroupSummary(
                    id: "00000000-0000-0000-0000-000000000203",
                    name: "Private network",
                    modeLabel: "Failover",
                    policyLabel: "Failover in member order",
                    memberIDs: ["srv-fi-01"]
                )
            ],
            routeRules: [
                RouteRuleSummary(
                    id: "00000000-0000-0000-0000-000000000301",
                    index: 0,
                    isEnabled: true,
                    action: .group("00000000-0000-0000-0000-000000000201"),
                    matchers: [
                        RouteMatcherSummary(
                            id: "rule-suffix-m0",
                            kind: .domainSuffix,
                            value: "media.example.invalid"
                        )
                    ],
                    note: "Sample suffix rule for the EU group."
                ),
                RouteRuleSummary(
                    id: "00000000-0000-0000-0000-000000000302",
                    index: 1,
                    isEnabled: true,
                    action: .block,
                    matchers: [
                        RouteMatcherSummary(
                            id: "rule-blocked-host-m0",
                            kind: .domain,
                            value: "api.example.invalid"
                        )
                    ],
                    note: "Sample host that never leaves the device."
                ),
                RouteRuleSummary(
                    id: "00000000-0000-0000-0000-000000000303",
                    index: 2,
                    isEnabled: true,
                    action: .direct,
                    matchers: [
                        RouteMatcherSummary(
                            id: "rule-private-lan-m0",
                            kind: .ipCIDR,
                            value: "192.168.0.0/16"
                        )
                    ],
                    note: "Sample private range that bypasses the tunnel."
                ),
                RouteRuleSummary(
                    id: "00000000-0000-0000-0000-000000000304",
                    index: 3,
                    isEnabled: false,
                    action: .block,
                    matchers: [
                        RouteMatcherSummary(
                            id: "rule-ssh-m0",
                            kind: .portRange,
                            value: "22",
                            upperValue: "23"
                        )
                    ],
                    note: "Sample rule kept disabled so the debugger can show a skipped rule."
                ),
                RouteRuleSummary(
                    id: "00000000-0000-0000-0000-000000000305",
                    index: 4,
                    isEnabled: true,
                    action: .direct,
                    matchers: [
                        RouteMatcherSummary(
                            id: "rule-dns-m0",
                            kind: .network,
                            value: "udp"
                        ),
                        RouteMatcherSummary(
                            id: "rule-dns-m1",
                            kind: .port,
                            value: "5300"
                        )
                    ],
                    note: "Sample unencrypted DNS that stays direct."
                )
            ],
            defaultRoute: .group("00000000-0000-0000-0000-000000000202"),
            subscription: SubscriptionSummary(
                id: "profile-sample",
                name: "Sample provider",
                sourceKindLabel: "Local sample",
                sourceDisplayValue: "sample-provider.invalid/••••••••",
                acceptedCount: 4,
                rejectedCount: 1,
                isSampleData: true,
                entries: [
                    SubscriptionEntrySummary(
                        id: "srv-fi-01",
                        displayName: "Helsinki relay",
                        protocolLabel: "VLESS",
                        redactedEndpointLabel: "Host hidden · port 443",
                        statusLabel: "Accepted"
                    ),
                    SubscriptionEntrySummary(
                        id: "srv-de-01",
                        displayName: "Berlin relay",
                        protocolLabel: "Trojan",
                        redactedEndpointLabel: "Host hidden · port 443",
                        statusLabel: "Accepted"
                    ),
                    SubscriptionEntrySummary(
                        id: "srv-us-01",
                        displayName: "Ashburn relay",
                        protocolLabel: "VLESS",
                        redactedEndpointLabel: "Host hidden · port 443",
                        statusLabel: "Accepted"
                    ),
                    SubscriptionEntrySummary(
                        id: "srv-us-02",
                        displayName: "Portland relay",
                        protocolLabel: "VMess",
                        redactedEndpointLabel: "Host hidden · port 443",
                        statusLabel: "Accepted"
                    ),
                    SubscriptionEntrySummary(
                        id: "srv-rejected-01",
                        displayName: "Entry 5",
                        protocolLabel: "Unrecognised",
                        redactedEndpointLabel: "Host hidden · port unknown",
                        statusLabel: "Rejected"
                    )
                ]
            ),
            debugSamples: [
                DebugSampleSummary(
                    id: "dbg-suffix",
                    label: "Media subdomain",
                    detail: "A sample hostname under the EU suffix, requested over HTTPS.",
                    input: DebugInput(host: "video.media.example.invalid", port: 443, network: "tcp")
                ),
                DebugSampleSummary(
                    id: "dbg-blocked",
                    label: "Blocked host",
                    detail: "A sample hostname that the sample rules block.",
                    input: DebugInput(host: "api.example.invalid", port: 443, network: "tcp")
                ),
                DebugSampleSummary(
                    id: "dbg-private",
                    label: "Private address",
                    detail: "A sample private address inside the direct range.",
                    input: DebugInput(ip: "192.168.10.24", port: 8080, network: "tcp")
                ),
                DebugSampleSummary(
                    id: "dbg-disabled",
                    label: "Disabled rule input",
                    detail: "A sample port that only the disabled sample rule matches.",
                    input: DebugInput(host: "db.example.invalid", port: 22, network: "tcp")
                ),
                DebugSampleSummary(
                    id: "dbg-udp",
                    label: "Unencrypted DNS",
                    detail: "A sample DNS request that the sample rules keep direct.",
                    input: DebugInput(host: "resolver.example.invalid", port: 5300, network: "udp")
                ),
                DebugSampleSummary(
                    id: "dbg-unmatched",
                    label: "No matching rule",
                    detail: "A sample request that no rule matches, so the default action applies.",
                    input: DebugInput(host: "unmatched.example.invalid", port: 443, network: "tcp")
                )
            ],
            defaultProfileID: "profile-sample",
            defaultGroupID: "00000000-0000-0000-0000-000000000201",
            defaultDebugSampleID: "dbg-unmatched",
            isSampleData: true
        )
    }()
}

enum PrimaryTunnelAction: Equatable, Sendable {
    case unavailable
    case connect
    case disconnect
    case busy
}

struct AppSnapshot: Equatable, Sendable {
    var system: SystemState = .idle
    var engine: TunnelState = .unknown
    var selection: SelectionState = .none
    var latency: LatencyState = .notMeasured
    var health: HealthConfidence = .unknown
    var healthEvidence: HealthEvidence = .none
    var content: AppContent = .empty
    var evaluation: DebugEvaluation?
    var lastError: AppError?
    var isSampleData: Bool = true
    /// The last add/refresh attempt: accepted/rejected counts for honest UI.
    var lastSubscriptionResult: SubscriptionImportSummary?

    var canConnect: Bool {
        system == .ready && engine.allowsStart && !engine.isBusy
    }

    var canDisconnect: Bool {
        engine.allowsStop
    }

    var isConnected: Bool {
        engine.isConnected
    }

    var isBusy: Bool {
        engine.isBusy
    }

    var hasContent: Bool {
        !content.isEmpty
    }

    var canExplainDebugSample: Bool {
        guard let sampleID = selection.debugSample else { return false }
        return content.debugSample(id: sampleID) != nil
    }

    var connectActionTitle: String {
        switch primaryTunnelAction {
        case .disconnect, .busy:
            "Disconnect"
        case .connect, .unavailable:
            "Connect"
        }
    }

    var primaryTunnelAction: PrimaryTunnelAction {
        if engine.unavailableReason != nil { return .unavailable }
        if engine.allowsStop { return .disconnect }
        if engine.isBusy { return .busy }
        return .connect
    }

    var isPrimaryActionEnabled: Bool {
        switch primaryTunnelAction {
        case .connect, .disconnect:
            true
        case .unavailable, .busy:
            false
        }
    }

    var primaryActionSystemImage: String {
        switch primaryTunnelAction {
        case .disconnect, .busy:
            "stop.circle.fill"
        case .connect, .unavailable:
            "play.circle.fill"
        }
    }

    var connectedSinceText: String? {
        guard case let .connected(since) = engine else { return nil }
        return "Connected since \(since.formatted(date: .omitted, time: .shortened))"
    }

    var primaryActionHint: String {
        switch primaryTunnelAction {
        case .unavailable:
            "\(engine.unavailableReason?.summary ?? "The tunnel engine is not available.") Connecting stays disabled until an engine is available."
        case .connect:
            "Sends a start request to the tunnel engine. A running tunnel is reported only after the engine confirms it."
        case .disconnect:
            "Sends a stop request to the tunnel engine."
        case .busy:
            "Waiting for the tunnel engine to finish the current request."
        }
    }

    var engineStatusText: String {
        engine.statusText
    }

    var systemStatusText: String {
        system.statusText
    }

    var selectedServerName: String? {
        selection.server.flatMap { content.server(id: $0)?.name }
    }

    var selectedGroupName: String? {
        selection.group.flatMap { content.group(id: $0)?.name }
    }

    var selectedProfileName: String? {
        guard let id = selection.profile else { return nil }
        return content.profile(id: id)?.name
    }

    var selectedProfileServerIDs: Set<ServerID>? {
        guard let id = selection.profile, let profile = content.profile(id: id) else { return nil }
        return Set(profile.serverIDs)
    }

    var serverFilterDescription: String {
        var parts: [String] = []
        if let name = selectedProfileName {
            parts.append("profile \(name)")
        }
        if let name = selectedGroupName {
            parts.append("group \(name)")
        }
        return parts.isEmpty ? "the current selection" : parts.joined(separator: " and ")
    }

    var visibleServers: [ServerSummary] {
        // Index once instead of scanning `allowed` per member: the old
        // `allowed.first { $0.id == memberID }` was O(group × servers) on
        // every recompute. Order semantics are unchanged — group order when
        // a group is selected, content order otherwise, profile filter
        // applied in both cases.
        guard let groupID = selection.group, let group = content.group(id: groupID) else {
            guard let profileServerIDs = selectedProfileServerIDs else {
                return content.servers
            }
            return content.servers.filter { profileServerIDs.contains($0.id) }
        }
        guard let profileServerIDs = selectedProfileServerIDs else {
            let byID = Dictionary(uniqueKeysWithValues: content.servers.map { ($0.id, $0) })
            return group.memberIDs.compactMap { byID[$0] }
        }
        let byID = Dictionary(uniqueKeysWithValues: content.servers.map { ($0.id, $0) })
        return group.memberIDs.compactMap { memberID in
            guard profileServerIDs.contains(memberID) else { return nil }
            return byID[memberID]
        }
    }
}
