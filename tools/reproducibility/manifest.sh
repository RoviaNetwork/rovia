#!/usr/bin/env bash
# Record the provenance of a release artifact.
#
# The manifest is the only place that ties a shipped binary to a source commit,
# an engine lock, an SBOM, and a toolchain. It therefore refuses to be written
# from partial inputs: a missing artifact, a missing engine lock, a missing
# SBOM, a malformed tag, or a version that disagrees with the tag is an error,
# not a warning. The source commit is recorded as null when the root is not a
# git repository, which the release gate treats as a refusal.
#
# Usage:
#   manifest.sh [--root PATH] [--artifact PATH] [--sbom PATH] [--tag TAG]
#               [--version VERSION] [--output PATH]
#   manifest.sh <artifact> [--tag TAG] ...      (positional form, still accepted)
#
# Exit status: 0 written, 1 refused, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=tools/release/tag-grammar.sh
source "$script_root/tools/release/tag-grammar.sh"

root="$script_root"
artifact=""
sbom=""
tag=""
version=""
output=""
runner=""

usage() {
  cat <<'USAGE'
usage: manifest.sh [--root PATH] [--artifact PATH] [--sbom PATH] [--tag TAG]
                   [--version VERSION] [--output PATH]

  --root PATH         repository root (default: this repository)
  --artifact PATH     artifact to describe (required)
  --sbom PATH         SBOM describing the build (optional; recorded when present)
  --tag TAG           release tag, for example v0.1.0 (optional)
  --version VERSION   marketing version; must agree with the tag when both are given
  --output PATH       manifest path (default: build-manifest.json beside the artifact)
  --runner IDENTITY   identity of the build that produced the artifact (default:
                      $ROVIA_RUNNER_IDENTITY, else unavailable)
  -h, --help          print this message
USAGE
}

usage_error() {
  printf '%s\n' "manifest.sh: $1" >&2
  usage >&2
  exit 2
}

refuse() {
  printf '%s\n' "manifest.sh: $1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) [[ $# -ge 2 ]] || usage_error "--root requires a value"; root="$2"; shift 2 ;;
    --root=*) root="${1#*=}" ; shift ;;
    --artifact) [[ $# -ge 2 ]] || usage_error "--artifact requires a value"; artifact="$2"; shift 2 ;;
    --artifact=*) artifact="${1#*=}" ; shift ;;
    --sbom) [[ $# -ge 2 ]] || usage_error "--sbom requires a value"; sbom="$2"; shift 2 ;;
    --sbom=*) sbom="${1#*=}" ; shift ;;
    --tag) [[ $# -ge 2 ]] || usage_error "--tag requires a value"; tag="$2"; shift 2 ;;
    --tag=*) tag="${1#*=}" ; shift ;;
    --version) [[ $# -ge 2 ]] || usage_error "--version requires a value"; version="$2"; shift 2 ;;
    --version=*) version="${1#*=}" ; shift ;;
    --output) [[ $# -ge 2 ]] || usage_error "--output requires a value"; output="$2"; shift 2 ;;
    --output=*) output="${1#*=}" ; shift ;;
    --runner) [[ $# -ge 2 ]] || usage_error "--runner requires a value"; runner="$2"; shift 2 ;;
    --runner=*) runner="${1#*=}" ; shift ;;
    -h|--help) usage; exit 0 ;;
    --*) usage_error "unknown option: $1" ;;
    *)
      if [[ -n "$artifact" ]]; then
        usage_error "unexpected argument: $1"
      fi
      artifact="$1"
      shift
      ;;
  esac
done

if [[ -z "$artifact" ]]; then
  usage_error "an artifact is required"
fi

if [[ ! -d "$root" ]]; then
  refuse "repository root does not exist: $root"
fi

if [[ ! -e "$artifact" ]]; then
  refuse "artifact does not exist: $artifact"
fi

if [[ ! -s "$artifact" ]]; then
  refuse "artifact is empty: $artifact"
fi

if [[ -n "$sbom" && ! -s "$sbom" ]]; then
  refuse "SBOM does not exist or is empty: $sbom"
fi

if [[ -n "$tag" ]] && ! rovia_tag_is_valid "$tag"; then
  refuse "invalid release tag: $tag (expected vMAJOR.MINOR.PATCH[-PRERELEASE][+BUILD] with no leading zeros)"
fi

tag_version=""
if [[ -n "$tag" ]]; then
  tag_version="$(rovia_tag_version "$tag")"
fi

if [[ -n "$tag_version" && -n "$version" && "$version" != "$tag_version" ]]; then
  refuse "version $version does not match the release tag $tag"
fi

resolved_version="$version"
if [[ -z "$resolved_version" ]]; then
  resolved_version="$tag_version"
fi

if [[ -z "$runner" ]]; then
  runner="${ROVIA_RUNNER_IDENTITY:-}"
fi

lock="$root/engines.lock.json"
if [[ ! -f "$lock" ]]; then
  refuse "engines.lock.json is required to record provenance"
fi

python3 - "$root" "$artifact" "$sbom" "$tag" "$resolved_version" "$output" "$lock" "$runner" <<'PY'
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root, artifact, sbom, tag, version, output, lock, runner = sys.argv[1:]
root_path = Path(root).resolve()
artifact_path = Path(artifact).resolve()
manifest_path = Path(output).resolve() if output else artifact_path.parent / "build-manifest.json"


def refuse(message):
    print(f"manifest.sh: {message}", file=sys.stderr)
    raise SystemExit(1)


def first_line(command):
    try:
        result = subprocess.run(command, cwd=root_path, text=True, capture_output=True)
    except OSError:
        return "unavailable"
    if result.returncode != 0:
        return "unavailable"
    lines = result.stdout.splitlines() or [""]
    return lines[0].strip() or "unavailable"


try:
    lock_document = json.loads(Path(lock).read_text(encoding="utf-8"))
except ValueError as error:
    refuse(f"engines.lock.json is not valid JSON: {error}")
if not isinstance(lock_document, dict):
    refuse("engines.lock.json must contain a JSON object")

engines = lock_document.get("productionEngines")
if not isinstance(engines, list):
    refuse("engines.lock.json is missing productionEngines")
candidates = lock_document.get("candidates")
if not isinstance(candidates, dict):
    refuse("engines.lock.json is missing candidates")

git_commit = first_line(["git", "rev-parse", "--verify", "HEAD"])
if git_commit == "unavailable" or len(git_commit) != 40:
    git_commit = None

resolved_files = []
for path in sorted(root_path.glob("**/Package.resolved")):
    if ".build" in path.parts:
        continue
    resolved_files.append(
        {
            "path": str(path.relative_to(root_path)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )

document = {
    "schemaVersion": 2,
    "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "gitCommit": git_commit,
    "releaseTag": tag or None,
    "version": version or None,
    "runner": runner.strip() or "unavailable",
    "artifact": {
        "name": artifact_path.name,
        "bytes": artifact_path.stat().st_size,
        "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    },
    "sbom": (
        {
            "name": Path(sbom).resolve().name,
            "sha256": hashlib.sha256(Path(sbom).resolve().read_bytes()).hexdigest(),
        }
        if sbom
        else None
    ),
    "engineLockSha256": hashlib.sha256(Path(lock).read_bytes()).hexdigest(),
    "enabledEngines": list(engines),
    "packageResolved": resolved_files,
    "platform": platform.platform(),
    "swift": first_line(["swift", "--version"]),
    "xcode": first_line(["xcodebuild", "-version"]),
}

try:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
except OSError as error:
    refuse(f"could not write {manifest_path}: {error}")

print(f"manifest.sh: wrote {manifest_path}")
PY
