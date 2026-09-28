# Security Policy

Rovia is a network client. Treat vulnerabilities in credential handling, routing isolation, tunnel lifecycle, engine updates, subscription parsing, local communication, and release signing as security-sensitive.

## Reporting a vulnerability

**Do not open a public issue, and do not open a pull request.**

Use **GitHub private vulnerability reporting** on this repository: the *Security* tab,
then *Report a vulnerability*. That opens an advisory visible only to the maintainer,
and it is the channel a researcher should use.

If private reporting is unavailable to you, open a public issue that says only *"a
security report is waiting for a private channel"* — no detail — and the maintainer will
open the advisory and tell you where to send it. Never post credentials, exploit
details, a real provider URL, or a real user configuration in public.

A note on what this costs a reporter: the project has one maintainer and no named
security contact, so acknowledgement depends on one person reading a notification. That
is a limitation of the project's size and it is recorded in `GOVERNANCE.md`; it is not
a reason to delay a report.

Include the minimum information needed to reproduce the issue, affected version or commit, impact, and whether a real provider URL or credential was involved. Redact all secrets before sharing diagnostic material, and describe the shape of any value that leaked rather than the value itself.

A privacy leak, a redaction failure, or an unexpected outbound request is a security report. See `PRIVACY.md` for what Rovia claims to handle and where those claims end.

## Security-sensitive changes

Changes under these areas require maintainer review:

- `platform/apple/`
- `engines/`
- `core/config/`
- `core/subscription/`
- `core/routing/`
- `client/app/ios/`
- `client/app/ios/RoviaTunnel/`
- `tools/ci/`
- `tools/reproducibility/`
- `tools/release/`
- `tools/build-engine/`
- `.github/workflows/`
- `engines.lock.json`
- `schemas/`
- `SECURITY.md`
- `THIRD_PARTY_NOTICES.md`
- `docs/security/`
- `docs/legal/`
- subscription parsers
- Keychain and App Group access
- routing and failover behavior
- `PRIVACY.md`

### The criterion for this list

A path is security-sensitive when a change to it can change what the product does
with a credential, a destination, a packet, or a signed artifact. That is a
property of the code, not of its name, and it is what decides membership:

- `core/config/` is on the list because it holds `SecretReference`, the
  `ConfigValidation` rules that bound a secret key, and the raw
  `RoutingDecisionTrace` — the three types a reviewer has to be able to trust.
  Its absence from this list was a defect, not a judgement: the most
  credential-adjacent code in the repository was the one path with no owner.
- `core/persistence/` was on the list and does not exist. Listing a path that is
  not in the tree is worse than omitting one, because it reads as coverage. Every
  path here is checked for existence by `tools/ci/test_ci_checks.py`, so a
  directory that is removed cannot leave its entry behind.
- `client/app/ios/` covers the host application, and `client/app/ios/RoviaTunnel/`
  is listed separately because the Packet Tunnel extension is the half that holds
  the network settings, the provider-message handler, and the control contract.
  A change to either can change what leaves the device.
- `tools/build-engine/` decides which engine binary is produced, and
  `tools/release/` decides what is signed and exported, so both can change what a
  signed artifact contains. They are engine- and release-sensitive rather than
  CI-sensitive; with a single owner there are no per-role handles left to
  distinguish them in `CODEOWNERS`, so this list is the only place the distinction
  is written down.
- `SECURITY.md`, `THIRD_PARTY_NOTICES.md`, `docs/security/`, and `docs/legal/` are
  on the list because a change to any of them changes what the project claims
  about credential handling, about the licensing of what it ships, or about the
  terms it is offered under. They change no behaviour, so they are the weakest
  entries here, and they are listed because a policy document nobody reviews is
  how a policy stops being true.
- `fixtures/` and `docs/` are deliberately not on this list. They are owned in
  `CODEOWNERS` so they are not unattended, but a fixture or a document does not
  change what the product does with a credential. `fixtures/` is covered instead
  by the schema gates, which refuse a fixture that stops being negative.

Every path in the list exists, and every path in the list is owned in
`CODEOWNERS`; `tools/ci/test_ci_checks.py` checks that both documents name the
same paths and that every path either one names is in the tree, so a
security-sensitive path with no owner and a listed directory that does not exist
are both failures.

### This list does not enforce a review

An active ruleset on `main` requires a pull request, forbids deletion and
force-push, and permits only a squash merge. **It does not require a review, and
that is a decision rather than an oversight.** The only account with write access
is the repository owner, and GitHub does not count the author's own approval, so a
one-review rule would make the repository unmergeable. `require_code_owner_review`
is off for the same reason: every handle in `CODEOWNERS` is a placeholder for a
team that does not exist, and requiring one would block every pull request.

So "requires maintainer review" above is a statement of intent that **nothing
currently enforces**. The protection that does exist is structural — a change to
`main` cannot arrive as a force-push or as a direct push — and the honest reading of
the sentence is that this project would benefit from a second pair of eyes and has
none. That is listed as an open external gate in
`docs/development/release-readiness.md` rather than described as a control.

The earlier version of this file named per-role handles under an organisation
that did not exist. That is worse than one real handle, not better: a team handle
that resolves to nothing reads as a review requirement and enforces none, which
is the same false signal as a badge. The role distinction survives in the criterion
above.

## Fail-closed release policy

A release may only be produced from inputs that are complete and mutually consistent. The repository enforces this rather than describing it:

- `tools/ci/verify-release-inputs.sh` requires every signing secret, a well-formed tag under the shared grammar in `tools/release/tag-grammar.sh`, an artifact whose processed `Info.plist` version equals the tag, a checksum that matches the artifact bytes, an SPDX 2.3 SBOM that covers every package in `tools/ci/local-packages.txt`, and a provenance manifest whose tag, commit, runner identity, artifact hash, SBOM hash, and engine-lock hash all match the files on disk.
- `tools/ci/verify-engine-checksums.sh --mode release` requires exactly one approved Xray entry with a full commit SHA, a 64-character artifact digest, and an artifact on disk whose bytes match. `--mode foundation` is the only mode that accepts an empty lock, and it is not used by the release workflow. Both modes refuse a candidate that is approved and enabled but missing from `productionEngines`: an approved binary needs a declared release path.
- `schemas/engine-lock.schema.json` states the same requirement in machine-checkable form, and `tools/ci/validate-schemas.py` proves it is load-bearing with negative probes.
- CI has no secrets and read-only repository permissions. A signing step that runs before the secret-presence check would defeat the gate, so the release workflow checks secrets first and the workflow order is asserted by `tools/ci/test_ci_checks.py`.
- `tools/ci/check-repository-hygiene.sh` refuses a tree that carries a credential shape, a developer's home directory, or a build artifact, and refuses a `.gitignore` that stops covering a class of them. It runs from `tools/ci/run-tool-tests.sh` and from CI, so the publication is checked on every change rather than once before the first commit.

A gate that cannot be satisfied is a stop, not a warning. Do not add a bypass, a default, or a fallback to make a release proceed.

## Verification status

Local and CI checks are not the same as a device or a signed-artifact check. A green CI run is evidence about schemas, tooling, package tests, app model tests, bundle metadata, and simulator install/launch. It is not evidence of a working VPN, a Packet Tunnel Provider lifecycle, a reproducible engine artifact, or a signed release.

`docs/development/ci.md` records the gate order, the local equivalents, and the external gates that remain open: GitHub Actions execution, signing, provisioning, archive and export, publishing, physical-device VPN behaviour, a production engine, branch protection, upstream SPDX tooling validation, and third-party advisory review. `docs/development/foundation-verification.md` holds the dated verification record for the build, schema, and install evidence.

## Non-goals

Rovia does not promise anonymity, resistance to a compromised device, or protection from a malicious operating system. Its security claims must remain limited to the documented architecture and reviewed release artifacts.
