#!/usr/bin/env bash
# Report whether this machine's toolchain matches the one the engine lock
# records, so a digest comparison knows what it can claim.
#
# Byte-identical output is a property of the whole toolchain: the Go compiler
# version, the gomobile revision, the host architecture (Go embeds it in the
# module build path), and the host's Xcode (the gobind glue is compiled by the
# host's clang against the host's SDK). A different Xcode or a different host
# architecture produces a different artifact from the same pinned source —
# that is not drift, and a digest check that cannot see the difference would
# report it as one.
#
# Usage:
#   toolchain-matches-lock.sh [--lock PATH]
#
# Exit status: 0 the toolchains match, 1 they do not (the difference is named
# on stdout), 2 usage error or a missing pin.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../../.." && pwd)"
lock="$script_root/engines.lock.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock)
      [[ $# -lt 2 ]] && { printf '%s\n' "toolchain-matches-lock: --lock requires a value" >&2; exit 2; }
      lock="$2"
      shift 2
      ;;
    --lock=*)
      lock="${1#*=}"
      shift
      ;;
    -h|--help)
      printf '%s\n' "usage: toolchain-matches-lock.sh [--lock PATH]" >&2
      exit 0
      ;;
    *)
      printf '%s\n' "toolchain-matches-lock: unknown option: $1" >&2
      exit 2
      ;;
  esac
done

[[ -f "$lock" ]] || { printf '%s\n' "toolchain-matches-lock: engines.lock.json is required" >&2; exit 2; }

python3 - "$lock" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
entry = (lock.get("candidates") or {}).get("xray") or {}
toolchain = entry.get("toolchain") or ""

match = re.search(r"(go\d+\.\d+(?:\.\d+)?)\s+(darwin/(?:amd64|arm64))", toolchain)
xcode_match = re.search(r"Xcode\s+([0-9.]+)", toolchain)
if not match:
    print("toolchain-matches-lock: the lock's toolchain string is unparseable", file=sys.stderr)
    raise SystemExit(2)

lock_go, lock_platform = match.group(1), match.group(2)
lock_xcode = xcode_match.group(1) if xcode_match else ""
lock_arch = lock_platform.split("/", 1)[1]

try:
    go_out = subprocess.run(
        ["go", "version"], capture_output=True, text=True, check=True
    ).stdout.split()
except FileNotFoundError:
    print("toolchain-matches-lock: no Go toolchain is available", file=sys.stderr)
    raise SystemExit(2)
actual_go = f"{go_out[2]}"
actual_arch = {"x86_64": "amd64", "arm64": "arm64"}.get(
    subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip(),
    "unknown",
)
try:
    actual_xcode = subprocess.run(
        ["xcodebuild", "-version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0].split()[1]
except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
    actual_xcode = ""

differences = []
if actual_go != lock_go:
    differences.append(f"go {actual_go} != {lock_go}")
if actual_arch != lock_arch:
    differences.append(f"host {actual_arch} != {lock_arch}")
if lock_xcode and actual_xcode != lock_xcode:
    differences.append(f"Xcode {actual_xcode or 'none'} != {lock_xcode}")

if differences:
    print("toolchain differs from the lock: " + ", ".join(differences))
    raise SystemExit(1)
print("toolchain matches the lock: " + f"{lock_go} {lock_platform}, gomobile pinned, Xcode {lock_xcode or 'unpinned'}")
PY
