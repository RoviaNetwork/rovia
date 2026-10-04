# Changelog

All notable changes to this project are documented here.

The project is pre-alpha. Nothing below has been signed, archived, uploaded, or
run on a physical device, and no production engine is enabled. The verification
record for the current state is `docs/development/foundation-verification.md`.

## Unreleased

### Added

- `ProductionFetchTests.swift`: the production composition — real
  `SubscriptionFetcher.production()` through a real coordinator over a local
  loopback server — covering redirect-chain blocking, oversized bodies without a
  Content-Length, stalled bodies, production cancellation, document-line
  rejection numbers, first-import rollback of the subscription URL secret,
  mid-import save-failure rollback, and the v1→v2 server-ID remap.
- The subscription coordinator now reports `remappedServerIDs` on every import
  summary, and the app carries the selection and favorites across a server's
  v1→v2 ID rotation instead of silently dropping both.
- A lint gate over the repository's Python: `tools/ci/check-python-lint.sh` runs a
  pinned `pyflakes` and is invoked by `tools/ci/run-tool-tests.sh`.
- A check that no module or class under `tools/` defines the same name twice, for
  the binding shapes `pyflakes` does not report when a name is rebound.
- Canonical configuration, routing, and subscription domain packages, with
  bounded parsing, redacted outputs, and deterministic server selection.
- An engine API boundary with an Xray adapter that reports the engine
  unavailable while `engines.lock.json` enables no production engine, and a
  disabled sing-box boundary.
- Portable JSON contracts in `schemas/` for the canonical config, the
  subscription document, the host/extension control API, the control response
  envelope, and the engine lock, each validated against real Draft 2020-12
  validation plus semantic probes that fail when a load-bearing constraint is
  removed.
- A SwiftUI host app with five semantic screens, an observable app model with an
  immutable snapshot and typed actions, and a Packet Tunnel extension that
  validates provider messages and returns a typed engine-unavailable error
  before it constructs or applies network settings.
- A gate on the app's dependency on the canonical domain packages:
  `tools/ci/test_app_dependencies.py` fails if the Xcode project stops linking
  `core/config` or `core/routing`, if either the app or the test target stops
  declaring the product dependencies, or if a second route evaluator reappears in
  the app sources.
- CI tooling that fails closed: two-mode engine verification
  (`foundation` and `release`), lockfile and external-dependency verification,
  a release-input gate that checks, in this order, the signing identity, the
  signing secrets, the tag grammar, the existence of the four input files, the
  engine lock, the artifact, the checksums, the SBOM, and the provenance
  manifest, plus a shell-syntax gate, a processed-bundle metadata gate, and a
  simulator install-and-launch gate. The engine lock is checked before the
  artifact is opened, not last.
- An SPDX 2.3 SBOM naming the shipped product, with an independent checker, a
  per-document namespace, and a versioned tool creator.
- A provenance manifest recording the artifact, SBOM, engine lock, resolved
  package locks, runner identity, tag, version, and commit.
- `PRIVACY.md` with a data inventory, the three data flows, retention and
  deletion, the known limits of redaction, and the App Store privacy answers;
  `SECURITY.md` with a fail-closed release policy; and `CODEOWNERS` covering
  every security-sensitive path.
- GitHub Actions workflows for pull requests, engine reproducibility, and a
  signed iOS release that stops at a verified artifact.

### Changed

- `docs/architecture/next-spikes.md` now leads with the two release gates — the
  pinned Xray packet-flow bridge and the signed Apple lifecycle on a physical
  device — instead of treating them as later refinements.
- Engine verification, lockfile verification, and tag validation are separate
  gates with three-way exit contracts rather than notices that cannot fail.
- The lockfile verifier classifies every SwiftPM dependency form, reads
  commented-out declarations as comments, and refuses an external dependency
  without an exact-revision `Package.resolved`.

### Fixed

- The production-composition fetch shim recursed forever: `SubscriptionFetchClient.fetch(_:policy:)`
  called `fetch(url, policy:)` inside its own conformance, binding to itself rather
  than to `SubscriptionFetcher.fetch(_:policy override:)` — every production fetch
  hung, and the app tests that exercised it stalled until the runner aborted. The
  protocol requirement now uses a distinct label (`fetchPolicy:`), which compiles
  to the real method.
- A cancelled or failed first import leaked the subscription URL secret into the
  Keychain: it was saved before `importAndStore`, and the transaction only rolled
  back server secrets. The URL key is now part of the same transaction, so every
  failure path — cancellation at any checkpoint, mid-import save failure, store
  failure — deletes it too, while `rollbackSecrets` keeps sparing keys still
  referenced by stored records.
- A credential-sink failure aborted no import: `SubscriptionImporter` maps it to a
  per-line rejection, so the discard of secret storage stayed atomic only on
  paper. The coordinator captures the first sink failure and aborts the import
  with it.
- A failed first import that produced zero accepted servers stored an empty
  record whose display state never restamped `updatedAt` or the schema version;
  the rebuild now sets both, matching every other store write.
- App-model hardening: a cancelled connect/disconnect no longer banners a
  failure or corrupts the engine state; a failed bootstrap drops a stale
  engine state; the persisted selection is re-validated against the
  profile and group it belongs to; subscription resyncs recompute the content
  state and no longer erase unrelated error banners; a cancelled stale
  refresh keeps the progress it already made instead of dropping it; the TCP
  probe honors cancellation; the favorite toggle no longer sits inside the
  row button, so favoriting a server can no longer also select it; and the
  import preview keeps a failed add's link instead of throwing it away.
- **Publication pass — the tree as an open-source repository.**
- The engine link is coherent with the app again: `rovia-engine` v0.2.1 (the
  first release that pins `rovia-core` 0.2.3, published to unblock the two
  pins meeting) rather than v0.2.0, which pulled `rovia-core` 0.2.1 from
  under the app and left the manifest unresolvable. The SBOM regenerated on
  that link, and the recorded figure — 5 components, 5 relationships —
  derives from it the same way the rest of the record's rows do. `CODEOWNERS` names a
  real owner instead of an organisation that does not exist, and `SECURITY.md` states
  the consequence: with one maintainer, a required review would be a self-review, so
  nothing is required yet. `docs/superpowers/` is gitignored rather than published with
  72 unticked checkboxes for finished work. `SECURITY.md` points security reports at
  GitHub private vulnerability reporting. The README's test counts are generated by
  `tools/ci/update-readme-counts.py` and held against their loaders, so they cannot
  drift silently. `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `GOVERNANCE.md` are
  rewritten for a public audience, including the single-maintainer limitation stated
  directly.
- **Added** `tools/ci/check-repository-hygiene.sh`, which refuses a tree that would
  publish a credential shape, a developer's home directory, or a build artefact. It
  runs from the tool runner and from CI, and it checks what git would publish rather
  than what sits in the working tree — the first version failed on 21 correctly ignored
  `.DS_Store` files, which is how a gate gets deleted.
- **Added** `.github/ISSUE_TEMPLATE/bug_report.yml`,
  `.github/ISSUE_TEMPLATE/feature_request.yml`,
  `.github/ISSUE_TEMPLATE/config.yml`, `.github/PULL_REQUEST_TEMPLATE.md`,
  `.github/dependabot.yml`, and `.github/FUNDING.yml`.
a public audience, including the single-maintainer limitation stated directly.

- The document check that states how many tests hold the Python lint gate counted
  them by searching test names for `"lint"`, so a gate test named without that
  marker was uncounted while every document still passed. The count now comes from
  the gate's own class, and every count occurrence in the documents is checked
  rather than the first one matched.
- A working-directory dependency that made the CI plumbing suite fail when run from
  `tools/ci` instead of the repository root, now covered by a test that runs the
  suite from an unrelated directory.
- Working-directory dependencies that made the CI plumbing suite fail when run
  from outside the repository, now pinned, and covered by a test that runs every
  test in the module from an unrelated directory and checks the run's own count.
- A derivation of the app's XCTest count from the test target's own methods rather
  than a transcription of an `xcodebuild test` run.
- The accessibility audit's `--app` default resolved from the script's own location,
  so it runs from any working directory, covered by a test that runs it from outside
  the repository.
- Changelog-shape tests: the changelog's section structure, a check that it carries
  an entry for every dated pass section in the record, and the reverse direction —
  the pass sections are pinned, so deleting one fails rather than removing its own
  requirement, and an entry with no pass behind it fails too.
- Runtime-pattern anchoring made explicit: every alternative in the gate-runtime
  consistency pattern is classified as either a catch-all phrase or subject-anchored,
  each proved against the pattern itself, and the false positives the catch-all
  phrases really carry are asserted as a test rather than left as a worry, and the
  coverage of the pattern is no longer claimed to be wider than it is.
- Every alternative in that pattern is now probed with a sentence naming the gate
  and a sentence naming something else, rather than one half of the corpus living
  in a different test from the other half.
- A guard against dead module-level constants under `tools/`, which `pyflakes` does
  not report, reading a constant as used wherever it is loaded in the tree.
- The accessibility identifier audit now enforces three rules its own docstring
  claimed and the code did not: a constant declared more than once is reported with
  both values, the container-treatment check requires the treatment that applies
  `.contain` rather than the bare word `accessibilityElement` that `.combine` also
  contains, and the container-component check finds components that wrap
  caller-supplied content instead of one hard-coded name — with the real line of each
  declaration reported, and covering components declared `public`, `final` or as a
  class, with a closure-typed or `some View` content property, and taking
  `accessibilityIdentifier`, `containerIdentifier` or `LocalizedStringKey`.
- That container-component check now reads every source file in the app target rather
  than `RootView.swift` alone — it had been examining 12 of 56 declarations — and the
  audit prints its per-file coverage on every run so a narrowing is visible.
- That scan reads component bodies with string literals in mind, so a brace in a
  string no longer moves where a type ends; reads sources recursively, as Xcode
  compiles a source listed under a group; and reaches a declaration preceded by
  attributes — including attributes with a nested argument list, and on their own
  lines — and `indirect`.
  That scope is now checked rather than asserted: every limit the audit's docstring
  lists must be named after a test, the six conditions a component is checked against
  must be six bullets with no prose between them — a continuation being an indented
  line that continues a sentence the previous line left open — and the qualifier set
  the anchor accepts is verified against the docstring and against the comment above
  the anchor, which has to give the reason and not only name the token.
  That rule is defined once and both directions call it, with a test that weakens the
  shared definition and requires both to fail, so the two cannot drift apart again.
- The verification record's pass sections are found structurally — by the dated-summary
  marker or the `Nth remediation pass` shape — rather than by filtering headings for
  the word "remediation", and the list of them is pinned in both directions, so a pass
  cannot be appended without a summary of its own. The narrative shape matches the ordinal itself,
  hyphenated forms included, so a pass inserted in the middle of the record is caught
  by the pinned list rather than slipping past a pattern that could not spell it.
- The Python warnings gate given the same standing as the lint gate: its wiring, its
  empty-tree refusal and its documentation are each held by a test, and CI is required
  to reach it through the runner.
- The warnings gate's empty-tree refusal made explicit. It previously relied on `set -u`
  aborting, which on the macOS default bash 3.2 exits 0 when an EXIT trap runs, so an
  empty tree was reported as a pass; the count is a scalar now and the interpreter step
  refuses an empty list independently of the shell guard.
- The tool-test totals, the runner's own description in `ci.md`, the `ci.yml` gate list
  and the `bash -n` script count are all derived rather than transcribed, so none of
  them can state a figure the tree does not hold.
- A warnings gate, `tools/ci/check-python-warnings.sh`, over the Python under
  `tools/`: every module must compile with
  `-W error::SyntaxWarning`, so an invalid escape sequence in a docstring fails the
  suite instead of printing a warning — it is scheduled to become an import error, which
  would stop a module's tests running at all rather than failing them.
- Suite test counts are now held in every place they appear across the development
  documents, not only where a table row happened to state one: a second occurrence of
  any count is a second claim.
- The count-completeness finding that the record's own completeness claim was
  ungated, and the lint-gate count check that a test now derives from the gate
  class rather than from a search over test names.
- A runtime-consistency check that required one specific phrase and so did not
  notice a stale 28-34 second range wherever the phrase it required was
  absent, while the documents that carried the phrase agreed on 28-52; every
  gate runtime span in those documents is now compared, with the pattern
  anchored on the gate's own sentences rather than on any `N-M seconds`.
- The iOS routing debugger no longer carries its own route evaluation. The app
  links the local `RoviaConfig` and `RoviaRouting` packages, converts its display
  models to the canonical route model, and renders the canonical
  `RoutingDiagnostic`; the duplicate matcher comparison, host normalization, and
  IPv4 CIDR containment are gone, the sample group and rule identifiers are
  canonical UUIDs, and a routing explanation that cannot be produced surfaces a
  sanitized error instead of a second answer.
- `schemas/control-response.schema.json` now describes what the Packet Tunnel
  extension returns: a closed envelope where a result and an error cannot appear
  together and the error codes are a closed set, with positive and negative
  fixtures and probes.
- A secret reference key is constrained everywhere it is read: printable ASCII
  without spaces, at most 512 characters, enforced by the loader, the validator,
  the raw-JSON walk, the JSON Schema, and the one `RoviaConfig` function the
  subscription parser now calls.
- `RoviaConfig.RoutingDecisionTrace` and `RuleEvaluation` are no longer
  `Codable`. The raw trace holds the hostname, address, and port that were
  evaluated, so it is an in-memory explanation; the redacted
  `RoutingDiagnostic` is the serializable form.
- `PRIVACY.md` no longer claims an App Group or Keychain write, a `packetFlow`
  bridge, or a bundled engine. It describes what the code does: nothing is
  written to disk in this slice, the extension never reads or writes
  `packetFlow`, and no engine is enabled or bundled.
- The control request and response contracts are symmetric. `requestID` is
  bounded at 128 characters on both sides, the Packet Tunnel extension refuses a
  request whose envelope carries a field the schema does not declare, and it
  refuses a `status.get` that carries a payload. The bounds live in one place in
  the provider and a test requires the provider and both schemas to agree.
- The app-dependency gate reads rules instead of names: it parses the Xcode
  project per object, decides from extracted declarations and bodies rather than a
  list of identifiers, and covers a raw trace reaching storage or a log through a
  wrapper, a stored property, a collection, a typealias, an encoder, `print`,
  `os_log`, `Logger`, or a provider message. Every rule is proven by a mutation
  that must fail, and the mutations do their surgery on the project by product
  name rather than by object identifier.
- `PRIVACY.md` no longer describes a typed destination. The debugger has no text
  field; it evaluates the content's built-in synthetic samples, and the document,
  the Swift comments, and the other eight documents that describe it say so.
- The release path now fails closed on the signing identity. The committed
  `ExportOptions.plist` holds `$(ROVIA_TEAM_ID)`, an unresolved reference, and no
  team was invented to replace it; `tools/release/verify-export-options.sh` refuses
  anything that is not a literal team ID, and it runs as the release gate's first
  action, before the secret check, so the gate can no longer report that signing
  inputs are present while the signing identity is unresolved. The release workflow
  carries the same check ahead of the keychain, the certificate, the profiles, the
  archive, and the export. Signing, provisioning, archive, export, and upload
  remain a manual gate that has not been executed.
- Engine licenses are derived rather than defaulted. `licenseDeclared` was MIT for
  every component, so a GPL-3.0-or-later engine would have been published as MIT.
  Each engine candidate in the lock now declares the license of the code it builds,
  the lock schema requires it, and the SBOM generator checks it against the upstream
  project the lock names — libXray is MIT, Xray-core is MPL-2.0, sing-box is
  GPL-3.0-or-later — and refuses a lock whose license is missing, unverifiable, or
  inconsistent with its source.
- The ownership lists are bidirectional and existence-checked. `core/config/`, which
  holds `SecretReference` and the raw routing trace, was in neither `CODEOWNERS` nor
  `SECURITY.md`; `core/persistence/` was in both and does not exist. Both are fixed,
  `SECURITY.md` states the criterion for the list, and the test now requires that
  every sensitive path is owned, that every security-handled path is sensitive, and
  that every path either file names exists. The handles are still placeholders, and
  both documents now say the review identity behind every one of them is unresolved,
  so no review is required on any path today.
- The gates that have not been executed are now disclosed in the repository, in
  `docs/development/release-readiness.md`, rather than only in a planning ledger
  outside it. All ten are listed with why each is open and what would close it, and
  a test derives the list from the repository so it cannot drift.
- An IPv4-mapped IPv6 address is accepted and normalised instead of refused. A
  destination written `::ffff:1.2.3.4` — a form a dual-stack socket hands out
  routinely — made route evaluation throw, because the parser returned nil and the
  evaluator treats that as an invalid address. It now resolves to the IPv4 address
  it maps, so the rules that describe it match. The one consequence, that an IPv6
  rule such as `::/0` does not match a mapped address, is recorded where the
  packetFlow spike will meet it.
- A degenerate domain is refused rather than normalised to a value. `normalizeDomain`
  turned `".."` into `"."` and `"..."` into `".."`, and route evaluation compared the
  two sides of a domain match as optionals — so a rule naming nothing matched a host
  naming nothing. Normalisation returns nothing for an empty label, which makes such
  a rule a configuration error, and the comparison no longer treats two absent values
  as equal.
- Both redacted-URL implementations keep the port. The config model dropped it and
  the subscription parser kept it, so the value shown to a user and written to a
  diagnostic depended on which code had produced it. The port is not the secret:
  redaction removes the credential. A URL carrying credentials is still refused
  outright by the config path, which reads a file an operator edited by hand.
- A subscription source's display value is now the same set of values in the schema
  and in the model. The model rewrote a pasted-text or file source to one of three
  literals and discarded whatever the file said, while the schema accepted any
  string, so a configuration could carry a value that was silently replaced.
- A generated SBOM is byte-reproducible when **both** of its run-dependent fields
  are fixed. `creationInfo.created` was a wall-clock reading, so two runs differed
  however fixed the namespace was, and the test that appeared to check this
  overwrote that field before comparing. The timestamp is now settable, and the
  generator says so when it is not set.

The app-dependency gate is a source-level check, and its limits are part of its
record rather than a footnote: it reads declarations and bodies, not Swift, so an
operator overload and a code-generated body are outside it; a body that avoids
every signal is invisible to it; a stored `RuleEvaluation` is deliberately
allowed because the canonical evaluator builds a local one; and it reads the
repository rather than the build, so a link it does not model fails closed. The
full list is in `tools/ci/test_app_dependencies.py` under "What this gate does
not claim".

### Known limitations

- No production engine is enabled, so the app cannot establish a tunnel.
- Signing, provisioning, archive, export, and publishing have never been
  executed; the release gate's happy path is exercised only against a synthetic
  artifact.
- No GitHub Actions run has occurred, so runner-specific behaviour is unverified.
- Physical-device VPN behaviour, the Packet Tunnel Provider lifecycle, and the
  host side of the control API are unimplemented or unverified.
- The app still renders compiled-in sample content rather than a configuration
  read through `RoviaConfig`, so the canonical bridge converts display data
  rather than real configuration. `docs/architecture/next-spikes.md` item 3 is
  that work.
- `routing.explain` still answers `not-implemented`; the response contract
  describes the shape a working implementation must return, not one it does.
- The debugger has no typed destination. A destination the user supplies would be
  the first value in the app that redaction could not remove, which is why it is
  a spike decision rather than a UI addition.
