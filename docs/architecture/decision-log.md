# Decision log

The authoritative decisions are the ADRs in `docs/adr/`. This file is a short index for reviewers.

| Decision | Status | ADR | Main consequence |
| --- | --- | --- | --- |
| Start with iOS and native SwiftUI | Accepted for foundation | 0001 | Apple lifecycle constraints are discovered early |
| Use a canonical, versioned model | Accepted | 0002 | UI and engines do not share native JSON |
| Keep the Engine API engine-neutral | Accepted | 0003 | Adapters can be added behind a stable boundary |
| Gate sing-box on licensing and distribution review | Accepted | 0004 | No sing-box binary is bundled in the foundation |
| Allow one Go runtime per process | Accepted | 0005 | Xray and sing-box are not independently linked together |
| Use public `packetFlow` for Apple packet I/O | Accepted | 0006 | The open problem is the Xray bridge, not packet-flow API access |

## Review corrections to the original plan

1. `NEPacketTunnelProvider.packetFlow` and `NEPacketTunnelFlow` are public Apple APIs. The plan should not describe the entire packet-flow path as unavailable or undocumented. The unresolved spike is how to bridge those IP packets to the selected engine without private APIs.
2. The current libXray README documents a structured `Invoke` API and explicitly warns about multiple independently built Go runtimes. Its API and supported methods must be pinned and rechecked at the exact source revision used for a release.
3. `stopTunnel` is a system lifecycle callback. An unrecoverable provider failure should use `cancelTunnelWithError` according to the public API contract rather than treating `stopTunnel` as a general-purpose shutdown command.
4. Apple App Review requirements are living requirements. The repository records the relevant public API and code-distribution constraints, while release owners must recheck the current VPN-specific review section and account requirements.

## Open assumptions

- The organization has, or will obtain, the Apple Developer resources required for Packet Tunnel distribution.
- A physical device and real provisioning profiles are available for the tunnel acceptance gate.
- Legal review will be obtained before distributing any GPL-covered engine in an App Store build.
- The Android implementation will consume the portable schemas and fixtures rather than reverse-engineer Swift types.
