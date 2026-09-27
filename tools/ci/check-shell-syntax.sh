#!/usr/bin/env bash
# Refuse a repository whose shell scripts do not parse.
#
# A syntax error in a gate is a gate that never runs, so the syntax check has to
# be a gate itself. Every tracked script is parsed with bash -n; build
# directories and version-control metadata are skipped because they contain
# generated and vendored code that this repository does not own.
#
# Usage:
#   check-shell-syntax.sh [--root PATH]
#
# Exit status: 0 all scripts parse, 1 a script does not parse or none exist, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
root="$script_root"

usage() {
  cat <<'USAGE'
usage: check-shell-syntax.sh [--root PATH]

  --root PATH    repository root to scan (default: this repository)
  -h, --help     print this message
USAGE
}

usage_error() {
  printf '%s\n' "check-shell-syntax: $1" >&2
  usage >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      if [[ $# -lt 2 ]]; then
        usage_error "--root requires a value"
      fi
      root="$2"
      shift 2
      ;;
    --root=*)
      root="${1#*=}"
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

if [[ ! -d "$root" ]]; then
  printf '%s\n' "check-shell-syntax: repository root does not exist: $root" >&2
  exit 1
fi

checked=0
failures=0

while IFS= read -r script; do
  checked=$((checked + 1))
  if ! bash -n "$script"; then
    printf '%s\n' "check-shell-syntax: $script does not parse" >&2
    failures=$((failures + 1))
  fi
done < <(
  find "$root" -type d \( -name .build -o -name .git -o -name DerivedData -o -name .venv -o -name .ci-schema-validator \) -prune -o \
    -type f -name '*.sh' -print | LC_ALL=C sort
)

if [[ $checked -eq 0 ]]; then
  printf '%s\n' "check-shell-syntax: no shell scripts were found under $root" >&2
  exit 1
fi

if [[ $failures -ne 0 ]]; then
  printf '%s\n' "check-shell-syntax: $failures of $checked shell scripts do not parse" >&2
  exit 1
fi

printf '%s\n' "check-shell-syntax: $checked shell scripts parse"
