# Next engineering spikes

Ordered by what blocks a release, not by what is interesting. The first two
spikes are release gates: nothing ships until both are green, and neither can be
closed on a simulator. Everything after them is work that makes the product
better without changing whether it can ship.

Current evidence for each claim is in
[`docs/development/foundation-verification.md`](../development/foundation-verification.md).
Do not read a green local gate as progress on items 1 and 2: the local gates
prove the repository is consistent, not that a tunnel carries a packet.

## 1. Pinned Xray packet-flow bridge

Prove that one pinned libXray artifact can take packets out of
`NEPacketTunnelFlow` and put packets back through the same public API.

This is first because it is the only spike that decides whether Rovia can be a
VPN at all. Today the extension checks engine availability before it constructs
or applies network settings and returns a typed engine-unavailable error,
because `engines.lock.json` enables no production engine.

Entry conditions, all of them required before the spike starts:

- one exact libXray release selected, with its source commit recorded in
  `engines.lock.json` as `approved` and `enabled`, and listed in
  `productionEngines` — the current lock satisfies none of this;
- an Apple XCFramework built by `tools/build-engine/xray/build-apple.sh`, which
  today refuses with `No approved Xray lock entry is available; refusing to
  build a floating engine`;
- an artifact whose bytes match the digest in the lock, so
  `tools/ci/verify-engine-checksums.sh --mode release` accepts the lock. That
  mode currently refuses the real lock;
- the license obligations of libXray written down next to the ADR, as
  `docs/adr/0004-engine-licensing.md` requires.

What the spike must demonstrate, on a physical device:

- read from `packetFlow`, decode, and hand a packet to the engine;
- write an engine-produced packet back through `packetFlow`;
- cancellation: a tunnel stop while traffic is in flight leaves no orphaned
  read or write loop;
- backpressure: a slow consumer does not grow an unbounded queue;
- IPv4, IPv6, and dual-stack tunnelling, including DNS;
- reconnect after the tunnel is stopped and restarted, and after the device
  changes network.

What it must not do: read or log packet payloads. `PRIVACY.md` states that
constraint, and the spike output must not become a diagnostic channel for them.
`RoviaConfig.RoutingDecisionTrace`, the one type in this repository that holds a
raw hostname, address, and port, is deliberately not `Codable` and nothing
persists it; the packet bridge must not reintroduce that shape.

Exit condition: `tools/reproducibility/verify-xray.sh` compares two independent
builds of the pinned commit and passes, instead of refusing as it does now.

## 2. Signed Apple lifecycle on a physical device

Prove the lifecycle Apple actually requires, on hardware, with a signed build.

This is second because it is the other half of "is this shippable", and it is
the one that has never been executed at all.

Entry conditions:

- a distribution certificate, the two provisioning profiles, and the
  `io.rovia.client` and `io.rovia.client.tunnel` App IDs and App Group
  registered. `docs/legal/app-store-distribution.md` lists what is still
  unconfigured;
- the five signing secrets stored in the protected `ios-production`
  environment, and an Apple Developer team. `tools/ci/verify-release-inputs.sh`
  refuses at step 0, before it looks at a secret at all, because
  `tools/release/ExportOptions.plist` still holds the unresolved
  `$(ROVIA_TEAM_ID)`; the secret check is only reachable once a literal team ID is
  written down, so "the five are absent" is not what this gate stops on today;
- ~~one commit, because `tools/reproducibility/manifest.sh` records `gitCommit:
  null` in a repository with no commits and the release gate refuses a null
  commit.~~ **Closed by the publication pass:** the repository now has a
  commit, so `manifest.sh` records a real SHA. The gate's refusal of a null
  commit is unchanged and is still tested — `test_manifest_leaves_the_commit_null_without_a_repository`
  covers the case that motivated it.

What the spike must demonstrate, on a physical device:

- the host app installs and updates a VPN configuration, and starts and stops
  the extension through `NETunnelProviderManager`;
- the Packet Tunnel Provider starts, applies settings, and tears down without
  leaking the provider process;
- versioned provider messages travel host to extension and back. Today only the
  provider side exists: `PacketTunnelProvider.handleAppMessage` validates the
  envelope, refuses anything above 64 KiB, answers `status.get`, and returns
  `not-implemented` otherwise. The host side is not wired, and a spike that
  claims both ends work would be wrong;
- recovery from extension termination without exposing credentials;
- a signed archive through `xcodebuild archive` and `-exportArchive`, exported
  with `tools/release/ExportOptions.plist`, passing the full
  `tools/ci/verify-release-inputs.sh` gate rather than the synthetic-IPA path
  its tests use;
- the App Store privacy answers in `PRIVACY.md` re-verified against what the
  build actually does.

Exit condition: one signed artifact that passes every gate, on a device, with
the tunnel from spike 1 carrying traffic.

## 3. Wire the app to real configuration instead of sample data

The app's routing debugger now evaluates with `RoviaRouting.RouteEvaluator` and
renders the canonical `RoutingDiagnostic`, through
`client/app/ios/RoviaApp/CanonicalRouteBridge.swift`. What it does not do is
read a real canonical configuration: `AppContent.sample` is compiled-in display
data, and the bridge converts that. The spike is to load an
`AppConfig` through `RoviaConfig`, map it into the display models, and keep the
one evaluator. Two things have to be settled first, and both are privacy
decisions rather than engineering:

- where the configuration lives. `PRIVACY.md` now says nothing is written to
  disk, so the first durable store is a change to that document;
- the sample group and rule identifiers became canonical UUIDs so the bridge
  never has to invent one. Real identifiers are real UUIDs, and the sample
  should not be the thing that teaches a different shape; and
- a decision about what a typed destination means. Today the debugger has no text
  field: it evaluates the content's built-in synthetic samples, so nothing the
  user supplies reaches it and there is nothing to redact. Adding a typed
  destination is a privacy change, not a feature, and `PRIVACY.md` says so in the
  place where the redaction limits are listed.

## 4. Subscription parser hardening

Add bounded readers, format-specific parsers, synthetic fixtures, fuzzing, and
redaction tests before URL refresh is ever enabled in a release build. The
parser is already bounded and redacting, and it now takes its secret-reference
key rule from `RoviaConfig` rather than keeping its own; this spike is about the
inputs nobody has tried yet, and about the redaction limits `PRIVACY.md` names.

## 5. Runtime identity and diagnostics

Make the runtime identifier of each process and engine visible to the operator
without concatenating it into a static accessibility constant, so the
identifier audit can stay a static check. This is the item deferred from the
Task 5 review: today a concatenated identifier is invisible to
`tools/ci/audit-accessibility-identifiers.py`, and the report should not imply
otherwise.

## 6. Android contract validation

Implement the canonical schemas and routing fixtures in Kotlin and compare
results against the Swift corpus before considering Rust or Kotlin Multiplatform.
The schemas in `schemas/` are portable precisely so this comparison is possible
later; nothing about it should pull the iOS work forward.

## Recorded decisions

Decisions taken during the client review that a later change should not silently
reverse. Each states what was decided, why, and what would have to change to
reverse it.

### An IPv4-mapped IPv6 address is accepted and normalised to IPv4

`::ffff:1.2.3.4` is a routine form — a dual-stack socket hands one out — and
`CanonicalRouteMatcherValidator.parseIPAddress` returned nil for it, so
`RouteEvaluator` threw `invalidIPAddress` for a destination that was perfectly
routable. The policy is **accept-and-normalise**, not refuse: the mapped form and
the plain form denote the same address, so the mapped form parses to four bytes
and `normalizeIPAddress` returns the dotted quad. IPv4 rules therefore match it.

The consequence, which the packetFlow spike will meet: a mapped address is four
bytes, so an IPv6 rule such as `::/0` does **not** match it. That is the safe
direction — the rules that describe the address match, and a rule meaning "all
IPv6" does not silently capture an IPv4 address. If a deployment needs
`::/0` to capture mapped traffic, the fix is to compare 16-byte networks against
the mapped expansion, not to relax the length guard.

Reversing this to refuse-with-a-reason would reintroduce a throw on a form the
platform produces. The behaviour is pinned in
`core/config/Tests/RoviaConfigTests/ConfigValidationTests.swift`, including the
`::/0` consequence above.

### A degenerate domain normalises to nothing, and is refused as a matcher

`normalizeDomain("..")` returned `"."`, and `"..."` returned `".."` — non-empty
strings describing no host. `RouteEvaluator` normalised both sides of a domain
comparison and compared them as `Optional`, where `nil == nil` is true, so a
degenerate matcher matched a degenerate host. Now `normalizeDomain` returns nil
for any name with an empty label, which makes such a matcher fail validation with
`invalidMatcher` before it can be compared, and the evaluator's comparison checks
that both sides are present rather than comparing two `Optional`s.

### One redacted URL form, and it keeps the port

`RoviaConfig.SubscriptionSource` and `RoviaSubscription.SubscriptionRedactor` both
redact a URL, and they disagreed: the first dropped the port, the second kept it.
The schema pattern, `tools/ci/validate-schemas.py`, the share-link fixtures, and
`PRIVACY.md` all kept it, so the config path was the outlier and the persisted
value depended on which code had produced it. The port is not the secret —
redaction removes the credential — so both keep it now, and
`core/subscription/Tests/RoviaSubscriptionTests/SubscriptionModelsTests.swift`
compares the two directly.

One difference is deliberate and not reconciled. A value carrying userinfo
(`https://user:password@host/…`) is refused outright by the config path and
replaced with the literal `redacted`, so neither the host nor anything from the
credentials survives; the subscription path keeps the host for such a value. The
config path reads a file an operator edited by hand, where credentials in a URL
are a plausible mistake, so it is the stricter of the two. A future change that
unifies them should make both stricter, not both laxer.

### `isSecretBearingKey` matches substrings on purpose

`TransportOptions.isSecretBearingKey` lowercases a key, strips everything that is
not a letter or a digit, and refuses the transport if the result contains any of
sixteen fragments — `password`, `token`, `secret`, `uuid`, `auth`, and the rest.
It is a **substring blocklist**, so it has false positives: `tokenizer`,
`authority`, and `passport` all contain a fragment and would be refused.

That is deliberate and is not to be tightened into a word list. The consequence of
a false positive is a transport configuration refused with a clear reason. The
consequence of a false negative is a credential in a query parameter reaching an
engine. The check runs on a key an operator wrote, not on a value, so a false
positive costs a rename and a false negative costs a secret. Any change that
narrows this list has to argue the other side of that trade explicitly.
