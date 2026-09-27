import Foundation

enum EngineAvailability: Equatable, Sendable {
    case available
    case unavailable(reason: String)
}

enum TunnelLaunchDecision: Equatable, Sendable {
    case applyNetworkSettings
    case unavailable(reason: String)
}

typealias NetworkSettingsApplying = @Sendable () async -> Void

final class TunnelCompletion: @unchecked Sendable {
    private let lock = NSLock()
    private let handler: (Error?) -> Void
    private var completed = false

    init(handler: @escaping (Error?) -> Void) {
        self.handler = handler
    }

    func call(_ error: Error?) {
        lock.lock()
        guard !completed else {
            lock.unlock()
            return
        }
        completed = true
        lock.unlock()
        handler(error)
    }
}

struct TunnelLaunchCoordinator: Sendable {
    private let availability: EngineAvailability
    private let networkSettingsApplying: NetworkSettingsApplying

    init(
        availability: EngineAvailability,
        networkSettingsApplying: @escaping NetworkSettingsApplying
    ) {
        self.availability = availability
        self.networkSettingsApplying = networkSettingsApplying
    }

    func launch() async -> TunnelLaunchDecision {
        switch availability {
        case let .unavailable(reason):
            return .unavailable(reason: reason)
        case .available:
            await networkSettingsApplying()
            return .applyNetworkSettings
        }
    }
}
