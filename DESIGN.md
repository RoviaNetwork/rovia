# Design

<!-- The durable record of the Scope visual world. Token truth lives in
     `client/app/ios/RoviaApp/ScopeTheme.swift`; this file explains the world,
     not the values. -->

## The world

Rovia is read as a **sonar range-scope**. A VPN client's whole job is trust:
the state on screen must be the state in the extension. A scope is an
instrument whose every mark is a measurement — so the metaphor is the product
claim. The category default (a map with pins, a glowing power button) is
refused: geography decorates, an instrument attests.

- **The face**: etched range rings, 45° major and 15° minor ticks, a dashed
  crosshair. Drawn, never photographed.
- **The sweep**: a low-alpha cyan sector that rotates only while the engine is
  starting or running. Idle shows a still face — no sweep without an engine.
  Reduce Motion holds it as a static lit sector.
- **Contacts**: the fleet's fastest servers, placed by measurement — latency
  is range, index is bearing. The selected server is the locked contact: the
  one element allowed to burn at full phosphor.
- **The center control** is the connect action. Phosphor while it can be
  pressed, quiet when it cannot; a short spring press, no bounce.

## Palette

Dynamic-provider colors (no asset catalog — see `RoviaLogoView`'s note), both
appearances designed:

| Role | Dark | Light |
| --- | --- | --- |
| ground | `#060D0B` deep ink | `#F2F6F3` instrument paper |
| housing | `#0B1714` | `#FFFFFF` |
| etched | `#1E3A32` | `#B9CFC6` |
| phosphor (accent) | `#3DF0A8` | `#0B9E77` |
| sweep | `#5EEAD4`, low alpha | `#0B9E77`, low alpha |
| ink | `#E6F4EE` | `#0C1A16` |
| ink secondary | `#8FB8AC` | `#41635A` |
| warn (transition) | `#FFB454` | `#B26A00` |
| alarm (failure) | `#FF6B6B` | `#C43D3D` |

Rules: phosphor appears only on the actionable or the locked contact. Amber is
transition, red is failure — never decoration. Secondary text is tinted from
the phosphor family, never plain gray.

## Type

SF system stack everywhere; `SF Mono` tabular figures only for real
measurements (latency ms, drop counters, error codes) so reranks never shift
the line. Dynamic Type throughout; the scope itself scales via
`@ScaledMetric(relativeTo: .largeTitle)`.

## Motion

One authored moment: the sweep. Everything else is quiet — state changes
crossfade (`ScopeTheme.stateChange`), presses use one spring
(`ScopeTheme.press`), server rows rerank in place rather than reappearing.
`accessibilityReduceMotion` removes rotation entirely.

## Structure

Tab bar with four destinations: **Overview** (the scope), **Servers**,
**Statistics**, **Settings**. Developer instruments (Routing, Routing
Debugger, Subscriptions) live under Settings → Tools. Panels (`SectionCard`)
are instrument housings: `housing` fill, 1 pt `etched` edge, 16 pt radius;
nesting panels inside panels is a defect.

## Voice

Factual, no hype. Errors name the problem and carry the machine code in
tabular figures. Sample data is always labelled.
