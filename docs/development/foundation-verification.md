# Foundation verification

Date: 2026-09-26
Repository state: the first public commit of `main`; the figures below describe that commit
Scope: the local CI equivalents in `docs/development/ci.md`, run on one machine

### Which counts are exempt from derivation

Ten live counts in this record were accurate and ungated: the JSON file and
schema and fixture counts, the accessibility identifier counts, the SBOM component
and relationship counts, the three workflows' job and step counts, the shell script
count, the local package manifest count, the tracked entry count, the signing
gate's step position, the unexecuted gate count, and the semantic probe count. Each
is now read from its real source by `LiveCountDerivationTests` — the schemas and
fixtures from the tree, the accessibility counts from the audit's own output, the
SBOM counts from a generated document, the workflow counts from the workflows, the
shell and manifest counts from the files, the tracked count from `git ls-files`, the
signing position from the step list, the gate count from the readiness rows, and
the probe count from the validator's probe functions.

Two groups cannot be derived and are exempt:

1. **The before/after tables in each pass section.** Their "before" values describe
   a tree that has since moved, so no derivation can recover them. A test requires
   each such table to sit under a pass heading so its numbers are read as history.
2. **The instrumented copy count.** It is 69, and it is measured by instrumenting
   the suite's `Workspace` construction. Measuring it costs the 20-90 seconds the
   suite already spends, so a test enforces a derived bracket instead of the
   figure.

A third group is not exempt. A count that cannot be derived belongs in one of these
two, named, with its reason. The app test count is the case that was almost a
third: the record carried `Executed 60 tests, with 0 failures` as a transcript of
an `xcodebuild test` run, and a test required that literal, so the only way to
change it was to run the suite and edit the document. It is derived now, by
counting the `func test…` methods in `RoviaAppTests` the same way the SwiftPM rows
are counted, which gives the same 60 from the sources.

**Which numbers in this record are derived, and which are not.** Every count above
is read from the thing it describes rather than written from a run: the suite
totals and the per-package SwiftPM rows come from the unittest loader and from the
suites' own test lists, the app test count from the XCTest target's own `func
test…` methods, the mutation and shape counts from the gate module's
tables, the refusal rows from the gates themselves, the probe and license-test
counts from the validator and the test loader, the sensitive path count from
`SECURITY.md`, the tool versions from the tools themselves, and the gate runtime
from the run recorded here. The before/after tables inside each pass section are
the exception: they are single observations from the run that pass recorded, their
"before" values describe a tree that has since moved, and nothing can derive them.
They are kept as history and a test requires each one to sit under a pass heading
so its numbers are read as what they are.

This record is evidence about this repository on one machine. It is not
evidence about a tunnel, a physical device, a signed artifact, a production
engine, or a hosted CI run. The gates that were not executed are listed at the
end, unchanged by anything below.

## Environment, exactly as reported

**This table is an observation of one machine, not a requirement.** It records the
toolchain the local evidence in this document was produced on, so a reader can judge
what the evidence covers. It is not a list of what the project needs, and a different
toolchain does not invalidate anything here: the hosted CI runs on a different Xcode
and a different Swift on every push, and the project's own floor is
`swift-tools-version: 6.0` with a 17.0 deployment target. The rows that *are*
requirements are the pinned ones — `check-jsonschema`, `pyflakes`, and every
`actions/*` commit SHA — and those are checked against what actually runs rather than
against this table.

| Thing | Value |
| --- | --- |
| Host | `Darwin iMac-princeofscale.local 24.6.0 Darwin Kernel Version 24.6.0` (x86_64) |
| macOS | 15.7.7 (24G720) |
| Xcode | 26.3, build 17C529 |
| Swift | 6.2.4 (swiftlang-6.2.4.1.4 clang-1700.6.4.2), swift-driver 1.127.15, target `x86_64-apple-macosx15.0` |
| Python | 3.14.7 |
| `uv` / `uvx` | 0.11.8 (0e961dd9a 2026-04-27 x86_64-apple-darwin), the output of `uv --version` |
| Schema validator | `check-jsonschema` 0.38.2, through `uvx` |
| YAML parser | `pyyaml` 6.0.2, through `uvx` |
| Python linter | `pyflakes` 3.2.0, through `uvx`, pinned as `pyflakes==3.2.0` |
| Simulator | iPhone 17 Pro, iOS 26.3 (26.3.1, 23D8133), `1AA6273F-720C-4A40-8526-45A871C771B6` |
| Derived data | a per-run directory under `$TMPDIR`, outside the checkout and outside any path this repository tracks |

The host is an x86_64 Mac running an x86_64 toolchain. Nothing here was run on
Apple silicon or on a hosted runner.

## Gates, and what each one returned

### Repository inputs

| Command | Result |
| --- | --- |
| `./tools/ci/check-shell-syntax.sh` | `18 shell scripts parse` |
| `./tools/ci/verify-lockfiles.sh` | `1 local package manifests verified, 0 with locked external dependencies, 0 local path dependencies` |
| `./tools/ci/verify-third-party-notices.sh` | accepted, no output |
| `./tools/release/verify-tag.sh v0.1.0` | `v0.1.0 is a valid release tag` |
| `./tools/release/verify-tag.sh 0.1.0` | refused: `expected vMAJOR.MINOR.PATCH[-PRERELEASE][+BUILD] with no leading zeros` |

### Python tool tests

`./tools/ci/run-tool-tests.sh` ran every `tools/**/test_*.py` as its own
process: **14 files, 627 tests, 0 failures**.

| Test file | Tests | Seconds |
| --- | --- | --- |
| `tools/ci/test_app_dependencies.py` | 27 | 25.53 |
| `tools/ci/test_audit_accessibility_identifiers.py` | 58 | 2.05 |
| `tools/ci/test_check_repository_hygiene.py` | 26 | 6.27 |
| `tools/ci/test_ci_changelog.py` | 10 | not measured |
| `tools/ci/test_ci_toolchain.py` | 67 | not measured |
| `tools/ci/test_ci_workflows.py` | 22 | not measured |
| `tools/ci/test_ci_counts.py` | 18 | not measured |
| `tools/ci/test_ci_docs.py` | 83 | not measured |
| `tools/ci/test_validate_schemas.py` | 59 | 105.12 |
| `tools/ci/test_verify_engine_checksums.py` | 38 | 2.96 |
| `tools/ci/test_verify_lockfiles.py` | 29 | 3.35 |
| `tools/ci/test_verify_release_inputs.py` | 99 | 95.48 |
| `tools/reproducibility/test_generate_sbom.py` | 64 | 10.33 |
| `tools/reproducibility/test_manifest.py` | 27 | 11.34 |

`tools/ci/test_app_dependencies.py` is the gate on the iOS app's dependency on
the canonical domain packages, and it is written as a mutation suite. The Xcode
project is parsed into objects — targets, local package references, product
dependencies, and the build files that link them — and the check requires both
`RoviaApp` and `RoviaAppTests` to declare *and* link `RoviaRouting` and
`RoviaConfig`, with the package paths resolving to a real `Package.swift` and
every product dependency pointing at a real local package. Its own mutations do
their surgery by product name and package path rather than by object identifier,
because a gate whose fixtures name `E10000000000000000000005` stops working the
moment Xcode renumbers, and the failure looks like a passing gate.

The limits of that gate are part of its record, not a footnote elsewhere: it reads
declarations and bodies, not Swift; it does not read an operator overload; a
stored `RuleEvaluation` is deliberately allowed because the canonical evaluator
builds a local one; and it reads the repository rather than the build.

The duplicate-evaluator check does not look for the old names. It extracts every
function and type declaration in the app sources and applies six rules — a range
type, a host normalizer in either spelling, a containment predicate, a matcher
predicate that returns a verdict, a decision function that returns a value of its
own, and (in the sources the app target compiles) a string compared by suffix or
prefix. The raw-trace check covers `core`, `client`, `platform`, and `engines`,
and finds `Codable` on the declaration, added by a retroactive extension, or
reached through a `Codable` wrapper, a stored property, a collection, a
typealias, or a function that accepts a trace and reaches for an encoder or a
durable store.

### Engine lock, in both modes

| Command | Result |
| --- | --- |
| `./tools/ci/verify-engine-checksums.sh --mode foundation --lock engines.lock.json --github-output /tmp/t7-gh-output` | `no production engine is enabled; foundation mode accepts an empty engine lock`; the output file contains `enabled=false` and `engine=none` |
| `./tools/ci/verify-engine-checksums.sh --mode release --lock engines.lock.json` | refused, exit 1: `release requires exactly one approved xray engine, but the engine lock enables none; foundation mode accepts this lock` |

### Schemas and JSON

| Command | Result |
| --- | --- |
| `python3 -m json.tool` over 38 files | all parse: 5 schemas, 32 fixtures, `engines.lock.json` |
| `python3 tools/ci/validate-schemas.py` | `Semantic schema checks OK (check-jsonschema 0.38.2)`, exit 0 |

`validate-schemas.py` checks the metaschema of all five schemas, validates the
positive fixtures, requires the negative fixtures to fail, and runs 48 semantic
probes on top of the schema validation: 13 control-API request cases (12 negative
plus the positive at exactly 128 characters)
(`matcher-extra-field`, `matcher-cross-role`, `rule-extra-field`,
`rule-cross-role`, `diagnostic-extra-field`, `diagnostic-cross-role`,
`selection-extra-field`, `selection-cross-role`, `api-version`,
`status-payload-field`, `status-extra-field`, `request-id-oversized`, and the
positive `request-id-at-the-bound`) and 20 engine-lock probes
(`engine-two-production`, `engine-unknown-production`, `engine-pending-approval`,
`engine-not-enabled`, `engine-short-commit`, `engine-missing-commit`,
`engine-short-digest`, `engine-missing-artifact`, `engine-empty-architectures`,
`engine-empty-build-flags`, `engine-unknown-approval`, `engine-unknown-field`,
`engine-two-go-runtimes`, `engine-disallowed-policy`,
`engine-unsupported-schema`, `engine-missing-candidate`,
`engine-approved-not-a-production-engine`, `engine-missing-license`,
`engine-unknown-license`, `engine-license-not-a-string`), 8 control-API
*response* probes
(`response-api-version`, `response-empty-request-id`, `response-missing-result`,
`response-empty-state`, `response-result-extra-field`,
`response-refused-with-result`, `response-missing-error`,
`response-unknown-error`), and 6 secret-reference key probes
(`secret-key-space`, `secret-key-control`, `secret-key-trailing-newline`,
`secret-key-non-ascii`, `secret-key-oversized`, `secret-key-empty`) plus one
further positive probe, a secret key at exactly 512 characters. That is 46
negative cases and 2 boundary positives, 48 in all, and
`tools/ci/test_validate_schemas.py` derives all four group counts from the
validator so the total cannot drift from the functions that produce it. A probe
that stops failing is the signal that a constraint stopped being load-bearing.

### Accessibility identifiers

| Command | Result |
| --- | --- |
| `python3 tools/ci/audit-accessibility-identifiers.py` | `46` declared constants, `12` container identifiers, `34` element identifiers, `46` reaching a view |
| `python3 tools/ci/test_audit_accessibility_identifiers.py` | 58 tests, 0 failures |

The audit is a structural check over the Swift sources. The container/element
split is a heuristic over how an identifier is applied, and a constant
concatenated at runtime is outside what a static constant audit can see.

### SwiftPM packages

Every entry in `tools/ci/local-packages.txt`, each with its own
`swift test --package-path`. The canonical core and the engine adapters moved
to RoviaNetwork/rovia-core and RoviaNetwork/rovia-engine, where their own CI
runs their suites; what remains here is the platform layer, and the app target
itself exercises the pinned core through the Xcode build and `RoviaAppTests`.

| Package | Tests | Failures |
| --- | --- | --- |
| `platform/apple` | 5 | 0 |
| **Total** | **5** | **0** |

### SBOM

`python3 tools/reproducibility/generate-sbom.py . build/SBOM.spdx.json` wrote
`4 components`; `python3 tools/reproducibility/check-sbom.py
build/SBOM.spdx.json --repository .` accepted it.

| Field | Value |
| --- | --- |
| `spdxVersion` / `dataLicense` | `SPDX-2.3` / `CC0-1.0` |
| `name` | `Rovia-iOS` |
| `creationInfo.created` | `2026-09-26T01:30:20Z` |
| `creationInfo.creators` | `Tool: rovia-sbom-0.2.0`, `Organization: Rovia contributors` |
| `documentNamespace` | a fresh UUID per run; a fixed `--namespace-id` fixes the namespace, and **on its own it does not reproduce the bytes** — see the correction below |
| Components | 4: the app, the Packet Tunnel extension, the local platform package, and the pinned rovia-core |
| Relationships | 4: 1 `DESCRIBES`, 1 `CONTAINS`, 2 `STATIC_LINK` |
| Engines listed | none, because the lock approves and enables none |
| File | 9 126 bytes, SHA-256 `59211b910ca002208ddaae496b14cedadcacebb1c6a49254a97b6357f93b9038` for this run's namespace |

**This claimed byte-reproducibility, and it was false.** Two runs with the same
`--namespace-id` did produce one distinct digest — because the test that checked it
overwrote `creationInfo.created` in both documents before comparing, and that field
is a wall-clock reading, so it was the one field that made two runs differ. The
digest above is for a run whose namespace was fixed and whose timestamp was not,
and the two runs happened to fall in the same second.

`creationInfo.created` is now settable: `--created` takes seconds since the Unix
epoch or an RFC 3339 UTC instant ending in `Z`, falling back to
`SOURCE_DATE_EPOCH`, and the tool prints a note on stderr when neither is supplied
so no reader can infer reproducibility from a fixed namespace alone. A document is
byte-reproducible only when `--namespace-id` **and** one of those are fixed. The
test now compares the SHA-256 of the bytes the tool wrote, with both fields fixed,
and a second test requires the note when the timestamp is not.

The namespace in the table above is from a run without `--namespace-id`, so it is a
fresh UUID and that file is not expected to match byte for byte.

### iOS app

| Command | Result |
| --- | --- |
| `xcodebuild -project client/app/ios/RoviaApp.xcodeproj -scheme RoviaApp -configuration Debug -destination "platform=iOS Simulator,id=1AA6273F-…" -derivedDataPath "$TMPDIR"/rovia-derived-data test` | `Executed 85 tests, with 0 failures`, `** TEST SUCCEEDED **` |
| the same, `-configuration Release -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build` | `** BUILD SUCCEEDED **` |
| the same, `-configuration Debug`, unsigned, generic simulator destination | `** BUILD SUCCEEDED **` |
| `./tools/ci/verify-bundle-metadata.sh …/Debug-iphonesimulator/Rovia.app --expect-version 0.1.0` | `io.rovia.client version 0.1.0 (1) executable Rovia, RoviaTunnel io.rovia.client.tunnel embedded` |
| the same against `…/Release-iphonesimulator/Rovia.app` | identical result |
| the same with `--expect-version 9.9.9` | refused: `the application bundle version 0.1.0 is not the expected 9.9.9` |
| `./tools/ci/verify-simulator-install.sh …/Debug-iphonesimulator/Rovia.app --device 1AA6273F-…` | `launched io.rovia.client as pid 2516 and the process is alive`, then terminated |
| the same against the Release bundle | `launched io.rovia.client as pid 2608 and the process is alive`, then terminated |

Derived data goes in a fresh directory under `$TMPDIR` on every run, and the path
is not recorded here: naming one would leave a stale path in a record the next run
invalidates. What is load-bearing is that it is outside the checkout, which is what
`tools/ci/test_ci_counts.py` requires — inside a checkout on the Desktop the test
runner loses access to its own bundle and the run times out before a single test
executes, which is a failure that looks like a hang rather than a misconfiguration.

The 85 tests are the `RoviaAppTests` suite: the model behaviour the slice has
always gated, plus four tests that hold the app to the canonical route model —
one that runs `RouteEvaluator.explain` for every sample input and requires the
debugger's display model to agree with it field for field, one that requires
every sample group and rule identifier to be a canonical UUID, one that requires
the bridge to refuse content the canonical model cannot represent, and one that
requires a refused evaluation to surface the sanitized `route.explanation.failed`
error without echoing the identifier it refused — plus four model tests for the
stored-subscription flow (adding a URL populates servers, refresh keeps the
selected server, a vanished server clears the selection, bootstrap loads
persisted subscriptions) and ten coordinator tests (fetch, decode, import with
honest counts, atomic refresh, stable IDs across reorder, the HTTP policy,
rename and remove with secret cleanup, and a legacy file without the insecure
flag) and two probe tests (measured latency lands on the servers, and probing
without a coordinator changes nothing) and one stale-refresh test (fresh
subscriptions are not re-fetched on foreground), one favorites test
(toggle, unknown rejection, and relaunch persistence), and four deep-link
tests (URL import with a name, single share links, base64 containers, and
rejected garbage), and one userinfo test (provider traffic/expiry persists
on add and clears when a refresh stops sending it).

The app and the test target both link `RoviaRouting` and `RoviaConfig` as local
Swift packages. Two build facts are part of that evidence: the Debug
configuration sets `ONLY_ACTIVE_ARCH = YES`, without which the app target
compiled both simulator slices while the package targets compiled only the active
one and the other slice failed with `Unable to find module dependency`; and the
derived data path stays outside the checkout. A live process is evidence that
the bundle launches. Neither is evidence of a tunnel.

### Workflow and lint checks

| Check | Result |
| --- | --- |
| `pyyaml` 6.0.2 over `.github/workflows/*.yml` | all three parse: `ci.yml` 1 job / 18 steps, `engine-repro.yml` 1 job / 6 steps, `release-ios.yml` 1 job / 17 steps; every one declares `permissions: contents: read` |
| `./tools/ci/check-python-lint.sh` | `3.2.0 Python 3.14.4 on Darwin, 14 files`, `no findings`; invoked by `run-tool-tests.sh`, followed by the warnings gate |
| `./tools/ci/check-python-warnings.sh` | `Python 3.14.7, 14 files, warnings are errors`, `no warnings`; the last step of `run-tool-tests.sh` |
| `bash -n` over every script in the tree | the same script count as the shell-syntax gate above, no syntax error |

### Gates that refuse, on purpose

These are recorded because a refusal is the result, not because anything failed.
Every row below is re-derived from the gate itself by
`tools/ci/test_ci_docs.py::test_the_refusal_table_is_what_the_gates_actually_do`,
which runs each command and matches the recorded outcome; the table cannot keep
describing a gate that has since changed its first refusal.

| Command | Result |
| --- | --- |
| `./tools/ci/verify-release-inputs.sh --tag v0.1.0` | refused, exit 1, on the **signing identity**, not on the secrets: the export options still hold `$(ROVIA_TEAM_ID)`, so it never reaches the secret check and never names a missing secret |
| `… --check-secrets-only` against this repository | refused, exit 1, for the same reason. `all signing secrets are present` is **not** reachable here: this repository has no team |
| `… --check-secrets-only` against a root whose `ExportOptions.plist` holds a literal team ID, with five placeholder secrets present | `all signing secrets are present`, exit 0. That path exists only in the test fixture, and it is about the secret check, not about a real signing identity |
| `./tools/release/verify-export-options.sh` | refused, exit 1: `unresolved teamID: $(ROVIA_TEAM_ID)`, plus the note that a build-setting reference would be substituted from whatever the environment held at export time |
| `./tools/build-engine/xray/build-apple.sh --lock engines.lock.json` | refused, exit 1: `No approved Xray lock entry is available; refusing to build a floating engine` |
| `./tools/reproducibility/verify-xray.sh` | refused, exit 1: `No approved Xray artifact exists; refusing to claim reproducibility` |
| `./tools/ci/verify-engine-checksums.sh --mode release --lock engines.lock.json` | refused, exit 1: `release requires exactly one approved xray engine, but the engine lock enables none` |

The first two rows were previously recorded as the release gate naming five
missing signing secrets, and as `--check-secrets-only` printing
`all signing secrets are present`. Both were true before the signing-identity
check became step 0, and both stopped being true when it did: the gate now
refuses earlier, on the thing that is actually missing.

## Working tree

23 tracked top-level entries, 164 files. `build/` holds the
generated `SBOM.spdx.json` and is gitignored; the `.build` directories, the
`__pycache__` directories, and the `.DS_Store` files are gitignored; derived data
was kept outside the checkout. `git check-ignore` confirms
`/.ci-schema-validator/` is ignored, so a locally created validator virtualenv
cannot be committed.

## What changed in this revision

A review of the client, privacy, and control surfaces produced six changes. What
each one did and where its tests live:

1. **One route evaluator.** `client/app/ios/RoviaApp/AppSnapshot.swift` used to
   carry `RouteMatcherSummary.matches`, `RouteMatcherSummary.normalizeHost`,
   `IPv4Range`, and `RouteRuleSummary.firstMatchingMatcher`: a second
   implementation of `RoviaRouting.RouteEvaluator` that could disagree with it
   silently. Those are deleted. The app now links the local packages through
   `CanonicalRouteBridge`, which converts the display models to a canonical
   `RouteSet` and `RouteInput`, calls `RouteEvaluator.explain`, and renders the
   returned `RoutingDiagnostic`; the sample group and rule identifiers became
   canonical UUIDs so the bridge never has to invent one, and a refusal is
   surfaced as a sanitized `route.explanation.failed` rather than a second
   answer. The Xcode project, the package references, and the deleted
   declarations are gated by `tools/ci/test_app_dependencies.py` (27 tests) and by
   four app tests.
2. **A response contract.** `schemas/control-response.schema.json` describes what
   `PacketTunnelProvider.handleAppMessage` returns: a closed envelope where
   `ok: true` requires `result` and forbids `error`, `ok: false` requires `error`
   and forbids `result`, and `error` is the closed set `invalid-request`,
   `not-implemented`. Three positive fixtures, six negative fixtures, eight
   generated probes, and eight schema tests, including one that deletes the two
   conditional branches and requires the checker to fail.
3. **A rule for secret reference keys.** `SecretReference.key` is a name, not
   data. It must be 1 to 512 printable ASCII characters without spaces, stated
   once as `RoviaConfig.SecretReference.isValidKey` and once as `maxLength` plus a
   pattern in `schemas/config.schema.json`. The decoder, the validator, and the
   raw-JSON walk all apply it, and `RoviaSubscription` now asks that function
   instead of keeping its own copy of the limit. Seven Swift tests, six schema
   probes, and four fixtures.
4. **`PRIVACY.md` corrected to the code.** It claimed an App Group container, a
   Keychain flow, a `packetFlow` bridge, and an engine shipped inside the app.
   None of those happens: `platform/apple` implements `KeychainSecretStore` and
   `AppGroupStore` and both targets declare the App Group entitlement, but no app
   or extension code calls either store, the extension never touches
   `packetFlow`, and no engine is bundled. The document now says so, and says
   that the debugger renders the canonical `RoutingDiagnostic` and never holds a
   destination at all. The wording tests read the Swift sources as well as the
   nine documents, because a comment that describes a text field is the same stale
   claim in the place a reader is most likely to meet it.
5. **The raw trace is not a persistence format.**
   `RoviaConfig.RoutingDecisionTrace` holds the raw hostname, address, and port
   that were evaluated. `Codable` is removed from it and from `RuleEvaluation`,
   the in-memory contract is written down, and
   `tools/ci/test_app_dependencies.py` fails if either conformance comes back, if
   the contract text is deleted, if a package source looks like it persists a
   trace, or if the redacted `RoutingDiagnostic` stops being `Codable`. Two Swift
   tests show why: the trace keeps the input, the diagnostic does not, and the
   diagnostic round-trips through the contract the control schema describes.
6. **Documentation and ownership.** `docs/development/control-api.md` documents
   the response envelope and its refusals, `docs/development/ci.md` records the
   secret-key rule, the trace contract, and the new gate,
   `docs/development/ios.md` documents the package references and the two build
   settings the dependency needs, and `docs/architecture/next-spikes.md` gains a
   spike for replacing the compiled-in sample content with a real
   configuration.

### Deliberately not done in this slice

This section was written by the first pass and has since been overtaken. It is
kept because the corrections are themselves part of the record, and a reader who
finds the old claim below should find the correction next to it.

- ~~`core/config/` is security-sensitive after the secret-key change, and
  `/core/config/` belongs in `CODEOWNERS` and in the `SECURITY.md` path list next
  to `core/routing/` and `core/subscription/`. This slice was told to leave the
  security list alone, so the entry is not there. `test_ci_checks.py` still
  passes, because it only checks that the two files agree with each other.~~
  **Corrected in the fifth pass.** `core/config/` is now in both files,
  `core/persistence/` — which was in both and does not exist — is gone, and the
  test is bidirectional and existence-checked. The original one-way check is the
  reason a path holding `SecretReference` could sit unowned while the suite was
  green; it checked that the sensitive list was owned, and never that the owned
  set matched the sensitive one or that either set existed.
- ~~The release gate, the SBOM generator and checker, and the security list were
  out of scope and are unchanged.~~ **Corrected in the fifth pass.** The release
  gate gained a signing-identity preflight as its first action and a new
  `--export-options` flag, the SBOM generator now derives engine licenses from the
  lock and refuses an unknown or inconsistent one, and the security list is
  different: it is now checked against the tree in both directions. What has
  *not* changed is the honest part — no signing, no upload, no release, and no
  real team behind any `CODEOWNERS` handle.

### Second remediation pass

A review of the first pass found four more open items. All four are fixed, and
the numbers above already include them.

**The control contract is symmetric.** The request schema bounded nothing where
the response schema bounded `requestID`, and the provider read four keys out of
whatever object it was handed. `schemas/control-api.schema.json` now caps
`requestID` at 128 and documents why, and `PacketTunnelProvider` enforces the
three rules the schema states — the envelope field set is compared with
`Set(fields.keys) == ControlContract.envelopeFields`, the identifier is
range-checked, and `status.get` must carry an empty payload. The numbers live in
one `ControlContract` enum in the provider, and
`tools/ci/test_validate_schemas.py` reads both schemas and the provider source
and requires them to agree, so a change on one side that is not made on the other
fails the suite. Two permanent negative request fixtures, two new probes, and a
positive probe at exactly 128 characters, because a probe set that only checked
refusals would not notice the bound being tightened to 127.

**The app-dependency gate reads rules instead of names.** The earlier version
searched for `IPv4Range`, `normalizeHost`, `firstMatchingMatcher`, and
`func evaluate(` — a snapshot of the defect that a rename walks straight past.
It now reads every *body* in the app sources: function declarations, computed
properties, closures bound to a name, and closures passed to a higher-order
function. **50 mutations plus 7 legitimate shapes**: 12 package-dependency
mutations, 16 ways of writing a second route evaluator (including the original
code restored verbatim, a file of its own, a computed property, a closure, and a
`contains { $0.matches(…) }`), 20 ways of giving a raw trace somewhere to live —
through a store, a serialiser, or one of the nine leak channels `print`, `os_log`,
`OSLog`, `Logger`, `logger`, `debugPrint`, `dump`, `NSLog`, and
`sendProviderMessage` — and 2 contract deletions. The 7 legitimate shapes are the
cases that look like a violation and must not be flagged, and they are not part of
the 50: adding one makes the gate no stricter. Each mutation is applied to a
temporary copy of the repository and the matching check must fail. The suite runs
27 tests and makes 69 copies of the tree. That figure is **measured**, by
counting `Workspace` instantiations — one per copy — rather than counting `shutil.copytree` calls, which recurse: the same run makes 6486 `copytree` calls and 69 outermost ones, and quoting the unqualified number would be wrong by two orders of magnitude. Measuring it costs the 20–90 seconds across the runs recorded in this repository's verification record, which is a measurement on one x86_64 Mac and not a bound. The width of that range is machine load and the number of mutation cases, not a property of the gate: the suite copies the tree once per case, so adding cases adds time, and a loaded machine stretches the rest. The observation in the table above sits inside it:
`test_app_dependencies.py` ran its 27 tests in 27.6s on an idle machine and in
51.6s while the machine reported a load average of 37, with no code change between
the two. The seconds column therefore records the run this entry describes, and a
loaded run is not evidence that the gate got slower — so no test
asserts the number itself. What
a test does assert is the bracket the mutation and shape counts imply, 54 copies at
the low end and 81 at the high, which a document cannot leave without being
wrong in a way that matters: a copy count below the number of mutation cases would
mean the cases are not being paid for.

It promises only what it reads, and the limits are written down in the gate
itself: an operator overload is not read, a body that avoids every signal is not
visible, a stored `RuleEvaluation` is deliberately allowed, Swift is not parsed,
and the gate reads the repository rather than the build. A third pass narrowed the
project mutations so their surgery is keyed on a product name and a package path
rather than on an object identifier — a gate whose own fixtures name
`E10000000000000000000005` stops working the moment Xcode renumbers, and the
failure looks like a passing gate. The pass also added `print`, `os_log`,
`Logger`, `dump`, `debugPrint`, `NSLog`, and `sendProviderMessage` to the channels
that count as a trace leak: nine channels, and now a mutation for each one rather
than five mutations between them. `OSLog(` and a lower-case `logger.` are separate
entries, and their mutations carry no `Logger(` token, because a mutation holding
all three proves them together and dropping `OSLog(` from the detector would fail
nothing. A test attributes every entry in `LEAK_CHANNELS` to a mutation, and a
second requires those two to be attributable without `Logger(` — and bounded every such check to the body it is about, which removed a false
positive: a trace-accepting function followed by an unrelated `print` was being
reported because the check read a window of characters to the end of the file.

**`PRIVACY.md`'s debugger claims were wrong three times.** It said the debugger
"evaluates exactly the input the user supplied", that it "accepts a destination
only as an explicit user-typed input", and that a typed destination was "the one
thing the app cannot redact". There is no text field in
`RoutingDebuggerView.swift`: the only input is a menu over the content's built-in
synthetic samples, which the view itself says on screen. The document now says
that, and three source-derived tests hold it: no `TextField`, `SecureField`,
`searchable`, or `NSTextView` in the view, the model refusing a sample id the
content does not contain, and the presence summary being a boolean.

**The bridge's unreachable branch is now a typed invariant.** The bridge
rendered a `guard`-based fallback for "the canonical evaluator returned a rule the
content does not contain", which no content can cause. That is now
`CanonicalRouteBridgeError.unreachableInvariant`, a case distinct from a content
refusal, applied through one `require` helper, with the three assumptions stated
in the source. A test names the two error shapes and requires them to read
differently. The optional consistency check is in too: a test compares
`RoutingDiagnostic.matchers` with `rules.flatMap(\.matchers)` for every sample
input and requires exactly one selected matcher in the deciding rule and none
elsewhere, so the nested and flat views cannot diverge unnoticed.

## Gates that were not executed

None of the following was run, and no claim is made about any of them. The same
list is held as a dated, in-repository disclosure in
`docs/development/release-readiness.md`, which is the canonical list of **nine**
gates and the copy a reviewer sees. This section is the run record's own account
of the same ground in **nine** entries: it groups signing, provisioning, archive,
and export into one item where the readiness document separates the signing
identity from the archive, and it separates publishing where the readiness
document folds publishing into the upload row. The two lists are the same ten
gates described at different granularity, not two lists of the same length, and
`tools/ci/test_ci_counts.py` counts both so neither number can drift.

1. **GitHub Actions.** No workflow has ever run. `$RUNNER_TEMP`,
   `GITHUB_OUTPUT`, `GITHUB_ENV`, the `macos-15` image contents, and the
   availability of `check-jsonschema` from `uvx` or `pip` on a runner are
   unverified.
2. **Signing, provisioning, archive, export.** No certificate, keychain import,
   provisioning profile, `xcodebuild archive`, `-exportArchive`, TestFlight, or
   App Store submission. The release gate's happy path is exercised only against
   a synthetic IPA in a throwaway repository.
3. **Publishing.** No upload, `altool`, `notarytool`, or release creation. The
   workflow has no upload step and a test fails if one appears.
4. **Physical-device VPN.** Profile installation, Packet Tunnel Provider
   lifecycle, IPv4, IPv6, dual-stack, reconnect, and real engine traffic are
   untouched. A simulator process staying alive says nothing about any of them.
5. **A production engine.** The lock enables none. No Xray build, no artifact
   hash, no reproducibility comparison was attempted.
6. **The `ios-production` environment and branch protection.** Secret presence
   was checked with local placeholders. Required reviewers, secret storage, and
   branch protection are unconfigured, and the `CODEOWNERS` handles are
   placeholders.
7. **Upstream SPDX tooling.** No `spdx-tools` run. `check-sbom.py` is a local
   checker of documented invariants, not a third-party validator. The
   `.invalid` namespace host is a deliberate placeholder and will not resolve.
8. **Third-party advisories, dependency review, secret scanning.** Not
   configured in this repository.
9. **Android.** Not started.

## What this means

The local product slice is stable: the domain packages, the engine boundaries,
the schemas, the CI and release gates, and the app model all pass, and the
repository's own tools refuse the states it is not ready for. The current
extension checks engine availability before constructing or applying network
settings and returns a typed engine-unavailable error when no production engine
is enabled. Simulator installation, a live process, and a green build are not a
VPN. `docs/architecture/next-spikes.md` is the ordered list of what has to
happen next.

### Third remediation pass

A second review of the client gate found six items. All six are fixed, and the
numbers above are from the run that fixed them.

**The gate's limits are in the gate, and a test holds them there.** The module
docstring used to advertise the check as beyond the reach of any change, and the
foundation record repeated a weaker version of the same claim. The docstring
now opens with what it reads, carries a `## What this gate does not claim`
section listing all five limits, and two new tests in `test_ci_docs.py` fail if
that section is deleted, if any of the five limits is reworded away, or if the
absolute claim and its relatives come back into the gate or into any of the five
documents that describe it. One of the two new tests is the old
`test_the_foundation_record_states_the_gate_limits`, which asserted that the
record carry a sentence whose only content was to disown the claim in the exact
words the claim used — a test that required the overclaim to stay written down in
order to be disowned.

**Every number in the documents is now computed, not remembered.** The
foundation record carried two different mutation tables: 8/12/11/2/6 and 33
workspace copies in one paragraph, 9/16/16/2/7 and 45 in another. Both are gone.
`test_ci_docs.py` now loads every `tools/**/test_*.py` with
`unittest.defaultTestLoader` and requires the record to state the count it finds
— including the count of that suite itself, which is the one that is easy to get
wrong and impossible to hard-code without recursion. A second test imports the
gate module, reads `PACKAGE_MUTATIONS`, `EVALUATOR_MUTATIONS`, `TRACE_MUTATIONS`,
`CONTRACT_MUTATIONS`, `LEGITIMATE_SHAPES`, and `LEAK_CHANNELS`, and requires
`ci.md` and `ios.md` to agree with all of them. The stale table also had the
wrong JSON breakdown: it said 29 fixtures where there are 32, which happened to
add up to 38 only because the number was wrong in one place and right in another.

**The mutations do their own surgery by name.** The last remaining hard-coded
object identifier was in `test_a_name_in_a_comment_does_not_declare_a_product`,
which rewrote the line
`\t\t\t\tE10000000000000000000005 /* RoviaConfig */,` by literal. It now calls
`_comment_out_product(text, "RoviaApp", "RoviaConfig")`, which looks the product
up through the same parsed project the gate uses, and that helper joined the
renumbering proof alongside the repointed path, the dropped product, the dropped
frameworks entry, the detached reference, the product pointed at no package, and
the renamed product. A first attempt at that rewrite used `re.sub(count=1)` over
the whole file and commented out the wrong entry — `RoviaApp` lists
`RoviaRouting` first — which still removed a product and still failed the gate,
for the wrong reason. The test asserts the gate notices, not just that the parse
changed.

**`debugPrint` and `NSLog` are leak channels with mutations.** The channel list
had five entries where it has nine. `debugPrint` in the app and `NSLog` in the
platform package are now mutations of their own, both caught, and both named in
the gate docstring, `ios.md`, `ci.md`, and the record. A new test extracts every
literal in `LEAK_CHANNELS` and requires each one to appear in the part of the
docstring that describes the channels, so a tenth channel cannot be added
silently.

**The Swift comments no longer describe a text field.** Two comments still said
the user types a destination: `CanonicalRouteBridge.swift` on the canonical input
and `AppSnapshot.swift` on what the display model holds. Both now say what is
true — one of the content's built-in samples, and no destination at all — and
the wording test in `test_ci_docs.py` reads every `client/**/*.swift` as well
as the nine documents, because a comment is where a reader is most likely to
meet a stale claim.

**The changelog has one `Fixed` section and carries the limits.** It had two,
split by a section that was not a section. The entries are merged in the order
the work happened, the sentence promising that renaming could not defeat the gate
is replaced by a description of what the gate reads, and the limits paragraph that used to
live only in the record is in the changelog as well. `grep -c '^### Fixed'`
returns 1.

### What this pass cost

| Thing | Before | After |
| --- | --- | --- |
| Tool tests | 364 | 611 |
| Mutations | 43 | 45 |
| Leak channels | 5 | 9 |
| Hard-coded object identifiers in the gate | 1 | 0 |
| `### Fixed` headings in the changelog | 2 | 1 |
| Fixtures the record claimed | 29 | 32 |

All three new tests are test methods in the docs suite, which is why its row moved from 83 to 86 when they landed (the file was `test_ci_checks.py` then, `test_ci_docs.py` after the thematic split): one for the overclaim and the limits, one for the channel
list, and one that computes the mutation and shape counts out of the gate module.
The two channel mutations are cases inside an existing test method, so they add
evidence without adding a test. The count in this record is computed by the
loader, so it cannot disagree with the suites it describes; the figures in the
table above are the ones that were wrong before and are read from the tree now.

### Fourth remediation pass

A third review of the client gate returned three accuracy items, D1, D2, and D4.
All three are fixed, the numbers above are from the run that fixed them, and the
count in the record is again the one the loader computes.

**D1 — the limits test now covers what the documents actually say, and the
blocklist covers the original wording.** The overclaim blocklist was missing the
sentence the gate originally used, the one about a check that nothing could get
past, so the gate had already been fixed and the test would not have noticed. The
limits half of the old combined test only read the gate's own docstring, while
its name promised the limits and every leak channel; the two responsibilities are
now separate tests. `GATE_LIMITS` is the five sentences quoted from the
docstring, and `DOCUMENT_LIMITS` is what `ci.md`, `ios.md`, and the changelog
have to say in their own words, so a limit repeated in a document cannot quietly
stop being repeated. The blocklist comment no longer quotes any of the phrases it
blocks, and `README.md` and `SECURITY.md` are out of the subject list because
neither mentions the gate; counting them would have made the record read better
than the coverage was, which is the error being fixed. The count itself is
corrected in the dated summary below, not here, so this narrative keeps the
wording the pass had.

**D2 — the composition is "50 mutations plus 7 legitimate shapes".** Every
document said "45 mutations, 7 of which are shapes", which folds the shapes into
the mutation count: they are the cases the check has to leave alone, and adding
one makes the gate no stricter rather than stricter. The count test now requires
the composition phrase and fails if the "N of which are shapes" phrasing returns.
It also required each group's number to appear next to its label, because
`assertIn(str(len(table)), record)` was satisfied by any `2` or `9` in the file.
All three documents now state 12 package-dependency mutations, 16 second route
evaluator mutations, 20 raw-trace mutations, 2 contract deletions, 50 in total,
7 legitimate shapes, and 69 tree copies (measured, not derived) — the copy count
having moved from 67 with the two channel mutations below. Phrases are compared with whitespace collapsed,
so a formatter wrapping a sentence cannot fail the test.

**D4 — `OSLog(` and `logger.` are proven on their own.** The nine-channel list had
five mutations between them: the `Logger` mutation contained both `Logger(` and
`logger.`, and nothing exercised `OSLog(` at all, so removing `OSLog(` from
`LEAK_CHANNELS` would have failed nothing. There is now a mutation that declares
an `OSLog` and one that calls `self.logger.debug`, neither containing a `Logger(`
token, and the trace table is 20 cases. Two tests hold it: one attributes every
entry in `LEAK_CHANNELS` to at least one mutation, and one requires `OSLog(` and
`logger.` to be attributable by a mutation that does not also contain `Logger(`.
The attribution test runs the mutation lambdas against a recorder that collects
appended text rather than against 20 copies of the repository, because asking
which channel a mutation exercises does not need the tree on disk.

| Thing | Before | After |
| --- | --- | --- |
| Tool tests | 361 | 364 |
| Mutations | 45 | 47 |
| Raw-trace mutations | 18 | 20 |
| Leak channels with no mutation of their own | 1 | 0 |
| Tree copies | 67 | 69 |
| Documents in the overclaim blocklist | 7 | 5 |

### Fifth remediation pass

A review of the release, provenance, security, and ownership surfaces found five
items. All five are fixed, the numbers above are from the run that fixed them,
and the count in this record is the one the loader computes.

**The export-options gate, and what it changed about the refusals.**
`tools/release/ExportOptions.plist` holds `$(ROVIA_TEAM_ID)`, an unresolved
build-setting reference, and no Apple Developer team was invented to replace it.
`tools/release/verify-export-options.sh` reads the plist and refuses anything
that is not a literal ten-character uppercase alphanumeric team ID, naming which
of four failures it found: an unresolved reference, a missing or empty `teamID`,
a malformed one, or a mismatch against a required team. Its acceptance message
says in the same breath that a written-down team ID is not evidence that signing
works.

`tools/ci/verify-release-inputs.sh` runs it as step 0, before the secret check,
and that reordering is what made the old "Gates that refuse" table false. The
release gate no longer names five missing signing secrets for this repository,
because it never reaches the secret check: it refuses on the thing that is
actually missing first. `--check-secrets-only` refuses for the same reason, so
`all signing secrets are present` is not reachable here at all — only against a
fixture root whose plist holds a literal team. The table above has been rewritten
to that, and `test_the_refusal_table_is_what_the_gates_actually_do` re-derives
each of its seven rows by running the gate and matching the recorded outcome, so a
refusal table cannot keep describing a gate that has changed its first refusal.

Writing that test found a defect in the flag added with the preflight:
`--export-options` was parsed and then discarded, because the default was assigned
after the parse loop and overwrote it. The release gate accepted the flag, and
used the repository's plist regardless.

**The team-ID check runs ahead of everything that could sign.** The release
workflow carries a named `Require a resolved signing identity` step at position 5
of 17 — after the tag and secret checks, before `Verify repository inputs`, and
well before `Create temporary keychain`, `Import distribution certificate`,
`Install provisioning profiles`, `Archive`, and `Export IPA`.
`test_the_export_identity_gate_precedes_every_signing_step_in_the_workflow`
asserts that order against the workflow itself, and `ci.md` documents the step
at that position so the two cannot drift.

**Engine licenses are derived, not defaulted.** `licenseDeclared` was hardcoded
to MIT for every component, so a GPL-3.0-or-later engine would have been published
as MIT. `engines.lock.json` candidates now carry a `license`,
`schemas/engine-lock.schema.json` requires it with an enum, and
`tools/reproducibility/generate-sbom.py` derives the component's license from the
lock and checks it against a source-to-license table: libXray is MIT, Xray-core is
MPL-2.0, sing-box is GPL-3.0-or-later. It refuses when the lock declares no
license, when the source is one it has no license for, and when the declaration
contradicts the source. The candidate named `xray` is built from libXray, so
libXray's license applies; Xray-core is a different project and would be a
different candidate. Eleven tests in `EngineLicenseTests` cover it, including the two
that matter most: a GPL engine declared MIT is refused and leaves no document
behind, and a missing license is a hard failure.

**Ownership is bidirectional, existence-checked, and has a stated criterion.**
`core/config/` was in neither `CODEOWNERS` nor `SECURITY.md` although it holds
`SecretReference`, `ConfigValidation`, and `RoutingDecisionTrace`;
`core/persistence/` was in both and does not exist. `SECURITY.md` now states the
criterion — a change that can alter what the product does with a credential, a
destination, a packet, or a signed artifact — and justifies each entry. The test
checks three directions: every sensitive path is owned by a security or engine
handle, every security-handled path is sensitive, and every path either file
names exists. The handles are still placeholders for teams that do not exist, so
no review is required on any path today, including the sensitive ones; both
documents now say that instead of leaving a reader to infer it from the word
"placeholder".

**The unexecuted gates are disclosed in the repository.**
`docs/development/release-readiness.md` is a dated, in-repository disclosure of
all ten gates, each with why it is open and what would close it, and each naming a
path in this repository that would have to change. It existed only in a planning
ledger outside the repository before, which is not disclosure: nobody reviewing a
change sees a ledger. Eight tests hold it, including one that requires each row's
title to be followed by an absence rather than a pass.

| Thing | Before | After |
| --- | --- | --- |
| Tool tests | 364 | 627 |
| Security-sensitive paths listed | 14, one of them nonexistent | 15, all existing |
| Ownership directions checked | 1 | 3 |
| Engine license declared per candidate | none, defaulted to MIT | required, derived, and cross-checked |
| Refusal rows derived from the gates | 0 | 7 |
| Unexecuted gates disclosed in the repository | 0 | 10 |

### Thirteenth remediation pass — a false reproducibility claim, and four reconciliations

Date: 2026-09-26

The last review of this slice found one false claim in this record, five stale
sentences in the documents, and four places where two implementations of the same
rule disagreed. All are fixed, and the numbers above are from the run that fixed
them.

**The byte-reproducibility claim was false, and the test that appeared to check it
was the reason.** `creationInfo.created` was a wall-clock reading, so two runs of
the same tree differed in that one field. The test named
`test_output_is_deterministic_for_a_fixed_namespace` overwrote `created` in both
documents before comparing them — it was a statement about the document minus its
timestamp, and the timestamp was the thing that differed. `--created` now takes
seconds since the epoch or an RFC 3339 UTC instant, falls back to
`SOURCE_DATE_EPOCH`, and the tool prints a note when neither is supplied so a
reader cannot infer reproducibility from a fixed namespace. A document is
byte-reproducible only when `--namespace-id` **and** a timestamp are both fixed.
The test now compares the SHA-256 of the bytes the tool wrote, and the record says
so above rather than claiming a digest proves it.

**Two redactors disagreed about the port.** `RoviaConfig.SubscriptionSource`
dropped it and `RoviaSubscription.SubscriptionRedactor` kept it, while the schema
pattern, `tools/ci/validate-schemas.py`, the share-link fixtures, and `PRIVACY.md`
all kept it — so the persisted display value depended on which code path had
produced it. The port is not the secret, so both keep it, and a test in
`core/subscription` compares the two directly, which it can do because that
package depends on `RoviaConfig`. One difference is deliberate and is recorded in
`PRIVACY.md` and in the decisions section of
`docs/architecture/next-spikes.md`: a URL carrying userinfo is refused outright by
the config path and replaced with the literal `redacted`, while the subscription
path keeps the host.

**An IPv4-mapped IPv6 address is accepted and normalised, not refused.**
`::ffff:1.2.3.4` returned nil from the parser, so `RouteEvaluator` threw
`invalidIPAddress` for a destination a dual-stack socket hands out routinely. It
now parses to the four bytes of the IPv4 address it maps, and the canonical form is
the dotted quad. The consequence — an IPv6 rule such as `::/0` does not match a
mapped address, because the candidate is four bytes and the network is sixteen — is
the safe direction and is recorded where the packetFlow spike will meet it.

**A degenerate domain no longer normalises to a value.** `normalizeDomain("..")`
returned `"."` and `"..."` returned `".."`, both non-empty strings describing no
host, and `RouteEvaluator` compared the two sides as `Optional` where `nil == nil`
is true. Normalisation now returns nil for any name with an empty label, which
makes such a matcher fail validation with `invalidMatcher` before it can be
compared, and the evaluator's comparison checks that both sides are present rather
than comparing two `Optional`s. A test in `core/routing` exercises the evaluator
itself, because the nil-to-nil match is a property of the comparison and not of
either function alone.

**The schema and the model now agree on a display value.** The model rewrites a
`pastedText` or `file` source to one of three literals and discards whatever the
file said, while the schema accepted any non-empty string — so a file could carry a
value the model would silently replace. The schema states the three literals, and
a test in `tools/ci/test_validate_schemas.py` reads the schema's enum and the
model's literals and requires them to be the same set.

**The preflight's arguments are an array.** The release gate built the
`verify-export-options.sh` invocation with an unquoted
`${ROVIA_TEAM_ID:+--require-team-id "$ROVIA_TEAM_ID"}` expansion, which
word-splits and glob-expands: a team ID of `*` would have been replaced by the file
list of the working directory before the tool ever saw it. The arguments are an
array now, and a test feeds the preflight `*`, `* wild word`, and `--plist` and
requires each to arrive as one argument and be rejected by the tool's own format
rule.

**The wording tests read every document, not a list of nine.** Three findings came
from files the hand-maintained list did not include: `docs/security/threat-model.md`
described a typed input the debugger does not have,
`docs/architecture/next-spikes.md` named the wrong refusal, and `docs/legal/` was
never checked at all. The test now enumerates the markdown tree and excludes
exactly two trees, both planning records rather than statements about the product:

- `.superpowers/` — the SDD ledger. Everything under `.superpowers/sdd/` is
  gitignored, through the `*` in `.superpowers/sdd/.gitignore` itself, and the
  ledger quotes superseded wording on purpose to record what was corrected.
- `docs/superpowers/` — the plan files. This one **was** part of the tree, which was
  a publication defect rather than a stylistic one: 72 of its checkboxes are still
  unticked for work that is in fact finished, so a public reader would have found a
  record of unfinished work next to a record of finished work. It is
  gitignored now, alongside `.superpowers/`, and `tools/ci/check-repository-hygiene.sh`
  holds that line in `.gitignore` so the exclusion cannot be dropped by accident. The
  design record meant to be read lives in `docs/adr/` and `docs/architecture/`.

The exclusion is `^(\.superpowers/|docs/superpowers/)`, and a test requires the
set of trees this paragraph names to be exactly the set that pattern excludes, and
requires the gitignore status of each to be as stated here — a claim about what is
ignored is checkable, so it is checked. It is the reason this paragraph had to be
rewritten rather than merely extended: `docs/superpowers/` stopped being part of the
tree, and the sentence that said it was part of the tree became false while the
rest of the claim about it stayed true. A gate that checked the unticked count and
not the ignore status would have reported nothing wrong here.

**The audit reads a container role as a bare word in one rule and by name in the
other, and the reason is written down.** Rule 3's `has_container_treatment` requires
`.accessibilityElement(children: .contain)` by name. Rule 5's second condition uses
the bare word `accessibilityElement`, so it accepts `.contain` and `.combine` alike.
That asymmetry is deliberate. In rule 3 the question is whether a container's children
keep their own identifiers, and `.combine` is the answer "no" — it merges the children
into the container's element and discards theirs — so only `.contain` is the guard. In
rule 5 the question is whether a component claims a container role of its own over
caller-supplied content, and both roles claim one, so either is a finding. The cost
is that rule 5 reports a component using `.contain` directly, which is why the docstring
says a component must not claim the role itself and let the treatment apply it. Both
readings have tests.

**The gate-runtime consistency check is anchored on the gate's own sentences, and
the reason is written down.** It began as one pattern requiring the phrase
"seconds across the runs", which let a stale `28-34` survive in a sentence phrased
"the seconds the suite already spends". Widening it to *any* `N-M seconds` in the
three documents fixed that and created a worse problem: an unrelated "1-2 seconds"
— a connection, a step, a simulator — would fail a check about the suite's
runtime, and the only remedy would be to weaken the pattern until that stopped
happening. It is now one alternative per phrasing these documents have actually
used, and the four alternatives are not equivalent. Two are **catch-all phrases**
and two are **anchored on the gate's subject**, and the difference is recorded here
because an earlier version of this paragraph claimed all four named the gate. That
was false of two, and the claim was unfalsifiable because the corpus only covered
the `second range` shape.

- **Catch-all phrase:** "seconds across the runs" and "seconds the suite already
  spends". These do not name the gate and cannot be made to: the sentences the
  documents actually use are phrased around the cost of *measuring* something —
  "Measuring it costs the N-M seconds across the runs recorded in this repository's
  verification record" — where the subject is the measurement, not the gate.
  Anchoring them would mean rewriting these documents to fit the check, so they
  stay as phrases and the false positives they carry are written down below.
- **Anchored on the subject:** "gate runtime range reads" and "gate runs in the".
  A span belonging to something else is not read from these.

A third alternative once matched `N-M second range` by phrase alone. It was both a
catch-all — it read "the 2-3 second range of the retry" as a gate runtime — and
dead, matching nothing in these documents. The subject-anchored alternative that
replaced it also picked up a sentence the others miss, this record's "the gate
runtime range reads N-M seconds in every document", which no `seconds across the
runs` phrasing covers. `RUNTIME_SPAN_KINDS` names the classification in the test
file, and a test proves each entry of it against the pattern rather than against a
description of it: a subject alternative must reject a sentence about another
subject, and a catch-all must read one. A catch-all therefore cannot sit in the
pattern described as subject-anchored.

Both directions of the trade-off are real, so both are written down.

**False positives — a span that is not the gate's.** These come in two sizes, and
only one of them is prevented. The subject-anchored alternatives cannot produce
them: a document discussing a connection, a retry or a telemetry window is not read
by those. **The two catch-all phrase alternatives can, and do.** Any sentence ending
in one of the two catch-all phrases is read as a gate runtime, including one about
the fuzzer or about a clean build, which is how an unrelated measurement in one of
these documents would be objected to. A test asserts exactly that, with the numbers
and the phrase in a sentence of its own, so the cost is a fact about the pattern
rather than a worry in a comment.

Those examples are written here as the two phrase fragments, not as whole
sentences with a span in front of them, and that is not only for the prose. This
paragraph originally quoted a full example sentence, and the check this paragraph
is about read *its own documentation* as two more inconsistent gate runtimes — the
false positive demonstrated by the record documenting it. The mitigation is that these three documents are ours and state
one thing about this range, so nothing today trips it. The risk is a future
sentence about another subject that reuses one of the two phrases, which would fail
this gate for a reason that has nothing to do with the suite. Fixing that properly
means anchoring the phrases on the gate and rewriting the sentences that use them,
which is a change to what these documents say and is not made here.

**False negatives — a stale span the pattern misses.** A *new* phrasing of the gate
runtime is not read until someone adds it to the pattern, so the check can be
defeated by rewording. Two things limit that. A new phrasing has to be added as a
visible alternative in the pattern rather than by loosening it, and a test requires
more than one phrasing to match, so tightening the pattern until it reads only the
sentence the first pattern already found fails rather than passing quietly. Two
further tests hold both ends: one requires an unrelated `N-M second range` to be
left alone, and one mutates each phrasing in turn and requires the pattern to read
both the correct and the wrong numbers from it — so an alternative cannot sit in
the pattern matching nothing and be assumed to work. The pattern finds a stale span
with the wrong numbers in every wording these documents use today; it would not
find one written in a wording nobody has used.

**`isSecretBearingKey` stays a substring blocklist, and the reason is written
down.** It refuses sixteen fragments after stripping non-alphanumerics, so it has
false positives: `tokenizer`, `authority`, and `passport` all match. That is
deliberate. A false positive costs a rename; a false negative puts a credential in
a query parameter that reaches an engine. The decision, and what reversing it
would have to argue, is in the decisions section of
`docs/architecture/next-spikes.md`.

### Fourteenth remediation pass — five documents that had drifted from the tree

Date: 2026-09-26

The last review compared five documents against the code and found each of them
describing something the repository does not do. All are fixed, and the numbers
above are from the run that fixed them.

**The SwiftPM table was stale and the gate hard-coded its total.** The table said
`core/config` 50, `core/routing` 40, `core/subscription` 39, total 140; the
realities after the mapped-address and degenerate-domain work were 64, 44, and
41, total 160. The gate's assertion held the string `140` as a literal, so it
would have kept passing against any number in the table. It now derives the total
by counting the `func test…` methods in every suite under each entry of
`tools/ci/local-packages.txt`, and requires the table's total to be that number.
The per-package figures are the recorded output of the run below.

**The legal document stated the opposite of the tree.** It said engine versions
"are pinned and shipped with the app release", while `engines.lock.json` enables
none and the app therefore cannot establish a tunnel — and `PRIVACY.md` already
recorded this document as holding the App Review note *for the day* a pinned engine
is added. The claim is now conditional, and a test requires the conditional form,
the statement that no engine is pinned today, and agreement with the privacy
answer it is referenced from.

**The threat model listed six controls that do not exist, in the present tense.**
Fuzz targets, CI secret scanning, dependency review, physical-device tunnel tests,
an independent reproducibility check, and Android golden fixtures were all written
as though they were mitigations this repository has. Two of the seven lines in that
list were real. Each control is now under **In place and executed here** or
**Planned, not implemented**, and a planned one names the row of
`release-readiness.md` that says it is open — so a reader can go from the threat
model to the dated disclosure. A test fails if any of the six appears under the
executed heading, if one is missing from the planned heading, or if a row it cites
does not exist.

**The record's own namespace cell still made the retracted claim.** The SBOM table
said a fixed `--namespace-id` reproduces the bytes, in the same table the pass
above retracted that claim in. The cell now says that fixing the namespace does not
by itself reproduce the bytes and points at the correction. A retraction that can
be deleted without failing anything is not a retraction, so a test requires the
superseded claim to still be present, marked, contradicted, and accompanied by the
reason the test that seemed to check it could not have caught it.

**`ios.md` listed four of the seven local packages.** The engine adapters and
`platform/apple` were absent, which read as though the adapter boundary and the
Keychain and App Group stores were untested. All seven entries are now listed, and
a test requires the documented commands to equal the entries of
`tools/ci/local-packages.txt` — the file the lockfile verifier, the SBOM generator,
and the release workflow all read — so a package added there cannot be left out of
the documented commands.

**The changelog records the pass.** Five entries: mapped-IPv6 acceptance and the
`::/0` consequence, the degenerate-domain refusal, the redactor that keeps the port,
the display-value enum shared by the schema and the model, and the SBOM timestamp
that makes the reproducibility claim true or false.

### Release, provenance, security, and ownership remediation — dated summary

Date: 2026-09-26

The fifth pass above is the narrative of the release, provenance, security, and
ownership remediation. This section is the dated, count-checked summary of the
same work, including the five further passes that corrected this record rather than
the code. It exists so the in-repo account does not stop at the fifth pass and
leave a reader to find the rest in a planning ledger outside the repository.

| Remediation | What it is | Where it is checked |
| --- | --- | --- |
| Export-options team-ID gate | `tools/release/ExportOptions.plist` ships `$(ROVIA_TEAM_ID)`. No Apple team was invented. `tools/release/verify-export-options.sh` refuses anything that is not a literal ten-character team ID, and it is step 0 of `tools/ci/verify-release-inputs.sh`, so the gate cannot report signing inputs present while the signing identity is unresolved | 14 tests in `ExportOptionsTests` (55 discovered, including 41 inherited from `ReleaseInputsTests`), covering the gate order on the output and on the script source, and the argument handling |
| Team-ID ahead of everything that signs | The release workflow carries `Require a resolved signing identity` at position 5 of 17, before the keychain, the certificate, the profiles, `Archive`, and `Export IPA` | `test_the_export_identity_gate_precedes_every_signing_step_in_the_workflow`, plus a test that `ci.md` documents it at the position the workflow has |
| Derived engine licenses | `licenseDeclared` was MIT for every component. Each candidate in the lock now declares the license of the code it builds, the schema requires it, and the generator checks it against the upstream project the lock names — libXray MIT, Xray-core MPL-2.0, sing-box GPL-3.0-or-later — refusing a missing, unverifiable, or inconsistent license | 11 tests in `EngineLicenseTests`; 3 lock-schema probes; the schema enum and the generator table are required to be the same set |
| Bidirectional ownership | `core/config/` was in neither ownership file; `core/persistence/` was in both and does not exist. `SECURITY.md` states the criterion, and the test checks three directions: sensitive implies owned by a security or engine handle, security-handled implies sensitive, and every path named exists | one test with three directions, plus a test for the stated criterion and one for the unresolved review identity |
| In-repo readiness disclosure | The nine unexecuted gates lived only in a ledger outside the repository. `docs/development/release-readiness.md` is dated, names the path or workflow step that would have to change for each gate, and makes no claim about any of them | 8 tests, including that every named path exists and that no gate title is followed by a claim that it passed |
| Derived counts | Suite totals, gate mutation and shape counts, the refusal-table row count, the overclaim subject count, the readiness gate count, the sensitive path count, the probe counts, the license-test count, and the gate runtime range are each read from the thing they describe rather than restated | the loader, `SemanticProbeCountTests`, and per-area drift tests |

**What the five correction passes changed in this record, rather than in the code.**
Each of these was a claim in this document that had stopped being true:

- The "Gates that refuse" table named five missing signing secrets, and said
  `--check-secrets-only` printed `all signing secrets are present`. Both stopped
  being true when the signing-identity check became step 0, which refuses earlier.
  The table now records seven refusals, and all seven are derived by running the
  gate.
- `CHANGELOG.md`, `docs/development/ci.md`, and the release gate's own header all
  listed the engine lock as the last check. It has never been last:
  `verify-engine-checksums.sh --mode release` runs before the IPA is opened. All
  three now state the order the body actually runs, derived from marker positions
  in the script.
- The semantic probe count was 45 where the validator runs 46 negative cases and 2
  boundary positives. The four probe groups return 13, 8, 20, and 6, and because
  `request-id-at-the-bound` is a positive case *inside* the request group, the
  total is 47 + 1 = **48**. Adding two positives to the group sums gives 49 and
  counts the 128 case twice.
- The fixture count was 29 where the tree has 32; the gate test count was 11 where
  the gate has 27; `EngineLicenseTests` was ten where it has eleven; the
  security-sensitive path list held 18 where SECURITY.md now lists 19.
- The copy count was attributed to "instrumenting `shutil.copytree`", which
  recurses: that instrument yields 6486 calls for 69 copies. The figure counts
  `Workspace` instantiations — 69, matching the outermost `copytree` calls — and
  the documents now say so. A derived bracket of 54 to 81 is what a test enforces,
  because measuring the number costs the 20–90 seconds the suite already spends.
- The overclaim blocklist covered seven documents before the fourth pass and five
  after it, because `README.md` and `SECURITY.md` were dropped — two documents, not
  one. The prose had been left describing the pre-pass count, and the before/after
  row had been given `6 | 5`, which was the subject count with the gate folded in
  under a "Documents" label. The row now reads `7 | 5`, both statements say five
  where they describe the current state, and a test reads the prose and the row
  and requires them to agree.
- The gate runtime was 31 seconds in two documents and 28 in the third. All three
  now state 20–90 seconds across recorded runs, labelled a measurement on one
  x86_64 Mac and not a bound, and the record's own seconds column for that suite is
  required to fall inside the stated range.
- "Ten gates" and the record's own nine-item list were not the same length. They
  are the same ten gates at different granularity, and both documents now say so
  rather than claiming an equality of length.

This section is the roll-up of the release, provenance, security and ownership work:
it indexes the passes above it, including the thirteenth and fourteenth, so a reader
who reads only this has that account. It is **not** the last section of the record —
the dated summaries that followed it are — and a test that used to say it had to be
last was reading a list built by filtering headings for the word "remediation", which
did not contain this record's actual last section at all. What is required, and
checked, is structural: the last `###` section of the record must be a dated summary,
and every pass section in the record must be listed in `EXPECTED_PASS_SECTIONS`, so a
pass cannot be appended without a summary of its own and without its changelog entry
being required. A pass section is a section carrying the dated marker, or a narrative
one titled with an ordinal — the ordinal is matched as an ordinal, so hyphenated forms
count and no other wording is admitted — and the list is compared in both directions,
so a section inserted anywhere in the record is caught and not only one appended at the
end.

**What none of this is evidence of.** The ten gates in
`docs/development/release-readiness.md` remain open, and the two that gate the rest
have not moved: there is no Apple Developer team, so no signature, archive, or
export can be produced, and every `CODEOWNERS` handle is a placeholder for a team
that does not exist, so no review is required on any path today. A refusal is a
result: the release gate refusing on the signing identity is the gate working.

### Lint-gate count and count-completeness remediation — dated summary

Date: 2026-09-26

The lint gate's document check counted its own tests by searching for `"lint"` in
a test name or `"pyflakes"` in its source, so a gate test named without either
marker would not be counted and all three documents would still pass. The count is
now the number of methods in `PythonLintGateTests`, a test proves a method added to
that class moves the count, and every "N tests hold it" occurrence in the three
documents is classified as quoted or live rather than only the first one matched.

The pass that followed ended by claiming "no other count in the documents is
hand-written and ungated". That sentence was the only claim in this record with no
derivation and no test, so it could not fail, and it was false: ten live counts
were accurate and ungated. Each is now read from its real source by
`LiveCountDerivationTests` — the JSON, schema and fixture counts from the tree, the
accessibility counts from the audit's own output, the SBOM counts from a generated
document, the workflow job and step counts from the workflows, the shell and
package-manifest counts from the files, the tracked count from `git ls-files`, the
signing gate's step position from the step list, the unexecuted gate count from the
readiness rows, and the semantic probe count from the validator's probe functions.
A mutation test runs each of the ten real tests against a record that states
something else and requires each to fail; a further test requires the exempt set to
remain exactly the two groups named above.

Also in these two passes: `DuplicateDefinitionTests` now refuses a name defined
twice at the same scope under `tools/`, covering `def`, `class`, `import`, and
assignments to a name, tuple, list or starred target — the shapes pyflakes 3.2.0
is silent about when a name is rebound, which was verified rather than assumed.
A duplicated test that re-implemented the quote-versus-claim cases inline was
removed, and three unreferenced module constants (`PRODUCT_PATTERN`,
`ANONYMOUS_CLOSURE`, `ENGINE_LOCK`) were removed after an AST walk confirmed no
reference to any of them.

The suite now passes from `tools/ci`, from the repository root, and from a
directory outside the repository. Two calls depended on the process working
directory rather than naming what they meant: the accessibility derivation shelled
out with an absolute script path while the audit resolves its `--app` default
relative to the process, and the gitignore probe ran `git check-ignore` with no
repository named, so git resolved one from wherever the process was. The first now
pins `cwd` and the second passes `-C`; a test runs every test in the module from
outside the repository and requires it to pass, and checks the nested run's own
count against the module so the claim cannot narrow back to a class.

The gate runtime range reads 20-90 seconds in every document that states it. A
stale 28-34 survived wherever the consistency check's required phrase was
absent, because the check only looked at the sentences that carried it; the check now collects
every runtime span in the three documents whatever phrase introduces it, and a test
confirms it rejects a span with the right shape and the wrong numbers.

### Working-directory, derivation and changelog-shape remediation — dated summary

Date: 2026-09-26

The suite runs from `tools/ci`, from the repository root, and from outside the
repository, and the accessibility audit it depends on runs from all three as well.
Three things depended on the process working directory rather than naming what they
meant. The gitignore probe ran `git check-ignore` with no repository named, so git
resolved one from wherever the process was. The accessibility derivation shelled out
with an absolute script path while the audit resolved its `--app` default relative
to the process, so the derivation needed a pinned `cwd`. And the audit's own
default was that relative path, so the script exited 1 from anywhere except the
repository root, reporting a file that was not missing. That third one means the
earlier claim that the suite runs from outside the repository was true of the
*suite* and false of the *script the suite runs*, which is the kind of half-true
sentence this record exists to avoid. The default is now resolved from the script's
own location, and a test invokes the script itself from outside the repository
with no arguments, requiring the same exit status and the same three counts it
reports from the root.

The gitignore defect is the reason the working-directory test runs every test in the
module rather than one class: the accessibility fix left it in place, and a
narrower check would not have found it. The nested run's own reported count is
checked against the module, so "the whole file" cannot quietly become "one class"
again.

The app test count is derived rather than transcribed. The record carried
`Executed 60 tests, with 0 failures` and a test required that literal, so the only
way to change it was to run the suite and edit the document; it is now counted from
the `func test…` methods in `RoviaAppTests`, the way the SwiftPM rows are counted,
and yields the same 60. The derived-counts paragraph names it, and the exempt
section records that it was nearly a third exempt group and is not one.

`ChangelogShapeTests` requires the changelog's structure: each section name once,
each `###` section followed by its own bullet, and no bullet list split by a blank
line. The file had two `### Added` sections and a split `### Fixed` list, both from
earlier edits in this work.

The gate-runtime consistency check is anchored on the gate's own sentences rather
than on any `N-M seconds`, and the reason is written down above with the other
trade-offs: anchoring on the number would make an unrelated "1-2 seconds" fail a
check about the suite's runtime, while anchoring on the subject means a new
phrasing is not read until it is added. A test requires more than one phrasing to
match, so the narrowing cannot pass vacuously.

### Runtime-pattern anchoring and changelog coverage — dated summary

Date: 2026-09-26

The gate-runtime pattern has four alternatives and they are not equivalent, which
an earlier paragraph of this record denied: it said every alternative named the
gate, and two of the four are catch-all phrases that do not. The claim was also
unfalsifiable, because the corpus that would have caught it only covered one
`second range` shape. `RUNTIME_SPAN_KINDS` now classifies each alternative, and a
test proves the classification against the pattern: a subject-anchored alternative
must reject a sentence about another subject, a catch-all must read one, and an
alternative that is neither classified nor present in the pattern fails. The false
positives the two catch-alls carry — a sentence about the fuzzer or a clean build
that happens to end in one of their phrases — are stated in the record above and
asserted as a test, so the cost is a fact about the pattern rather than a worry in
a comment.

The changelog-per-pass check was one-directional. It read the record to learn which
passes it owed an entry for, so deleting a pass section made its own obligation
disappear and every test still passed — it could not fail on the edit it exists to
catch. The pass sections are pinned explicitly now, the way this record already
pins its first dated summary, and a deleted section is a failure. A second check
runs from the other end and fails when the record no longer holds a pass in full,
which is what an orphaned changelog entry looks like. The per-pass match also
required only a majority of a subject's words, so deleting part of an entry passed;
it requires all of them.

The accessibility audit resolved its `--app` default against the process working
directory and exited 1 outside the repository, while this record claimed the suite
runs from outside the repository. The default is now resolved from the script's own
location, and a test runs the script from outside the repository.


### Publication pass — an open-source repository — dated summary

Date: 2026-09-26

This pass changed no behaviour in `core/`, `client/`, `platform/`, or `engines/`. It
changed what a reader of the repository can conclude about it, and it added one gate.

**A hygiene gate, because a clean tree is a moment and a claim is not.**
`tools/ci/check-repository-hygiene.sh` checks the set of files git would publish —
`git ls-files --cached --others --exclude-standard` — and refuses a credential shape, a
path under `/Users` or `/home` naming a real person, a build artefact, a file over
4 MiB, or a `.gitignore` that has stopped covering one of the artefact classes. It runs
from `tools/ci/run-tool-tests.sh` and from CI.

The first version walked the working tree and failed on 21 `.DS_Store` files, all of
which `.gitignore` already excludes. That is the failure mode worth recording: a gate
that fails on a correct tree gets deleted, and the claim it held goes with it. The gate
now asks git what it would publish, which is the honest scope of a publication check,
and `tools/ci/test_check_repository_hygiene.py` holds both directions — an ignored
`.DS_Store` is accepted, and the same file with its ignore rule removed is refused.

**`CODEOWNERS` no longer names an organisation that does not exist.** The handles were
`@rovia-net/*` placeholders, which read as a review requirement and enforced none:
GitHub teams only exist inside an organisation, and there is none. They are now
`@princeofscale`, a real account with write access. The consequence is stated rather
than hidden: with one owner, a required review would be a self-review, so the
security-sensitive classification now lives only in `SECURITY.md`, and the reverse
ownership direction that depended on role handle names was removed and replaced by
`test_ownership_alone_is_not_a_security_signal`.

**`docs/superpowers/` is now gitignored.** It held 72 checkboxes unticked for work that
is finished, so publishing it would have put a record of unfinished work next to a
record of finished work. The gate holds the ignore line.

**The README's figures are generated.** `tools/ci/update-readme-counts.py` writes the
test counts between `<!-- counts:start -->` and `<!-- counts:end -->` from the same
loaders the suite uses, and `tools/ci/test_ci_docs.py` fails if the committed text
drifts from them. The file count in that check was a literal `9` and is now derived;
adding a test file had made the record wrong, and a literal is a number somebody has
to remember to bump.

**What this pass did not do.** It did not add a release, a tag, or a version: the
project is pre-alpha and the tunnel does not exist, so a tag would be a claim nothing
supports. It did not enable a branch-protection ruleset, because with one maintainer
the requirement would be satisfied by a self-review. It did not create a GitHub
organisation, because choosing that name is a branding decision and not one to make on
the owner's behalf.
