#!/usr/bin/env bash
# Lint every Python file in tools/ with a pinned pyflakes, and fail on any finding.
#
# The verification record used to claim "pyflakes clean" without saying how pyflakes
# was obtained, and pyflakes is not installed for any system interpreter on the
# machine the record was written on. An unpinned `uvx pyflakes` resolves to whatever
# is newest — 4.0.0 at the time this was written, while the record claimed 3.2.0 —
# so an unpinned invocation is not a gate either: the same command would report
# different things on different days, and a finding could appear or vanish with a
# release rather than with a change to this repository.
#
# So the version is pinned here, the exact command is recorded in
# docs/development/ci.md and the verification record, and this script is what the
# record's claim refers to. `uvx` is used because it resolves the pinned version
# into a cache without touching the system interpreter; the alternative is a
# virtualenv, which is what the workflows build for check-jsonschema.
#
# Usage:
#   check-python-lint.sh [--root PATH] [--pyflakes VERSION]
#
# Exit status: 0 no findings, 1 a finding or a missing file, 2 usage error.
set -euo pipefail

# The version the verification record's claim is about. Changing it means the
# record's toolchain table is wrong until it is updated.
PYFLAKES_VERSION="3.2.0"

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
root="$script_root"

usage() {
  cat <<'USAGE'
usage: check-python-lint.sh [--root PATH] [--pyflakes VERSION]

  --root PATH            repository root to lint (default: this repository)
  --pyflakes VERSION     pyflakes version to run (default: 3.2.0)
  -h, --help             print this message

Exits 1 on any pyflakes finding, and refuses to report success if it could not run
the linter at all: a gate that cannot execute must not look like a gate that passed.
USAGE
}

usage_error() {
  printf '%s\n' "check-python-lint: $1" >&2
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
    --root)
      require_value "--root" "$#"
      root="$2"
      shift 2
      ;;
    --root=*)
      root="${1#*=}"
      shift
      ;;
    --pyflakes)
      require_value "--pyflakes" "$#"
      PYFLAKES_VERSION="$2"
      shift 2
      ;;
    --pyflakes=*)
      PYFLAKES_VERSION="${1#*=}"
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

if ! command -v uvx >/dev/null 2>&1; then
  printf '%s\n' "check-python-lint: uvx is not on PATH, so the pinned pyflakes cannot be resolved" >&2
  printf '%s\n' "check-python-lint: refusing to report success from a linter that did not run" >&2
  exit 1
fi

# A while-read loop rather than mapfile: the macOS default bash is 3.2, which has
# no mapfile, and this script has to run on a developer machine as well as in CI.
files=()
while IFS= read -r file; do
  files+=("$file")
done < <(
  find "$root/tools" -type d \( -name .build -o -name __pycache__ \) -prune -o \
    -type f -name '*.py' -print | LC_ALL=C sort
)

if [[ ${#files[@]} -eq 0 ]]; then
  printf '%s\n' "check-python-lint: no Python files under $root/tools" >&2
  exit 1
fi

# --version is asked for first so that a linter which resolved but produced no
# findings is distinguishable from one that never ran.
version_line="$(uvx "pyflakes==${PYFLAKES_VERSION}" --version 2>&1)" || {
  printf '%s\n' "check-python-lint: could not run pyflakes==${PYFLAKES_VERSION}:" >&2
  printf '%s\n' "$version_line" >&2
  exit 1
}
if ! printf '%s' "$version_line" | grep -q "${PYFLAKES_VERSION}"; then
  printf '%s\n' "check-python-lint: asked for pyflakes ${PYFLAKES_VERSION} and got: $version_line" >&2
  exit 1
fi

printf '%s\n' "check-python-lint: $version_line, ${#files[@]} files"

findings=0
for file in "${files[@]}"; do
  if ! output="$(uvx "pyflakes==${PYFLAKES_VERSION}" "$file" 2>&1)"; then
    printf '%s\n' "$output" >&2
    findings=$((findings + 1))
  fi
done

if [[ $findings -ne 0 ]]; then
  printf '%s\n' "check-python-lint: $findings of ${#files[@]} files have findings" >&2
  exit 1
fi

printf '%s\n' "check-python-lint: no findings"
