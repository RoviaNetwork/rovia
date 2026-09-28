import XCTest
import RoviaConfig
import RoviaRouting

@MainActor
final class AppModelTests: XCTestCase {
    private let fixedNow = Date(timeIntervalSince1970: 1_750_000_000)
    private let canarySecret = "canary-secret-9f21"
    private let canaryHost = "node.example.invalid"

    private func makeModel(
        tunnel: any TunnelControlling,
        content: AppContent = .sample,
        loadError: (any Error)? = nil
    ) -> (AppModel, CountingFixtureProvider) {
        let now = fixedNow
        let provider = CountingFixtureProvider(content: content, loadError: loadError)
        let model = AppModel(tunnel: tunnel, fixtures: provider, now: { now })
        return (model, provider)
    }

    private func makePreparedModel(
        content: AppContent = .sample,
        loadError: (any Error)? = nil
    ) async -> AppModel {
        let (model, _) = makeModel(
            tunnel: StubTunnelController(),
            content: content,
            loadError: loadError
        )
        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared, "the fixture environment should prepare")
        return model
    }

    private func assertTrue(
        _ value: Bool,
        _ message: String = "",
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(value, message, file: file, line: line)
    }

    private func assertFalse(
        _ value: Bool,
        _ message: String = "",
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertFalse(value, message, file: file, line: line)
    }

    private func assertEqual<T: Equatable>(
        _ value: T,
        _ expected: T,
        _ message: String = "",
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(value, expected, message, file: file, line: line)
    }

    func testFreshModelExposesSeparatedEmptyState() {
        let (model, _) = makeModel(tunnel: StubTunnelController())

        assertEqual(model.snapshot.system, .idle)
        assertEqual(model.snapshot.engine, .unknown)
        assertEqual(model.snapshot.selection, .none)
        assertEqual(model.snapshot.latency.quality, .unavailable)
        assertEqual(model.snapshot.health, .unknown)
        assertEqual(model.snapshot.healthEvidence, HealthEvidence(sampleCount: 0, successCount: 0))
        assertEqual(model.snapshot.content, .empty)
        assertEqual(model.snapshot.evaluation, nil)
        assertEqual(model.snapshot.lastError, nil)
        assertTrue(model.snapshot.isSampleData)
        assertFalse(model.snapshot.canConnect)
        assertFalse(model.snapshot.canDisconnect)
        assertFalse(model.snapshot.isConnected)
        assertFalse(model.snapshot.canExplainDebugSample)
        assertFalse(model.snapshot.hasContent)
    }

    func testBootstrapLoadsFixturesOnceAndIsIdempotent() async {
        let (model, provider) = makeModel(tunnel: StubTunnelController())

        let firstResult = await model.bootstrap()
        assertTrue(firstResult)
        let loadsAfterFirst = await provider.loadCount
        assertEqual(loadsAfterFirst, 1)
        assertEqual(model.snapshot.system, .ready)
        assertEqual(model.snapshot.content, .sample)

        let secondResult = await model.bootstrap()
        let thirdResult = await model.bootstrap()
        assertFalse(secondResult, "bootstrap must be idempotent")
        assertFalse(thirdResult, "bootstrap must be idempotent")

        let loadsAfterRepeats = await provider.loadCount
        assertEqual(loadsAfterRepeats, 1, "bootstrap must not reload fixtures")
        assertEqual(model.snapshot.system, .ready)
        assertEqual(model.snapshot.content, .sample)
    }

    func testConcurrentBootstrapRunsASingleLoad() async {
        let (model, provider) = makeModel(tunnel: StubTunnelController())
        await provider.gate()

        async let first = model.bootstrap()
        await provider.waitUntilParked()
        let secondResult = await model.bootstrap()
        assertFalse(secondResult, "a duplicate bootstrap must be ignored while one is in flight")
        await provider.release()

        let firstResult = await first
        assertTrue(firstResult)
        let loadCount = await provider.loadCount
        assertEqual(loadCount, 1)
        assertEqual(model.snapshot.system, .ready)
    }

    func testBootstrapAppliesEngineAvailabilityAndDeclaredDefaults() async {
        let model = await makePreparedModel()

        assertEqual(model.snapshot.engine, .idle)
        assertEqual(model.snapshot.selection.profile, AppContent.sample.defaultProfileID)
        assertEqual(model.snapshot.selection.group, AppContent.sample.defaultGroupID)
        assertEqual(model.snapshot.selection.server, nil)
        assertTrue(model.snapshot.canConnect)

        let unavailable = AppModel()
        let unavailableResult = await unavailable.bootstrap()
        assertTrue(unavailableResult)
        assertEqual(unavailable.snapshot.engine, .unavailable(.noEngineConfigured))
        assertFalse(unavailable.snapshot.canConnect)
    }

    func testConnectIsRefusedWhileTheEngineIsUnavailable() async {
        let controller = StubTunnelController()
        await controller.setAvailability(.unavailable(.engineBinaryMissing))
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertFalse(model.snapshot.canConnect)
        let connectResult = await model.connect()
        assertFalse(connectResult, "an unavailable engine must never accept a start request")
        assertFalse(model.snapshot.canConnect)
        assertEqual(model.snapshot.engine, .unavailable(.engineBinaryMissing))
        assertFalse(model.snapshot.isConnected)
        assertEqual(model.snapshot.lastError, .engineUnavailable(reason: .engineBinaryMissing))

        let startCount = await controller.startCallCount
        assertEqual(startCount, 0, "an unavailable engine must never be asked to start")
    }

    func testConnectDoesNotReportConnectedBeforeEngineConfirmation() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        let connectResult = await model.connect()
        assertTrue(connectResult)
        assertEqual(model.snapshot.engine, .starting)
        assertFalse(model.snapshot.isConnected, "a start request alone must never mean connected")
        assertEqual(model.snapshot.lastError, nil)
        assertFalse(model.snapshot.canConnect, "a starting engine must not accept another start")

        await controller.setStatus(.connecting)
        let firstRefresh = await model.refreshStatus()
        assertTrue(firstRefresh)
        assertEqual(model.snapshot.engine, .starting)
        assertFalse(model.snapshot.isConnected, "a connecting engine must not report a connection")

        await controller.setStatus(.connected)
        let confirmedRefresh = await model.refreshStatus()
        assertTrue(confirmedRefresh)
        assertEqual(model.snapshot.engine, .connected(since: fixedNow))
        assertTrue(model.snapshot.isConnected)
        assertFalse(model.snapshot.canConnect)
        assertTrue(model.snapshot.canDisconnect)
    }

    func testRefreshStatusReturnsToIdleWhenTheEngineReportsDisconnected() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        let connectResult = await model.connect()
        assertTrue(connectResult)

        await controller.setStatus(.disconnected)
        let refreshResult = await model.refreshStatus()
        assertTrue(refreshResult)
        assertEqual(model.snapshot.engine, .idle)
        assertFalse(model.snapshot.isConnected)
    }

    func testRefreshStatusDropsAConnectionWhenTheEngineBecomesUnavailable() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        let connectResult = await model.connect()
        assertTrue(connectResult)
        await controller.setStatus(.connected)
        let confirmResult = await model.refreshStatus()
        assertTrue(confirmResult)
        assertTrue(model.snapshot.isConnected)

        await controller.setStatus(.engineUnavailable(.engineSignatureUnverified))
        let lostResult = await model.refreshStatus()
        assertTrue(lostResult)
        assertEqual(model.snapshot.engine, .unavailable(.engineSignatureUnverified))
        assertFalse(model.snapshot.isConnected)
        assertEqual(model.snapshot.lastError, .engineUnavailable(reason: .engineSignatureUnverified))
    }

    func testDuplicateConnectWhileInFlightIsIgnored() async {
        let controller = GateTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        async let first = model.perform(.connect)
        await controller.waitUntilStartIsParked()
        assertTrue(model.pendingActions.contains(.connect))
        assertTrue(model.inFlightActions.contains(.connect))

        let secondResult = await model.perform(.connect)
        assertFalse(secondResult, "a duplicate connect must be ignored while one is in flight")
        assertTrue(model.pendingActions.contains(.connect))

        await controller.releaseStarts()
        let firstResult = await first
        assertTrue(firstResult)

        let startCount = await controller.startCallCount
        assertEqual(startCount, 1, "only one start request may reach the engine")
        assertEqual(model.snapshot.engine, .starting)
        assertTrue(model.pendingActions.isEmpty)
    }

    func testDisconnectAfterAStartRequestReturnsTheEngineToIdle() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        let connectResult = await model.connect()
        assertTrue(connectResult)
        await controller.setStatus(.connected)
        let confirmResult = await model.refreshStatus()
        assertTrue(confirmResult)

        let disconnectResult = await model.disconnect()
        assertTrue(disconnectResult)
        assertEqual(model.snapshot.engine, .idle)
        assertFalse(model.snapshot.isConnected)
        let stopCount = await controller.stopCallCount
        assertEqual(stopCount, 1)
    }

    func testDisconnectIsRefusedWhileTheEngineIsUnavailable() async {
        let (model, _) = makeModel(tunnel: UnavailableTunnelController())
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertFalse(model.snapshot.canDisconnect)
        let disconnectResult = await model.disconnect()
        assertFalse(disconnectResult)
        assertEqual(model.snapshot.engine, .unavailable(.noEngineConfigured))
        assertEqual(model.snapshot.lastError, .engineUnavailable(reason: .noEngineConfigured))
    }

    func testConnectBeforeBootstrapIsRefused() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)

        let connectResult = await model.connect()
        let refreshResult = await model.refreshStatus()
        assertFalse(connectResult, "an unprepared model must not start a tunnel")
        assertFalse(refreshResult)
        let startCount = await controller.startCallCount
        assertEqual(startCount, 0)
        assertEqual(model.snapshot.system, .idle)
        assertEqual(model.snapshot.engine, .unknown)
    }

    func testSanitizedStartFailureNeverExposesUnderlyingDetails() async {
        let controller = StubTunnelController()
        await controller.setStartError(CanaryError("start failed for \(canarySecret) at \(canaryHost)"))
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        let connectResult = await model.connect()
        assertFalse(connectResult)
        guard let error = model.snapshot.lastError else {
            return XCTFail("expected a sanitized error")
        }
        assertEqual(error, .unknown(code: "app.connect.failed"))
        assertEqual(model.snapshot.engine, .failed(.unknown(code: "app.connect.failed")))
        assertFalse(model.snapshot.isConnected)

        let rendered = [
            String(describing: error),
            error.userMessage,
            error.code,
            String(describing: model.snapshot),
            model.snapshot.engineStatusText
        ]
        for text in rendered {
            assertFalse(text.contains(canarySecret), "a sanitized error leaked a secret")
            assertFalse(text.contains(canaryHost), "a sanitized error leaked an endpoint")
        }
        assertTrue(model.snapshot.canConnect, "a failed start must stay retryable")
    }

    func testKnownTunnelFailuresMapToStableCodes() {
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.engineUnavailable, operation: .connect),
            .engineUnavailable(reason: .noEngineConfigured)
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.permissionDenied, operation: .connect).code,
            "tunnel.start.permission-denied"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.configurationRejected, operation: .connect).code,
            "tunnel.start.configuration-rejected"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.timedOut, operation: .connect).code,
            "tunnel.start.timed-out"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.permissionDenied, operation: .disconnect).code,
            "tunnel.stop.permission-denied"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.timedOut, operation: .disconnect).code,
            "tunnel.stop.timed-out"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.unknown, operation: .disconnect).code,
            "tunnel.stop.rejected"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.timedOut, operation: .refreshStatus).code,
            "tunnel.status.timed-out"
        )
        assertEqual(
            AppError(sanitizing: TunnelControlFailure.configurationRejected, operation: .bootstrap).code,
            "fixtures.load.failed"
        )
        assertEqual(
            AppError(sanitizing: CanaryError("anything at all"), operation: .bootstrap).code,
            "fixtures.load.failed"
        )
    }

    func testFixtureLoadFailureSurfacesASanitizedSystemError() async {
        let (model, provider) = makeModel(
            tunnel: StubTunnelController(),
            loadError: CanaryError("cannot read \(canarySecret) from \(canaryHost)")
        )

        let bootstrapResult = await model.bootstrap()
        assertFalse(bootstrapResult)
        let loadCount = await provider.loadCount
        assertEqual(loadCount, 1)
        assertEqual(model.snapshot.system, .failed(.fixtureLoadFailed(code: "fixtures.load.failed")))
        assertEqual(model.snapshot.content, .empty)
        assertEqual(model.snapshot.evaluation, nil)
        assertEqual(model.snapshot.selection, .none)
        assertFalse(model.snapshot.canConnect)
        assertFalse(String(describing: model.snapshot).contains(canarySecret))
    }

    func testClearErrorRemovesTheBannerWithoutTouchingEngineState() async {
        let controller = StubTunnelController()
        await controller.setStartError(TunnelControlFailure.permissionDenied)
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        let connectResult = await model.connect()
        assertFalse(connectResult)
        assertEqual(model.snapshot.lastError, .tunnelStartRejected(code: "tunnel.start.permission-denied"))

        model.clearError()
        assertEqual(model.snapshot.lastError, nil)
        assertEqual(model.snapshot.engine, .failed(.tunnelStartRejected(code: "tunnel.start.permission-denied")))
    }

    func testSelectingAServerUpdatesLatencyAndHealthOnly() async {
        let model = await makePreparedModel()
        assertEqual(model.snapshot.latency.quality, .unavailable)
        assertEqual(model.snapshot.health, .unknown)

        let firstSelection = await model.selectServer("srv-fi-01")
        assertTrue(firstSelection)
        assertEqual(model.snapshot.selection.server, "srv-fi-01")
        assertEqual(model.snapshot.latency.milliseconds, 84)
        assertEqual(model.snapshot.latency.quality, .good)
        assertEqual(model.snapshot.latency.displayText, "84 ms")
        assertEqual(model.snapshot.health, .high)
        assertEqual(model.snapshot.healthEvidence.sampleCount, 6)
        assertEqual(model.snapshot.system, .ready)
        assertEqual(model.snapshot.engine, .idle)
        assertFalse(model.snapshot.isConnected)

        let repeatedSelection = await model.selectServer("srv-fi-01")
        assertFalse(repeatedSelection, "reselecting the same server changes nothing")
        let nonMemberSelection = await model.selectServer("srv-us-01")
        assertFalse(nonMemberSelection, "a server outside the selected group is rejected")
        assertEqual(model.snapshot.latency.milliseconds, 84)

        let groupResult = await model.selectGroup("00000000-0000-0000-0000-000000000202")
        assertTrue(groupResult)
        assertEqual(model.snapshot.latency.quality, .unavailable)
        let secondSelection = await model.selectServer("srv-us-01")
        assertTrue(secondSelection)
        assertEqual(model.snapshot.latency.milliseconds, 218)
        assertEqual(model.snapshot.latency.quality, .fair)
        assertEqual(model.snapshot.health, .high)
        assertEqual(model.snapshot.healthEvidence.displayText, "5 of 5 samples succeeded")

        let lowHealthSelection = await model.selectServer("srv-us-02")
        assertTrue(lowHealthSelection)
        assertEqual(model.snapshot.health, .low)
        assertEqual(model.snapshot.healthEvidence.displayText, "2 of 5 samples succeeded")
    }

    func testUnmeasuredSelectionFallsBackToUnknownMeasurements() async {
        let (model, _) = makeModel(tunnel: StubTunnelController())
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        let groupResult = await model.selectGroup("00000000-0000-0000-0000-000000000203")
        assertTrue(groupResult)
        let selection = await model.selectServer("srv-fi-01")
        assertTrue(selection)
        let unmeasured = await model.selectServer("srv-no-01")
        assertFalse(unmeasured)
        assertEqual(model.snapshot.latency.milliseconds, 84)
    }

    func testSelectingAServerOutsideTheSelectedGroupIsRejected() async {
        let (model, _) = makeModel(tunnel: StubTunnelController())
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        assertEqual(model.snapshot.selection.group, "00000000-0000-0000-0000-000000000201", "the sample default group is EU")

        let rejected = await model.selectServer("srv-us-01")
        assertFalse(rejected, "a non-member server must be rejected")
        assertEqual(model.snapshot.selection.server, nil)
        assertEqual(model.snapshot.latency.quality, .unavailable)

        let accepted = await model.selectServer("srv-de-01")
        assertTrue(accepted)
        assertEqual(model.snapshot.selection.server, "srv-de-01")
        assertEqual(model.snapshot.latency.quality, .poor)
        assertEqual(model.snapshot.health, .low)
    }

    func testVisibleServersFollowTheSelectedGroup() async {
        let model = await makePreparedModel()
        assertEqual(model.snapshot.visibleServers.map(\.id), ["srv-fi-01", "srv-de-01"])
        let groupResult = await model.selectGroup("00000000-0000-0000-0000-000000000202")
        assertTrue(groupResult)
        assertEqual(model.snapshot.visibleServers.map(\.id), ["srv-us-01", "srv-us-02"])
        let selection = await model.selectServer("srv-us-02")
        assertTrue(selection)
        assertEqual(model.snapshot.latency.quality, .fair)
        assertEqual(model.snapshot.health, .low)
        assertEqual(model.snapshot.healthEvidence.displayText, "2 of 5 samples succeeded")

        let unmeasured = await model.selectServer("srv-no-01")
        assertFalse(unmeasured)
    }

    func testSelectingAGroupClearsTheServerSelection() async {
        let model = await makePreparedModel()
        let selection = await model.selectServer("srv-fi-01")
        assertTrue(selection)

        let groupResult = await model.selectGroup("00000000-0000-0000-0000-000000000202")
        assertTrue(groupResult)
        assertEqual(model.snapshot.selection.group, "00000000-0000-0000-0000-000000000202")
        assertEqual(model.snapshot.selection.server, nil)
        assertEqual(model.snapshot.latency.quality, .unavailable)
        assertEqual(model.snapshot.health, .unknown)

        let repeated = await model.selectGroup("00000000-0000-0000-0000-000000000202")
        let unknown = await model.selectGroup("grp-missing")
        assertFalse(repeated)
        assertFalse(unknown, "an unknown group must be rejected")
        assertEqual(model.snapshot.selection.group, "00000000-0000-0000-0000-000000000202")
    }

    func testShippedTunnelControllerCanNeverReportAConnection() async {
        let controller = UnavailableTunnelController()

        let availability = await controller.engineAvailability()
        assertEqual(availability, .unavailable(.noEngineConfigured))
        let status = await controller.currentStatus()
        assertEqual(status, .engineUnavailable(.noEngineConfigured))

        do {
            try await controller.requestStart()
            XCTFail("the shipped controller must refuse to start a tunnel")
        } catch let failure as TunnelControlFailure {
            assertEqual(failure, .engineUnavailable)
        } catch {
            XCTFail("unexpected error \(error)")
        }

        do {
            try await controller.requestStop()
            XCTFail("the shipped controller must refuse to stop a tunnel")
        } catch let failure as TunnelControlFailure {
            assertEqual(failure, .engineUnavailable)
        } catch {
            XCTFail("unexpected error \(error)")
        }

        let model = AppModel()
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        assertEqual(model.snapshot.engine, .unavailable(.noEngineConfigured))
        assertFalse(model.snapshot.canConnect)
        assertFalse(model.snapshot.canDisconnect)

        let connectResult = await model.connect()
        assertFalse(connectResult)
        assertFalse(model.snapshot.isConnected)
        assertEqual(model.snapshot.lastError, .engineUnavailable(reason: .noEngineConfigured))

        let refreshResult = await model.refreshStatus()
        assertTrue(refreshResult)
        assertEqual(model.snapshot.engine, .unavailable(.noEngineConfigured))
        assertFalse(model.snapshot.isConnected)
    }

    func testSelectingAProfileChangesOnlyTheProfile() async {
        let model = await makePreparedModel()
        assertEqual(model.snapshot.selection.profile, "profile-sample")
        assertEqual(model.snapshot.selection.group, "00000000-0000-0000-0000-000000000201")
        assertEqual(model.snapshot.selectedProfileName, "Sample provider")

        let repeated = await model.selectProfile("profile-sample")
        assertFalse(repeated, "reselecting the loaded profile changes nothing")
        let changed = await model.selectProfile("profile-secondary")
        assertTrue(changed)
        assertEqual(model.snapshot.selection.profile, "profile-secondary")
        assertEqual(model.snapshot.selection.group, "00000000-0000-0000-0000-000000000201", "profile selection must not change the group")
        assertEqual(model.snapshot.selectedProfileName, "Sample provider EU")
    }

    func testPrimaryActionIconMatchesThePrimaryAction() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertEqual(model.snapshot.primaryTunnelAction, .connect)
        assertEqual(model.snapshot.primaryActionSystemImage, "play.circle.fill")

        let connectResult = await model.connect()
        assertTrue(connectResult)
        assertEqual(model.snapshot.connectActionTitle, "Disconnect")
        assertEqual(
            model.snapshot.primaryActionSystemImage,
            "stop.circle.fill",
            "a Disconnect button must never show a play icon"
        )

        await controller.setStatus(.connected)
        let refreshResult = await model.refreshStatus()
        assertTrue(refreshResult)
        assertEqual(model.snapshot.connectActionTitle, "Disconnect")
        assertEqual(model.snapshot.primaryActionSystemImage, "stop.circle.fill")

        let stopResult = await model.disconnect()
        assertTrue(stopResult)
        assertEqual(model.snapshot.connectActionTitle, "Connect")
        assertEqual(model.snapshot.primaryActionSystemImage, "play.circle.fill")

        let unavailable = AppModel()
        _ = await unavailable.bootstrap()
        assertEqual(unavailable.snapshot.primaryTunnelAction, .unavailable)
        assertEqual(unavailable.snapshot.connectActionTitle, "Connect")
        assertEqual(unavailable.snapshot.primaryActionSystemImage, "play.circle.fill")
    }

    func testRefreshPreservesTheOriginalConnectionTimestamp() async {
        let clock = TestClock(fixedNow)
        let controller = StubTunnelController()
        let provider = StaticFixtureProvider(content: .sample)
        let model = AppModel(tunnel: controller, fixtures: provider, now: { clock.now })
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        let connectResult = await model.connect()
        assertTrue(connectResult)
        await controller.setStatus(.connected)
        let firstRefresh = await model.refreshStatus()
        assertTrue(firstRefresh)
        assertEqual(model.snapshot.engine, .connected(since: fixedNow))

        clock.advance(600)
        let secondRefresh = await model.refreshStatus()
        assertTrue(secondRefresh)
        assertEqual(
            model.snapshot.engine,
            .connected(since: fixedNow),
            "a status refresh must not restamp an existing connection"
        )

        await controller.setStatus(.disconnected)
        _ = await model.refreshStatus()
        let reconnect = await model.connect()
        assertTrue(reconnect)
        await controller.setStatus(.connected)
        let reconnectRefresh = await model.refreshStatus()
        assertTrue(reconnectRefresh)
        assertEqual(
            model.snapshot.engine,
            .connected(since: clock.now),
            "a new connection receives a fresh timestamp"
        )
        XCTAssertNotEqual(model.snapshot.engine, .connected(since: fixedNow))
    }

    func testConnectedSinceTextIsAbsentUntilTheEngineConfirms() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        assertEqual(model.snapshot.connectedSinceText, nil)

        _ = await model.connect()
        assertEqual(model.snapshot.connectedSinceText, nil, "a start request is not a connection")

        await controller.setStatus(.connected)
        let refreshResult = await model.refreshStatus()
        assertTrue(refreshResult)
        XCTAssertNotNil(model.snapshot.connectedSinceText)

        let stopResult = await model.disconnect()
        assertTrue(stopResult)
        assertEqual(model.snapshot.connectedSinceText, nil)
    }


    func testSelectingAnUnknownProfileIsRejectedAndKeepsTheSelection() async {
        let model = await makePreparedModel()
        assertEqual(model.snapshot.selection.profile, "profile-sample")

        let rejected = await model.selectProfile("profile-missing")
        assertFalse(rejected, "a profile that is not in the loaded content must be rejected")
        assertEqual(model.snapshot.selection.profile, "profile-sample")
        assertEqual(model.snapshot.selectedProfileName, "Sample provider")

        let empty = await model.selectProfile("")
        assertFalse(empty)
        assertEqual(model.snapshot.selection.profile, "profile-sample")
    }

    func testTheSelectedProfileFiltersVisibleServers() async {
        let model = await makePreparedModel()
        assertEqual(model.snapshot.visibleServers.map(\.id), ["srv-fi-01", "srv-de-01"])

        let groupChange = await model.selectGroup("00000000-0000-0000-0000-000000000202")
        assertTrue(groupChange)
        assertEqual(
            model.snapshot.visibleServers.map(\.id),
            ["srv-us-01", "srv-us-02"],
            "the full sample profile includes the US group"
        )

        let profileChange = await model.selectProfile("profile-secondary")
        assertTrue(profileChange)
        assertTrue(
            model.snapshot.visibleServers.isEmpty,
            "profile-secondary declares no US servers, so the filtered list must be empty"
        )

        let rejected = await model.selectServer("srv-us-01")
        assertFalse(rejected, "a server outside the selected profile must be rejected")
        assertEqual(model.snapshot.selection.server, nil)
    }

    func testVisibleServersScaleToThousands() async {
        let count = 5_000
        let ids = (0..<count).map { String(format: "perf-srv-%05d", $0) }
        var content = AppContent()
        content.servers = ids.map {
            ServerSummary(
                id: $0,
                name: "Relay \($0)",
                protocolLabel: "VLESS",
                locationLabel: "Nowhere",
                latency: .notMeasured,
                health: .none,
                groupIDs: ["perf-group"]
            )
        }
        content.groups = [
            ServerGroupSummary(
                id: "perf-group",
                name: "All",
                modeLabel: "Manual",
                policyLabel: "Manual selection",
                memberIDs: ids
            )
        ]
        content.profiles = [
            ProfileSummary(id: "perf-profile", name: "P", sourceKindLabel: "Test", serverIDs: ids)
        ]
        content.defaultProfileID = "perf-profile"
        content.defaultGroupID = "perf-group"
        content.isSampleData = false
        let model = await makePreparedModel(content: content)
        let start = Date()
        let visible = model.snapshot.visibleServers
        let elapsed = Date().timeIntervalSince(start)
        assertEqual(visible.count, count)
        assertEqual(visible.map(\.id), ids, "group order with the profile filter applied")
        print("visibleServers(\(count)) = \(String(format: "%.3f", elapsed))s")
    }

    func testSwitchingProfileClearsAServerThatTheNewProfileDoesNotContain() async {
        let model = await makePreparedModel()
        let groupChange = await model.selectGroup("00000000-0000-0000-0000-000000000202")
        assertTrue(groupChange)
        let selected = await model.selectServer("srv-us-01")
        assertTrue(selected)
        assertEqual(model.snapshot.latency.milliseconds, 218)

        let profileChange = await model.selectProfile("profile-secondary")
        assertTrue(profileChange)
        assertEqual(model.snapshot.selection.server, nil, "a stale server must not survive a profile change")
        assertEqual(model.snapshot.latency.quality, .unavailable)
        assertEqual(model.snapshot.health, .unknown)
    }

    func testSwitchingProfileKeepsAServerThatTheNewProfileStillContains() async {
        let model = await makePreparedModel()
        let selected = await model.selectServer("srv-fi-01")
        assertTrue(selected)

        let profileChange = await model.selectProfile("profile-secondary")
        assertTrue(profileChange)
        assertEqual(model.snapshot.selection.server, "srv-fi-01")
        assertEqual(model.snapshot.latency.milliseconds, 84)
        assertEqual(model.snapshot.health, .high)
    }

    func testEveryAcceptedProfileResolvesToADisplayName() async {
        for profile in AppContent.sample.profiles {
            let model = await makePreparedModel()
            assertTrue(model.snapshot.content.isKnownProfile(profile.id), "\(profile.id) must be accepted")
            let alreadySelected = model.snapshot.selection.profile == profile.id
            let accepted = await model.selectProfile(profile.id)
            assertEqual(
                accepted,
                !alreadySelected,
                "\(profile.id) reports whether the selection actually changed"
            )
            assertEqual(
                model.snapshot.selectedProfileName,
                profile.name,
                "every accepted profile id must resolve to a display name"
            )
        }

        let model = await makePreparedModel()
        let defaultProfileID = try? XCTUnwrap(model.snapshot.content.defaultProfileID)
        XCTAssertNotNil(defaultProfileID)
        if let defaultProfileID, let profile = model.snapshot.content.profile(id: defaultProfileID) {
            assertTrue(model.snapshot.content.isKnownProfile(defaultProfileID))
            assertEqual(model.snapshot.selection.profile, defaultProfileID)
            assertEqual(model.snapshot.selectedProfileName, profile.name)
        }
    }

    func testPrimaryTunnelActionAgreesWithItsTitleHintAndEffect() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertEqual(model.snapshot.primaryTunnelAction, .connect)
        assertEqual(model.snapshot.connectActionTitle, "Connect")
        assertTrue(model.snapshot.isPrimaryActionEnabled)
        assertTrue(model.snapshot.primaryActionHint.contains("start request"))

        let connectResult = await model.connect()
        assertTrue(connectResult)
        assertEqual(model.snapshot.engine, .starting)
        assertEqual(
            model.snapshot.primaryTunnelAction,
            .disconnect,
            "a tunnel that is starting must offer Disconnect, never Connect"
        )
        assertEqual(model.snapshot.connectActionTitle, "Disconnect")
        assertEqual(
            model.snapshot.primaryActionHint,
            "Sends a stop request to the tunnel engine.",
            "the hint must describe the action the button performs"
        )

        let stopResult = await model.disconnect()
        assertTrue(stopResult)
        assertEqual(model.snapshot.engine, .idle)
        assertEqual(model.snapshot.primaryTunnelAction, .connect)
        assertEqual(model.snapshot.connectActionTitle, "Connect")
        let stopCount = await controller.stopCallCount
        assertEqual(stopCount, 1)
    }

    func testUnavailableEngineOffersNoPrimaryAction() async {
        let model = AppModel()
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertEqual(model.snapshot.primaryTunnelAction, .unavailable)
        assertFalse(model.snapshot.isPrimaryActionEnabled)
        assertEqual(model.snapshot.connectActionTitle, "Connect")
        assertTrue(model.snapshot.primaryActionHint.contains("No tunnel engine is bundled in this build."))
    }

    func testConfirmedTunnelOffersDisconnect() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        _ = await model.connect()
        await controller.setStatus(.connected)
        let refreshResult = await model.refreshStatus()
        assertTrue(refreshResult)

        assertTrue(model.snapshot.isConnected)
        assertEqual(model.snapshot.primaryTunnelAction, .disconnect)
        assertEqual(model.snapshot.connectActionTitle, "Disconnect")
        assertEqual(model.snapshot.primaryActionHint, "Sends a stop request to the tunnel engine.")
        assertFalse(model.snapshot.canConnect)
    }

    func testAFailedStopKeepsTheTunnelStateAndStaysRetryable() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        _ = await model.connect()
        await controller.setStatus(.connected)
        let refreshResult = await model.refreshStatus()
        assertTrue(refreshResult)
        assertTrue(model.snapshot.isConnected)

        await controller.setStopError(TunnelControlFailure.permissionDenied)
        let stopResult = await model.disconnect()
        assertFalse(stopResult)
        assertEqual(
            model.snapshot.engine,
            .connected(since: fixedNow),
            "a refused stop must not pretend the tunnel ended"
        )
        assertTrue(model.snapshot.isConnected)
        assertEqual(model.snapshot.lastError, .tunnelStopRejected(code: "tunnel.stop.permission-denied"))
        assertTrue(model.snapshot.canDisconnect, "a failed stop must stay retryable")
        assertEqual(model.snapshot.primaryTunnelAction, .disconnect)

        let stopCount = await controller.stopCallCount
        assertEqual(stopCount, 1)
    }

    func testAFailedStopOnAStartingTunnelReturnsToStarting() async {
        let controller = StubTunnelController()
        let (model, _) = makeModel(tunnel: controller)
        let prepared = await model.bootstrap()
        assertTrue(prepared)
        _ = await model.connect()
        assertEqual(model.snapshot.engine, .starting)

        await controller.setStopError(TunnelControlFailure.timedOut)
        let stopResult = await model.disconnect()
        assertFalse(stopResult)
        assertEqual(model.snapshot.engine, .starting)
        assertEqual(model.snapshot.lastError, .tunnelStopRejected(code: "tunnel.stop.timed-out"))
        assertTrue(model.snapshot.canDisconnect)
    }

    func testProfileSelectionIsRefusedBeforeContentIsPrepared() async {
        let (model, _) = makeModel(tunnel: StubTunnelController())
        let rejected = await model.selectProfile("profile-sample")
        assertFalse(rejected)
        assertEqual(model.snapshot.selection.profile, nil)
    }

    func testSampleContentDeclaresOnlyKnownProfilesAndConsistentDefault() {
        let content = AppContent.sample
        assertFalse(content.profiles.isEmpty)
        XCTAssertNotNil(content.profile(id: "profile-sample"))
        XCTAssertNotNil(content.profile(id: "profile-secondary"))
        XCTAssertNil(content.profile(id: "profile-missing"))
        assertTrue(content.isKnownProfile("profile-sample"))
        assertTrue(content.isKnownProfile("profile-secondary"))
        assertFalse(content.isKnownProfile("profile-missing"))
        XCTAssertNotNil(content.profile(id: content.defaultProfileID ?? ""))

        let profileIDs = Set(content.profiles.map(\.id))
        let serverIDs = Set(content.servers.map(\.id))
        for profile in content.profiles {
            for serverID in profile.serverIDs {
                assertTrue(serverIDs.contains(serverID), "profile \(profile.id) references an unknown server")
            }
        }
        assertEqual(profileIDs.count, content.profiles.count, "profile identifiers must be unique")
        if let subscription = content.subscription {
            assertTrue(
                profileIDs.contains(subscription.id),
                "the loaded subscription must belong to a declared profile"
            )
        }
    }

    func testAccessibilityIdentifiersAreNamespacedUniqueAndNonEmpty() {
        let concrete: [String] = [
            AppAccessibilityIdentifier.emptySelection,
            AppAccessibilityIdentifier.overviewScreen,
            AppAccessibilityIdentifier.overviewEngineStatus,
            AppAccessibilityIdentifier.overviewSystemStatus,
            AppAccessibilityIdentifier.overviewSelection,
            AppAccessibilityIdentifier.overviewLatency,
            AppAccessibilityIdentifier.overviewHealth,
            AppAccessibilityIdentifier.overviewPrimaryAction,
            AppAccessibilityIdentifier.overviewRefreshAction,
            AppAccessibilityIdentifier.overviewErrorMessage,
            AppAccessibilityIdentifier.overviewErrorDismiss,
            AppAccessibilityIdentifier.overviewRetry,
            AppAccessibilityIdentifier.overviewLoadConfiguration,
            AppAccessibilityIdentifier.overviewEmptyFailed,
            AppAccessibilityIdentifier.overviewPreparing,
            AppAccessibilityIdentifier.overviewSampleNotice,
            AppAccessibilityIdentifier.serversScreen,
            AppAccessibilityIdentifier.serversProfileMenu,
            AppAccessibilityIdentifier.serversGroupMenu,
            AppAccessibilityIdentifier.serversList,
            AppAccessibilityIdentifier.serversEmpty,
            AppAccessibilityIdentifier.routingScreen,
            AppAccessibilityIdentifier.routingSummary,
            AppAccessibilityIdentifier.routingDefaultAction,
            AppAccessibilityIdentifier.routingRules,
            AppAccessibilityIdentifier.routingPrivacy,
            AppAccessibilityIdentifier.routingEmpty,
            AppAccessibilityIdentifier.routingDebuggerScreen,
            AppAccessibilityIdentifier.routingDebuggerSampleMenu,
            AppAccessibilityIdentifier.routingDebuggerExplain,
            AppAccessibilityIdentifier.routingDebuggerDecision,
            AppAccessibilityIdentifier.routingDebuggerSteps,
            AppAccessibilityIdentifier.routingDebuggerRedaction,
            AppAccessibilityIdentifier.routingDebuggerEmpty,
            AppAccessibilityIdentifier.subscriptionScreen,
            AppAccessibilityIdentifier.subscriptionSummary,
            AppAccessibilityIdentifier.subscriptionEntries,
            AppAccessibilityIdentifier.subscriptionRedaction,
            AppAccessibilityIdentifier.subscriptionEmpty
        ]
        let prefixes: [String] = [
            AppAccessibilityIdentifier.overviewServerRowPrefix,
            AppAccessibilityIdentifier.serversRowPrefix,
            AppAccessibilityIdentifier.routingRulePrefix,
            AppAccessibilityIdentifier.routingDebuggerStepPrefix,
            AppAccessibilityIdentifier.subscriptionEntryPrefix
        ]

        for identifier in concrete {
            assertTrue(identifier.hasPrefix("rovia."), "\(identifier) is outside the rovia. namespace")
            assertFalse(identifier.contains(" "), "\(identifier) contains whitespace")
            assertFalse(identifier.hasSuffix("."), "\(identifier) is a prefix, not an element identifier")
            assertFalse(identifier.isEmpty)
        }
        for identifier in prefixes {
            assertTrue(identifier.hasPrefix("rovia."), "\(identifier) is outside the rovia. namespace")
            assertTrue(identifier.hasSuffix("."), "\(identifier) must end with a separator")
            assertFalse(identifier.contains(" "), "\(identifier) contains whitespace")
        }

        let all = concrete + prefixes
        assertEqual(Set(all).count, all.count, "accessibility identifiers must be unique")
        for prefix in prefixes {
            let collisions = concrete.filter { $0.hasPrefix(prefix) }
            assertTrue(collisions.isEmpty, "\(prefix) collides with concrete identifier \(collisions)")
        }
    }

    func testSidebarIdentifiersAreStableAndNamespaced() {
        let routes = ["overview", "servers", "routing", "routingDebugger", "subscription"]
        let identifiers = routes.map(AppAccessibilityIdentifier.sidebarRoute)
        assertEqual(
            identifiers,
            [
                "rovia.sidebar.overview",
                "rovia.sidebar.servers",
                "rovia.sidebar.routing",
                "rovia.sidebar.routingDebugger",
                "rovia.sidebar.subscription"
            ]
        )
        assertEqual(Set(identifiers).count, routes.count)
    }

    func testContainerIdentifiersAreDisjointFromElementIdentifiers() {
        let containers = AppAccessibilityIdentifier.containerIdentifiers
        let elements = AppAccessibilityIdentifier.elementIdentifiers
        assertFalse(containers.isEmpty, "container identifiers must be declared so views can treat them safely")
        assertFalse(elements.isEmpty)

        for identifier in containers + elements {
            assertTrue(identifier.hasPrefix("rovia."), "\(identifier) is outside the rovia. namespace")
            assertFalse(identifier.contains(" "), "\(identifier) contains whitespace")
        }
        let containerSet = Set(containers)
        assertEqual(containerSet.count, containers.count, "container identifiers must be unique")
        assertEqual(Set(elements).count, elements.count, "element identifiers must be unique")
        assertTrue(
            containerSet.isDisjoint(with: Set(elements)),
            "an identifier must not be treated as both a container and an element"
        )

        let prefixes = [
            AppAccessibilityIdentifier.overviewServerRowPrefix,
            AppAccessibilityIdentifier.serversRowPrefix,
            AppAccessibilityIdentifier.routingRulePrefix,
            AppAccessibilityIdentifier.routingDebuggerStepPrefix,
            AppAccessibilityIdentifier.subscriptionEntryPrefix
        ]
        assertTrue(
            containerSet.isDisjoint(with: Set(prefixes)),
            "a row prefix must never be treated as a container identifier"
        )

        for container in containers {
            assertFalse(
                elements.contains(container),
                "\(container) must use the container treatment, not the element treatment"
            )
        }
    }

    func testBootstrapSelectsTheDeclaredDebugSampleSoTheDebuggerIsUsefulOffline() async {
        let model = await makePreparedModel()

        assertEqual(model.snapshot.selection.debugSample, AppContent.sample.defaultDebugSampleID)
        assertTrue(model.snapshot.canExplainDebugSample)
        assertEqual(model.snapshot.evaluation, nil, "an explanation is only produced on request")

        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)
        XCTAssertNotNil(model.snapshot.evaluation)
    }

    func testRunDebugEvaluationRequiresASelectedSample() async {
        let (model, _) = makeModel(tunnel: StubTunnelController(), content: .empty)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertEqual(model.snapshot.selection.debugSample, nil)
        assertFalse(model.snapshot.canExplainDebugSample)
        let withoutSample = await model.runDebugEvaluation()
        assertFalse(withoutSample)
        assertEqual(model.snapshot.evaluation, nil)

        let unknownSample = await model.selectDebugSample("dbg-missing")
        assertFalse(unknownSample)
        let stillWithoutSample = await model.runDebugEvaluation()
        assertFalse(stillWithoutSample)
        assertEqual(model.snapshot.evaluation, nil)
    }

    func testRunDebugEvaluationAppliesTheFirstMatchingRuleAndHidesRawInput() async {
        let model = await makePreparedModel()
        let selected = await model.selectDebugSample("dbg-suffix")
        assertTrue(selected)
        assertTrue(model.snapshot.canExplainDebugSample)

        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)
        guard let evaluation = model.snapshot.evaluation else {
            return XCTFail("expected a routing evaluation")
        }
        assertEqual(evaluation.sampleID, "dbg-suffix")
        assertEqual(evaluation.decision, .group("00000000-0000-0000-0000-000000000201"))
        assertEqual(evaluation.selectedGroupID, "00000000-0000-0000-0000-000000000201")
        assertEqual(evaluation.appliedRuleIndex, 0)
        assertEqual(evaluation.steps.count, AppContent.sample.routeRules.count)
        assertEqual(evaluation.steps.first?.ruleIndex, 0)
        assertEqual(evaluation.steps.first?.matched, true)
        assertEqual(evaluation.steps.first?.appliedMatcherIndex, 0)
        assertEqual(evaluation.steps.first?.reason, .applied)
        assertEqual(evaluation.steps.last?.matched, false)
        assertTrue(evaluation.isSampleData)
        assertEqual(evaluation.inputPresence, "host present, port present, network present")

        let rendered = String(describing: evaluation) + String(describing: evaluation.steps)
        assertFalse(rendered.contains("media.example.invalid"), "the evaluation must not echo the sample host")
        assertFalse(rendered.contains("443"), "the evaluation must not echo the sample port")
        assertFalse(rendered.contains("tcp"), "the evaluation must not echo the sample network")
    }

    func testRunDebugEvaluationFallsBackToTheDefaultActionAndSkipsDisabledRules() async {
        let model = await makePreparedModel()
        let selected = await model.selectDebugSample("dbg-disabled")
        assertTrue(selected)
        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)

        guard let evaluation = model.snapshot.evaluation else {
            return XCTFail("expected a routing evaluation")
        }
        assertEqual(evaluation.decision, .group("00000000-0000-0000-0000-000000000202"))
        assertEqual(evaluation.selectedGroupID, "00000000-0000-0000-0000-000000000202")
        assertEqual(evaluation.appliedRuleIndex, nil)
        let disabledStep = evaluation.steps.first { $0.ruleID == "00000000-0000-0000-0000-000000000304" }
        assertEqual(disabledStep?.isEnabled, false)
        assertEqual(disabledStep?.matched, false)
        assertEqual(disabledStep?.reason, .ruleDisabled)
        assertTrue(evaluation.steps.allSatisfy { $0.matched == false })
    }

    func testRunDebugEvaluationAppliesABlockedRule() async {
        let model = await makePreparedModel()
        let selected = await model.selectDebugSample("dbg-blocked")
        assertTrue(selected)
        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)

        guard let evaluation = model.snapshot.evaluation else {
            return XCTFail("expected a routing evaluation")
        }
        assertEqual(evaluation.decision, .block)
        assertEqual(evaluation.selectedGroupID, nil)
        assertEqual(evaluation.appliedRuleIndex, 1)
        assertEqual(evaluation.steps[0].matched, false)
        assertEqual(evaluation.steps[1].reason, .applied)
    }

    func testRunDebugEvaluationAppliesTheDirectPrivateRangeRule() async {
        let model = await makePreparedModel()
        let selected = await model.selectDebugSample("dbg-private")
        assertTrue(selected)
        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)

        guard let evaluation = model.snapshot.evaluation else {
            return XCTFail("expected a routing evaluation")
        }
        assertEqual(evaluation.decision, .direct)
        assertEqual(evaluation.appliedRuleIndex, 2)
        assertEqual(evaluation.steps[2].reason, .applied)
    }

    func testRunDebugEvaluationEvaluatesEveryRuleAndMarksLaterMatchesAsShadowed() async {
        let model = await makePreparedModel()
        let selected = await model.selectDebugSample("dbg-udp")
        assertTrue(selected)
        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)

        guard let evaluation = model.snapshot.evaluation else {
            return XCTFail("expected a routing evaluation")
        }
        assertEqual(evaluation.decision, .direct)
        assertEqual(evaluation.appliedRuleIndex, 4)
        assertEqual(evaluation.steps.count, AppContent.sample.routeRules.count)
        assertEqual(evaluation.steps[4].reason, .applied)
        assertEqual(evaluation.steps[4].evaluatedMatcherCount, 2)
        assertTrue(evaluation.steps[4].matched)
    }

    func testChangingTheDebugSampleInvalidatesThePreviousEvaluation() async {
        let model = await makePreparedModel()
        let selected = await model.selectDebugSample("dbg-suffix")
        assertTrue(selected)
        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated)
        XCTAssertNotNil(model.snapshot.evaluation)

        let changed = await model.selectDebugSample("dbg-blocked")
        assertTrue(changed)
        assertEqual(model.snapshot.evaluation, nil, "a stale explanation must not stay on screen")
    }

    func testEmptyFixtureEnvironmentKeepsEveryScreenInAnEmptyState() async {
        let (model, _) = makeModel(tunnel: StubTunnelController(), content: .empty)
        let prepared = await model.bootstrap()
        assertTrue(prepared)

        assertEqual(model.snapshot.system, .ready)
        assertFalse(model.snapshot.hasContent)
        assertTrue(model.snapshot.content.isEmpty)
        assertEqual(model.snapshot.selection, .none)
        assertFalse(model.snapshot.canExplainDebugSample)
        assertTrue(model.snapshot.isSampleData)
        assertTrue(model.snapshot.canConnect, "engine availability is independent of loaded content")
        XCTAssertTrue(model.snapshot.visibleServers.isEmpty)

        let evaluated = await model.runDebugEvaluation()
        assertFalse(evaluated)
        assertEqual(model.snapshot.evaluation, nil)
    }

    func testLatencyQualityThresholds() {
        assertEqual(LatencyState(milliseconds: nil).quality, .unavailable)
        assertEqual(LatencyState(milliseconds: -1).quality, .unavailable)
        assertEqual(LatencyState(milliseconds: 0).quality, .good)
        assertEqual(LatencyState(milliseconds: 149).quality, .good)
        assertEqual(LatencyState(milliseconds: 150).quality, .fair)
        assertEqual(LatencyState(milliseconds: 399).quality, .fair)
        assertEqual(LatencyState(milliseconds: 400).quality, .poor)
        assertEqual(LatencyState(milliseconds: nil).displayText, "Not measured")
        assertEqual(LatencyState(milliseconds: 84).displayText, "84 ms")
        assertEqual(LatencyState(milliseconds: nil).quality.summary, "No measurement")
    }

    func testHealthConfidenceThresholds() {
        assertEqual(HealthConfidence.confidence(sampleCount: 0, successCount: 0), .unknown)
        assertEqual(HealthConfidence.confidence(sampleCount: 1, successCount: 1), .low)
        assertEqual(HealthConfidence.confidence(sampleCount: 2, successCount: 0), .low)
        assertEqual(HealthConfidence.confidence(sampleCount: 3, successCount: 3), .medium)
        assertEqual(HealthConfidence.confidence(sampleCount: 4, successCount: 1), .medium)
        assertEqual(HealthConfidence.confidence(sampleCount: 5, successCount: 5), .high)
        assertEqual(HealthConfidence.confidence(sampleCount: 6, successCount: 5), .high)
        assertEqual(HealthConfidence.confidence(sampleCount: 6, successCount: 4), .low)
        assertEqual(HealthEvidence(sampleCount: 6, successCount: 4).normalizedSuccessCount, 4)
        assertEqual(HealthEvidence(sampleCount: 2, successCount: 9).normalizedSuccessCount, 2)
        assertEqual(HealthEvidence(sampleCount: 2, successCount: 9).sampleCount, 2)
        assertEqual(HealthEvidence.none.displayText, "No samples")
        assertEqual(HealthEvidence(sampleCount: 6, successCount: 5).displayText, "5 of 6 samples succeeded")
    }

    func testErrorCodesStayInsideTheClosedSet() {
        let codes: [String] = [
            AppError.engineUnavailable(reason: .noEngineConfigured).code,
            AppError.engineUnavailable(reason: .engineBinaryMissing).code,
            AppError.engineUnavailable(reason: .engineSignatureUnverified).code,
            AppError.engineUnavailable(reason: .platformUnsupported).code,
            AppError.tunnelStartRejected(code: "tunnel.start.permission-denied").code,
            AppError.tunnelStopRejected(code: "tunnel.stop.timed-out").code,
            AppError.tunnelStatusRejected(code: "tunnel.status.timed-out").code,
            AppError.fixtureLoadFailed(code: "fixtures.load.failed").code,
            AppError.routeExplanationFailed(code: "route.explanation.failed").code,
            AppError.unknown(code: "app.connect.failed").code,
            AppError(sanitizing: TunnelControlFailure.unknown, operation: .connect).code,
            AppError(sanitizing: TunnelControlFailure.permissionDenied, operation: .disconnect).code,
            AppError(sanitizing: TunnelControlFailure.configurationRejected, operation: .refreshStatus).code,
            AppError(sanitizing: TunnelControlFailure.permissionDenied, operation: .refreshStatus).code,
            AppError(sanitizing: TunnelControlFailure.configurationRejected, operation: .disconnect).code,
            AppError(sanitizing: TunnelControlFailure.timedOut, operation: .disconnect).code,
            AppError(sanitizing: TunnelControlFailure.configurationRejected, operation: .connect).code,
            AppError(sanitizing: TunnelControlFailure.timedOut, operation: .connect).code,
            AppError(sanitizing: TunnelControlFailure.permissionDenied, operation: .connect).code,
            AppError(sanitizing: TunnelControlFailure.timedOut, operation: .bootstrap).code,
            AppError(sanitizing: TunnelControlFailure.unknown, operation: .refreshStatus).code,
            AppError(sanitizing: TunnelControlFailure.unknown, operation: .disconnect).code,
            AppError(sanitizing: CanaryError("anything"), operation: .bootstrap).code,
            AppError(sanitizing: CanaryError("anything"), operation: .connect).code,
            AppError(sanitizing: CanaryError("anything"), operation: .disconnect).code,
            AppError(sanitizing: CanaryError("anything"), operation: .refreshStatus).code,
            AppError(sanitizing: TunnelControlFailure.engineUnavailable, operation: .connect).code,
            AppError(sanitizing: TunnelControlFailure.engineUnavailable, operation: .disconnect).code
        ]
        let allowed: Set<String> = [
            "engine.unavailable",
            "tunnel.start.permission-denied",
            "tunnel.start.configuration-rejected",
            "tunnel.start.timed-out",
            "tunnel.start.rejected",
            "tunnel.stop.permission-denied",
            "tunnel.stop.configuration-rejected",
            "tunnel.stop.timed-out",
            "tunnel.stop.rejected",
            "tunnel.status.permission-denied",
            "tunnel.status.configuration-rejected",
            "tunnel.status.timed-out",
            "tunnel.status.rejected",
            "fixtures.load.failed",
            "route.explanation.failed",
            "app.connect.failed",
            "app.disconnect.failed",
            "app.refreshStatus.failed"
        ]
        let produced = Set(codes)
        for code in produced {
            assertTrue(allowed.contains(code), "unexpected error code \(code)")
        }
        assertEqual(produced, allowed, "every declared error code should be reachable")
    }

    func testSampleFixtureContentStaysSelfConsistent() {
        let content = AppContent.sample
        assertTrue(content.isSampleData)
        assertFalse(content.isEmpty)
        assertFalse(content.servers.isEmpty)
        assertFalse(content.groups.isEmpty)
        assertFalse(content.routeRules.isEmpty)
        assertFalse(content.debugSamples.isEmpty)
        XCTAssertNotNil(content.subscription)
        assertEqual(content.enabledRuleCount, 4)

        let serverIDs = Set(content.servers.map(\.id))
        for group in content.groups {
            assertFalse(group.memberIDs.isEmpty)
            for member in group.memberIDs {
                assertTrue(serverIDs.contains(member), "group \(group.id) references an unknown server")
            }
        }
        for server in content.servers {
            for groupID in server.groupIDs {
                XCTAssertNotNil(content.group(id: groupID), "server \(server.id) references an unknown group")
            }
        }
        for (offset, rule) in content.routeRules.enumerated() {
            assertFalse(rule.matchers.isEmpty)
            assertEqual(rule.index, offset)
        }
        for sample in content.debugSamples {
            XCTAssertNotNil(content.debugSample(id: sample.id))
            assertFalse(sample.detail.isEmpty)
        }
        for rule in content.routeRules {
            if case let .group(id) = rule.action {
                XCTAssertNotNil(content.group(id: id), "rule \(rule.id) references an unknown group")
            }
        }
        if let subscription = content.subscription {
            assertFalse(subscription.entries.isEmpty)
            assertEqual(subscription.acceptedCount, subscription.entries.filter(\.isAccepted).count)
            assertTrue(subscription.hasRejectedEntries)
            for entry in subscription.entries {
                assertFalse(entry.redactedEndpointLabel.contains("."), "endpoint hosts must stay hidden")
            }
        }
    }

    func testSampleGroupAndRuleIdentifiersAreCanonicalUUIDs() {
        // The debugger hands the sample policy to the canonical route model,
        // which identifies groups and rules by UUID. A non-canonical identifier
        // cannot be bridged, and the bridge refuses rather than inventing one.
        let content = AppContent.sample
        XCTAssertFalse(content.groups.isEmpty)
        for group in content.groups {
            XCTAssertNotNil(
                UUID(uuidString: group.id),
                "group \(group.id) is not a canonical identifier"
            )
        }
        for rule in content.routeRules {
            XCTAssertNotNil(
                UUID(uuidString: rule.id),
                "rule \(rule.id) is not a canonical identifier"
            )
            if case let .group(id) = rule.action {
                XCTAssertNotNil(
                    UUID(uuidString: id),
                    "rule \(rule.id) names a group that is not a canonical identifier"
                )
            }
        }
        for groupID in content.groups.map(\.id) {
            XCTAssertNotNil(content.servers.filter { $0.groupIDs.contains(groupID) }, "unused group")
        }
    }

    func testTheBridgeRefusesContentTheCanonicalModelCannotRepresent() throws {
        // A display identifier that is not a canonical UUID cannot be handed to
        // the route model, and the bridge refuses instead of inventing one. The
        // display models are immutable, so each case is built rather than
        // mutated: a refusal has to be reachable from data a caller could
        // actually supply.
        let sample = AppContent.sample

        var actionless = sample
        actionless.routeRules[0] = rule(
            sample.routeRules[0],
            action: .group("grp-eu")
        )
        XCTAssertThrowsError(try CanonicalRouteBridge.routeSet(for: actionless)) { error in
            XCTAssertTrue(
                "\(error)".contains("grp-eu"),
                "the refusal must name the identifier it could not use, got \(error)"
            )
        }

        var unnamed = sample
        unnamed.groups[0] = ServerGroupSummary(
            id: "not-a-uuid",
            name: sample.groups[0].name,
            modeLabel: sample.groups[0].modeLabel,
            policyLabel: sample.groups[0].policyLabel,
            memberIDs: sample.groups[0].memberIDs
        )
        XCTAssertThrowsError(try CanonicalRouteBridge.context(for: unnamed)) { error in
            XCTAssertTrue(
                "\(error)".contains("not-a-uuid"),
                "the refusal must name the group identifier it could not use, got \(error)"
            )
        }
        XCTAssertThrowsError(try CanonicalRouteBridge.evaluation(
            sample: try XCTUnwrap(sample.debugSamples.first),
            content: unnamed
        ))

        var unevaluable = sample
        unevaluable.defaultRoute = .unavailable
        XCTAssertThrowsError(try CanonicalRouteBridge.routeSet(for: unevaluable)) { error in
            XCTAssertTrue(
                "\(error)".contains("unavailable"),
                "the refusal must explain why the outcome is not a route action, got \(error)"
            )
        }

        var badMatcher = sample
        badMatcher.routeRules[0] = rule(
            sample.routeRules[0],
            matchers: [
                RouteMatcherSummary(id: "rule-suffix-m0", kind: .port, value: "not-a-port")
            ]
        )
        XCTAssertThrowsError(try CanonicalRouteBridge.routeSet(for: badMatcher)) { error in
            XCTAssertTrue(
                "\(error)".contains("not-a-port"),
                "the refusal must name the matcher value it could not read, got \(error)"
            )
        }

        var misordered = sample
        misordered.routeRules[1] = rule(sample.routeRules[1], index: 7)
        XCTAssertThrowsError(try CanonicalRouteBridge.evaluation(
            sample: try XCTUnwrap(sample.debugSamples.first),
            content: misordered
        )) { error in
            XCTAssertTrue(
                "\(error)".contains("index"),
                "the refusal must say the declared order and the canonical order disagree, got \(error)"
            )
        }
    }

    func testTheDebuggerShowsExactlyWhatTheCanonicalEvaluatorDecided() throws {
        // The point of this test is that there is one route evaluator. It runs
        // the canonical evaluator directly for every sample input and requires
        // the debugger's display model to agree with it field for field, so a
        // second implementation inside the app cannot pass.
        let content = AppContent.sample
        let routeSet = try CanonicalRouteBridge.routeSet(for: content)
        let groupIDs = Set(try content.groups.map { group in
            guard let uuid = UUID(uuidString: group.id) else {
                throw CanonicalRouteBridgeError.notACanonicalIdentifier(group.id)
            }
            return uuid
        })
        let evaluator = RouteEvaluator()
        XCTAssertFalse(content.debugSamples.isEmpty)

        for sample in content.debugSamples {
            let canonical = try evaluator.explain(
                CanonicalRouteBridge.canonicalInput(for: sample.input),
                using: routeSet,
                context: RouteEvaluationContext(knownGroupIDs: groupIDs, selectedServers: [:])
            )
            let display = try CanonicalRouteBridge.evaluation(sample: sample, content: content)

            assertEqual(display.decision, expectedOutcome(canonical.finalDecision))
            assertEqual(display.selectedGroupID, canonical.selectedGroup?.uuidString)
            assertEqual(
                display.appliedRuleIndex,
                canonical.rules.firstIndex { $0.selected },
                "the applied rule index must come from the canonical diagnostic"
            )
            assertEqual(display.steps.count, canonical.rules.count)
            assertEqual(display.inputPresence, expectedPresence(canonical.inputSummary))

            for (step, rule) in zip(display.steps, canonical.rules) {
                assertEqual(step.ruleID, rule.ruleID.uuidString)
                assertEqual(step.isEnabled, rule.enabled)
                assertEqual(step.matched, rule.matched)
                assertEqual(step.evaluatedMatcherCount, rule.matchers.count)
                assertEqual(
                    step.appliedMatcherIndex,
                    rule.matchers.firstIndex { $0.applied },
                    "the applied matcher index must come from the canonical diagnostic"
                )
                assertEqual(
                    step.reason,
                    expectedReason(rule.reasonCode),
                    "the display reason must be derived from the canonical reason code"
                )
            }
        }
    }

    func testAFailedCanonicalEvaluationSurfacesASanitizedError() async {
        var content = AppContent.sample
        content.routeRules[0] = rule(
            content.routeRules[0],
            action: .group("grp-eu")
        )
        let model = await makePreparedModel(content: content)
        _ = await model.selectDebugSample("dbg-suffix")
        let evaluated = await model.runDebugEvaluation()
        assertTrue(evaluated, "the action is accepted; the evaluation is what fails")
        assertEqual(model.snapshot.evaluation, nil)
        assertEqual(model.snapshot.lastError?.code, "route.explanation.failed")
        let rendered = String(describing: model.snapshot.lastError)
        assertFalse(rendered.contains("grp-eu"), "the error must not echo the identifier it refused")
    }

    func testTheBridgeNamesAnInvariantViolationRatherThanIndexingPastTheContent() {
        // The count invariant cannot be reached from content the caller could
        // build, so it is not tested by producing one. What is tested is that the
        // failure mode is typed and named: the bridge states the assumption, and
        // the error case exists to carry it.
        let invariant = CanonicalRouteBridgeError.unreachableInvariant(
            "the canonical evaluator returned 4 rules for a route set of 3"
        )
        assertEqual(
            "\(invariant)",
            "the bridge and the canonical route model disagree: the canonical evaluator returned 4 rules for a route set of 3"
        )
        let refusal = CanonicalRouteBridgeError.evaluationRefused("invalidPort")
        assertEqual(
            "\(refusal)",
            "the canonical route evaluator refused the input: invalidPort"
        )
        assertFalse(
            "\(refusal)" == "\(invariant)",
            "a content refusal and an invariant violation must not read the same"
        )
    }

    func testADiagnosticAndItsRuleListCarryTheSameMatchers() throws {
        // `RoutingDiagnostic` exposes the matchers twice: nested under each rule,
        // and flattened. A renderer that reads one and a schema that describes
        // the other would disagree if the two could differ, so they are compared
        // here for every sample input.
        let content = AppContent.sample
        let routeSet = try CanonicalRouteBridge.routeSet(for: content)
        let context = try CanonicalRouteBridge.context(for: content)
        XCTAssertFalse(content.debugSamples.isEmpty)

        for sample in content.debugSamples {
            let diagnostic = try RouteEvaluator().explain(
                CanonicalRouteBridge.canonicalInput(for: sample.input),
                using: routeSet,
                context: context
            )
            assertEqual(
                diagnostic.matchers,
                diagnostic.rules.flatMap(\.matchers),
                "the flat matcher list must be the rule list flattened"
            )
            for rule in diagnostic.rules {
                assertEqual(
                    rule.matchers.filter(\.selected).count,
                    rule.selected ? 1 : 0,
                    "exactly one matcher is selected in the deciding rule, and none in any other"
                )
            }
        }
    }

    private func rule(
        _ source: RouteRuleSummary,
        index: Int? = nil,
        action: RouteOutcome? = nil,
        matchers: [RouteMatcherSummary]? = nil
    ) -> RouteRuleSummary {
        RouteRuleSummary(
            id: source.id,
            index: index ?? source.index,
            isEnabled: source.isEnabled,
            action: action ?? source.action,
            matchers: matchers ?? source.matchers,
            note: source.note
        )
    }

    private func expectedOutcome(_ action: RouteAction) -> RouteOutcome {
        switch action {
        case .direct: return .direct
        case .block: return .block
        case let .group(id): return .group(id.uuidString)
        }
    }

    private func expectedPresence(_ summary: RoutingInputSummary) -> String {
        var fields: [String] = []
        if summary.hasHost { fields.append("host present") }
        if summary.hasIP { fields.append("address present") }
        if summary.hasPort { fields.append("port present") }
        if summary.hasNetwork { fields.append("network present") }
        return fields.isEmpty ? "no input fields" : fields.joined(separator: ", ")
    }

    private func expectedReason(_ reasonCode: String) -> DebugReason {
        guard let code = RoutingRuleReasonCode(rawValue: reasonCode) else {
            return .noMatcherMatched
        }
        switch code {
        case .ruleDisabled: return .ruleDisabled
        case .noMatchers, .noMatchingMatcher: return .noMatcherMatched
        case .firstMatchingRule: return .applied
        case .shadowedByEarlierMatch: return .shadowed
        }
    }
}

private struct CanaryError: Error, CustomStringConvertible, LocalizedError {
    let description: String

    init(_ description: String) {
        self.description = description
    }

    var errorDescription: String? { description }
}

private final class TestClock: @unchecked Sendable {
    private let lock = NSLock()
    private var current: Date

    init(_ start: Date) {
        current = start
    }

    var now: Date {
        lock.lock()
        defer { lock.unlock() }
        return current
    }

    func advance(_ seconds: TimeInterval) {
        lock.lock()
        current = current.addingTimeInterval(seconds)
        lock.unlock()
    }
}

actor CountingFixtureProvider: FixtureProviding {
    private(set) var loadCount = 0
    private var isGated = false
    private var isParked = false
    private var gateWaiters: [CheckedContinuation<Void, Never>] = []
    private let content: AppContent
    private let loadError: (any Error)?

    init(content: AppContent, loadError: (any Error)? = nil) {
        self.content = content
        self.loadError = loadError
    }

    func gate() {
        isGated = true
    }

    func waitUntilParked() async {
        while !isParked {
            await Task.yield()
        }
    }

    func release() {
        isGated = false
        isParked = false
        let waiters = gateWaiters
        gateWaiters = []
        for waiter in waiters {
            waiter.resume()
        }
    }

    func loadFixture() async throws -> AppContent {
        loadCount += 1
        if isGated {
            await withCheckedContinuation { continuation in
                gateWaiters.append(continuation)
                isParked = true
            }
        }
        if let loadError {
            throw loadError
        }
        return content
    }
}

actor StubTunnelController: TunnelControlling {
    private var availability: EngineAvailability = .available
    private var status: TunnelStatus = .disconnected
    private var startError: (any Error)?
    private var stopError: (any Error)?
    private(set) var startCallCount = 0
    private(set) var stopCallCount = 0

    func setAvailability(_ availability: EngineAvailability) {
        self.availability = availability
    }

    func setStatus(_ status: TunnelStatus) {
        self.status = status
    }

    func setStartError(_ error: (any Error)?) {
        startError = error
    }

    func setStopError(_ error: (any Error)?) {
        stopError = error
    }

    func engineAvailability() async -> EngineAvailability {
        availability
    }

    func requestStart() async throws {
        startCallCount += 1
        if let startError {
            throw startError
        }
    }

    func requestStop() async throws {
        stopCallCount += 1
        if let stopError {
            throw stopError
        }
    }

    func currentStatus() async -> TunnelStatus {
        status
    }
}

actor GateTunnelController: TunnelControlling {
    private var startWaiters: [CheckedContinuation<Void, Never>] = []
    private var isStartParked = false
    private(set) var startCallCount = 0
    private(set) var stopCallCount = 0

    func engineAvailability() async -> EngineAvailability {
        .available
    }

    func requestStart() async throws {
        startCallCount += 1
        await withCheckedContinuation { continuation in
            startWaiters.append(continuation)
            isStartParked = true
        }
    }

    func requestStop() async throws {
        stopCallCount += 1
    }

    func currentStatus() async -> TunnelStatus {
        .connecting
    }

    func waitUntilStartIsParked() async {
        while !isStartParked {
            await Task.yield()
        }
    }

    func releaseStarts() {
        isStartParked = false
        let waiters = startWaiters
        startWaiters = []
        for waiter in waiters {
            waiter.resume()
        }
    }
}
