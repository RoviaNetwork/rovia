# ADR-0005: One Go runtime per process

- Status: Accepted
- Date: 2026-09-24
- Owners: Rovia maintainers

## Context

Xray/libXray and sing-box are Go-based. The current libXray README warns that independently built Go/cgo/gomobile runtimes must not be loaded into one process and recommends one combined build when packages from multiple libraries are required.

## Decision

The production Packet Tunnel extension may contain one production Go runtime. Xray is the only production engine in the initial release. Sing-box remains disabled. Independently built LibXray and Libbox artifacts must never be linked into the same extension process as a shortcut.

If a future design needs both engines, it must use one reviewed combined build or a separately justified process boundary. The process boundary must be proven viable on iOS; a desktop sidecar assumption is not sufficient.

## Consequences

- The engine lock must include the Go toolchain and exact source revisions.
- A future sing-box adapter may require a different app/build variant rather than a runtime flag.
- Engine adapters cannot be tested only as abstract interfaces; process-level startup and shutdown must be tested on a device.

## Verification

The release pipeline records the exact Go version, source commits, build flags, artifact hashes, and linked libraries. A mismatched or floating engine input fails the build.
