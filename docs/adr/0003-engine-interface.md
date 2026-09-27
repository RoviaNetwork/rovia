# ADR-0003: Engine-neutral engine interface

- Status: Accepted
- Date: 2026-09-24
- Owners: Rovia maintainers

## Context

Rovia must support more than one proxy engine without making the domain depend on any engine. The interface needs to express capabilities, validation, preparation, lifecycle, status, and health probing without exposing native JSON.

## Decision

Define a `TunnelEngine` protocol with these operations:

```swift
var descriptor: EngineDescriptor { get }
func capabilities() async -> EngineCapabilities
func validate(_ configuration: CanonicalTunnelConfiguration) async throws -> ValidationReport
func prepare(_ configuration: CanonicalTunnelConfiguration) async throws -> PreparedEngineConfiguration
func start(_ context: TunnelRuntimeContext) async throws
func stop() async
func status() async -> EngineStatus
func probe(_ request: HealthProbeRequest) async throws -> HealthProbeResult
```

Define a separate compiler contract that converts a canonical tunnel configuration to an engine-owned output. The output type is not part of the domain API. `TunnelRuntimeContext` also carries a platform-neutral `PacketBridge`; the Apple adapter supplies a bridge backed by `NEPacketTunnelFlow` without exposing NetworkExtension to the engine package.

The initial adapters are explicit unavailable implementations. An adapter is an architectural boundary, not an automatic licensing boundary.

## Consequences

- Engine-specific configuration stays inside the adapter.
- A future sing-box adapter can be added without changing the UI model.
- Engine capabilities can be used to disable unsupported features in the UI.
- Engine runtime health and routing health remain separate concerns.

## Rejected alternatives

- Exposing Xray JSON throughout the app.
- Defining a lowest-common-denominator configuration that hides meaningful engine capabilities.
- Treating a Swift wrapper as proof of legal isolation from its linked engine.
