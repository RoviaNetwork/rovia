#!/usr/bin/env bash
# Print the Go toolchain version the engine lock pins, without the "go" prefix.
#
# The engine workflows need the pinned version to select a toolchain before the
# build runs, and an inline `python3 -c` in a workflow is unreviewable — the
# policy gate refuses one — so the read lives here, where a test can reach it.
#
# Usage:
#   locked-go-version.sh [--lock PATH]
#
# Exit status: 0 the version was printed, 1 no usable pin exists, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../../.." && pwd)"
lock="$script_root/engines.lock.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock)
      if [[ $# -lt 2 ]]; then
        printf '%s\n' "locked-go-version: --lock requires a value" >&2
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
      printf '%s\n' "usage: locked-go-version.sh [--lock PATH]" >&2
      exit 0
      ;;
    *)
      printf '%s\n' "locked-go-version: unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$lock" ]]; then
  printf '%s\n' "locked-go-version: engines.lock.json is required" >&2
  exit 1
fi

python3 - "$lock" <<'PY'
import json
import re
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])
try:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
except ValueError:
    print("locked-go-version: the engine lock is not valid JSON", file=sys.stderr)
    raise SystemExit(1)
candidates = lock.get("candidates") or {}
entry = candidates.get("xray") or {}
version = entry.get("goVersion")
if not isinstance(version, str) or not re.fullmatch(r"go\d+\.\d+(\.\d+)?", version.strip()):
    print("locked-go-version: the xray candidate has no usable goVersion pin", file=sys.stderr)
    raise SystemExit(1)
print(version.strip().removeprefix("go"))
PY
