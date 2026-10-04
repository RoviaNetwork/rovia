# Reproducible build policy

Rovia does not promise that a signed iOS IPA is byte-for-byte identical across machines. Signing, provisioning, timestamps, and distribution metadata can change the outer archive.

## Verification layers

### Level A: engine artifact

When an engine is enabled, pin:

- source repository and full commit
- Go and wrapper toolchain versions
- target architectures
- compiler flags and linker metadata policy
- source archive and output SHA-256
- complete dependency lock

Compare two builds in controlled environments. If the native toolchain or upstream build cannot yet be deterministic, publish the observed difference and do not call the artifact reproducible.

### Level B: unsigned application inputs

Produce an unsigned source-derived build and a manifest containing:

- Git commit
- `Package.resolved`
- engine lock
- toolchain versions
- file hashes
- SBOM
- build timestamp and runner identity

### Level C: signed release

A signed release is traceable to the exact unsigned inputs, source tag, signing environment, and CI run. It is not automatically byte-for-byte reproducible.

## The SBOM

`tools/reproducibility/generate-sbom.py` writes an SPDX 2.3 document that
`tools/reproducibility/check-sbom.py` re-reads and checks, so the file that was
actually produced is validated rather than the generator's own assumptions.

```text
python3 tools/reproducibility/generate-sbom.py . build/SBOM.spdx.json
python3 tools/reproducibility/check-sbom.py build/SBOM.spdx.json
```

The document names the shipped components, not only the source tree: the host
application and the Packet Tunnel extension with the versions and bundle
identifiers taken from the Xcode inputs, every package in
`tools/ci/local-packages.txt`, and every engine candidate the lock has approved
and enabled, with its source commit and artifact digest.

The engine list is an inventory, not a decision. A candidate that is approved
and enabled but missing from `productionEngines` still appears here, because
omitting it would hide a binary the build inputs contain;
`tools/ci/verify-engine-checksums.sh` refuses that lock in both modes, and
`schemas/engine-lock.schema.json` says the same thing.

Three SPDX 2.3 details are asserted by `tools/reproducibility/test_generate_sbom.py`
because they are easy to get wrong:

- `creationInfo.created` is a UTC instant ending in `Z`. Python's
  `datetime.isoformat()` emits `+00:00` and microseconds, which is not a valid
  SPDX timestamp.
- `creationInfo.creators` entries are actors: `Person:`, `Organization:`, or
  `Tool:` followed by a name. A bare tool name is not a valid creator, and the
  tool creator carries its version.
- `documentNamespace` is unique per document. It carries a run identifier: pass
  `--namespace-id` with a fixed value, or accept a random UUID per run so two
  documents are never conflated.
- `creationInfo.created` is a wall-clock reading, so two runs of the same tree
  differed in that one field. It is now settable: `--created` takes seconds since
  the Unix epoch or an RFC 3339 UTC instant ending in `Z`, and falls back to
  `SOURCE_DATE_EPOCH` when the flag is absent. With neither, the current time is
  used and the tool prints a note that the document is not byte-reproducible.

A document is byte-reproducible only when both `--namespace-id` and one of those
two are fixed. Fixing only the namespace does not make it reproducible, which is
what this document previously said.

The checker also refuses duplicate SPDX identifiers, dangling relationships,
invalid relationship types, a package without `copyrightText` or `downloadLocation`,
an orphaned component, a missing application or extension component, and a
document that is missing a package listed in `tools/ci/local-packages.txt`. It
cannot check upstream SPDX tooling compatibility, purl resolution, or licence
conclusions; those remain reviewer responsibilities.

## The provenance manifest

`tools/reproducibility/manifest.sh` records what a released artifact is made of:

```text
./tools/reproducibility/manifest.sh \
  --artifact build/export/Rovia.ipa \
  --sbom build/SBOM.spdx.json \
  --tag v0.1.0 \
  --output build/export/build-manifest.json
```

It records a UTC `Z` timestamp, the source commit, the release tag and version,
the runner identity, the artifact name, size, and SHA-256, the SBOM name and
SHA-256, the engine-lock SHA-256, the enabled engines, every `Package.resolved`
with its digest, the platform, and the Swift and Xcode versions or the literal
`unavailable`.

The runner identity comes from `--runner` or `ROVIA_RUNNER_IDENTITY`; the
release workflow sets it from the GitHub run, job, and attempt. It records
`unavailable` rather than inventing one, and
`tools/ci/verify-release-inputs.sh` refuses a manifest that says `unavailable`,
because a release has to say which build produced the artifact.

It refuses to be written from partial inputs: a missing or empty artifact, a
missing or unparsable engine lock, a missing SBOM, a tag that is not a release
tag under the shared grammar in `tools/release/tag-grammar.sh`, or a version
that disagrees with the tag are errors. When the root is not a git repository,
the source commit is `null` rather than a placeholder, and
`tools/ci/verify-release-inputs.sh` treats a null commit as a refusal.

`--root PATH` points the tool at another repository root, which is how the tests
build a real commit without touching this repository.

## Locking

`tools/ci/verify-lockfiles.sh` requires a `Package.swift` for every entry in
`tools/ci/local-packages.txt` and an engine lock that still declares the MVP
policy. It classifies every `.package(...)` declaration by its arguments rather
than by a text match: `path:` is a sibling package in this repository and needs
no lock file, while `url:`, `id:`, `name:`, `from:`, `exact:`, `branch:`, and
`revision:` identify a remote source that must have a `Package.resolved` whose
pins carry an exact 40-character revision. A branch, a version range, or a
version without a revision is refused, because an unlocked dependency changes
code under a tag without failing any build. An argument list the verifier does
not recognise is refused rather than assumed to be local, so a new SwiftPM
form cannot slip through unreviewed.

The engine lock verifier also refuses, in both foundation and release mode, a
candidate that is approved and enabled but missing from `productionEngines`:
an approved binary with no declared release path.

`tools/ci/test_verify_lockfiles.py` fails when a `Package.swift` exists in the
tree but is not listed, so the list, the scripts, and the tests cannot drift.

## Current state

The lock enables one production engine: xray v26.9.9, pinned to commit
`50b95979f5db551bd273165cf469e5daaf791341` with a verified source archive
digest. `tools/build-engine/xray/build-apple.sh` builds
`LibXray.xcframework.zip` from that pin, `tools/reproducibility/verify-xray.sh`
builds it twice in isolation and refuses unless both digests agree, and
`tools/ci/verify-engine-checksums.sh --mode release` refuses anything whose
bytes do not match the recorded digest
`8c9eadede96413189dbc6587056790e8de108657968165faf3adbe98ee3f2891`. The digest
is reproduced by two independent builds on the reference machine, and the
engine-proof workflow reruns both checks on every change to the lock.
