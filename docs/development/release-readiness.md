# Release readiness: what has not been verified

Date: 2026-09-26
Repository state: the first public commit of `main`; no release and no tag exist
Scope: the gates this repository can run on one machine, and the gates it cannot

This document exists because the list of things that have *not* been checked is
itself evidence, and until now it lived only in a planning ledger outside the
repository. A disclosure that is not in the repository is not disclosure: nobody
reviewing a pull request, and nobody reading a release, sees it.

Everything below is unexecuted. Nothing in this repository is evidence about any
of it, and the local gates that *are* green are listed in
`docs/development/foundation-verification.md`, which says the same thing about
its own scope in its first paragraph.

## The rule this document follows

A gate is either executed with a recorded result, or listed here. There is no
third state, and in particular a gate is never described as passing because it
looks like it would, because the workflow that would run it parses, or because a
gate above it refused for an unrelated reason.

Each row names a path in this repository that would have to change for the gate
to be executed, or says in as many words that there is no such path. Where a row
names a step number in `.github/workflows/release-ios.yml`, that number is checked
against the workflow by `tools/ci/test_ci_checks.py`, because a step number in
prose is exactly the kind of detail that goes stale when a step is inserted. Row 10 is
the only one of those, and it is the honest case: Android work has not started,
so there is no file here that would have to change.
`tools/ci/test_ci_checks.py` checks that every path named in the table exists,
that the table carries this date, that the gate numbering is contiguous, and that
the set of gates is exactly the set the source-derived check expects, so the list
cannot quietly lose a row or gain one that names nothing.

## Not verified, and not executed here

| # | Gate | Why it is open | What would close it |
| --- | --- | --- | --- |
| 1 | **GitHub Actions execution** | The three workflows in `.github/workflows/` are written, YAML-parsed, and their step order and permissions asserted by tests, but no run has ever occurred. Runner-specific behaviour — `$RUNNER_TEMP`, `GITHUB_OUTPUT`, `GITHUB_ENV`, the `macos-15` image contents, and `check-jsonschema` being resolvable through `uvx` — is unverified. | A run on the real runners, with the artifacts it produces retained. |
| 2 | **Signing, provisioning, and the Apple team identity** | No certificate has been imported, no provisioning profile installed, and no keychain created. `tools/release/ExportOptions.plist` holds `$(ROVIA_TEAM_ID)`, an unresolved reference, and `tools/release/verify-export-options.sh` refuses it; `tools/ci/verify-release-inputs.sh` runs that refusal before it reports on any other input. No Apple Developer team is configured for this repository and none was invented. | A real team, written into the plist as a literal ten-character identifier, plus a certificate and two profiles. |
| 3 | **Archive and export** | `xcodebuild archive` and `-exportArchive` have never been run. The release gate's happy path is exercised only against a synthetic IPA in a throwaway repository (`tools/ci/test_verify_release_inputs.py`), which is a test of the checker, not of Apple's tooling. | Steps 13 and 14 of `.github/workflows/release-ios.yml` running to completion, which cannot happen before step 2. |
| 4 | **Upload, TestFlight, and App Store submission** | No upload step exists in any workflow, and `tools/ci/test_ci_checks.py` fails if one appears. Nothing has been submitted anywhere, and no submission is planned by this slice. | A deliberate decision to add an upload step, with credentials and an App Store Connect record. |
| 5 | **Physical-device VPN behaviour** | Profile installation, the Packet Tunnel Provider lifecycle, IPv4, IPv6, dual-stack, failover, and reconnect are all unverified. A simulator process staying alive says nothing about any of them, and the simulator runs in `tools/ci/verify-simulator-install.sh` are launch checks only. | A signed build on a device, with tunnel traffic observed. Blocked by step 2. |
| 6 | **A production engine** | `engines.lock.json` enables no engine and approves none. `tools/build-engine/xray/build-apple.sh` refuses even with an approved lock, because the deterministic build recipe does not exist, and `tools/reproducibility/verify-xray.sh` refuses because no approved artifact exists. No engine has been built, hashed, or compared. | A reproducible engine build: a pinned commit, a verified upstream digest, a 64-character artifact hash matching bytes on disk, and a second build producing the same digest. |
| 7 | **Environment approvals and branch protection** | The `ios-production` environment, its reviewers, and branch protection are unconfigured. Every handle in `CODEOWNERS` is a placeholder for a team that does not exist, so **no review is currently required on any path, including the security-sensitive ones**. The ownership lists in `CODEOWNERS` and `SECURITY.md` are now checked against each other and against the tree, but that checks the lists agree, not that anyone is reviewing. | Real GitHub teams, then branch protection requiring their review on the paths `SECURITY.md` lists. |
| 8 | **Third-party advisories, dependency review, and secret scanning** | None is configured in this repository. The local packages have no external dependencies (`tools/ci/verify-lockfiles.sh` reports 7 local path dependencies and 0 locked externals), so there is nothing to scan today, and nothing would catch a dependency added tomorrow. | GitHub dependency review and secret scanning, or an equivalent pinned scanner. |
| 9 | **Upstream SPDX tooling** | `tools/reproducibility/check-sbom.py` checks this repository's own documented invariants. It is not a third-party SPDX validator, and no `spdx-tools` run has occurred. The `documentNamespace` host is a deliberate `.invalid` placeholder that will not resolve. | A run of a conformant SPDX validator against the generated document. |
| 10 | **Android** | Not started. No path in this repository is Android code, so this row names no file: there is nothing here that would have to change, and claiming a path would be a fiction. No claim is made about any other platform. | A separate slice. |

## What is deliberately not claimed

- A green local suite is evidence about this repository on one x86_64 Mac. It is
  not evidence about a tunnel, a device, a signed artifact, a production engine,
  or a hosted runner.
- The refusal of a gate is a result, not a gap. `tools/ci/verify-release-inputs.sh`
  refusing on row 2 is the gate working: it refuses because the repository has no
  team, and it refuses before it says anything about readiness.
- A simulator process staying alive is a launch check. It is not a VPN.
- The `CODEOWNERS` handles are placeholders and the review identity behind every
  one of them is unresolved. This is row 7, not a control.

## Related documents

- `docs/development/foundation-verification.md` — the dated record of what *was*
  executed on this machine, with exact counts and the same statement of scope.
- `docs/development/ci.md` — the gate order and the local equivalents of the
  hosted gates.
- `SECURITY.md` — the fail-closed release policy and the security-sensitive paths,
  with the criterion for that list and the unresolved review identity.
