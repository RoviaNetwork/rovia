#!/usr/bin/env bash
# Verify the engine lock.
#
# Two modes with opposite obligations:
#
#   foundation  the current slice ships no production engine, so an empty lock
#               is a valid answer. Any entry that is present must still be
#               complete: approved, enabled, a full commit SHA, and an artifact
#               whose bytes match the recorded digest.
#   release     a release may only be built from exactly one approved Xray
#               entry. Every missing, partial, or ambiguous input is a refusal;
#               the script never repairs or downgrades a lock to make it pass.
#
# Usage:
#   verify-engine-checksums.sh [--mode foundation|release] [--lock PATH]
#                              [--github-output PATH]
#
# Exit status: 0 accepted, 1 refused, 2 usage error.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
mode="foundation"
lock=""
github_output=""

usage() {
  cat <<'USAGE'
usage: verify-engine-checksums.sh [--mode foundation|release] [--lock PATH] [--github-output PATH]

  --mode MODE        foundation (default) permits an empty engine lock;
                     release requires exactly one approved xray entry.
  --lock PATH        engine lock to verify (default: <repository>/engines.lock.json)
  --github-output    write "enabled=<bool>" and "engine=<name>" for CI steps
  -h, --help         print this message
USAGE
}

usage_error() {
  printf '%s\n' "verify-engine-checksums: $1" >&2
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
    --mode)
      require_value "--mode" "$#"
      mode="$2"
      shift 2
      ;;
    --mode=*)
      mode="${1#*=}"
      shift
      ;;
    --lock)
      require_value "--lock" "$#"
      lock="$2"
      shift 2
      ;;
    --lock=*)
      lock="${1#*=}"
      shift
      ;;
    --github-output)
      require_value "--github-output" "$#"
      github_output="$2"
      shift 2
      ;;
    --github-output=*)
      github_output="${1#*=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage_error "unknown option: $1"
      ;;
  esac
done

case "$mode" in
  foundation|release) ;;
  *)
    usage_error "unknown mode: $mode (expected foundation or release)"
    ;;
esac

if [[ -z "$lock" ]]; then
  lock="$root/engines.lock.json"
fi

if [[ ! -f "$lock" ]]; then
  printf '%s\n' "verify-engine-checksums: $(basename "$lock") is required" >&2
  exit 1
fi

python3 - "$lock" "$mode" "$github_output" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])
mode = sys.argv[2]
github_output = sys.argv[3] or ""

FULL_SHA = re.compile(r"[0-9a-fA-F]{40}")
DIGEST = re.compile(r"[0-9a-fA-F]{64}")
APPROVALS = ("pending", "approved")
PRODUCTION_ENGINE = "xray"


def fail(message):
    print(f"rovia: {message}", file=sys.stderr)
    raise SystemExit(1)


def report(message):
    print(f"rovia: {message}")


def resolve_artifact(entry):
    artifact = Path(entry["artifact"])
    if not artifact.is_absolute():
        artifact = lock_path.parent / artifact
    return artifact


def verify_candidate(name, entry):
    if not isinstance(entry, dict):
        fail(f"the {name} candidate is missing")
    if entry.get("enabled") is not True:
        fail(f"the {name} candidate is not enabled")
    approval = entry.get("approval")
    if approval not in APPROVALS:
        fail(f"the {name} approval must be one of {', '.join(APPROVALS)}; found {approval!r}")
    if approval != "approved":
        fail(f"the {name} candidate is not approved")

    for key in (
        "version",
        "commit",
        "sourceArchiveSha256",
        "artifact",
        "sha256",
        "goVersion",
        "toolchain",
    ):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f"{name} is missing {key}")

    for key in ("architectures", "buildFlags", "linkedFrameworks"):
        value = entry.get(key)
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            fail(f"{name} is missing a valid {key} list")

    if not FULL_SHA.fullmatch(entry["commit"]):
        fail(f"{name} commit must be a 40-character hexadecimal commit")
    if not DIGEST.fullmatch(entry["sha256"]):
        fail(f"{name} sha256 must be a 64-character hexadecimal digest")
    if not DIGEST.fullmatch(entry["sourceArchiveSha256"]):
        fail(f"{name} sourceArchiveSha256 must be a 64-character hexadecimal digest")

    artifact = resolve_artifact(entry)
    if not artifact.is_file():
        fail(f"{name} artifact does not exist: {artifact}")
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual.lower() != entry["sha256"].lower():
        fail(f"{name} artifact checksum does not match the engine lock: {artifact}")


def write_github_output(enabled, engine):
    if not github_output:
        return
    target = Path(github_output)
    try:
        target.write_text(f"enabled={'true' if enabled else 'false'}\nengine={engine}\n", encoding="utf-8")
    except OSError as error:
        fail(f"github output could not be written to {target}: {error}")


try:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
except (OSError, ValueError) as error:
    fail(f"{lock_path.name} is not valid JSON: {error}")
except UnicodeDecodeError as error:
    fail(f"{lock_path.name} is not valid UTF-8: {error}")

if not isinstance(lock, dict):
    fail(f"{lock_path.name} must contain a JSON object")
if lock.get("schemaVersion") != 1:
    fail(f"{lock_path.name} has an unsupported schema version")

policy = lock.get("runtimePolicy")
if not isinstance(policy, dict):
    fail("runtimePolicy is required")
if policy.get("maxGoRuntimesPerProcess") != 1:
    fail("runtimePolicy must allow exactly one Go runtime per process")
if policy.get("allowedProductionEngine") != PRODUCTION_ENGINE:
    fail("the MVP runtime policy must allow only xray")

engines = lock.get("productionEngines")
if not isinstance(engines, list):
    fail("productionEngines must be a list")
if len(engines) > 1 or any(engine != PRODUCTION_ENGINE for engine in engines):
    fail("the App Store MVP must enable exactly one production engine: xray")

candidates = lock.get("candidates")
if not isinstance(candidates, dict):
    fail("candidates must be an object")

# An approved, enabled candidate that is not listed as a production engine is
# an approved binary with no reviewable release path: the SBOM would list it as
# shipped while the release mode would not require it. Both modes refuse it.
for name in sorted(candidates):
    entry = candidates[name]
    if not isinstance(entry, dict):
        continue
    if entry.get("enabled") is True and entry.get("approval") == "approved" and name not in engines:
        fail(
            f"the {name} candidate is approved and enabled but is not listed in productionEngines; "
            "an engine that ships must be declared as a production engine"
        )

if not engines:
    if mode == "release":
        write_github_output(False, "none")
        fail(
            "release requires exactly one approved xray engine, but the engine lock enables none; "
            "foundation mode accepts this lock"
        )
    write_github_output(False, "none")
    report(f"no production engine is enabled; {mode} mode accepts an empty engine lock")
    raise SystemExit(0)

verify_candidate(PRODUCTION_ENGINE, candidates.get(PRODUCTION_ENGINE))
write_github_output(True, PRODUCTION_ENGINE)
report(
    f"xray is approved and verified: version {candidates['xray']['version']}, "
    f"commit {candidates['xray']['commit']}, artifact {resolve_artifact(candidates['xray'])}"
)
PY
