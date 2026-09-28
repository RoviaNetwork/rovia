# Release readiness: what has not been verified

Date: 2026-09-26
Repository state: the first public commit of `main`; no release and no tag exist
Scope: the gates this repository can run on one machine, and the gates it cannot

This document exists because the list of things that have *not* been checked is
itself evidence, and until now it lived only in a planning ledger outside the
repository. A disclosure that is not in the repository is not disclosure: nobody
reviewing a pull request, and nobody reading a release, sees it.

Everything below is unexecuted, with one exception noted in its row: the hosted
CI gate has now run, and its result is recorded with the run that produced it.
Nothing in this repository is evidence about any other row, and the local gates
that *are* green are listed in
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
## Closed

A gate leaves this list by being executed, with a result someone else can read.
One has.

| Gate | Closed | Evidence |
| --- | --- | --- |
| **Hosted CI execution** | 2026-09-27 | `.github/workflows/ci.yml` ran to
  completion on the real runners at commit `13981d5`:
  <https://github.com/princeofscale/rovia/actions/runs/36344718641> — nineteen
  steps, all green, 824 s. |

**What that run found was four real defects in this repository**, each of the kind
no local check can see, and the first five runs failed in this order:

1. A workflow-level `env:` named `${{ runner.temp }}`. GitHub does not provide the
   `runner` context there, so it rejected the file outright — a 0-second run with
   no job created. Moving it to a job-level `env:` failed identically, because
   `runner` is only available in a step's `env:` and inside a `run`.
2. The same variable written as `$RUNNER_TEMP`. GitHub interpolates `${{ }}` and
   nothing else, so it reached the step as literal text and `xcodebuild` resolved
   it against the working directory: `/Users/runner/work/rovia/rovia/Users/runner/
   work/_temp/…`. It is now computed in a shell and exported through `$GITHUB_ENV`.
3. The lint gate, and a test that shells out to the same linter, both required
   `uvx` — which a GitHub-hosted macOS runner does not have. Both now resolve
   through the interpreter when `pyflakes` is importable.
4. Two tests read files this repository deliberately does not publish. They passed
   on the machine that wrote them and failed on a fresh clone, which is what every
   contributor and every runner would have seen.

The other two workflows remain unrun by design: `engine-repro` fires on engine
paths no commit has touched, and `ios-release` on a `v*` tag, and no tag exists.
No release has been made and none is planned until the rows below close.


| # | Gate | Why it is open | What would close it |
| --- | --- | --- | --- |

      What the run found was four real defects in this repository, not runner
      peculiarities, and each is the kind no local check can see: a workflow-level
      `env:` naming a context GitHub does not provide there, which rejects the file
      and creates no job; the same variable written as a shell reference, which
      GitHub does not expand at all, so `xcodebuild` resolved it against the working
      directory and produced a path with the checkout glued to the runner's temp
      directory; a lint gate and a test that both required `uvx`, which a hosted
      macOS runner does not have; and two tests that read files the repository
      deliberately does not publish, so they passed on the machine that wrote them
      and failed on a fresh clone. The first five runs failed, for those reasons,
      in that order.

      The other two workflows remain unrun by design: `engine-repro` fires on
      engine paths no commit has touched, and `ios-release` on a `v*` tag, and no
      tag exists. | Nothing further. Every later commit produces another run, which
      is the point of having it. |
| 1 | **Signing, provisioning, and the Apple team identity** | No certificate has been imported, no provisioning profile installed, and no keychain created. `tools/release/ExportOptions.plist` holds `$(ROVIA_TEAM_ID)`, an unresolved reference, and `tools/release/verify-export-options.sh` refuses it; `tools/ci/verify-release-inputs.sh` runs that refusal before it reports on any other input. No Apple Developer team is configured for this repository and none was invented. | A real team, written into the plist as a literal ten-character identifier, plus a certificate and two profiles. |
| 2 | **Archive and export** | `xcodebuild archive` and `-exportArchive` have never been run. The release gate's happy path is exercised only against a synthetic IPA in a throwaway repository (`tools/ci/test_verify_release_inputs.py`), which is a test of the checker, not of Apple's tooling. | Steps 13 and 14 of `.github/workflows/release-ios.yml` running to completion, which cannot happen before step 2. |
| 3 | **Upload, TestFlight, and App Store submission** | No upload step exists in any workflow, and `tools/ci/test_ci_checks.py` fails if one appears. Nothing has been submitted anywhere, and no submission is planned by this slice. | A deliberate decision to add an upload step, with credentials and an App Store Connect record. |
| 4 | **Physical-device VPN behaviour** | Profile installation, the Packet Tunnel Provider lifecycle, IPv4, IPv6, dual-stack, failover, and reconnect are all unverified. A simulator process staying alive says nothing about any of them, and the simulator runs in `tools/ci/verify-simulator-install.sh` are launch checks only. | A signed build on a device, with tunnel traffic observed. Blocked by step 2. |
| 5 | **A production engine** | `engines.lock.json` enables no engine and approves none. `tools/build-engine/xray/build-apple.sh` refuses even with an approved lock, because the deterministic build recipe does not exist, and `tools/reproducibility/verify-xray.sh` refuses because no approved artifact exists. No engine has been built, hashed, or compared. | A reproducible engine build: a pinned commit, a verified upstream digest, a 64-character artifact hash matching bytes on disk, and a second build producing the same digest. |
| 6 | **Environment approvals and branch protection** | The `ios-production` environment, its reviewers, and branch protection are unconfigured. Every handle in `CODEOWNERS` is a placeholder for a team that does not exist, so **no review is currently required on any path, including the security-sensitive ones**. The ownership lists in `CODEOWNERS` and `SECURITY.md` are now checked against each other and against the tree, but that checks the lists agree, not that anyone is reviewing. | Real GitHub teams, then branch protection requiring their review on the paths `SECURITY.md` lists. |
| 7 | **Third-party advisories, dependency review, and secret scanning** | None is configured in this repository. The local packages have no external dependencies (`tools/ci/verify-lockfiles.sh` reports 7 local path dependencies and 0 locked externals), so there is nothing to scan today, and nothing would catch a dependency added tomorrow. | GitHub dependency review and secret scanning, or an equivalent pinned scanner. |
| 8 | **Upstream SPDX tooling** | `tools/reproducibility/check-sbom.py` checks this repository's own documented invariants. It is not a third-party SPDX validator, and no `spdx-tools` run has occurred. The `documentNamespace` host is a deliberate `.invalid` placeholder that will not resolve. | A run of a conformant SPDX validator against the generated document. |
| 9 | **Android** | Not started. No path in this repository is Android code, so this row names no file: there is nothing here that would have to change, and claiming a path would be a fiction. No claim is made about any other platform. | A separate slice. |

## What is deliberately not claimed

- A green local suite is evidence about this repository on one x86_64 Mac. It is
  not evidence about a tunnel, a device, a signed artifact, or a production
  engine. It was not evidence about a hosted runner either, and the first five
  hosted runs said so plainly: every one failed on something no local check could
  see. A green run is now evidence about the hosted runner, for the commit it ran
  on, and about nothing else in this list.
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
