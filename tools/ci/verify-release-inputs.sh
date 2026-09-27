#!/usr/bin/env bash
# Verify every input a signed release depends on, and fail closed.
#
# A release is the only moment where a missing input becomes a shipped artifact,
# so this gate refuses rather than repairs. It requires, in order:
#
#   0. the export options name a resolved signing identity, because a plist left
#      holding $(ROVIA_TEAM_ID) would be substituted from the environment at
#      export time. This runs before the secret check, so the gate never reports
#      that signing inputs are present while the signing identity is unresolved;
#   1. every signing secret is present and non-blank (checked before any build
#      work, with --check-secrets-only, so a run cannot fail after archiving);
#   2. the release tag is well formed;
#   3. the artifact, SBOM, checksum file, and provenance manifest all exist and
#      are non-empty;
#   4. the engine lock is exactly one approved Xray entry whose artifact hash
#      matches (delegated to tools/ci/verify-engine-checksums.sh --mode release).
#      This runs before the artifact is opened, so a lock that cannot ship is
#      refused before anything is read out of an IPA;
#   5. the artifact is a readable IPA whose processed Info.plist has a resolved
#      identifier, a numeric build, and a marketing version that equals the tag;
#   6. the SHA256SUMS file lists the artifact and the digest matches its bytes;
#   7. the SBOM is SPDX 2.3, describes the app, and covers every package in
#      tools/ci/local-packages.txt;
#   8. the provenance manifest was written for this tag, commit, artifact,
#      SBOM, and engine lock, with hashes that match the files on disk.
#
# The order of 4 through 8 is the order the body runs in, and
# tools/ci/test_ci_checks.py derives this list from the body and requires
# CHANGELOG.md and docs/development/ci.md to state the same order. The engine
# lock used to be documented as the last check, which it has never been.
#
# Step 0 is delegated to tools/release/verify-export-options.sh, which refuses an
# unresolved or malformed team ID. No Apple Developer team is configured for this
# repository, so that delegation refuses today and signing stays a manual gate.
#
# Secret values are never printed, only their names.
#
# Usage:
#   verify-release-inputs.sh [--root PATH] [--tag TAG] [--artifact PATH]
#                            [--sbom PATH] [--checksums PATH] [--manifest PATH]
#                            [--check-secrets-only] [--export-options PATH]
#
# Paths default to the ROVIA_RELEASE_* environment variables.
# Signing secrets are read from ROVIA_KEYCHAIN_PASSWORD,
# ROVIA_IOS_DIST_CERT_BASE64, ROVIA_IOS_DIST_CERT_PASSWORD,
# ROVIA_IOS_APP_PROFILE_BASE64, and ROVIA_IOS_TUNNEL_PROFILE_BASE64.
#
# Exit status: 0 accepted, 1 refused, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=tools/release/tag-grammar.sh
source "$script_root/tools/release/tag-grammar.sh"

root="$script_root"
tag="${ROVIA_RELEASE_TAG:-}"
artifact="${ROVIA_RELEASE_ARTIFACT:-}"
sbom="${ROVIA_RELEASE_SBOM:-}"
checksums="${ROVIA_RELEASE_CHECKSUMS:-}"
manifest="${ROVIA_RELEASE_MANIFEST:-}"
secrets_only=0

SECRET_NAMES=(
  ROVIA_KEYCHAIN_PASSWORD
  ROVIA_IOS_DIST_CERT_BASE64
  ROVIA_IOS_DIST_CERT_PASSWORD
  ROVIA_IOS_APP_PROFILE_BASE64
  ROVIA_IOS_TUNNEL_PROFILE_BASE64
)

usage() {
  cat <<'USAGE'
usage: verify-release-inputs.sh [--root PATH] [--tag TAG] [--artifact PATH]
                                 [--sbom PATH] [--checksums PATH] [--manifest PATH]
                                 [--check-secrets-only] [--export-options PATH]

  --root PATH            repository root; the engine lock and, unless overridden,
                         the export options are read from it (default: this repository)
  --tag TAG              release tag, for example v0.1.0
  --artifact PATH        exported .ipa
  --sbom PATH            SPDX 2.3 SBOM for the build
  --checksums PATH       SHA256SUMS listing the artifact
  --manifest PATH        build-manifest.json written by tools/reproducibility/manifest.sh
  --check-secrets-only   only require the signing identity and the signing
                         secrets, then exit
  --export-options PATH  export options plist to check for a resolved team ID
                         (default: <root>/tools/release/ExportOptions.plist)
  -h, --help             print this message
USAGE
}

usage_error() {
  printf '%s\n' "verify-release-inputs: $1" >&2
  usage >&2
  exit 2
}

require_value() {
  if [[ $2 -lt 2 ]]; then
    usage_error "$1 requires a value"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) require_value "--root" "$#"; root="$2"; shift 2 ;;
    --root=*) root="${1#*=}"; shift ;;
    --tag) require_value "--tag" "$#"; tag="$2"; shift 2 ;;
    --tag=*) tag="${1#*=}"; shift ;;
    --artifact) require_value "--artifact" "$#"; artifact="$2"; shift 2 ;;
    --artifact=*) artifact="${1#*=}"; shift ;;
    --sbom) require_value "--sbom" "$#"; sbom="$2"; shift 2 ;;
    --sbom=*) sbom="${1#*=}"; shift ;;
    --checksums) require_value "--checksums" "$#"; checksums="$2"; shift 2 ;;
    --checksums=*) checksums="${1#*=}"; shift ;;
    --manifest) require_value "--manifest" "$#"; manifest="$2"; shift 2 ;;
    --manifest=*) manifest="${1#*=}"; shift ;;
    --check-secrets-only) secrets_only=1; shift ;;
    --export-options) require_value "--export-options" "$#"; export_options="$2"; shift 2 ;;
    --export-options=*) export_options="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage_error "unknown option: $1" ;;
  esac
done

if [[ $secrets_only -eq 0 && $# -eq 0 && -z "$tag$artifact$sbom$checksums$manifest" ]]; then
  usage_error "no release inputs were given"
fi

# Step 0, before anything reports on readiness. A gate that says "all signing
# secrets are present" while the export options still hold $(ROVIA_TEAM_ID) has
# told the operator it is ready to sign, and it is not.
export_options="${ROVIA_EXPORT_OPTIONS:-${export_options:-$root/tools/release/ExportOptions.plist}}"
# Built as an array rather than expanded inline. An unquoted
# ${ROVIA_TEAM_ID:+--require-team-id "$ROVIA_TEAM_ID"} word-splits and
# glob-expands: a team id of "*" or of two words would reach the preflight as
# several arguments, and a plist path that happened to contain a space would be
# torn in half. The array keeps each element one argument whatever it holds.
preflight_arguments=(--plist "$export_options")
if [[ -n "${ROVIA_TEAM_ID:-}" ]]; then
  preflight_arguments+=(--require-team-id "$ROVIA_TEAM_ID")
fi
if ! "$script_root/tools/release/verify-export-options.sh" "${preflight_arguments[@]}"; then
  printf '%s\n' "verify-release-inputs: refusing before any readiness check: the export options do not name a resolved signing identity" >&2
  printf '%s\n' "verify-release-inputs: signing, provisioning, archive, and export are a manual gate and have not been executed for this repository" >&2
  exit 1
fi

missing_secret=0
for name in "${SECRET_NAMES[@]}"; do
  value="${!name-}"
  if [[ -z "${value//[[:space:]]/}" ]]; then
    printf '%s\n' "verify-release-inputs: required signing secret $name is missing" >&2
    missing_secret=1
  fi
done
if [[ $missing_secret -ne 0 ]]; then
  exit 1
fi
printf '%s\n' "verify-release-inputs: all signing secrets are present"

if [[ $secrets_only -eq 1 ]]; then
  exit 0
fi

if [[ -z "$tag" ]]; then
  printf '%s\n' "verify-release-inputs: a release tag is required" >&2
  exit 1
fi
if ! rovia_tag_is_valid "$tag"; then
  printf '%s\n' "verify-release-inputs: invalid release tag: $tag" >&2
  printf '%s\n' "verify-release-inputs: expected vMAJOR.MINOR.PATCH[-PRERELEASE][+BUILD] with no leading zeros" >&2
  exit 1
fi
tag_version="$(rovia_tag_version "$tag")"

require_file() {
  local label="$1" path="$2"
  if [[ -z "$path" ]]; then
    printf '%s\n' "verify-release-inputs: a $label is required" >&2
    exit 1
  fi
  if [[ ! -f "$path" ]]; then
    printf '%s\n' "verify-release-inputs: $label does not exist: $path" >&2
    exit 1
  fi
  if [[ ! -s "$path" ]]; then
    printf '%s\n' "verify-release-inputs: $label is empty: $path" >&2
    exit 1
  fi
}

require_file "artifact" "$artifact"
require_file "SBOM" "$sbom"
require_file "checksum file" "$checksums"
require_file "provenance manifest" "$manifest"

"$script_root/tools/ci/verify-engine-checksums.sh" --mode release --lock "$root/engines.lock.json"

python3 - "$tag" "$tag_version" "$artifact" "$sbom" "$checksums" "$manifest" "$root/engines.lock.json" "$script_root" <<'PY'
import hashlib
import json
import plistlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

tag, tag_version, artifact, sbom, checksums, manifest, lock_path, script_root = sys.argv[1:]
FULL_SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")


def fail(message):
    print(f"verify-release-inputs: {message}", file=sys.stderr)
    raise SystemExit(1)


def report(message):
    print(f"verify-release-inputs: {message}")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


artifact_path = Path(artifact)
sbom_path = Path(sbom)
checksums_path = Path(checksums)
manifest_path = Path(manifest)
lock = Path(lock_path)

# -- the artifact itself ---------------------------------------------------

try:
    with zipfile.ZipFile(artifact_path) as archive:
        payload = sorted(
            name
            for name in archive.namelist()
            if name.startswith("Payload/") and name.endswith(".app/Info.plist")
        )
        if not payload:
            fail(f"the artifact has no Payload/*.app/Info.plist: {artifact_path}")
        with archive.open(payload[0]) as stream:
            info = plistlib.load(stream)
except (zipfile.BadZipFile, KeyError, plistlib.InvalidFileException) as error:
    fail(f"the artifact is not a readable IPA with a payload Info.plist: {error}")

if not isinstance(info, dict):
    fail("the artifact payload Info.plist is not a dictionary")

identifier = info.get("CFBundleIdentifier")
if not isinstance(identifier, str) or not identifier.strip():
    fail("the artifact payload Info.plist has no CFBundleIdentifier")
if "$(" in identifier or "${" in identifier:
    fail(f"the artifact payload Info.plist contains an unexpanded build variable: {identifier}")

executable = info.get("CFBundleExecutable")
if not isinstance(executable, str) or not executable.strip():
    fail("the artifact payload Info.plist has no CFBundleExecutable")
if "$(" in executable:
    fail(f"the artifact payload Info.plist contains an unexpanded build variable: {executable}")

build = info.get("CFBundleVersion")
if build is None or not re.fullmatch(r"[0-9]+", str(build)):
    fail(f"the artifact payload Info.plist needs a numeric CFBundleVersion, found {build!r}")

version = info.get("CFBundleShortVersionString")
if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(\.[0-9]+)*", version):
    fail(f"the artifact payload Info.plist needs a dotted CFBundleShortVersionString, found {version!r}")
if version != tag_version:
    fail(f"the artifact version {version} does not match the release tag {tag}")

# -- checksums -------------------------------------------------------------

listed = {}
for line in checksums_path.read_text(encoding="utf-8").splitlines():
    parts = line.split()
    if len(parts) < 2:
        continue
    listed[Path(parts[-1].lstrip("*")).name] = parts[0].lower()

artifact_name = artifact_path.name
if artifact_name not in listed:
    fail(f"the checksum file does not list the artifact {artifact_name}: {checksums_path}")
if not DIGEST.fullmatch(listed[artifact_name]):
    fail(f"the checksum file entry for {artifact_name} is not a SHA-256 digest")
if listed[artifact_name] != digest(artifact_path):
    fail(f"the checksum for {artifact_name} does not match the artifact bytes")

# -- SBOM ------------------------------------------------------------------

try:
    sbom_document = json.loads(sbom_path.read_text(encoding="utf-8"))
except ValueError as error:
    fail(f"the SBOM is not valid JSON: {error}")
sbom_check = subprocess.run(
    [
        sys.executable,
        str(Path(script_root) / "tools/reproducibility/check-sbom.py"),
        str(sbom_path),
        # The SBOM inventory describes this repository's Swift packages, which is
        # the tree this script lives in. --root selects the engine lock, which may
        # be a fixture; the package list is the real one on purpose, so a package
        # cannot be dropped from the SBOM by pointing the gate elsewhere.
        "--repository",
        Path(script_root).as_posix(),
    ],
    capture_output=True,
    text=True,
)
if sbom_check.returncode != 0:
    fail(
        "the SBOM does not satisfy the SPDX 2.3 invariants:\n"
        + (sbom_check.stdout + sbom_check.stderr).strip()
    )
if sbom_document.get("spdxVersion") != "SPDX-2.3":
    fail("the SBOM is not an SPDX 2.3 document")

# -- provenance manifest ---------------------------------------------------

try:
    provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
except ValueError as error:
    fail(f"the provenance manifest is not valid JSON: {error}")
if not isinstance(provenance, dict):
    fail("the provenance manifest is not a JSON object")
if provenance.get("schemaVersion") != 2:
    fail(f"the provenance manifest schemaVersion must be 2, found {provenance.get('schemaVersion')!r}")
if provenance.get("releaseTag") != tag:
    fail(f"the provenance manifest release tag {provenance.get('releaseTag')!r} does not match {tag}")
if provenance.get("version") != tag_version:
    fail(f"the provenance manifest version {provenance.get('version')!r} does not match {tag_version}")

commit = provenance.get("gitCommit")
if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
    fail(f"the provenance manifest must record a 40-character source commit, found {commit!r}")

runner = provenance.get("runner")
if not isinstance(runner, str) or not runner.strip():
    fail("the provenance manifest must record the runner identity that produced the artifact")
if runner.strip() == "unavailable":
    fail(
        "the provenance manifest records no runner identity; a release has to say which "
        "build produced the artifact (pass --runner or ROVIA_RUNNER_IDENTITY)"
    )

artifact_record = provenance.get("artifact")
if not isinstance(artifact_record, dict):
    fail("the provenance manifest has no artifact record")
if artifact_record.get("name") != artifact_name:
    fail(f"the provenance manifest describes {artifact_record.get('name')!r}, not {artifact_name}")
if artifact_record.get("sha256") != digest(artifact_path):
    fail("the provenance manifest artifact hash does not match the artifact")

sbom_record = provenance.get("sbom")
if not isinstance(sbom_record, dict):
    fail("the provenance manifest has no SBOM record")
if sbom_record.get("name") != sbom_path.name:
    fail(f"the provenance manifest describes {sbom_record.get('name')!r}, not {sbom_path.name}")
if sbom_record.get("sha256") != digest(sbom_path):
    fail("the provenance manifest SBOM hash does not match the SBOM")

if provenance.get("engineLockSha256") != digest(lock):
    fail("the provenance manifest engine lock hash does not match engines.lock.json")

engines = provenance.get("enabledEngines")
if not isinstance(engines, list) or len(engines) != 1 or engines[0] != "xray":
    fail(f"the provenance manifest must record exactly one xray engine, found {engines!r}")

report(f"tag {tag} matches artifact {artifact_name} ({identifier}, build {build})")
report("checksums, SBOM, and provenance manifest all match the files on disk")
PY

printf '%s\n' "verify-release-inputs: every release input verified"
