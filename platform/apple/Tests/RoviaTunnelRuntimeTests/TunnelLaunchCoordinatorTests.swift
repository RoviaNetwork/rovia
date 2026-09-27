import Foundation
import XCTest
@testable import RoviaTunnelRuntime

final class TunnelLaunchCoordinatorTests: XCTestCase {
    func testUnavailableEngineDoesNotApplyNetworkSettings() async {
        let counter = NetworkSettingsCounter()
        let reason = "No production engine is enabled."
        let coordinator = TunnelLaunchCoordinator(
            availability: .unavailable(reason: reason),
            networkSettingsApplying: {
                await counter.increment()
            }
        )

        let decision = await coordinator.launch()

        XCTAssertEqual(decision, .unavailable(reason: reason))
        let calls = await counter.count
        XCTAssertEqual(calls, 0)
    }

    func testAvailableEngineAppliesNetworkSettingsExactlyOnce() async {
        let counter = NetworkSettingsCounter()
        let coordinator = TunnelLaunchCoordinator(
            availability: .available,
            networkSettingsApplying: {
                await counter.increment()
            }
        )

        let decision = await coordinator.launch()

        XCTAssertEqual(decision, .applyNetworkSettings)
        let calls = await counter.count
        XCTAssertEqual(calls, 1)
    }

    func testTunnelCompletionInvokesHandlerAtMostOnce() {
        let recorder = CompletionRecorder()
        let completion = TunnelCompletion { error in
            recorder.record(error)
        }
        let firstError = TestError(identifier: "first")
        let secondError = TestError(identifier: "second")

        completion.call(firstError)
        completion.call(secondError)

        XCTAssertEqual(recorder.count, 1)
        XCTAssertEqual((recorder.firstError as? TestError)?.identifier, "first")
    }
}

private actor NetworkSettingsCounter {
    private(set) var count = 0

    func increment() {
        count += 1
    }
}

private final class CompletionRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var recordedCount = 0
    private var recordedFirstError: Error?

    var count: Int {
        lock.lock()
        defer { lock.unlock() }
        return recordedCount
    }

    var firstError: Error? {
        lock.lock()
        defer { lock.unlock() }
        return recordedFirstError
    }

    func record(_ error: Error?) {
        lock.lock()
        recordedCount += 1
        if recordedFirstError == nil {
            recordedFirstError = error
        }
        lock.unlock()
    }
}

private struct TestError: Error, Equatable {
    let identifier: String
}
