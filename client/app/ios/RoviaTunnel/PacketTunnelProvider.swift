import Foundation
import NetworkExtension
import RoviaConfig
import RoviaEngineAPI
import RoviaXray
import RoviaXrayLive

/// NEPacketTunnelProvider is invoked on the system's queue and its mutable
/// state is only ever touched from the provider's own async hops, so the
/// class isSendable-by-discipline: the conformance is declared, and the
/// state is confined to the tasks the provider itself starts.
final class PacketTunnelProvider: NEPacketTunnelProvider, @unchecked Sendable {
    /// The live adapter for this process, built once: the descriptor version
    /// is read from the artifact at construction. The secret reader resolves
    /// the placeholder keys in the compiled engine config from the shared
    /// Keychain access group — credentials never travel through the App Group
    /// file.
    private var adapter: XrayAdapter?
    private var engineObserver: Task<Void, Never>?

    private static var secretReader: @Sendable (String) throws -> Data? {
        let store = KeychainSecretStore(
            service: "io.rovia.client",
            accessGroup: KeychainAccessGroup.resolve()
        )
        return { key in try store.read(for: key) }
    }

    override func startTunnel(
        options: [String: NSObject]?,
        completionHandler: @escaping (Error?) -> Void
    ) {
        let completion = TunnelCompletion(handler: completionHandler)
        Task {
            do {
                try await self.startEngine()
                completion.call(nil)
            } catch {
                completion.call(error)
            }
        }
    }

    /// The start order is the fail-closed contract: the engine is prepared
    /// and started *before* any network setting is applied, so the default
    /// route never exists without something consuming it. A failure at any
    /// step leaves the extension refusing to start rather than half-up.
    private func startEngine() async throws {
        let handoff = try TunnelHandoff()
        let configuration = try handoff.readCanonicalConfiguration()
        let settings = handoff.readSettings()

        let adapter = XrayAdapter.live(secretReader: Self.secretReader)
        let report = try await adapter.validate(configuration)
        guard report.valid else {
            throw TunnelProviderError.engineUnavailable(reason: "the stored configuration failed validation")
        }
        let prepared = try await adapter.prepare(configuration)
        let context = TunnelRuntimeContext(
            sessionID: UUID(),
            platform: "ios",
            preparedConfiguration: prepared,
            packetBridge: PacketFlowBridge(flow: packetFlow)
        )
        try await adapter.start(context)
        self.adapter = adapter

        // The engine is running and consuming the fd before the default route
        // exists; anything the engine emits in between waits in the pair.
        try await applyNetworkSettings(Self.makeNetworkSettings())

        if settings.killSwitch {
            observeEngineFailure(adapter)
        }
    }

    /// Kill-switch semantics: an engine that dies while the tunnel is up
    /// tears the tunnel down. With `includeAllNetworks` and the always-connect
    /// on-demand rules the app installs, iOS blackholes traffic until the
    /// tunnel returns, and restarts it — the retry is the platform's, with its
    /// own backoff, not a loop this process owns.
    private func observeEngineFailure(_ adapter: XrayAdapter) {
        engineObserver = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if case let .failed(reason) = await adapter.status() {
                    self?.cancelTunnelWithError(TunnelProviderError.engineFailed(reason: reason))
                    return
                }
            }
        }
    }

    private func applyNetworkSettings(_ settings: NEPacketTunnelNetworkSettings) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            setTunnelNetworkSettings(settings) { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }
    }

    /// The tunnel's own addresses: the engine answers DNS through its `dns`
    /// outbound, so the resolver points at the tunnel and every lookup enters
    /// as a packet — no DNS leaves the device unproxied.
    private static func makeNetworkSettings() -> NEPacketTunnelNetworkSettings {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "10.255.0.1")
        let ipv4 = NEIPv4Settings(
            addresses: ["10.255.0.2"],
            subnetMasks: ["255.255.255.0"]
        )
        ipv4.includedRoutes = [NEIPv4Route.default()]
        settings.ipv4Settings = ipv4

        let ipv6 = NEIPv6Settings(addresses: ["fd00:102::2"], networkPrefixLengths: [64])
        ipv6.includedRoutes = [NEIPv6Route.default()]
        settings.ipv6Settings = ipv6

        let dns = NEDNSSettings(servers: ["10.255.0.1"])
        dns.matchDomains = [""]
        settings.dnsSettings = dns
        return settings
    }

    override func stopTunnel(
        with reason: NEProviderStopReason,
        completionHandler: @escaping () -> Void
    ) {
        engineObserver?.cancel()
        engineObserver = nil
        let completion = TunnelCompletion(handler: { _ in completionHandler() })
        Task {
            await self.adapter?.stop()
            self.adapter = nil
            completion.call(nil)
        }
    }

    override func handleAppMessage(
        _ messageData: Data,
        completionHandler: ((Data?) -> Void)?
    ) {
        guard let request = decodeRequest(messageData) else {
            completionHandler?(
                makeResponse(
                    requestID: "unknown",
                    ok: false,
                    error: ControlContract.refusalInvalidRequest
                )
            )
            return
        }

        switch request.method {
        case .statusGet:
            let completion = MessageCompletion(completionHandler)
            Task {
                let payload = await statusPayload()
                completion.call(makeResponse(requestID: request.requestID, ok: true, result: payload))
            }
        case .engineCapabilities, .subscriptionInspect, .routingExplain, .healthSnapshot, .groupSelect:
            completionHandler?(
                makeResponse(
                    requestID: request.requestID,
                    ok: false,
                    error: ControlContract.refusalNotImplemented
                )
            )
        }
    }

    /// The status vocabulary the response schema allows: one bounded string,
    /// plus the engine's version and the pump's drop counters when an engine
    /// exists. Counters and a version, never payloads — that is the whole
    /// observability surface this method is allowed to have.
    private func statusPayload() async -> [String: Any] {
        guard let adapter else { return ["state": "disconnected"] }
        var payload: [String: Any] = ["state": await statusString(adapter: adapter)]
        let version = adapter.descriptor.version
        if !version.isEmpty, version != "not-enabled" {
            payload["engineVersion"] = version
        }
        let counters = await adapter.pumpCounters()
        payload["droppedOutbound"] = counters.outboundDrops
        payload["droppedInbound"] = counters.inboundDrops
        return payload
    }

    private func statusString(adapter: XrayAdapter) async -> String {
        switch await adapter.status() {
        case .unavailable:
            return "unavailable"
        case .idle:
            return "idle"
        case .preparing:
            return "connecting"
        case .running:
            return "connected"
        case .stopping:
            return "disconnecting"
        case .failed:
            return "failed"
        }
    }

    /// Decodes a control request, or refuses it.
    ///
    /// The three rules below are the request contract in
    /// `schemas/control-api.schema.json`, and they are enforced here because the
    /// schema cannot run inside the extension:
    ///
    /// - the envelope is closed, so a fifth field is refused rather than
    ///   ignored, and reading four keys out of a five-key object would let a
    ///   caller smuggle state past the contract;
    /// - `requestID` is 1 to 128 characters, which is the same bound
    ///   `schemas/control-response.schema.json` puts on the echoed identifier, so
    ///   a host can always match a refusal to its own request; and
    /// - `status.get` takes no parameters, so its payload must be empty.
    private func decodeRequest(_ messageData: Data) -> ControlRequest? {
        guard messageData.count <= ControlContract.maximumMessageBytes,
              let object = try? JSONSerialization.jsonObject(with: messageData),
              let fields = object as? [String: Any],
              Set(fields.keys) == ControlContract.envelopeFields,
              fields["apiVersion"] as? Int == ControlContract.apiVersion,
              let requestID = fields["requestID"] as? String,
              (1...ControlContract.maximumRequestIDCharacters).contains(requestID.count),
              let methodValue = fields["method"] as? String,
              let method = ControlMethod(rawValue: methodValue),
              let payload = fields["payload"] as? [String: Any] else {
            return nil
        }
        guard !method.needsEmptyPayload || payload.isEmpty else { return nil }
        return ControlRequest(requestID: requestID, method: method, payload: payload)
    }

    private func makeResponse(
        requestID: String,
        ok: Bool,
        result: [String: Any]? = nil,
        error: String? = nil
    ) -> Data? {
        var response: [String: Any] = [
            "apiVersion": ControlContract.apiVersion,
            "requestID": requestID,
            "ok": ok
        ]
        if let result {
            response["result"] = result
        }
        if let error {
            response["error"] = error
        }
        return try? JSONSerialization.data(withJSONObject: response, options: [.sortedKeys])
    }
}

/// The parts of the control contract the extension enforces at runtime.
///
/// Every value here is stated in a schema as well: the API version and the
/// envelope fields in `schemas/control-api.schema.json`, and the refusals in
/// `schemas/control-response.schema.json`. `tools/ci/test_validate_schemas.py`
/// reads both schemas and this file and requires them to agree, so a change to
/// one side that is not made on the other fails the suite.
private enum ControlContract {
    static let apiVersion = 1
    /// A request is refused above this size rather than truncated or buffered.
    static let maximumMessageBytes = 65_536
    /// The same bound the response schema puts on the echoed identifier.
    static let maximumRequestIDCharacters = 128
    /// The closed request envelope. A field outside this set is refused.
    static let envelopeFields: Set<String> = ["apiVersion", "requestID", "method", "payload"]
    static let refusalInvalidRequest = "invalid-request"
    static let refusalNotImplemented = "not-implemented"
}

private struct ControlRequest {
    let requestID: String
    let method: ControlMethod
    let payload: [String: Any]
}

/// A provider-message completion boxed for the async hop: `handleAppMessage`
/// answers on a Task, and the closure is only ever called once by
/// construction.
private final class MessageCompletion: @unchecked Sendable {
    private let handler: (Data?) -> Void

    init(_ handler: ((Data?) -> Void)?) {
        self.handler = handler ?? { _ in }
    }

    func call(_ data: Data?) {
        handler(data)
    }
}

private enum ControlMethod: String, CaseIterable {
    case statusGet = "status.get"
    case engineCapabilities = "engine.capabilities"
    case subscriptionInspect = "subscription.inspect"
    case routingExplain = "routing.explain"
    case healthSnapshot = "health.snapshot"
    case groupSelect = "group.select"

    /// `status.get` takes no parameters: the extension reports what it knows, and
    /// a payload would turn the request into a channel for host state the
    /// extension did not already report.
    ///
    /// The other methods are the documented limit of this slice.
    /// `schemas/control-api.schema.json` defines a payload shape for
    /// `routing.explain` and for `group.select`, and the provider does not check
    /// either, because neither is implemented: it answers `not-implemented`
    /// before it reads the payload. A method that starts answering has to
    /// validate its payload against the declared shape in the same commit that
    /// makes it answer.
    var needsEmptyPayload: Bool { self == .statusGet }
}

private enum TunnelProviderError: LocalizedError {
    case engineUnavailable(reason: String)
    case engineFailed(reason: String)

    var errorDescription: String? {
        switch self {
        case let .engineUnavailable(reason):
            reason
        case let .engineFailed(reason):
            "engine failed: \(reason)"
        }
    }
}
