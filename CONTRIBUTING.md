# Contributing to Rovia

Thank you for looking at this. Rovia is pre-alpha, its architectural boundaries are
deliberate, and a change that respects them is worth more here than a large one that
crosses them.

## Before you write code

- **Check [`docs/architecture/next-spikes.md`](docs/architecture/next-spikes.md) first.**
  A fair amount of the obvious work is already scoped there, with the decision it has
  to settle written down.
- **Open an issue or start a discussion** before a substantial change. That is not gatekeeping;
  the boundaries in `docs/adr/` mean most real changes also need an ADR, and finding
  that out in a review is slower than finding it out in a discussion.
- **A new boundary needs an ADR.** Changes to canonical configuration, routing
  semantics, the engine interface, the control API, secret storage, engine integration,
  licensing, or the shared-core strategy are decisions, not diffs. Put the decision in
  `docs/adr/` with its context and its consequences.

## Ground rules

These are the invariants the gates enforce. If a change breaks one, the gate fails —
that is deliberate, and the fix is to change the design or to change the gate
deliberately, with the reason in the same commit.

- **The core stays pure.** Packages under `core/` must not import SwiftUI, UIKit,
  AppKit, NetworkExtension, or any engine library. It is the property that makes the
  core testable without a simulator and reusable from another platform.
- **Engine-native configuration stays inside the adapter.** An engine's own JSON
  dialect must never reach the canonical model, a routing diagnostic, or the UI.
  `tools/ci/test_app_dependencies.py` fails the build if one does.
- **Raw routing traces are not persisted.** `RoutingDecisionTrace` and `RuleEvaluation`
  are deliberately not `Codable`. Nine separate leak channels are checked for, and a
  tenth is added only with a test that proves the new one fires.
- **No real credentials, ever.** No subscription URLs, passwords, UUIDs, private keys,
  provider tokens, or Apple team IDs. Use sanitised fixtures and synthetic identifiers.
  Every host in `fixtures/` is `synthetic.example`. `tools/ci/check-repository-hygiene.sh`
  fails a tree that would publish something that looks like a credential.
- **Public APIs only on Apple platforms.** `NEPacketTunnelProvider` and
  `NEPacketTunnelFlow.packetFlow`. No raw `utun` file descriptor, no private API.
- **A gate that cannot be satisfied is a stop, not a warning.** Do not add a bypass, a
  default, or a fallback to make a pipeline proceed. If a gate is wrong, fix the gate
  and say why in the commit.

## Tests

A new behaviour needs a test that **fails without your change**. This repository holds
its own documentation to that standard: a rule with no mutation that must fail is not a
gate, it is an assertion about today's source. If you cannot name the failure, that is
useful information — say so in the pull request rather than shipping a test that only
documents the present.

Run before you push:

```bash
./tools/ci/run-tool-tests.sh                    # every tool test, then three gates
for p in $(grep -v '^#' tools/ci/local-packages.txt); do swift test --package-path "$p"; done
python3 tools/ci/validate-schemas.py
```

If your change touches the app or the extension, also run the app tests. Derived data
has to live outside the checkout or the XCTest runner times out before it runs
anything — see [`docs/development/ios.md`](docs/development/ios.md).

## Pull requests

Keep them focused. A pull request that mixes a refactor with a behaviour change makes
the change hard to review, which is the only reason anyone reads it.

- Focused code, tests, and the documentation that describes the behaviour, in the same
  commit. A claim that outlives the code it describes is a defect.
- No unrelated formatting. If a formatter disagrees with you, do it in its own commit.
- Fill in the security and privacy impact section when the pull request touches
  parsers, secrets, routing, tunnels, signing, or CI. "This cannot affect any of them"
  is a valid answer; leaving it blank is not.
- **A pull request is required, and no review is enforced.** An active ruleset on
  `main` requires a pull request, forbids deletion and force-push, permits only a
  squash merge, and requires the `swift-tests` status check to pass, so open a pull
  request rather than pushing to `main` and expect CI to have run before it can land.
  A review is not required, and not enforced: the only account with write access is
  the maintainer, and GitHub does not count the author's own approval, so a review
  requirement here would make the repository unmergeable rather than safer.
  `CODEOWNERS` therefore enforces nothing yet. What is missing is an independent
  approver, not a resolvable handle. Both are tracked as an open gate in
  [`docs/development/release-readiness.md`](docs/development/release-readiness.md).


## Before you commit

`pre-commit` is configured in `.pre-commit-config.yaml`, and pre-commit.ci runs the
same configuration on every pull request. Ten hooks, of which three are the same
gates the hosted runner executes — the publishable-tree hygiene check, the
warnings-are-errors compile, and the shell syntax check — so the defects they catch
are found before a runner is spent on them. The pinned pyflakes gate is the fourth
hosted gate and is not among them: it resolves pyflakes from the current interpreter
or through `uvx`, and the pre-commit.ci container has neither, so it would run and
refuse rather than pass quietly. Run `./tools/ci/run-tool-tests.sh` for the pyflakes
gate, or let `ios-ci` run it.

```text
pre-commit run --all-files
```

Two hooks are left out on purpose, and the reason is in the file: 92 tracked files
carry trailing whitespace, and cleaning it is a separate mechanical change rather
than part of wiring up a gate. Two of the arguments in the file are load-bearing —
`--assume-in-merge` on `check-merge-conflict` and `--enforce-all` on
`check-added-large-files` — and `tools/ci/test_ci_checks.py` fails if either is
removed, because a hook that silently cannot fire is worse than no hook at all.

Details, including what the hooks do not catch, are in
[`docs/development/ci.md`](docs/development/ci.md#the-pre-commit-gate).

## Reporting a vulnerability

Not through a public issue and not through a pull request. See
[`SECURITY.md`](SECURITY.md).

## Privacy

New telemetry, analytics, advertising, or user-activity collection is not accepted
through ordinary feature requests. It would require a public governance decision, and
the default assumption is that it does not belong in Rovia. The reasoning is in
[`PRIVACY.md`](PRIVACY.md), and `docs/security/threat-model.md` records which
verification controls are not implemented — adding a control is welcome; claiming one
that does not exist is not.

## Dependencies

Do not add a source or binary dependency without recording its upstream project, exact
version or commit, licence, source location, build procedure, and redistribution
obligations in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Rovia currently has
**no** external package dependencies; the first one added has to justify itself against
that.

There is no `Package.resolved` to update and no lockfile to regenerate for the Swift
packages, because all seven are local path dependencies. A remote dependency changes
that, and `tools/ci/verify-lockfiles.sh` starts enforcing pinned revisions the moment
one appears.
