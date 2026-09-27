#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ ! -f "$root/engines.lock.json" ]]; then
  printf '%s\n' "engines.lock.json is required" >&2
  exit 1
fi

printf '%s\n' "No approved Xray artifact exists; refusing to claim reproducibility" >&2
exit 1
