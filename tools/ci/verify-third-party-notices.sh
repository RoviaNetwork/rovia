#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
notices="$root/THIRD_PARTY_NOTICES.md"

python3 - "$notices" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit("THIRD_PARTY_NOTICES.md is missing")
text = path.read_text(encoding="utf-8")
for component in ("Xray-core", "libXray", "sing-box"):
    if component not in text:
        raise SystemExit(f"third-party notice is missing {component}")
PY
