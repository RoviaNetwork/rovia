# Threat model

## Scope

This document covers the Rovia host app, Packet Tunnel extension, canonical configuration, subscription importer, routing evaluator, engine adapters, local control messages, CI, and release artifacts. It does not claim to protect a device that is already fully compromised.

## Assets

- Subscription URLs, provider tokens, server credentials, private keys, and user-selected destinations.
- Routing policy and the selected server.
- Packet contents and connection metadata.
- Signing certificates, provisioning profiles, and CI tokens.
- Engine source revisions and native artifacts.
- Diagnostic exports and local control messages.

## Threat actors and abuse cases

| Threat | Example | Required control |
| --- | --- | --- |
| Malicious subscription | Oversized input, hostile URLs, parser edge cases | Size limits, strict parsing, fuzzing, no crashes, redaction |
| Hostile provider | Returns misleading or changing node data | Sanitized inspection, explicit refresh, content hashes, no automatic trust escalation |
| Compromised engine release | Modified binary or dependency | Exact source pin, checksum, provenance, independent review |
| Compromised dependency | Malicious package or CI action | Lockfiles, full-SHA action pins, least privilege, review |
| Malicious local app | Attempts to reach a local control API | No LAN listener, narrow provider messaging, authenticated transport where applicable |
| Accidental secret logging | Credentials in error text or diagnostics | Structured redaction before serialization, tests with canary secrets |
| Routing leak during reconnect | Traffic bypasses the intended policy or fails closed incorrectly | Explicit state machine, tests for transition and default behavior |
| Malformed configuration | Invalid CIDR, port, action, or schema version | Typed validation errors and no partial activation |
| CI signing compromise | Release certificate or profile theft | Protected environment, short-lived keychain, tag verification, manual approval |
| App Review mismatch | Undocumented behavior or prohibited code loading | Release notes, public API review, no post-install executable download |

## Security invariants

1. No packet payload is written to logs or diagnostics.
2. No canonical persisted model contains a credential value.
3. No engine executable is fetched or installed after app installation.
4. A production build cannot use a mutable or missing engine lock.
5. Routing traces contain only the built-in synthetic samples the content ships. The debugger has no text field and no typed input: a sample is chosen from a menu, so there is no user-supplied string a trace could carry.
6. The host app and extension share only non-secret configuration and status data through the minimum required App Group surface.
7. Release artifacts are traceable to a source commit, dependency lock, engine revision, and signing event.

## Verification strategy

Every control below is labelled with whether it exists. A control listed as planned
is not a mitigation this repository has, and none of them may be counted as one.
`docs/development/release-readiness.md` is the dated disclosure of which gates have
never been executed; the row numbers there are quoted so the two documents cannot
drift apart.

**In place and executed here**

- Unit tests for parser limits, normalization, redaction, and route evaluation.

**Planned, not implemented**

- Golden routing fixtures shared with Android. Android is not started, so there is
  no second platform to share them with. `release-readiness.md` row 9.
- Fuzz targets for share-link and subscription parsing. There is no fuzz target in
  the tree and no fuzzing step in any workflow. No row of `release-readiness.md`
  covers this one: that disclosure lists the gates that are open, and fuzzing is
  not among them, so citing a row here would be citing a gate that is about
  something else.
- CI secret scanning and workflow review. The workflow has now run, so there is
  something to scan, and nothing scans it. `release-readiness.md` row 7.
  `CODEOWNERS` lists the paths a review would cover, and the handles in it are
  placeholders, so no review is currently required on any path.
  `release-readiness.md` row 6.
- Dependency review and advisory monitoring. SBOM generation does exist and runs,
  but dependency review, advisory monitoring, and secret scanning are not
  configured. `release-readiness.md` row 7.
- Physical-device tunnel tests for lifecycle, IPv4, IPv6, and reconnect behaviour.
  Simulator install and launch are checked; a simulator process staying alive says
  nothing about a tunnel. `release-readiness.md` row 4.
- Independent reproducibility check for the engine artifact. No engine is built, so
  there is no artifact to reproduce, and the verifier refuses rather than claiming
  it. `release-readiness.md` row 5.

## Residual risks

- A malicious or compromised operating system can observe or alter traffic.
- A malicious provider can observe traffic it is selected to carry.
- A legal interpretation of GPL and platform terms may differ across jurisdictions.
- A pinned artifact can still contain an upstream vulnerability; pinning improves provenance, not correctness.
- Network-level blocking and availability failures cannot be fixed by client-side routing logic.
