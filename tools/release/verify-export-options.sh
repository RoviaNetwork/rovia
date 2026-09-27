#!/usr/bin/env bash
# Refuse an export options file whose signing identity is unresolved.
#
# tools/release/ExportOptions.plist ships with the team ID as the build-setting
# reference $(ROVIA_TEAM_ID). That is deliberate: nobody has an Apple Developer
# team to put here, and inventing one would be a false claim about who signs the
# app. The consequence is that -exportArchive would either be handed an
# unresolved string or, worse, be handed a team ID substituted from whatever the
# environment happened to contain.
#
# So the release path checks before it says anything about readiness. A plist is
# accepted only when its teamID is a literal Apple team identifier: ten
# uppercase alphanumeric characters. Anything else -- an unresolved build-setting
# reference, an empty string, whitespace, a placeholder -- is refused, and the
# diagnostic says which of those it was.
#
# This gate never contacts Apple and never signs anything. It cannot tell you
# whether a team ID is real; it can only tell you that one has been written down
# instead of left to be resolved at export time.
#
# Usage:
#   verify-export-options.sh [--plist PATH] [--require-team-id TEAMID]
#
# Exit status: 0 the team ID is resolved, 1 refused, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
plist="$script_root/tools/release/ExportOptions.plist"
expected="${ROVIA_TEAM_ID:-}"

usage() {
  cat <<'USAGE'
usage: verify-export-options.sh [--plist PATH] [--require-team-id TEAMID]

  --plist PATH         export options plist to check (default: tools/release/ExportOptions.plist)
  --require-team-id ID require this exact team ID, so a CI variable and the file
                       cannot disagree about who signs
  -h, --help           print this message

The team ID must be ten uppercase alphanumeric characters. An unresolved
build-setting reference such as $(ROVIA_TEAM_ID) is refused.
USAGE
}

usage_error() {
  printf '%s\n' "verify-export-options: $1" >&2
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
    --plist) require_value "--plist" "$#"; plist="$2"; shift 2 ;;
    --plist=*) plist="${1#*=}"; shift ;;
    --require-team-id) require_value "--require-team-id" "$#"; expected="$2"; shift 2 ;;
    --require-team-id=*) expected="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage_error "unknown option: $1" ;;
  esac
done

if [[ -n "$expected" && ! "$expected" =~ ^[A-Z0-9]{10}$ ]]; then
  printf '%s\n' "verify-export-options: the required team ID is not a team ID: $expected" >&2
  exit 1
fi

if [[ ! -f "$plist" ]]; then
  printf '%s\n' "verify-export-options: export options file does not exist: $plist" >&2
  exit 1
fi

team_id="$(python3 - "$plist" <<'PYTHON'
import plistlib
import sys

with open(sys.argv[1], "rb") as stream:
    document = plistlib.load(stream)
value = document.get("teamID")
print("" if value is None else str(value))
PYTHON
)"

if [[ -z "${team_id//[[:space:]]/}" ]]; then
  printf '%s\n' "verify-export-options: $plist has no teamID" >&2
  printf '%s\n' "verify-export-options: the export step has no signing identity, so refuse rather than resolve it at export time" >&2
  exit 1
fi

if [[ "$team_id" == *'$('* || "$team_id" == *'${'* ]]; then
  printf '%s\n' "verify-export-options: $plist has an unresolved teamID: $team_id" >&2
  printf '%s\n' "verify-export-options: a build-setting reference is not a team ID; it would be substituted from whatever the environment held at export time" >&2
  printf '%s\n' "verify-export-options: no Apple Developer team is configured for this repository, so signing is a manual gate that has not been executed" >&2
  exit 1
fi

if ! [[ "$team_id" =~ ^[A-Z0-9]{10}$ ]]; then
  printf '%s\n' "verify-export-options: $plist has a malformed teamID: $team_id" >&2
  printf '%s\n' "verify-export-options: an Apple team ID is ten uppercase alphanumeric characters" >&2
  exit 1
fi

if [[ -n "$expected" && "$expected" != "$team_id" ]]; then
  printf '%s\n' "verify-export-options: $plist names team $team_id but $expected was required" >&2
  exit 1
fi

printf '%s\n' "verify-export-options: teamID is resolved ($team_id)"
printf '%s\n' "verify-export-options: this says a team ID is written down, not that signing works; no certificate, profile, or export has been exercised"
