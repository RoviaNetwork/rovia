#!/usr/bin/env bash
# Build the pinned Xray engine artifact for Apple platforms.
#
# This is a stub that refuses, on purpose. The build recipe is not written yet,
# and a script that can be made to succeed by an unapproved lock, a floating
# tag, or a machine that happens to have a Go toolchain would let a release
# claim a reproducible engine that nobody built from a pinned source. Each
# refusal names the input that is missing so the next implementation knows what
# it has to satisfy.
#
# Usage:
#   build-apple.sh [--lock PATH]
#
# Exit status: 0 only when a pinned, approved engine was actually built.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../../.." && pwd)"
lock="$script_root/engines.lock.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock)
      if [[ $# -lt 2 ]]; then
        printf '%s\n' "build-apple: --lock requires a value" >&2
        exit 2
      fi
      lock="$2"
      shift 2
      ;;
    --lock=*)
      lock="${1#*=}"
      shift
      ;;
    -h|--help)
      printf '%s\n' "usage: build-apple.sh [--lock PATH]" >&2
      exit 0
      ;;
    *)
      printf '%s\n' "build-apple: unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$lock" ]]; then
  printf '%s\n' "engines.lock.json is required" >&2
  exit 1
fi

python3 - "$lock" <<'PY'
import json
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])

try:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
except ValueError as error:
    print(f"build-apple: the engine lock is not valid JSON: {error}", file=sys.stderr)
    raise SystemExit(1)

engines = lock.get("productionEngines")
candidates = lock.get("candidates")
if not isinstance(engines, list) or not isinstance(candidates, dict):
    print("build-apple: the engine lock has no productionEngines or candidates", file=sys.stderr)
    raise SystemExit(1)
if not engines:
    print(
        "No approved Xray lock entry is available; refusing to build a floating engine",
        file=sys.stderr,
    )
    raise SystemExit(1)
if engines != ["xray"]:
    print(f"build-apple: the App Store MVP builds only xray, not {engines}", file=sys.stderr)
    raise SystemExit(1)
entry = candidates.get("xray")
if not isinstance(entry, dict) or entry.get("approval") != "approved" or entry.get("enabled") is not True:
    print("build-apple: the xray candidate is not approved and enabled", file=sys.stderr)
    raise SystemExit(1)
for key in ("version", "commit", "sourceArchiveSha256", "artifact", "sha256", "goVersion"):
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        print(f"build-apple: the xray candidate is missing {key}", file=sys.stderr)
        raise SystemExit(1)
print(
    "build-apple: the lock pins an approved xray build, but the deterministic build "
    "recipe is not implemented yet; refusing to claim an artifact nobody built",
    file=sys.stderr,
)
raise SystemExit(1)
PY

if ! command -v go >/dev/null 2>&1; then
  printf '%s\n' "build-apple: no Go toolchain is available" >&2
  exit 1
fi

printf '%s\n' "build-apple: refusing to claim a reproducible engine artifact" >&2
exit 1
