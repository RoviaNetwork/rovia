import Foundation
import Observation

protocol TunnelControlling: Sendable {
    func engineAvailability() async -> EngineAvailability
    func requestStart() async throws
    func requestStop() async throws
    func currentStatus() async -> TunnelStatus
}

struct UnavailableTunnelController: TunnelControlling {
    static let reason = EngineUnavailableReason.noEngineConfigured

    func engineAvailability() async -> EngineAvailability {
        .unavailable(Self.reason)
    }

    func requestStart() async throws {
        throw TunnelControlFailure.engineUnavailable
    }

    func requestStop() async throws {
        throw TunnelControlFailure.engineUnavailable
    }

    func currentStatus() async -> TunnelStatus {
        .engineUnavailable(Self.reason)
    }
}

protocol FixtureProviding: Sendable {
    func loadFixture() async throws -> AppContent
}

struct StaticFixtureProvider: FixtureProviding {
    let content: AppContent
    let loadError: (any Error)?

    init(content: AppContent = .sample, loadError: (any Error)? = nil) {
        self.content = content
        self.loadError = loadError
    }

    func loadFixture() async throws -> AppContent {
        if let loadError {
            throw loadError
        }
        return content
    }
}

enum AppAction: Hashable, Sendable {
    case bootstrap
    case connect
    case disconnect
    case refreshStatus
    case selectProfile(ProfileID)
    case selectGroup(ServerGroupID)
    case selectServer(ServerID)
    case selectDebugSample(DebugSampleID)
    case runDebugEvaluation

    var label: String {
        switch self {
        case .bootstrap:
            "Prepare local data"
        case .connect:
            "Start the tunnel"
        case .disconnect:
            "Stop the tunnel"
        case .refreshStatus:
            "Refresh tunnel status"
        case .selectProfile:
            "Select a profile"
        case .selectGroup:
            "Select a group"
        case .selectServer:
            "Select a server"
        case .selectDebugSample:
            "Select a debug sample"
        case .runDebugEvaluation:
            "Explain the selected sample"
        }
    }
}

@MainActor
@Observable
final class AppModel {
    private(set) var snapshot = AppSnapshot()
    private(set) var inFlightActions: Set<AppAction> = []

    private let tunnel: any TunnelControlling
    private let fixtures: any FixtureProviding
    private let now: @Sendable () -> Date

    init(
        tunnel: any TunnelControlling = UnavailableTunnelController(),
        fixtures: any FixtureProviding = StaticFixtureProvider(),
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.tunnel = tunnel
        self.fixtures = fixtures
        self.now = now
    }

    var pendingActions: Set<AppAction> {
        inFlightActions
    }

    var canConnect: Bool {
        snapshot.canConnect
    }

    var canDisconnect: Bool {
        snapshot.canDisconnect
    }

    var isConnected: Bool {
        snapshot.isConnected
    }

    var canExplainDebugSample: Bool {
        snapshot.canExplainDebugSample
    }

    func clearError() {
        snapshot.lastError = nil
    }

    @discardableResult
    func bootstrap() async -> Bool {
        await perform(.bootstrap)
    }

    @discardableResult
    func connect() async -> Bool {
        await perform(.connect)
    }

    @discardableResult
    func disconnect() async -> Bool {
        await perform(.disconnect)
    }

    @discardableResult
    func refreshStatus() async -> Bool {
        await perform(.refreshStatus)
    }

    @discardableResult
    func selectProfile(_ id: ProfileID) async -> Bool {
        await perform(.selectProfile(id))
    }

    @discardableResult
    func selectGroup(_ id: ServerGroupID) async -> Bool {
        await perform(.selectGroup(id))
    }

    @discardableResult
    func selectServer(_ id: ServerID) async -> Bool {
        await perform(.selectServer(id))
    }

    @discardableResult
    func selectDebugSample(_ id: DebugSampleID) async -> Bool {
        await perform(.selectDebugSample(id))
    }

    @discardableResult
    func runDebugEvaluation() async -> Bool {
        await perform(.runDebugEvaluation)
    }

    @discardableResult
    func perform(_ action: AppAction) async -> Bool {
        guard inFlightActions.insert(action).inserted else { return false }
        defer { inFlightActions.remove(action) }

        switch action {
        case .bootstrap:
            return await prepare()
        case .connect:
            return await requestStart()
        case .disconnect:
            return await requestStop()
        case .refreshStatus:
            return await readStatus()
        case let .selectProfile(id):
            return applyProfile(id)
        case let .selectGroup(id):
            return applyGroup(id)
        case let .selectServer(id):
            return applyServer(id)
        case let .selectDebugSample(id):
            return applyDebugSample(id)
        case .runDebugEvaluation:
            return applyDebugEvaluation()
        }
    }

    private func prepare() async -> Bool {
        if snapshot.system == .ready { return false }

        snapshot.system = .preparing
        snapshot.lastError = nil

        let content: AppContent
        do {
            content = try await fixtures.loadFixture()
        } catch {
            let sanitized = AppError(sanitizing: error, operation: .bootstrap)
            snapshot.content = .empty
            snapshot.evaluation = nil
            snapshot.selection = .none
            snapshot.system = .failed(sanitized)
            snapshot.lastError = sanitized
            updateDerivedMeasurements()
            return false
        }

        snapshot.content = content
        snapshot.isSampleData = content.isSampleData
        snapshot.evaluation = nil
        if content.defaultProfileID != nil {
            snapshot.selection.profile = content.defaultProfileID
        }
        if content.defaultGroupID != nil {
            snapshot.selection.group = content.defaultGroupID
        }
        if content.defaultDebugSampleID != nil {
            snapshot.selection.debugSample = content.defaultDebugSampleID
        }

        let availability = await tunnel.engineAvailability()
        switch availability {
        case .available:
            snapshot.engine = .idle
        case let .unavailable(reason):
            snapshot.engine = .unavailable(reason)
        }
        snapshot.system = .ready
        updateDerivedMeasurements()
        return true
    }

    private func requestStart() async -> Bool {
        guard snapshot.system == .ready else { return false }
        if let reason = snapshot.engine.unavailableReason {
            snapshot.lastError = .engineUnavailable(reason: reason)
            return false
        }
        guard snapshot.canConnect else { return false }

        do {
            try await tunnel.requestStart()
        } catch {
            let sanitized = AppError(sanitizing: error, operation: .connect)
            snapshot.engine = .failed(sanitized)
            snapshot.lastError = sanitized
            return false
        }

        snapshot.engine = .starting
        snapshot.lastError = nil
        return true
    }

    private func requestStop() async -> Bool {
        if let reason = snapshot.engine.unavailableReason {
            snapshot.lastError = .engineUnavailable(reason: reason)
            return false
        }
        guard snapshot.canDisconnect else { return false }

        let engineBeforeStop = snapshot.engine
        snapshot.engine = .stopping
        do {
            try await tunnel.requestStop()
        } catch {
            let sanitized = AppError(sanitizing: error, operation: .disconnect)
            snapshot.engine = engineBeforeStop
            snapshot.lastError = sanitized
            return false
        }

        snapshot.engine = .idle
        snapshot.lastError = nil
        return true
    }

    private func readStatus() async -> Bool {
        guard snapshot.system == .ready else { return false }

        switch await tunnel.currentStatus() {
        case let .engineUnavailable(reason):
            snapshot.engine = .unavailable(reason)
            snapshot.lastError = .engineUnavailable(reason: reason)
        case .disconnected:
            snapshot.engine = .idle
            snapshot.lastError = nil
        case .connecting, .reasserting:
            snapshot.engine = .starting
            snapshot.lastError = nil
        case .connected:
            if case .connected = snapshot.engine {
                break
            }
            snapshot.engine = .connected(since: now())
            snapshot.lastError = nil
        case .disconnecting:
            snapshot.engine = .stopping
            snapshot.lastError = nil
        }

        updateDerivedMeasurements()
        return true
    }

    private func applyProfile(_ id: ProfileID) -> Bool {
        guard snapshot.system == .ready, snapshot.content.isKnownProfile(id) else { return false }
        guard snapshot.selection.profile != id else { return false }
        snapshot.selection.profile = id
        revalidateServerSelection()
        return true
    }

    private func applyGroup(_ id: ServerGroupID) -> Bool {
        guard snapshot.system == .ready, snapshot.content.group(id: id) != nil else { return false }
        guard snapshot.selection.group != id else { return false }
        snapshot.selection.group = id
        snapshot.selection.server = nil
        snapshot.evaluation = nil
        updateDerivedMeasurements()
        return true
    }

    private func applyServer(_ id: ServerID) -> Bool {
        guard snapshot.system == .ready, snapshot.content.server(id: id) != nil else { return false }
        if let profileServerIDs = snapshot.selectedProfileServerIDs {
            guard profileServerIDs.contains(id) else { return false }
        }
        if let groupID = snapshot.selection.group, let group = snapshot.content.group(id: groupID) {
            guard group.contains(id) else { return false }
        }
        guard snapshot.selection.server != id else { return false }
        snapshot.selection.server = id
        updateDerivedMeasurements()
        return true
    }

    private func revalidateServerSelection() {
        guard let serverID = snapshot.selection.server else { return }
        if let profileServerIDs = snapshot.selectedProfileServerIDs, !profileServerIDs.contains(serverID) {
            snapshot.selection.server = nil
        } else if let groupID = snapshot.selection.group,
                  let group = snapshot.content.group(id: groupID),
                  !group.contains(serverID) {
            snapshot.selection.server = nil
        }
        updateDerivedMeasurements()
    }

    private func applyDebugSample(_ id: DebugSampleID) -> Bool {
        guard snapshot.system == .ready, snapshot.content.debugSample(id: id) != nil else { return false }
        guard snapshot.selection.debugSample != id else { return false }
        snapshot.selection.debugSample = id
        snapshot.evaluation = nil
        return true
    }

    private func applyDebugEvaluation() -> Bool {
        guard let sampleID = snapshot.selection.debugSample,
              let sample = snapshot.content.debugSample(id: sampleID) else { return false }
        do {
            // The canonical evaluator decides; the bridge only converts. If the
            // content cannot be represented canonically the evaluation fails
            // visibly rather than falling back to a second implementation.
            snapshot.evaluation = try CanonicalRouteBridge.evaluation(
                sample: sample,
                content: snapshot.content
            )
        } catch {
            snapshot.evaluation = nil
            snapshot.lastError = .routeExplanationFailed(code: AppError.routeExplanationFailedCode)
        }
        return true
    }

    private func updateDerivedMeasurements() {
        guard let serverID = snapshot.selection.server,
              let server = snapshot.content.server(id: serverID) else {
            snapshot.latency = .notMeasured
            snapshot.healthEvidence = .none
            snapshot.health = .unknown
            return
        }
        snapshot.latency = server.latency
        snapshot.healthEvidence = server.health
        snapshot.health = server.health.confidence
    }
}
