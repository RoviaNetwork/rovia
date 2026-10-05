import Foundation
import NetworkExtension
import XCTest

/// The profile the controller drives, recorded. No call reaches the system's
/// real VPN preferences.
private final class MockTunnelProfile: TunnelProfileManaging, @unchecked Sendable {
    var isEnabled = false
    var isOnDemandEnabled = false
    var onDemandRules: [NEOnDemandRule]? = []
    var includeAllNetworks = false

    private(set) var saves = 0
    private(set) var reloads = 0
    private(set) var starts = 0
    private(set) var stops = 0
    var statusStub: TunnelStatus = .disconnected
    var responseData: Data?

    func save() async throws { saves += 1 }
    func reload() async throws { reloads += 1 }
    func start() throws { starts += 1 }
    func stop() { stops += 1 }
    func status() -> TunnelStatus { statusStub }
    func sendStatusRequest(_ body: Data) async -> Data? { responseData }
}

@MainActor
final class TunnelControllerTests: XCTestCase {
    private func makeController(
        profile: MockTunnelProfile,
        killSwitch: Bool = false
    ) -> NETunnelController {
        NETunnelController(
            profileProvider: { profile },
            settingsProvider: { TunnelSettings(killSwitch: killSwitch) }
        )
    }

    func testStartWithKillSwitchArmsTheProfile() async throws {
        let profile = MockTunnelProfile()
        let controller = makeController(profile: profile, killSwitch: true)

        try await controller.requestStart()

        XCTAssertTrue(profile.isEnabled)
        XCTAssertTrue(profile.isOnDemandEnabled)
        XCTAssertEqual(profile.onDemandRules?.count, 1)
        XCTAssertTrue(profile.includeAllNetworks)
        XCTAssertEqual(profile.saves, 1)
        XCTAssertEqual(profile.reloads, 1)
        XCTAssertEqual(profile.starts, 1)
    }

    func testStartWithoutKillSwitchLeavesTrafficOpenOnFailure() async throws {
        let profile = MockTunnelProfile()
        let controller = makeController(profile: profile, killSwitch: false)

        try await controller.requestStart()

        XCTAssertFalse(profile.isOnDemandEnabled)
        XCTAssertTrue(profile.onDemandRules?.isEmpty ?? false)
        XCTAssertFalse(profile.includeAllNetworks)
        XCTAssertEqual(profile.starts, 1)
    }

    /// The regression: an always-connect on-demand rule restarts the tunnel
    /// the moment it is stopped. Stop must disarm the rule first.
    func testStopDisarmsOnDemandBeforeStopping() async throws {
        let profile = MockTunnelProfile()
        profile.isOnDemandEnabled = true
        profile.onDemandRules = [NEOnDemandRuleConnect()]
        let controller = makeController(profile: profile, killSwitch: true)

        try await controller.requestStop()

        XCTAssertFalse(profile.isOnDemandEnabled)
        XCTAssertTrue(profile.onDemandRules?.isEmpty ?? false)
        XCTAssertEqual(profile.saves, 1, "the disarm is persisted before the stop")
        XCTAssertEqual(profile.stops, 1)
    }

    func testStopWithoutOnDemandDoesNotSave() async throws {
        let profile = MockTunnelProfile()
        let controller = makeController(profile: profile, killSwitch: false)

        try await controller.requestStop()

        XCTAssertEqual(profile.saves, 0)
        XCTAssertEqual(profile.stops, 1)
    }

    func testStatusReportDecodesTheExtensionEnvelope() async throws {
        let profile = MockTunnelProfile()
        profile.responseData = try JSONSerialization.data(withJSONObject: [
            "apiVersion": 1,
            "requestID": "x",
            "ok": true,
            "result": [
                "state": "connected",
                "engineVersion": "Xray 26.9.9",
                "droppedOutbound": 2,
                "droppedInbound": 1,
            ],
        ])
        let controller = makeController(profile: profile)

        let maybeReport = await controller.statusReport()
        let report = try XCTUnwrap(maybeReport)
        XCTAssertEqual(report.state, "connected")
        XCTAssertEqual(report.engineVersion, "Xray 26.9.9")
        XCTAssertEqual(report.droppedOutbound, 2)
        XCTAssertEqual(report.droppedInbound, 1)
    }

    func testStatusReportIsNilWhenTheExtensionRefuses() async throws {
        let profile = MockTunnelProfile()
        profile.responseData = try JSONSerialization.data(withJSONObject: [
            "apiVersion": 1,
            "requestID": "x",
            "ok": false,
            "error": "invalid-request",
        ])
        let controller = makeController(profile: profile)

        let refused = await controller.statusReport()
        XCTAssertNil(refused)
    }

    func testStatusReportIsNilWithoutARunningTunnel() async throws {
        let profile = MockTunnelProfile()
        profile.responseData = nil
        let controller = makeController(profile: profile)

        let silent = await controller.statusReport()
        XCTAssertNil(silent)
    }
}
