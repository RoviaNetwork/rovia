# Product

<!-- impeccable:product-schema 1 -->

## Platform

ios

## Users

Inferred from the brief and repository (user unavailable; told the agent to
proceed autonomously): the primary user is the developer/owner and early
testers of Rovia — technically literate iPhone users who operate a VPN client
daily. The job: connect, trust the state on screen, pick a server, get on with
life.

## Product Purpose

Rovia is an iOS VPN client on a pinned, reproducibly built Xray engine
(`engines.lock.json`, byte-reproducible `LibXray.xcframework`). It exists to
give its user a tunnel whose reported state is always the truth: the app never
fabricates status, and a dead engine can never present as a working tunnel.
Success: the user opens the app, taps once, and believes what they see.

## Positioning

Honesty as the mechanism. Where other clients synthesize a friendly state, this
client's every status line traces to the extension's own report or the canonical
model — a claim a neighboring client cannot copy without rebuilding its engine
attestation the same way (pinned engine, schema-described status channel,
offline-fixture development that never touches the network).

## Operating Context

- iPhone first; runs on iOS 26 simulator class and physical devices (device
  proof on real hardware is a roadmap item — a simulator cannot run a Packet
  Tunnel).
- Dark and light appearances both ship; the user can pin one in Settings.
- Kill switch (on-demand + includeAllNetworks) is a first-class user setting.
- Development happens against an offline fixture environment; sample data is
  always labelled as such on screen.

## Capabilities and Constraints

- Sections: Overview (connect hero), Servers, Statistics, Routing, Routing
  Debugger, Subscription Inspector, Settings.
- Engine states: unknown / unavailable / idle / starting / connected /
  stopping / failed. The UI must never invent a state.
- Dynamic Type is a commitment (hero already scales via `@ScaledMetric`).
- Accessibility identifiers gate the UI tests (`AppAccessibilityIdentifier`);
  redesign must preserve every identifier the test suite audits.
- HIG conformance: system navigation, safe areas, platform controls, SF
  Symbols, Reduce Motion honored.

## Brand Commitments

- Name: Rovia. Existing logo view (`RoviaLogoView`) is the incumbent mark.
- Voice: factual, no hype, no gamification. Errors name the problem and the
  recovery.

## Evidence on Hand

- Offline fixtures under `fixtures/` drive sample content; labelled on screen.
- No marketing site, testimonials, or store assets exist; none may be
  fabricated.

## Product Principles

1. The state on screen is the state in the extension — never synthesize.
2. One thumb, one tap: the connect action dominates Overview.
3. Native first: HIG components and behaviors; custom work only where a VPN
   client genuinely needs it (the hero, live latency).
4. Both appearances are designed, not defaulted.
5. Sample data is always labelled; claims are never invented.

## Accessibility & Inclusion

Dynamic Type support, VoiceOver labels/hints on every control (gated by
`tools/ci/audit-accessibility-identifiers.py`), Reduce Motion honored.
