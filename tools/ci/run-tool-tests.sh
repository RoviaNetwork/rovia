#!/usr/bin/env bash
# Run every Python test in tools/ as its own process.
#
# Each test file is executed directly rather than through unittest discovery, so
# a test file that fails to import is reported as a failure instead of being
# silently skipped, and so the same command works on a developer machine and in
# CI. A non-zero exit from any file fails this script.
#
# Usage:
#   run-tool-tests.sh [--root PATH] [pattern]
#
# The text gates read core sources from the pinned revision
# (tools/ci/core-pin.txt). When ROVIA_CORE_ROOT is unset this script fetches
# it once into the local cache; CI sets the variable explicitly after its own
# fetch step, so the two cannot disagree about where the sources came from.
#
# Exit status: 0 all tests passed, 1 a test file failed, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
root="$script_root"
pattern='test_*.py'

usage() {
  cat <<'USAGE'
usage: run-tool-tests.sh [--root PATH] [pattern]

  --root PATH    repository root to scan (default: this repository)
  pattern        glob for the test files (default: test_*.py)
  -h, --help     print this message
USAGE
}

usage_error() {
  printf '%s\n' "run-tool-tests: $1" >&2
  usage >&2
  exit 2
}

pattern_argument=""
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
    --*)
      usage_error "unknown option: $1"
      ;;
    *)
      if [[ -n "$pattern_argument" ]]; then
        usage_error "only one pattern may be given"
      fi
      pattern_argument="$1"
      shift
      ;;
  esac
done

if [[ -n "$pattern_argument" ]]; then
  pattern="$pattern_argument"
fi

fetch_script="$script_root/tools/ci/fetch-core.sh"
if [[ -z "${ROVIA_CORE_ROOT:-}" ]]; then
  ROVIA_CORE_ROOT=$("$fetch_script")
  export ROVIA_CORE_ROOT
fi

files=()
while IFS= read -r file; do
  files+=("$file")
done < <(
  find "$root/tools" -type d \( -name .build -o -name .git \) -prune -o \
    -type f -name "$pattern" -print | LC_ALL=C sort
)

if [[ ${#files[@]} -eq 0 ]]; then
  printf '%s\n' "run-tool-tests: no test files matched $pattern under $root/tools" >&2
  exit 1
fi

failures=0
for file in "${files[@]}"; do
  relative="${file#"$root"/}"
  printf '%s\n' "run-tool-tests: $relative"
  if ! python3 "$file"; then
    failures=$((failures + 1))
  fi
done

if [[ $failures -ne 0 ]]; then
  printf '%s\n' "run-tool-tests: $failures of ${#files[@]} test files failed" >&2
  exit 1
fi

# The lint gate runs here rather than beside this script in a document, because the
# verification record claimed it had been run and nothing about the claim made a
# reader able to reproduce it. It is a gate in the same sense the tests are.
printf '%s\n' "run-tool-tests: check-python-lint.sh"
if ! "$script_root/tools/ci/check-python-lint.sh" --root "$root"; then
  printf '%s\n' "run-tool-tests: the Python lint gate reported findings" >&2
  exit 1
fi

# Beside the lint gate rather than inside it: a different tool and a different class of
# finding. pyflakes reports what a module *does*; this reports what it emits while
# compiling. The two are separate gates because a file can be perfectly clean and still
# warn — one was, with an invalid escape sequence in a docstring, which pyflakes says
# nothing about and which on a future interpreter stops the module importing and takes
# every test in it with it.
printf '%s\n' "run-tool-tests: check-python-warnings.sh"
if ! "$script_root/tools/ci/check-python-warnings.sh" --root "$root"; then
  printf '%s\n' "run-tool-tests: the Python warnings gate reported findings" >&2
  exit 1
fi

# A third gate, and the only one that is not about code at all. Everything above
# checks a property of the source; this one checks a property of the publication —
# that nothing in the tree is a secret, a developer's home directory, or a build
# product. It runs last because it is the one whose failure means the repository
# should not be published as it stands, and it has to keep running after the commit
# that publishes it, which is the only way a hygiene claim stays true.
printf '%s\n' "run-tool-tests: check-repository-hygiene.sh"
if ! "$script_root/tools/ci/check-repository-hygiene.sh" --root "$root"; then
  printf '%s\n' "run-tool-tests: the repository hygiene gate reported findings" >&2
  exit 1
fi

printf '%s\n' "run-tool-tests: ${#files[@]} test files passed"
