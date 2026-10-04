import Foundation
import RoviaApplePlatform
import RoviaConfig
import RoviaSubscription
import XCTest

private let wiringVLESS =
    "vless://00000000-0000-0000-0000-000000000001@synthetic.example:443?encryption=none&security=tls&type=tcp"

private final class RecordingConfigWriter: TunnelConfigWriting, @unchecked Sendable {
    private(set) var calls: [(serverID: ServerID, killSwitch: Bool)] = []

    func writeConfiguration(serverID: ServerID, killSwitch: Bool) async throws {
        calls.append((serverID, killSwitch))
    }
}

private final class RecordingSettingsStore: TunnelSettingsStoring, @unchecked Sendable {
    private var stored = TunnelSettings()
    private(set) var saves: [TunnelSettings] = []

    func loadSettings() -> TunnelSettings { stored }

    func saveSettings(_ settings: TunnelSettings) throws {
        saves.append(settings)
        stored = settings
    }
}

@MainActor
final class TunnelWiringTests: XCTestCase {
    private func makeModel(
        tunnel: any TunnelControlling,
        coordinator: SubscriptionCoordinator? = nil,
        configWriter: (any TunnelConfigWriting)? = nil,
        settingsStore: (any TunnelSettingsStoring)? = nil,
        appearanceStorage: UserDefaults? = nil
    ) -> AppModel {
        AppModel(
            tunnel: tunnel,
            fixtures: StaticFixtureProvider(content: .sample),
            subscriptions: coordinator,
            configWriter: configWriter,
            settingsStore: settingsStore,
            selectionStorage: UserDefaults(suiteName: "rovia.test.\(UUID().uuidString)"),
            appearanceStorage: appearanceStorage
        )
    }

    private func makeCoordinator() -> (SubscriptionCoordinator, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let coordinator = SubscriptionCoordinator(
            store: SubscriptionStore(directory: directory),
            secrets: InMemorySecretStore(),
            session: CoordinatorNeverSession()
        )
        return (coordinator, directory)
    }

    func testKillSwitchTogglePersistsThroughTheStore() async {
        let settings = RecordingSettingsStore()
        let model = makeModel(tunnel: StubTunnelController(), settingsStore: settings)

        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared)
        XCTAssertFalse(model.snapshot.killSwitch)

        let flipped = await model.setKillSwitch(true)
        XCTAssertTrue(flipped)
        XCTAssertTrue(model.snapshot.killSwitch)
        XCTAssertEqual(settings.saves, [TunnelSettings(killSwitch: true)])

        // A fresh model over the same store restores the toggle.
        let restored = makeModel(tunnel: StubTunnelController(), settingsStore: settings)
        let restoredPrepared = await restored.bootstrap()
        XCTAssertTrue(restoredPrepared)
        XCTAssertTrue(restored.snapshot.killSwitch)
    }

    func testConnectWritesTheHandoffForTheResolvedServer() async throws {
        let (coordinator, directory) = makeCoordinator()
        defer { try? FileManager.default.removeItem(at: directory) }
        let summary = try await coordinator.addSingleLink(wiringVLESS, name: "Single")
        XCTAssertEqual(summary.accepted, 1)

        let writer = RecordingConfigWriter()
        let model = makeModel(
            tunnel: StubTunnelController(),
            coordinator: coordinator,
            configWriter: writer
        )
        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared)
        let connected = await model.connect()
        XCTAssertTrue(connected)

        XCTAssertEqual(writer.calls.count, 1)
        // No explicit selection: the first visible server is the resolved one.
        let records = await coordinator.subscriptions()
        let servers = records.flatMap(\.servers)
        let expectedID = SubscriptionCoordinator.summaryID(
            subscriptionID: records.first!.id,
            serverID: servers.first!.id
        )
        XCTAssertEqual(writer.calls.first?.serverID, expectedID)
        XCTAssertFalse(writer.calls.first?.killSwitch ?? true)
    }

    func testConnectWithoutAnyServerIsRefusedLoudly() async {
        let (coordinator, directory) = makeCoordinator()
        defer { try? FileManager.default.removeItem(at: directory) }
        let writer = RecordingConfigWriter()
        let model = makeModel(
            tunnel: StubTunnelController(),
            coordinator: coordinator,
            configWriter: writer
        )
        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared)
        let connected = await model.connect()
        XCTAssertFalse(connected)
        XCTAssertEqual(model.snapshot.lastError, .tunnelStartRejected(code: "tunnel.start.no-server"))
        XCTAssertEqual(writer.calls.count, 0)
    }

    func testHandoffWriterPlacesPlaceholdersNotCredentials() async throws {
        let (coordinator, directory) = makeCoordinator()
        let container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer {
            // Cleanup is best-effort; a cleanup failure is not the test's result.
            try? FileManager.default.removeItem(at: directory)
            try? FileManager.default.removeItem(at: container)
        }
        _ = try await coordinator.addSingleLink(wiringVLESS, name: "Single")

        let handoff = TunnelHandoff(container: container)
        let writer = TunnelHandoffWriter(coordinator: coordinator, handoff: handoff)

        let records = await coordinator.subscriptions()
        let server = try XCTUnwrap(records.first?.servers.first)
        let summaryID = SubscriptionCoordinator.summaryID(subscriptionID: records.first!.id, serverID: server.id)

        do {
            try await writer.writeConfiguration(serverID: summaryID, killSwitch: true)
        } catch {
            XCTFail("writeConfiguration threw: \(error)")
            return
        }

        let settings = handoff.readSettings()
        XCTAssertTrue(settings.killSwitch)

        let canonical = try handoff.readCanonicalConfiguration()
        XCTAssertEqual(canonical.appConfig.servers.count, 1)
        let written = try XCTUnwrap(canonical.appConfig.servers.first)
        XCTAssertEqual(written.endpoint.host, "synthetic.example")
        // The credential is a reference, never a value.
        XCTAssertNotNil(written.credential?.key)
        let text = String(decoding: try JSONEncoder().encode(canonical), as: UTF8.self)
        XCTAssertFalse(text.contains("00000000-0000-0000-0000-000000000001"), "the credential UUID leaked into the hand-off file")
    }

    func testHandoffReadsBackWhatItWritesAndDefaultsSafely() throws {
        let container = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: container) }
        let handoff = TunnelHandoff(container: container)

        // Nothing written: safe defaults, no throw.
        XCTAssertEqual(handoff.readSettings(), TunnelSettings())
        XCTAssertThrowsError(try handoff.readCanonicalConfiguration()) { error in
            XCTAssertEqual(error as? TunnelHandoff.TunnelHandoffError, .configurationMissing)
        }
    }

    func testAppearancePersistsAndRestores() async {
        let storage = UserDefaults(suiteName: "rovia.test.\(UUID().uuidString)")!
        let model = makeModel(tunnel: StubTunnelController(), appearanceStorage: storage)
        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared)
        XCTAssertEqual(model.snapshot.appearance, .system)

        let changed = await model.setAppearance(.dark)
        XCTAssertTrue(changed)
        XCTAssertEqual(model.snapshot.appearance, .dark)

        let restored = makeModel(tunnel: StubTunnelController(), appearanceStorage: storage)
        let restoredPrepared = await restored.bootstrap()
        XCTAssertTrue(restoredPrepared)
        XCTAssertEqual(restored.snapshot.appearance, .dark)
    }

    func testStatisticsRefreshStoresTheEnginesOwnReport() async {
        let tunnel = StubTunnelController()
        await tunnel.setReport(TunnelStatusReport(
            state: "connected",
            engineVersion: "Xray 26.9.9",
            droppedOutbound: 3,
            droppedInbound: 1
        ))
        let model = makeModel(tunnel: tunnel)
        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared)

        XCTAssertNil(model.snapshot.engineReport)
        let refreshed = await model.refreshStatistics()
        XCTAssertTrue(refreshed)
        XCTAssertEqual(model.snapshot.engineReport?.engineVersion, "Xray 26.9.9")
        XCTAssertEqual(model.snapshot.engineReport?.droppedOutbound, 3)
        XCTAssertEqual(model.snapshot.engineReport?.droppedInbound, 1)
    }

    func testAnUnansweredStatisticsPollKeepsThePreviousReport() async {
        let tunnel = StubTunnelController()
        await tunnel.setReport(TunnelStatusReport(
            state: "connected",
            engineVersion: "Xray 26.9.9",
            droppedOutbound: 0,
            droppedInbound: 0
        ))
        let model = makeModel(tunnel: tunnel)
        let prepared = await model.bootstrap()
        XCTAssertTrue(prepared)
        _ = await model.refreshStatistics()
        XCTAssertNotNil(model.snapshot.engineReport)

        await tunnel.setReport(nil)
        _ = await model.refreshStatistics()
        // An unanswered poll leaves the previous report — never a fabricated zero.
        XCTAssertNotNil(model.snapshot.engineReport)
    }
}

private final class CoordinatorNeverSession: SubscriptionHTTPSession {
    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        throw SubscriptionFetchError.timedOut
    }
}
