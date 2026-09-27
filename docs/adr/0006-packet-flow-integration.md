# ADR-0006: Public Apple packet-flow integration

- Status: Accepted for the foundation; bridge spike pending
- Date: 2026-09-24
- Owners: Rovia Apple maintainers

## Context

The original plan treated the entire iOS packet-flow path as an undocumented raw file-descriptor problem. Current Apple documentation exposes `NEPacketTunnelProvider.packetFlow` as an `NEPacketTunnelFlow`, with public methods for reading and writing IP packets. The entitlement and Packet Tunnel extension requirements remain.

The remaining uncertainty is how to connect those packets to Xray's TUN implementation inside the extension process without private APIs, unsafe assumptions, or multiple runtimes.

## Decision

Use `packetFlow` for packet I/O. Do not design around a raw utun file descriptor. Build a dedicated spike that bridges public packet-flow reads/writes to the pinned Xray/libXray artifact, with explicit backpressure, cancellation, IPv4/IPv6 behavior, and shutdown semantics.

The foundation may configure a minimal tunnel and report a typed unavailable-engine error, but it must not claim end-to-end proxy connectivity until the spike passes on a physical device.

## Acceptance criteria for the spike

- A pinned XCFramework builds for arm64 iOS.
- The extension starts and stops without private API usage.
- Outbound packets enter the engine and inbound packets return through `packetFlow`.
- IPv4 and IPv6 tests pass.
- Backpressure and cancellation do not deadlock.
- No packet payload appears in logs.
- The test result records the exact device, OS, artifact hash, and configuration.
