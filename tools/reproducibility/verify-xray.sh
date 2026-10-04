#!/usr/bin/env bash
# Verify that the pinned Xray engine builds reproducibly.
#
# The claim this script backs: the artifact digest recorded in the engine
# lock is a property of the pinned source and toolchain, not of one machine.
# It builds the pinned commit twice, in isolated work directories, through
# the same gated path a release uses, and compares the two digests. Any
# difference — a timestamp, a path leak, a nondeterministic archive member —
# is a refusal, because a lock that pins bytes nobody can reproduce is a
# claim nobody can check.
#
# Usage:
#   verify-xray.sh [--lock PATH] [--keep-work]
#
# Exit status: 0 two independent builds agree and match the lock,
#              1 refused (nothing approved, or the builds disagree),
#              2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
lock="$script_root/engines.lock.json"
keep_work=0

usage() {
  cat <<'USAGE'
usage: verify-xray.sh [--lock PATH] [--keep-work]

  --lock PATH   engine lock to verify (default: <repository>/engines.lock.json)
  --keep-work   keep the two build directories for inspection
  -h, --help    print this message
USAGE
}

usage_error() {
  printf '%s\n' "verify-xray: $1" >&2
  usage >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock)
      [[ $# -lt 2 ]] && usage_error "--lock requires a value"
      lock="$2"
      shift 2
      ;;
    --lock=*)
      lock="${1#*=}"
      shift
      ;;
    --keep-work)
      keep_work=1
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

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ -f "$lock" ]] || fail "engines.lock.json is required"

artifact_name="$(python3 - "$lock" <<'PY'
import json
import sys
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
engines = lock.get("productionEngines")
candidates = lock.get("candidates")
if not isinstance(engines, list) or not isinstance(candidates, dict) or engines != ["xray"]:
    print("")
    raise SystemExit(0)
entry = candidates.get("xray") or {}
if entry.get("approval") != "approved" or entry.get("enabled") is not True:
    print("")
    raise SystemExit(0)
artifact = entry.get("artifact")
print(artifact if isinstance(artifact, str) else "")
PY
)"

if [[ -z "$artifact_name" ]]; then
  # The documented foundation refusal; the wording is pinned by the docs.
  fail "No approved Xray artifact exists; refusing to claim reproducibility"
fi

build_once() {
  local out_dir="$1"
  mkdir -p "$out_dir"
  "$script_root/tools/build-engine/xray/build-apple.sh" \
    --lock "$lock" \
    --out "$out_dir" >&2 \
    || return 1
  shasum -a 256 "$out_dir/$artifact_name" | awk '{print $1}'
}

work="$(mktemp -d -t rovia-engine-repro)"
cleanup() {
  if [[ "$keep_work" -eq 0 ]]; then
    rm -rf "$work"
  else
    printf '%s\n' "verify-xray: build directories kept: $work" >&2
  fi
}
trap cleanup EXIT

printf '%s\n' "verify-xray: first independent build" >&2
first="$(build_once "$work/first")" \
  || fail "verify-xray: the first build failed"
printf '%s\n' "verify-xray: second independent build" >&2
second="$(build_once "$work/second")" \
  || fail "verify-xray: the second build failed"

if [[ "$first" != "$second" ]]; then
  fail "verify-xray: two independent builds of the pinned commit disagree: $first != $second"
fi

recorded="$(python3 -c "
import json, sys
entry = json.load(open(sys.argv[1]))['candidates']['xray']
print(entry.get('sha256') or '')
" "$lock")"
if [[ -n "$recorded" ]] && [[ "$recorded" != "$first" ]]; then
  fail "verify-xray: the reproducible digest does not match the engine lock: $first != $recorded"
fi

printf '%s\n' "verify-xray: two independent builds agree: $first"
