# Rovia architecture overview

## Goal

Rovia separates a native network client from its proxy engines. The application owns user intent, routing policy, health observations, and secrets. An engine adapter owns translation to a native engine configuration and runtime lifecycle.

## Layers

```text
SwiftUI host app
    -> application/view models
    -> canonical domain core
    -> engine API
    -> Xray adapter or future sing-box adapter
    -> Packet Tunnel Provider extension
```

The Packet Tunnel extension is the only component that should own the running engine. The host app owns the VPN profile and communicates with the extension through a versioned control message envelope.

## Module boundaries

- `RoviaConfig` owns versioned canonical persisted models and secret references.
- `RoviaRouting` owns deterministic, offline route evaluation and traces.
- `RoviaSubscription` owns sanitized subscription source and server models.
- `RoviaEngineAPI` owns engine-neutral lifecycle and compilation contracts.
- `RoviaXray` and `RoviaSingBox` are adapters. They must not leak native JSON into the domain.
- `platform/apple` owns NetworkExtension, Keychain, App Group, and platform lifecycle integration.

Core packages must not import Apple UI frameworks, NetworkExtension, or native engine libraries.

## Canonical data flow

```text
User model
    -> Canonical Rovia model
    -> EngineConfigCompiler
    -> Engine-native configuration
    -> Prepared engine configuration
```

Routing rules are ordered domain objects. They are not aliases for Xray routing rules or sing-box route rules.

## Privacy invariants

- No analytics or telemetry SDK is present.
- Packet payloads are not logged.
- Browsing history is not collected.
- Provider URLs, tokens, UUID credentials, and passwords are never persisted in canonical configuration.
- Diagnostics are sanitized before serialization, not merely hidden in the UI.
- No unauthenticated network listener is opened by the foundation.

## Apple integration invariant

The host app and Packet Tunnel extension are separate processes with a narrow shared surface. The extension uses `NEPacketTunnelProvider` and its public `packetFlow` property. The implementation does not assume access to a raw utun file descriptor or any private Apple API.

## Current foundation status

The repository currently implements the domain and boundary contracts, not a production VPN. A production engine is intentionally disabled until the packet-flow bridge, exact artifact pinning, signing, and licensing gates are completed.
