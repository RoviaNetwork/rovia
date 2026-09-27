# ADR-0001: iOS-first platform strategy

- Status: Accepted for the foundation
- Date: 2026-09-24
- Owners: Rovia maintainers

## Context

Rovia is intended to become a cross-platform network client, but the first implementation must expose platform lifecycle constraints early. iOS Packet Tunnel providers have strict entitlements, signing, extension lifecycle, and App Review requirements. Android's `VpnService` exposes a different file-descriptor-oriented integration path.

## Decision

Phase 1 uses Swift, SwiftUI, and NetworkExtension with an `NEPacketTunnelProvider` extension. Android follows with Kotlin, Jetpack Compose, and `VpnService` after the iOS vertical slice is proven.

The first three implementation sprints do not introduce Flutter, React Native, Kotlin Multiplatform, Rust, or another cross-platform UI/runtime framework. Portable JSON schemas and golden fixtures are the cross-platform contract.

## Consequences

- Core domain code is written in Swift without Apple framework dependencies.
- The Apple adapter and tunnel lifecycle become first-class modules.
- Some domain logic may later be duplicated in Kotlin; duplication is acceptable until measured complexity justifies an FFI or shared-runtime decision.
- A simulator-only test is insufficient for tunnel acceptance.

## Non-goals

This ADR does not claim that iOS is easier, permanently the primary market, or the correct platform for every distribution model.
