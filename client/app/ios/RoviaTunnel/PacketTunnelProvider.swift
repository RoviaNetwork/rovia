import Foundation
import NetworkExtension

final class PacketTunnelProvider: NEPacketTunnelProvider {
    private static let engineAvailability: EngineAvailability = .unavailable(
        reason: "No production engine is enabled in this foundation build."
    )

    override func startTunnel(
        options: [String: NSObject]?,
        completionHandler: @escaping (Error?) -> Void
    ) {
        let completion = TunnelCompletion(handler: completionHandler)
        let providerBridge = TunnelProviderBridge(provider: self)
        let coordinator = TunnelLaunchCoordinator(
            availability: Self.engineAvailability,
            networkSettingsApplying: { [providerBridge] in
                await withCheckedContinuation { continuation in
                    let settings = Self.makeNetworkSettings()
                    let settingsCompletion = TunnelCompletion { error in
                        completion.call(error)
                        continuation.resume()
                    }
                    providerBridge.applyNetworkSettings(settings) { error in
                        settingsCompletion.call(error)
                    }
                }
            }
        )

        Task {
            let decision = await coordinator.launch()
            switch decision {
            case .applyNetworkSettings:
                break
            case let .unavailable(reason):
                completion.call(TunnelProviderError.engineUnavailable(reason: reason))
            }
        }
    }

    private static func makeNetworkSettings() -> NEPacketTunnelNetworkSettings {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "127.0.0.1")
        let ipv4 = NEIPv4Settings(
            addresses: ["10.255.0.2"],
            subnetMasks: ["255.255.255.0"]
        )
        ipv4.includedRoutes = [NEIPv4Route.default()]
        settings.ipv4Settings = ipv4

        let ipv6 = NEIPv6Settings(addresses: ["fd00:102::2"], networkPrefixLengths: [64])
        ipv6.includedRoutes = [NEIPv6Route.default()]
        settings.ipv6Settings = ipv6
        return settings
    }

    override func stopTunnel(
        with reason: NEProviderStopReason,
        completionHandler: @escaping () -> Void
    ) {
        completionHandler()
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
            completionHandler?(makeResponse(requestID: request.requestID, ok: true, result: ["state": "disconnected"]))
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

private final class TunnelProviderBridge: @unchecked Sendable {
    private let provider: PacketTunnelProvider

    init(provider: PacketTunnelProvider) {
        self.provider = provider
    }

    func applyNetworkSettings(
        _ settings: NEPacketTunnelNetworkSettings,
        completion: @escaping @Sendable (Error?) -> Void
    ) {
        provider.setTunnelNetworkSettings(settings, completionHandler: completion)
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

    var errorDescription: String? {
        switch self {
        case let .engineUnavailable(reason):
            reason
        }
    }
}
