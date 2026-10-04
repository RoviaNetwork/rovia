# App Store distribution notes

This document is an engineering checklist, not legal advice.

## Relevant public constraints

Apple's App Review Guidelines state that apps may only use public APIs and that apps should be self-contained and may not download, install, or execute code that introduces or changes features. The current guidelines also contain VPN-specific requirements and data/privacy obligations. The release owner must recheck the current guideline text and the developer's distribution agreement before submission.

Relevant primary sources:

- https://developer.apple.com/app-store/review/guidelines/
- https://developer.apple.com/documentation/networkextension/nepackettunnelprovider
- https://developer.apple.com/documentation/networkextension/netunnelprovidersession/sendprovidermessage(_:responsehandler:)

## Rovia decisions

- The Packet Tunnel extension uses public NetworkExtension APIs.
- Engine versions are pinned, and a release ships only the version its lock names. The lock now pins xray v26.9.9, and the gated build pipeline produces the artifact with the recorded digest, but the adapter is not wired to it yet, so the app cannot establish a tunnel today. The App Review note for the wired state is recorded in `PRIVACY.md` and has to be kept in step with the lock.
- The app does not download an executable engine after installation.
- Host-to-extension communication uses a versioned provider message rather than a LAN HTTP server.
- The app group contains only the minimum shared data; credentials belong in Keychain.
- App Review notes explain VPN functionality, provider handling, privacy disclosures, and any region-specific licensing requirements.
- Export-compliance responses are completed before TestFlight and App Store submission.

## Pre-submission evidence

- App and extension App IDs match bundle identifiers and provisioning profiles.
- NetworkExtension entitlement is present only where required.
- App Group identifiers are registered and shared by the intended targets.
- The app has been tested on a physical device with a real VPN configuration.
- IPv4-only, IPv6-only, and dual-stack behavior are documented.
- Diagnostics and screenshots are sanitized.
- Third-party notices and source obligations are complete.
- A qualified reviewer has approved the distribution model for every bundled engine.

## Open legal question

If a future build includes GPL-covered sing-box code, the project must choose a compliant distribution model and obtain legal review. The existence of an official sing-box Apple client is not a license grant to Rovia.
