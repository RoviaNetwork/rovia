# Governance

Rovia is maintained by one person, has no releases, and has a narrow governance
surface on purpose. This document says who decides what, and — more usefully for a
reader deciding whether to trust it — says where a single maintainer is a bottleneck.

## Who decides

`@princeofscale` is the sole maintainer and the only account with write access. There
is no organisation behind this repository and no team structure, so there is no
consensus process to describe and no second opinion available inside the project.

That is a real constraint, not a formality. The two consequences worth naming:

- **No review is enforced.** `CODEOWNERS` names a real account, but no ruleset requires
  a review, and a review by the only possible reviewer would be a self-review. So
  "requires maintainer review" in `SECURITY.md` and in this file is a statement of
  intent. It is tracked as open gate 7 in
  [`docs/development/release-readiness.md`](docs/development/release-readiness.md).
- **One person's judgement is the whole process.** An ADR records a decision and its
  reasoning, and there is no second reader who has to agree before it is merged.

What partially offsets this: the decisions are written down before they are
implemented, the gates are executable rather than reviewed, and every claim the
project makes about itself is derived from a test that can fail. A reviewer does not
have to trust the prose; they can run it.

## Decision model

- Routine implementation changes use normal pull requests.
- Architectural changes use an ADR or RFC **before** implementation, not after.
- Security-sensitive changes require review from the relevant CODEOWNERS — which, see
  above, means an intent rather than an enforced requirement today.
- Engine updates require a human-reviewed lockfile pull request. No engine update is
  possible mechanically: the lock refuses an entry without a full commit SHA, a
  64-character artifact digest, and matching bytes on disk.
- Licensing or App Store distribution changes require explicit maintainer approval and
  documented legal review. Nothing in this repository constitutes legal advice.

## Becoming more than one maintainer

This is the project's most important open question, and it is not a documentation
detail — it decides whether a security claim in this repository is worth anything.

The concrete requirement: **a second maintainer with write access who is not the
author of the change.** A self-review satisfies a ruleset without adding a pair of eyes,
which is why the ruleset is not enabled today rather than enabled and quietly
satisfied.

Two things that have to happen first, and neither is a technical task:

1. A decision about hosting. A GitHub organisation is what makes per-role teams and a
   second reviewer possible, because teams only exist inside an organisation. The
   repository is currently under a personal account, so `CODEOWNERS` cannot name a
   team at all.
2. A named security contact that is not a personal address, so a researcher has
   somewhere to report that does not depend on one person's inbox.

Until both exist, the honest description of this project is: one maintainer, no
enforced review, and gates that are strong enough that an external reviewer can verify
the claims independently.

## Transparency

ADRs, the threat model, third-party notices, release provenance, the dated
verification record, and meaningful governance changes are kept in the repository.
Private security reports stay private until a coordinated disclosure decision is made.

What is **not** claimed: that this is a mature project, that it has been reviewed by
anyone outside the maintainer, or that the nine external gates in the readiness document
have been closed. The Status section of the README is the authoritative summary.

## Community expectations

Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). The project
does not accept telemetry, advertising, or covert user-activity collection through
ordinary feature requests, and it does not accept them through sponsorship either.
