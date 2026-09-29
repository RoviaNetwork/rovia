import Foundation
import Observation
import RoviaSubscription

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
    case addSubscriptionURL(URL, String, Bool)
    case addSubscriptionText(String, String)
    case refreshSubscription(UUID)
    case renameSubscription(UUID, String)
    case removeSubscription(UUID)
    case probeServers
    case refreshStaleSubscriptions(TimeInterval)
    case toggleFavorite(ServerID)

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
        case .addSubscriptionURL:
            "Add a subscription from a URL"
        case .addSubscriptionText:
            "Add pasted subscription text"
        case .refreshSubscription:
            "Refresh a subscription"
        case .renameSubscription:
            "Rename a subscription"
        case .removeSubscription:
            "Remove a subscription"
        case .probeServers:
            "Measure server latency"
        case .refreshStaleSubscriptions:
            "Refresh subscriptions updated over an hour ago"
        case .toggleFavorite:
            "Toggle a favorite server"
        }
    }
}

@MainActor
@Observable
final class AppModel {
    private(set) var snapshot = AppSnapshot()
    private(set) var inFlightActions: Set<AppAction> = []
    /// Stored subscriptions for the management UI. Updated on every
    /// subscription mutation and on bootstrap.
    private(set) var storedSubscriptions: [StoredSubscription] = []
    /// A deep link waiting for explicit user confirmation. Stored, never
    /// acted on: an external URL must not trigger a silent add or a network
    /// request, including when it arrives before bootstrap finishes.
    var pendingImport: PendingImport?
    /// Favorite servers, persisted across launches. IDs are stable across
    /// refreshes, so a favorite survives subscription updates; a favorite
    /// whose server disappeared simply matches nothing.
    private(set) var favoriteServerIDs: Set<ServerID> = []

    var refreshingSubscriptions: Set<UUID> {
        subscriptions?.isRefreshing ?? []
    }

    var subscriptionsAvailable: Bool {
        subscriptions != nil
    }

    private let tunnel: any TunnelControlling
    private let fixtures: any FixtureProviding
    private let subscriptions: SubscriptionCoordinator?
    private let probeLatency: (@Sendable (String, Int) async -> Int?)?
    private let favoritesStorage: UserDefaults
    private let selectionStorage: UserDefaults
    private let now: @Sendable () -> Date

    init(
        tunnel: any TunnelControlling = UnavailableTunnelController(),
        fixtures: any FixtureProviding = StaticFixtureProvider(),
        subscriptions: SubscriptionCoordinator? = nil,
        probeLatency: (@Sendable (String, Int) async -> Int?)? = nil,
        favoritesStorage: UserDefaults = .standard,
        selectionStorage: UserDefaults? = nil,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.tunnel = tunnel
        self.fixtures = fixtures
        self.subscriptions = subscriptions
        self.probeLatency = probeLatency
        self.favoritesStorage = favoritesStorage
        // An explicit store persists across launches; tests that pass none
        // get an isolated suite so selections never leak between cases.
        self.selectionStorage = selectionStorage ?? UserDefaults(suiteName: "rovia.test.\(UUID().uuidString)")!
        self.now = now
        self.favoriteServerIDs = Set(favoritesStorage.stringArray(forKey: Self.favoritesKey) ?? [])
    }

    func queueDeepLink(text: String, name: String?) {
        pendingImport = PendingImport(text: text, name: name)
    }

    func discardPendingImport() {
        pendingImport = nil
    }

    private static let favoritesKey = "rovia.favoriteServerIDs"
    private static let selectionProfileKey = "rovia.selection.profile"
    private static let selectionGroupKey = "rovia.selection.group"
    private static let selectionServerKey = "rovia.selection.server"

    private func persistSelection() {
        let selection = snapshot.selection
        if let profile = selection.profile {
            selectionStorage.set(profile, forKey: Self.selectionProfileKey)
        } else {
            selectionStorage.removeObject(forKey: Self.selectionProfileKey)
        }
        if let group = selection.group {
            selectionStorage.set(group, forKey: Self.selectionGroupKey)
        } else {
            selectionStorage.removeObject(forKey: Self.selectionGroupKey)
        }
        if let server = selection.server {
            selectionStorage.set(server, forKey: Self.selectionServerKey)
        } else {
            selectionStorage.removeObject(forKey: Self.selectionServerKey)
        }
    }

    /// Restores the persisted selection level by level: a stored server is
    /// kept only if its group and profile still contain it, otherwise the
    /// content defaults apply. Runs after every bootstrap content swap.
    private func restoreSelection() {
        let content = snapshot.content
        if let profile = selectionStorage.string(forKey: Self.selectionProfileKey),
           content.isKnownProfile(profile)
        {
            snapshot.selection.profile = profile
        } else if let fallback = content.defaultProfileID {
            snapshot.selection.profile = fallback
        }
        if let group = selectionStorage.string(forKey: Self.selectionGroupKey),
           content.group(id: group) != nil
        {
            snapshot.selection.group = group
        } else if let fallback = content.defaultGroupID {
            snapshot.selection.group = fallback
        }
        if let server = selectionStorage.string(forKey: Self.selectionServerKey),
           content.server(id: server) != nil
        {
            snapshot.selection.server = server
        } else {
            snapshot.selection.server = nil
        }
        updateDerivedMeasurements()
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
    func addSubscription(url: URL, name: String, allowInsecure: Bool = false) async -> Bool {
        await perform(.addSubscriptionURL(url, name, allowInsecure))
    }

    @discardableResult
    func addSubscriptionText(_ text: String, name: String) async -> Bool {
        await perform(.addSubscriptionText(text, name))
    }

    @discardableResult
    func refreshSubscription(_ id: UUID) async -> Bool {
        await perform(.refreshSubscription(id))
    }

    @discardableResult
    func renameSubscription(_ id: UUID, name: String) async -> Bool {
        await perform(.renameSubscription(id, name))
    }

    @discardableResult
    func removeSubscription(_ id: UUID) async -> Bool {
        await perform(.removeSubscription(id))
    }

    @discardableResult
    func probeVisibleServers() async -> Bool {
        await perform(.probeServers)
    }

    /// Foreground auto-refresh: subscriptions whose last successful update
    /// is older than `maxAge` are re-fetched. No background modes, no timer
    /// draining the battery — the OS suspends us anyway, so refresh happens
    /// when the user returns, plus manual refresh anytime.
    @discardableResult
    func refreshStaleSubscriptions(maxAge: TimeInterval = 3600) async -> Bool {
        await perform(.refreshStaleSubscriptions(maxAge))
    }

    func isFavorite(_ id: ServerID) -> Bool {
        favoriteServerIDs.contains(id)
    }

    @discardableResult
    func toggleFavorite(_ id: ServerID) async -> Bool {
        await perform(.toggleFavorite(id))
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
        case let .addSubscriptionURL(url, name, allowInsecure):
            return await addSubscriptionFromURL(url, name: name, allowInsecure: allowInsecure)
        case let .addSubscriptionText(text, name):
            return await addSubscriptionFromText(text, name: name)
        case let .refreshSubscription(id):
            return await refreshStoredSubscription(id)
        case let .renameSubscription(id, name):
            return await renameStoredSubscription(id, name: name)
        case let .removeSubscription(id):
            return await removeStoredSubscription(id)
        case .probeServers:
            return await probeServers()
        case let .refreshStaleSubscriptions(maxAge):
            return await refreshStale(maxAge: maxAge)
        case let .toggleFavorite(id):
            return applyFavorite(id)
        }
    }

    private func prepare() async -> Bool {
        if snapshot.system == .ready { return false }

        snapshot.system = .preparing
        snapshot.lastError = nil

        if await prepareFromSubscriptions() {
            // Handled upstream: report whether the app is actually ready, so
            // an unreadable store surfaces as a failed bootstrap with retry
            // instead of a silent fallback.
            return snapshot.system == .ready
        }

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
        snapshot.contentSource = .sample
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
        restoreSelection()
        persistSelection()

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

    /// Stored subscriptions are the source of truth when a coordinator is
    /// wired. Every outcome is an explicit state — never a silent fixture
    /// fallback: no subscriptions yet (`.none`), real servers (`.live`),
    /// stored but all rejected (`.allRejected`), or an unreadable store
    /// (`.unavailable`, with retry). A corrupt file is never overwritten.
    /// Returns true when the coordinator handled the bootstrap, whatever the
    /// outcome; only a missing coordinator falls through to fixtures.
    private func prepareFromSubscriptions() async -> Bool {
        guard let coordinator = subscriptions else { return false }
        do {
            try await coordinator.loadPersisted()
        } catch {
            snapshot.content = .empty
            snapshot.isSampleData = false
            snapshot.contentSource = .unavailable
            snapshot.evaluation = nil
            snapshot.selection = .none
            storedSubscriptions = []
            let failure = AppError.unknown(code: "subscription.storage.failed")
            snapshot.system = .failed(failure)
            snapshot.lastError = failure
            updateDerivedMeasurements()
            return true
        }
        let records = await coordinator.subscriptions()
        storedSubscriptions = records
        snapshot.content = await coordinator.syncToContent()
        snapshot.isSampleData = false
        snapshot.evaluation = nil
        if records.isEmpty {
            snapshot.contentSource = .none
        } else if snapshot.content.servers.isEmpty {
            snapshot.contentSource = .allRejected
        } else {
            snapshot.contentSource = .live
        }
        restoreSelection()
        persistSelection()
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
        persistSelection()
        return true
    }

    private func applyGroup(_ id: ServerGroupID) -> Bool {
        guard snapshot.system == .ready, snapshot.content.group(id: id) != nil else { return false }
        guard snapshot.selection.group != id else { return false }
        snapshot.selection.group = id
        snapshot.selection.server = nil
        snapshot.evaluation = nil
        updateDerivedMeasurements()
        persistSelection()
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
        persistSelection()
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

    // MARK: - Subscriptions

    private func addSubscriptionFromURL(_ url: URL, name: String, allowInsecure: Bool) async -> Bool {
        guard snapshot.system == .ready, let coordinator = subscriptions else { return false }
        do {
            let summary = try await coordinator.add(url: url, name: name, allowInsecure: allowInsecure)
            await resyncSubscriptions(lastResult: summary)
            return true
        } catch is CancellationError {
            return false
        } catch let error as SubscriptionCoordinatorError {
            await resyncAfterSubscriptionFailure(error)
            return false
        } catch {
            snapshot.lastError = .unknown(code: "subscription.add.failed")
            return false
        }
    }

    private func addSubscriptionFromText(_ text: String, name: String) async -> Bool {
        guard snapshot.system == .ready, let coordinator = subscriptions else { return false }
        do {
            let kind = SubscriptionInputClassifier.classify(text)
            let summary: SubscriptionImportSummary
            switch kind {
            case .none:
                throw SubscriptionCoordinatorError.invalidInput
            case let .subscriptionURL(url):
                summary = try await coordinator.add(url: url, name: name, allowInsecure: false)
            case .singleShareLink:
                summary = try await coordinator.addSingleLink(text, name: name)
            case .pastedText:
                summary = try await coordinator.addPastedText(text, name: name)
            }
            await resyncSubscriptions(lastResult: summary)
            return true
        } catch is CancellationError {
            return false
        } catch let error as SubscriptionCoordinatorError {
            await resyncAfterSubscriptionFailure(error)
            return false
        } catch {
            snapshot.lastError = .unknown(code: "subscription.add.failed")
            return false
        }
    }

    private func refreshStoredSubscription(_ id: UUID) async -> Bool {
        guard snapshot.system == .ready, let coordinator = subscriptions else { return false }
        do {
            let summary = try await coordinator.refresh(id: id)
            await resyncSubscriptions(lastResult: summary)
            return true
        } catch is CancellationError {
            return false
        } catch is CancellationError {
            return false
        } catch let error as SubscriptionCoordinatorError {
            await resyncAfterSubscriptionFailure(error)
            return false
        } catch {
            snapshot.lastError = .unknown(code: "subscription.refresh.failed")
            return false
        }
    }

    private func renameStoredSubscription(_ id: UUID, name: String) async -> Bool {
        guard snapshot.system == .ready, let coordinator = subscriptions else { return false }
        do {
            try await coordinator.rename(id: id, name: name)
            await resyncSubscriptions(lastResult: nil)
            return true
        } catch is CancellationError {
            return false
        } catch {
            snapshot.lastError = .unknown(code: "subscription.rename.failed")
            return false
        }
    }

    private func removeStoredSubscription(_ id: UUID) async -> Bool {
        guard snapshot.system == .ready, let coordinator = subscriptions else { return false }
        do {
            try await coordinator.remove(id: id)
            await resyncSubscriptions(lastResult: nil)
            return true
        } catch is CancellationError {
            return false
        } catch {
            snapshot.lastError = .unknown(code: "subscription.remove.failed")
            return false
        }
    }

    private func resyncSubscriptions(lastResult: SubscriptionImportSummary?) async {
        guard let coordinator = subscriptions else { return }
        let content = await coordinator.syncToContent()
        storedSubscriptions = await coordinator.subscriptions()
        if content.servers.isEmpty, content.subscription == nil {
            snapshot.content = .empty
        } else {
            snapshot.content = content
            snapshot.isSampleData = false
        }
        snapshot.lastSubscriptionResult = lastResult
        snapshot.lastError = nil
        reconcileSelection()
    }

    /// A failed add/refresh still updates what the UI shows: an empty first
    /// import is stored (0 accepted, N rejected), and a failed refresh never
    /// touches the record — either way the screen reflects the attempt.
    private func resyncAfterSubscriptionFailure(_ error: SubscriptionCoordinatorError) async {
        guard let coordinator = subscriptions else { return }
        let content = await coordinator.syncToContent()
        storedSubscriptions = await coordinator.subscriptions()
        if !content.servers.isEmpty || content.subscription != nil {
            snapshot.content = content
            snapshot.isSampleData = false
        }
        switch error {
        case let .nothingAccepted(accepted, rejected):
            snapshot.lastSubscriptionResult = SubscriptionImportSummary(
                subscriptionID: UUID(),
                accepted: accepted,
                rejected: rejected
            )
            snapshot.lastError = .unknown(code: "subscription.import.empty")
        case .unknownSubscription:
            snapshot.lastError = .unknown(code: "subscription.unknown")
        case .invalidInput:
            snapshot.lastError = .unknown(code: "subscription.input.invalid")
        case .secretUnavailable:
            snapshot.lastError = .unknown(code: "subscription.secret.missing")
        case .persistenceFailed:
            snapshot.lastError = .unknown(code: "subscription.storage.failed")
        case .fetchFailed:
            snapshot.lastError = .unknown(code: "subscription.fetch.failed")
        case .decodeFailed:
            snapshot.lastError = .unknown(code: "subscription.decode.failed")
        }
        reconcileSelection()
    }

    /// TCP-connect latency for the visible servers. Bounded twice: at most
    /// 100 servers per run and 6 concurrent handshakes, so a huge list
    /// cannot open thousands of sockets. Unreachable servers keep their old
    /// state — the UI shows "Not measured", never a fake number.
    private func probeServers() async -> Bool {
        guard snapshot.system == .ready else { return false }
        let candidates = Array(snapshot.visibleServers.prefix(100))
        guard !candidates.isEmpty else { return true }
        let endpoints = await subscriptions?.endpoints() ?? [:]
        let measuredAt = now()
        var results: [String: Int] = [:]
        // Every attempted server lands here, measured or not: a failed
        // re-measurement clears the number below, so a stale millisecond
        // value never looks fresh. Servers with no known endpoint are not
        // attempted and keep their previous state.
        var attempted: Set<ServerID> = []
        if let probeLatency {
            for server in candidates {
                guard let endpoint = endpoints[server.id] else { continue }
                attempted.insert(server.id)
                if let ms = await probeLatency(endpoint.host, endpoint.port) {
                    results[server.id] = ms
                }
            }
        } else {
            let targets = candidates.compactMap { server -> (id: String, host: String, port: Int)? in
                guard let endpoint = endpoints[server.id] else { return nil }
                return (server.id, endpoint.host, endpoint.port)
            }
            let values = await LatencyProber.probeAll(targets.map { (host: $0.host, port: $0.port) })
            for (target, ms) in zip(targets, values) {
                attempted.insert(target.id)
                if let ms {
                    results[target.id] = ms
                }
            }
        }
        snapshot.content.servers = snapshot.content.servers.map { server in
            guard attempted.contains(server.id) else { return server }
            guard let ms = results[server.id] else {
                return server.withLatency(.notMeasured)
            }
            return server.withLatency(LatencyState(milliseconds: ms, observedAt: measuredAt))
        }
        updateDerivedMeasurements()
        return true
    }

    private func refreshStale(maxAge: TimeInterval) async -> Bool {
        guard snapshot.system == .ready, let coordinator = subscriptions else { return false }
        let cutoff = now().addingTimeInterval(-max(60, maxAge))
        let stale = await coordinator.subscriptions().filter { $0.updatedAt < cutoff }
        guard !stale.isEmpty else { return true }
        var last: SubscriptionImportSummary?
        var failed: Set<UUID> = []
        for record in stale {
            do {
                last = try await coordinator.refresh(id: record.id)
            } catch is CancellationError {
                return false
            } catch let error as SubscriptionCoordinatorError {
                failed.insert(record.id)
                if case let .nothingAccepted(accepted, rejected) = error {
                    last = SubscriptionImportSummary(
                        subscriptionID: record.id,
                        accepted: accepted,
                        rejected: rejected
                    )
                }
            } catch {
                failed.insert(record.id)
            }
        }
        await resyncSubscriptions(lastResult: last)
        snapshot.failedRefreshIDs = failed
        if failed.isEmpty {
            return true
        }
        // Partial failure is not success, and the resync above already
        // cleared the banner: record exactly which subscriptions failed.
        snapshot.lastError = .unknown(code: "subscription.refresh.partial")
        return false
    }

    private func applyFavorite(_ id: ServerID) -> Bool {
        guard snapshot.system == .ready, snapshot.content.server(id: id) != nil else { return false }
        if favoriteServerIDs.contains(id) {
            favoriteServerIDs.remove(id)
        } else {
            favoriteServerIDs.insert(id)
        }
        favoritesStorage.set(Array(favoriteServerIDs), forKey: Self.favoritesKey)
        return true
    }

    /// Keeps the selected server across refreshes (stable importer IDs) and
    /// clears it only when the server actually disappeared.
    private func reconcileSelection() {
        if let serverID = snapshot.selection.server,
           snapshot.content.server(id: serverID) == nil
        {
            snapshot.selection.server = nil
        }
        if let profileID = snapshot.selection.profile,
           !snapshot.content.isKnownProfile(profileID)
        {
            snapshot.selection.profile = snapshot.content.defaultProfileID
        }
        if let groupID = snapshot.selection.group,
           snapshot.content.group(id: groupID) == nil
        {
            snapshot.selection.group = snapshot.content.defaultGroupID
            snapshot.selection.server = nil
        }
        updateDerivedMeasurements()
        persistSelection()
    }
}
