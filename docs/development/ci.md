# CI and release workflow

Every gate below is a repository script, so the same command runs on a
developer machine and in CI. No gate reads a secret except the release
workflow's secret-presence and signing steps.

## Local equivalents

```text
pre-commit run --all-files                           # the same four Python/shell/hygiene gates, plus the structural hooks, before a commit exists
./tools/ci/check-shell-syntax.sh                     # every tracked script parses
./tools/ci/run-tool-tests.sh                         # every tools/**/test_*.py file, then both Python gates and the hygiene gate
./tools/ci/verify-lockfiles.sh                        # package manifests and the engine lock
./tools/ci/verify-engine-checksums.sh --mode foundation
./tools/ci/verify-third-party-notices.sh
./tools/ci/check-python-lint.sh                 # pinned pyflakes==3.2.0 over tools/**.py
./tools/ci/check-python-warnings.sh             # every module compiles, warnings are errors
./tools/ci/check-repository-hygiene.sh          # no secrets, machine paths, or artifacts
python3 tools/ci/audit-accessibility-identifiers.py  # identifier contract
python3 tools/ci/test_audit_accessibility_identifiers.py
python3 tools/ci/test_validate_schemas.py            # schema checker tests
python3 tools/ci/validate-schemas.py                 # real Draft 2020-12 validation
python3 tools/reproducibility/generate-sbom.py . build/SBOM.spdx.json
python3 tools/reproducibility/check-sbom.py build/SBOM.spdx.json
```

Then the Swift work: every package in `tools/ci/local-packages.txt`, the
accessibility audit, the simulator test target, the unsigned simulator build,
processed-bundle metadata, and simulator install/launch:

```text
export DERIVED_DATA="${TMPDIR:-/tmp}/rovia-derived-data"   # must be outside the checkout
xcodebuild -project client/app/ios/RoviaApp.xcodeproj -scheme RoviaApp \
  -configuration Debug -destination "platform=iOS Simulator,id=$SIMULATOR_ID" \
  -derivedDataPath "$DERIVED_DATA" test
xcodebuild -project client/app/ios/RoviaApp.xcodeproj -scheme RoviaApp \
  -configuration Debug -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$DERIVED_DATA" CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO build
./tools/ci/verify-bundle-metadata.sh "$DERIVED_DATA/Build/Products/Debug-iphonesimulator/Rovia.app"
./tools/ci/verify-simulator-install.sh "$DERIVED_DATA/Build/Products/Debug-iphonesimulator/Rovia.app"
```

`run-tool-tests.sh` picks up every `tools/**/test_*.py` file, including
`tools/ci/test_app_dependencies.py`, which is the gate on the iOS app's
dependency on the canonical domain packages. It reads the Xcode project and the
Swift sources rather than building anything, so it runs in the Python step; the
app builds that prove the dependency are the `xcodebuild` commands above.
`docs/development/ios.md` describes the package references and the two build
settings the dependency needs.

That gate is a mutation suite, not a list of names. It breaks one property at a
time on a temporary copy of the repository and requires the matching check to
fail: **50 mutations plus 7 legitimate shapes** — 12 package-dependency
mutations, 16 ways of writing a second route evaluator (including a computed
property, a closure, and a `contains { $0.matches(…) }`), 20 ways of giving a raw
trace somewhere to live through a store, a serialiser, or one of the nine leak
channels (`print`, `os_log`, `OSLog`, `Logger`, `logger`, `debugPrint`, `dump`,
`NSLog`, `sendProviderMessage`), and 2 contract deletions. The 7 legitimate
shapes are not part of that 47: they are the cases the check has to leave alone,
and adding one makes the gate no stricter. `test_app_dependencies.py` runs 27
tests and copies the
tree 69 times, because each test that needs a broken repository pays for one copy
and the mutation cases pay for one each. That figure is **measured**, not derived:
it comes from counting `Workspace` instantiations — one per copy — rather than counting `shutil.copytree` calls, which recurse: the same run makes 6486 `copytree` calls and 69 outermost ones, and quoting the unqualified number would be wrong by two orders of magnitude, and measuring it costs the 20–90 seconds across the runs recorded in this repository's verification record, which is a measurement on one x86_64 Mac and not a bound, so
`tools/ci/test_ci_counts.py` enforces only the bracket the mutation and test
counts imply — 54 copies at the low end, 81 at the high — and not the number
itself. A check with no mutation is an assertion
about today's source, so the count of mutations is the count of rules.
`test_ci_counts.py` reads the tables out of the gate module and requires each
group to be stated with its label attached, so a bare digit cannot satisfy it by
accident.

It also has to be honest about its limits, which `tools/ci/test_app_dependencies.py`
states in its own docstring: it reads declarations and bodies rather than Swift,
so an operator overload is invisible to it and a determined rewrite that avoids
every signal is invisible too.

Keep the derived data path outside the repository. With
`-derivedDataPath build/DerivedData` inside a checkout on the Desktop, the app
test target builds, installs, and then fails with "the test runner timed out
while preparing to run tests" before running a single test, because the XCTest
runner process is not granted access to the protected Desktop directory. The
same command with the path under `/tmp` runs all tests. CI uses
`${{ runner.temp }}`, which is outside the workspace for the same reason.

## The Python lint gate

`./tools/ci/check-repository-hygiene.sh` is the one gate that is not about code. It
reads the working tree and refuses a credential shape, a developer's home directory
under `/Users` or `/home`, a build artifact, a `.gitignore` that has stopped covering
a class of those, or a file over 4 MiB. It is what lets this repository claim it holds
nothing private, and it has to run after the commit that publishes it — a hygiene claim
checked once before the first commit is a claim about a moment. The gate excludes its
own source and its own test from the secret scan, because a scanner written as source
contains the shapes it searches for; the exclusion is two named paths and
`tools/ci/test_check_repository_hygiene.py` asserts that it is exactly those two.

`./tools/ci/check-python-lint.sh` runs `uvx pyflakes==3.2.0` over every
`tools/**/*.py`. The exact command is:

```text
uvx pyflakes==3.2.0 tools/ci/*.py tools/reproducibility/*.py
```

which the script does per file, and `run-tool-tests.sh` invokes after the test
files, so a finding fails the same command that runs the tests.

**Why the version is pinned, and why the script exists.** The verification record
claimed "pyflakes clean" as executed evidence without saying how pyflakes was
obtained. It is not installed for any system interpreter on the machine that record
was written on — `python3 -c "import pyflakes"` fails and it is absent from
`pip list` — so nobody reading the record could have reproduced the claim. An
unpinned `uvx pyflakes` does resolve and run, but it resolves to whatever is newest:
4.0.0 at the time of writing, while the record named 3.2.0. An unpinned invocation
is not a gate either, because a finding could appear or vanish with a release of the
linter rather than with a change to this repository.

The script also refuses to report success when it could not lint: if `uvx` is
missing, if the pinned version does not resolve, if `--version` does not report the
version that was asked for, or if there are no Python files to lint, it exits 1. A
gate that cannot run must not look like a gate that passed. `uvx` is used because it
resolves the pin into a cache without touching the system interpreter; the workflows
build a virtualenv for `check-jsonschema` for the same reason.

Five tests hold this: the gate exists, is executable, pins the version, and uses no
unpinned invocation; `run-tool-tests.sh` invokes it; it refuses a file with a
finding; it refuses an empty tree rather than reporting a clean lint of nothing;
and both documents name the command and the pinned version. The number is derived
from `tools/ci/test_ci_toolchain.py` rather than written here, and a test requires this
sentence to state what the module holds.

## Pull requests

`.github/workflows/ci.yml` runs on a pinned macOS runner label, with
`permissions: contents: read` and no secrets and no environment. It resolves an
iPhone simulator from `simctl` instead of hard-coding a device name, so it keeps
working as the runner's simulator set changes, and it fails if no iPhone
simulator is available.

Two of its steps assert facts rather than exit codes:

- `tools/ci/test_ci_workflows.py` fails if a third-party action is not pinned to a
  40-character commit, if the pull-request workflow ever references a secret or
  an environment, if `ROVIA_MARKETING_VERSION` drifts from the app's
  `CFBundleShortVersionString`, if the release workflow ever checks secrets
  after it starts building, or if a release workflow grows an upload step.
- `tools/ci/verify-bundle-metadata.sh` reads the bundle that was actually built
  and refuses an unexpanded build variable, a missing or non-numeric version, a
  missing `CFBundleExecutable` binary, or a missing Packet Tunnel extension.
  A successful `xcodebuild` is not evidence of a usable bundle.

`tools/ci/verify-simulator-install.sh` installs that bundle, launches it, checks
the process is alive, and terminates it. It is not evidence of a Packet Tunnel
Provider lifecycle or of anything on a physical device.

## The pre-commit gate

The pre-commit.ci app is installed on this repository, so a pull request gets a
second status alongside `swift-tests`. It reads `.pre-commit-config.yaml` from
the pull request itself, which is why every hook repository is pinned there for
the same reason every action in `.github/workflows` is pinned: an unpinned ref
would let a pull request decide what runs in CI.

The file exists because the app is installed. With no configuration the app does
not skip - it posts `error during ci config` and leaves a failing status on
every pull request, which is worse than no status, because a check that is always
red is a check people learn to ignore. Adding the file to silence that status
would be the wrong fix, so the hooks are real and they pass on this tree.

Ten hooks, and three of them are the hosted runner's own gates run earlier and on
the same code:

| Hook | What it is |
| --- | --- |
| `check-merge-conflict` | a conflict marker that survived a resolution |
| `check-case-conflict` | two paths differing only in case, which build on macOS and not on Linux |
| `check-yaml`, `check-json` | a workflow or manifest that does not parse never runs |
| `check-added-large-files` | build products, archives, derived data, over 2 MB |
| `detect-private-key` | key material, independently of the repository's own hygiene gate |
| `destroyed-symlinks` | a committed symlink replaced by a regular file |
| the three local hooks | `check-repository-hygiene.sh`, `check-python-warnings.sh`, `check-shell-syntax.sh` |

Two arguments in that file are load-bearing, and both were absent in the version
that was written first. They are asserted by `PreCommitConfigTests` in
`tools/ci/test_ci_toolchain.py`, because a hook that cannot fail is worse than a hook
that is absent - the configuration then reads as coverage:

- `check-merge-conflict` takes `--assume-in-merge`. Without it the hook reads the
  git directory, finds no `MERGE_HEAD`, and returns success without opening a
  file - so on `pre-commit run --all-files`, which is how pre-commit.ci invokes it,
  it never fires at all.
- `check-added-large-files` takes `--enforce-all`. Without it the hook intersects
  its input with `git diff --staged --diff-filter=A`, so it only sees files added
  in this one commit. A build product committed small and replaced by a later
  commit - the ordinary way one arrives - is never checked.

`check-python-lint.sh` is the fourth hosted gate and is deliberately not a
pre-commit hook, for an environment reason rather than a preference. That gate
resolves pyflakes only from a pinned route: it imports pyflakes from the current
interpreter, or fetches `pyflakes==3.2.0` through `uvx`. On a contributor's
machine both routes exist. In the pre-commit.ci container neither does, and the
gate runs and refuses:

```text
check-python-lint: no pyflakes available: python3 cannot import it
check-python-lint:   and uvx is not on PATH to fetch pyflakes==3.2.0
check-python-lint: refusing to report success from a linter that did not run
```

This is the same defect that failed the first hosted run - a hosted macOS runner
has no `uvx` either - and the same discipline that fixed it there is the reason
the hook is absent here. Both available fixes were rejected: declaring the hook
with pre-commit's own `language: python` and `additional_dependencies:
[pyflakes==3.2.0]` does work in that container, but it gives one claim two routes
and "pyflakes clean" stops having a single meaning; and skipping the gate when the
tool is absent is a gate that reports success without running. `ios-ci` builds a
virtualenv with `pyflakes==3.2.0` and puts it on PATH before calling the script, and
`run-tool-tests.sh` reaches the same script locally, so the lint gate still runs in
both of the places that can actually run it.

`trailing-whitespace` and `end-of-file-fixer` are deliberately absent. 92 tracked
files carry trailing whitespace, and cleaning it is a 92-file mechanical diff
that has nothing to do with a pre-commit configuration. `PreCommitConfigTests`
asserts they stay absent until that diff and this record are updated together.

What the hooks do *not* catch is recorded rather than assumed. Five of them were
verified by planting a defect - a conflict marker, malformed YAML, malformed
JSON, key material, an oversized file, and a machine path in the publishable set
- and confirming the run fails; `detect-private-key` and the repository's own
hygiene gate both caught the planted key, from different implementations.
`check-case-conflict` cannot be exercised on a case-insensitive filesystem, and
`destroyed-symlinks` cannot be exercised in a tree with no symlinks, so those two
are unverified here and are recorded as such.

## App model tests

The app model tests run in CI on a real simulator through the `RoviaAppTests`
target, which compiles the same model sources the app compiles as a host-less
logic test bundle. They gate model behavior rather than presentation: the suite
fails if a start request is ever reported as a connection without engine
confirmation, or if profile and server selection stop validating their inputs. A
green run is evidence about model behavior only. It is not evidence of a
working tunnel, an installed profile, or a Packet Tunnel Provider lifecycle.

## Schema validation

Schema validation uses the pinned `check-jsonschema==0.38.2` package through
`uvx`, or an installed copy of that exact version, and the Draft 2020-12
schemas in this repository:

```text
python3 tools/ci/validate-schemas.py
python3 tools/ci/test_validate_schemas.py
```

It checks the metaschema of `schemas/config.schema.json`,
`schemas/subscription.schema.json`, `schemas/control-api.schema.json`,
`schemas/control-response.schema.json`, and `schemas/engine-lock.schema.json`,
then validates positive fixtures, requires expected failures for negative
fixtures, and probes that the load-bearing constraints still bite:

- the config `required` list and the credential `oneOf` are removed in a
  temporary copy, and the checker must fail;
- the control API rejects extra fields and cross-role reason codes, and
  `status.get` must take an empty payload;
- the engine lock schema must refuse a lock that enables an engine without an
  approval, a full commit, a digest, or a non-empty architecture list, and
  deleting the conditional that enforces this must make the checker fail.

Two more rules are stated in more than one place, so the tests compare the
places rather than trusting any one of them:

- a secret reference key is a name, not data: printable ASCII without spaces
  (0x21-0x7E) and at most 512 characters. `schemas/config.schema.json` says it
  with `maxLength` and a pattern, `RoviaConfig.SecretReference.isValidKey` is the
  rule in code, the loader and the raw-JSON walk both apply it, and
  `RoviaSubscription` asks that one function instead of keeping a second copy of
  the limit. Six generated probes and four fixtures hold it in place.
- `RoviaConfig.RoutingDecisionTrace` holds the raw hostname, address, and port
  that were evaluated, so it is not `Codable` and nothing persists it. The
  redacted, serializable form is `RoviaRouting.RoutingDiagnostic`.

The engine-lock schema and `tools/ci/verify-engine-checksums.sh` are two
independent statements of the same rule. The schema says what a lock may
contain; the shell verifier adds that the artifact named by the lock exists and
its bytes match the recorded digest, which a schema cannot check.

## SBOM commands

The two SBOM tools take more arguments than the local-equivalent block above
uses, and every one of them is listed here. The command reference is checked
against the tools' own `--help` output by
`tools/reproducibility/test_generate_sbom.py`, so a flag cannot be added,
removed, or renamed without this section changing with it.

`tools/reproducibility/generate-sbom.py`:

| Argument | Meaning |
| --- | --- |
| `<root>` | repository root to read the Xcode inputs, the package list, and the default engine lock from |
| `<output>` | path to write; parent directories are created |
| `--lock PATH` | engine lock to read instead of `<root>/engines.lock.json` |
| `--namespace-id ID` | the run identifier in `documentNamespace`; a random UUID by default. It must be an ASCII token without slashes |
| `--created SECONDS\|RFC3339` | `creationInfo.created`, as seconds since the Unix epoch or an RFC 3339 UTC instant ending in `Z`. Overrides `SOURCE_DATE_EPOCH`. Without either, the current time is used, the tool says so on stderr, and the document is **not** byte-reproducible |
| `-h`, `--help` | print the usage summary |

It exits 0 after writing, 1 when the root does not exist or the file cannot be
written, and 2 for a namespace identifier that is not an ASCII token, a
`--created` that is neither an epoch count nor an RFC 3339 instant, or an unknown
option.

**What is reproducible, exactly.** Two fields in the document depend on the run:
`documentNamespace`, which carries `--namespace-id`, and `creationInfo.created`,
which carries `--created` or `SOURCE_DATE_EPOCH`. A document is byte-reproducible
only when **both** are fixed. Fixing the namespace alone leaves the timestamp
different between two runs, which is why the tool prints a note saying the
document is not reproducible when no timestamp was supplied — the earlier claim
that a fixed namespace made the document byte-reproducible was false, and the test
that appeared to check it overwrote `created` before comparing.

`tools/reproducibility/check-sbom.py`:

| Argument | Meaning |
| --- | --- |
| `<sbom>` | the document to check |
| `<repository-root>` | instead of a document, check every `*.spdx.json` and `SBOM*.json` under the root and apply the package-coverage check to each |
| `--repository PATH` | also require the document to cover every package in that tree's `tools/ci/local-packages.txt`; this is the flag the release gate uses |
| `-h`, `--help` | print the usage summary |

It exits 0 when the document is usable, 1 when it reports problems or when a
requested document cannot be read, and 2 for a usage error. `--repository` takes
the tree the gate lives in, not the root that
`tools/reproducibility/manifest.sh` uses to select the engine lock, so pointing
the gate at a fixture cannot quietly drop a package from the check.

## Engine verification modes

`tools/ci/verify-engine-checksums.sh` has two modes with opposite obligations:

| Mode | Empty lock | Present entry | Used by |
| --- | --- | --- | --- |
| `foundation` | accepted | must be complete: enabled, approved, full commit, matching artifact | CI, engine-repro |
| `release` | refused | must be exactly one approved Xray entry, verified | release |

Both modes refuse a missing lock file, unparsable JSON, an unsupported schema
version, a runtime policy that allows more than one Go runtime or a production
engine other than Xray, a disabled or unapproved candidate, a short commit, a
short digest, an empty architecture list, a missing artifact, and a checksum
mismatch. `--github-output PATH` writes `enabled=<bool>` and `engine=<name>` so
a workflow step can branch without an inline script.

## Release

The release workflow runs only for a version tag and uses the protected
`ios-production` environment. It stops at a verified artifact: there is no
upload step, and `tools/ci/test_ci_workflows.py` fails the build if one appears.
That check reads the workflow's steps and inspects each step's `uses:` and its
whole step text — the name, the keys, and the comments, not only the `run:`
body — for a publishing action, so it forbids `actions/upload-artifact`,
`actions/upload-release-asset`, `gh release`, `gh api`, `notarytool`, `altool`,
`fastlane`, `pilot`, `deliver`, and `transporter`. The scan is fail-closed
inside a step: a step may not name a publishing tool even in a comment, and the
cost of that is a step that has to be reworded rather than an upload that slips
through. Content outside a step is not inspected, which is why the words are
listed once in `tools/ci/script_test_support.py` instead of being searched for
in this document.

Its order is part of the guarantee, and
`tools/ci/test_ci_workflows.py` fails if this list stops matching the workflow:

1. `Checkout`
2. `Install pinned Python tooling` — the release job runs the same schema
   checker as CI, so it installs the same pinned `check-jsonschema` version
   first rather than resolving one at test time
3. `Verify release tag` — `tools/release/verify-tag.sh`, using the shared
   grammar in `tools/release/tag-grammar.sh` that the manifest and the release
   gate also use
4. `Require every release secret` — before any build work, so a run cannot fail
   after it has already archived something
5. `Require a resolved signing identity` —
   `tools/release/verify-export-options.sh` refuses the `$(ROVIA_TEAM_ID)`
   placeholder in `tools/release/ExportOptions.plist`, before a keychain exists
   or anything is built. It refuses today: no Apple Developer team is configured
   for this repository, and none was invented. `tools/ci/verify-release-inputs.sh`
   performs the same check as its first action, before it reports that any
   signing input is present, so the gate cannot announce readiness while the
   signing identity is unresolved
6. `Verify repository inputs` — shell syntax, lockfiles, third-party notices
7. `Run tool and schema tests` — the tool tests, the accessibility audit and its
   self-test, and the schema checker and its tests
8. `Run foundation tests` — every package in `tools/ci/local-packages.txt`
9. `Generate and check the SBOM`
10. `Create temporary keychain`
11. `Import distribution certificate`
12. `Install provisioning profiles` — the decoded profiles are checked for
    emptiness and parsed with `security cms` before the archive, and removed
    again by the cleanup step
13. `Archive`
14. `Export IPA`
15. `Produce checksums and provenance manifest` — `SHA256SUMS` plus
    `manifest.sh`, recording the runner identity from `ROVIA_RUNNER_IDENTITY`
16. `Verify every release input` — `tools/ci/verify-release-inputs.sh` refuses a
    missing secret, a malformed tag, a tag whose version differs from the
    artifact's `CFBundleShortVersionString`, a missing or non-IPA artifact, a
    checksum mismatch, an SBOM that is not SPDX 2.3 or that does not cover every
    package in `tools/ci/local-packages.txt`, and a manifest that records no
    runner or whose tag, commit, artifact hash, SBOM hash, or engine-lock hash
    disagrees with the files on disk

    The order those refusals happen in is the order the gate runs, and it is not
    the order they are easiest to describe. `tools/ci/verify-release-inputs.sh`
    checks, in sequence: the **signing identity** (an export options plist that
    still holds `$(ROVIA_TEAM_ID)`), the **signing secrets**, the **tag grammar**,
    the **existence and non-emptiness** of the four input files,
    then the **engine lock** — refused unless it is exactly one approved
    Xray entry, before the artifact is opened — and only then the **artifact**,
    the **checksums**, the **SBOM**, and the **provenance manifest**. The engine
    lock has never been the last check, though it was documented as one until
    `tools/ci/test_ci_docs.py` began deriving this order from the script body
    and requiring both this document and `CHANGELOG.md` to state it.
17. `Cleanup signing material` — `always()`, removes the certificate, the
    profiles, and the keychain

`tools/ci/verify-release-inputs.sh` has 99 tests, including one per refusal, and
builds its fixture with the repository's own SBOM generator, SBOM checker, and
manifest generator inside a throwaway git repository. Its fixture writes an
`ExportOptions.plist` holding a literal team ID, because a repository that has a
team configured is the case where the rest of the gate applies; a separate test
requires this repository's own plist, with its `$(ROVIA_TEAM_ID)` placeholder, to
be refused. Secret values are never printed; only secret names are.

## Tags

Three gates must agree on the tag, so they share one grammar in
`tools/release/tag-grammar.sh`: `tools/release/verify-tag.sh`,
`tools/reproducibility/manifest.sh`, and `tools/ci/verify-release-inputs.sh`.
It is the release subset of semantic versioning — `vMAJOR.MINOR.PATCH`, an
optional prerelease, optional build metadata, and no leading zeros in the
numbers or in a numeric prerelease identifier. `v1.2.3-01` and `v1.2.3.4` are
refused, `v1.2.3-0.3.7` and `v1.2.3-rc.1+build.5` are accepted. A gate that
accepted a different set of tags would let a run archive and then refuse its own
tag.

## Before production use

- Replace placeholder team handles in `CODEOWNERS`.
- Register App IDs, App Group, and capabilities.
- Store signing secrets only in the protected environment.
- Pin every third-party action to a reviewed full commit SHA.
- Configure a release branch protection policy and required reviewers.
- Review `PRIVACY.md` and complete the App Store privacy label.

## External gates that are not executed here

The gates above are evidence about this repository. They are not evidence about
anything outside it. The following remain open, and no local run closes them. The
same list is held as a dated, in-repository disclosure in
`docs/development/release-readiness.md`, which is where a reviewer should look
rather than at this summary.

- **Hosted CI has run, and is no longer an external gate.** `.github/workflows/ci.yml`
  completed on the real runners at commit `13981d5`:
  <https://github.com/princeofscale/rovia/actions/runs/36344718641>. The first five
  runs failed on four real defects this repository could not see locally — a context
  GitHub does not provide in a workflow-level `env:`, a shell variable it does not
  expand there, a dependency on `uvx` that a hosted runner does not have, and two
  tests that read files the repository does not publish. `docs/development/release-readiness.md`
  lists what a run found and what is still open.
  The remaining external gates are:
- **The pre-commit gate runs, and is not an external gate.** `.pre-commit-config.yaml`
  is a real configuration whose eleven hooks pass on this tree, and the arguments that
  make two of them functional instead of inert are asserted by `PreCommitConfigTests`.
  What the gate does not cover - a case-only path conflict, and a committed symlink
  replaced by a regular file - is recorded above as unverified rather than assumed.
- **Signing, provisioning, archive, and export.** No certificate import,
  `xcodebuild archive`, `-exportArchive`, TestFlight, or App Store submission has
  been performed, so the release gate's happy path is only exercised against a
  synthetic IPA in a throwaway repository.
- **Publishing.** No upload step exists, and the policy test keeps it that way.
- **A physical-device VPN.** Profile installation, the Packet Tunnel Provider
  lifecycle, IPv4/IPv6/dual-stack, and reconnect are unverified.
- **A production engine.** The engine lock enables none, and
  `tools/build-engine/xray/build-apple.sh` refuses even with an approved lock
  because the deterministic build recipe does not exist yet.
- **Branch protection, required reviews, and the `ios-production` environment
  approvals.** The `CODEOWNERS` handles are placeholders.
- **Upstream SPDX tooling.** `check-sbom.py` checks this repository's
  invariants; it is not a third-party SPDX validator.
- **Third-party advisories, dependency review, and secret scanning.** None is
  configured. There is nothing external to scan today, and nothing that would
  catch a dependency added tomorrow.
- **Android.** Not started. No path in this repository is Android code, and no
  claim is made about any other platform.

## Security references

- https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions
