#!/usr/bin/env bash
# Compile every Python file in tools/ with warnings as errors, and fail on any.
#
# This covers a class pyflakes does not: an invalid escape sequence in a docstring is
# a SyntaxWarning on 3.12 and earlier and is scheduled to become a SyntaxError, which
# means a module that mentions `\w` in a non-raw docstring stops importing altogether.
# When that happens the tests inside that module do not fail — they never run — and
# whatever gates it held, such as the pinned pass-section list, go with it. One such
# docstring was in this repository: the warning appeared on stderr during a normal run,
# the lint gate reported nothing, and it was found only because somebody compiled the
# file with -W error::SyntaxWarning.
#
# So a warning is the error here, not output to read. Two passes run over every file:
# `py_compile` with warnings as errors, which is what turns a warning into a failure,
# and `compileall`, the interpreter's own check that a file compiles. Neither imports
# the module, so nothing is executed.
#
# Usage:
#   check-python-warnings.sh [--root PATH]
#
# Exit status: 0 every file compiles without a warning, 1 a warning or a file that
# does not compile, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
root="$script_root"

usage() {
  cat <<'USAGE'
usage: check-python-warnings.sh [--root PATH]

  --root PATH   repository root to check (default: this repository)
  -h, --help    print this message

Exits 1 if any file emits a warning while compiling with warnings as errors, or does
not compile. Refuses to report success if it found no files: a gate that checked
nothing must not look like a gate that passed.
USAGE
}

usage_error() {
  printf '%s\n' "check-python-warnings: $1" >&2
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage_error "unknown option: $1"
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' "check-python-warnings: python3 is not on PATH" >&2
  printf '%s\n' "check-python-warnings: refusing to report success from a check that did not run" >&2
  exit 1
fi

python_version="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# A while-read loop rather than mapfile: the macOS default bash is 3.2, which has no
# mapfile, and this script runs on a developer machine as well as in CI.
#
# The count is kept in a scalar as well as derivable from the array. On the macOS
# default bash 3.2, `set -u` plus an EXIT trap that runs a command turns an unbound
# array expansion into exit 0 rather than exit 1 — so a guard written as
# `${#files[@]}` relying on `set -u` to stop the script fails open, and the runner's
# `if !` reads that as success. A scalar is never unbound, so the guard below is a
# real `exit 1`, and the interpreter step refuses an empty list independently.
files=()
file_count=0
while IFS= read -r file; do
  files+=("$file")
  file_count=$((file_count + 1))
done < <(
  find "$root/tools" -type d \( -name .build -o -name __pycache__ \) -prune -o \
    -type f -name '*.py' -print | LC_ALL=C sort
)

if [[ $file_count -eq 0 ]]; then
  printf '%s\n' "check-python-warnings: no Python files under $root/tools" >&2
  printf '%s\n' "check-python-warnings: refusing to report success from a check that checked nothing" >&2
  exit 1
fi

printf '%s\n' "check-python-warnings: Python ${python_version}, ${#files[@]} files, warnings are errors"

# The byte-compiled output goes to a throwaway directory: `py_compile` refuses
# `/dev/null` as a target, and writing next to the sources would leave .pyc files in
# the tree. A directory is created and removed here rather than left for the caller.
bytecode_dir="$(mktemp -d)"
trap 'rm -rf "$bytecode_dir"' EXIT

if ! python3 -W error::SyntaxWarning -W error::DeprecationWarning - \
    "$bytecode_dir" ${files[@]+"${files[@]}"} <<'PYTHON'
import os
import py_compile
import sys

cache, paths = sys.argv[1], sys.argv[2:]
if not paths:
    # The second refusal. The guard above is the first; this is here so that
    # removing the guard does not turn an empty tree into a success, which is what
    # happens on bash 3.2 when the unbound array expansion exits 0.
    sys.stderr.write("check-python-warnings: no files were passed to check\n")
    sys.exit(1)
failures = 0
for path in paths:
    target = os.path.join(cache, os.path.basename(path) + "c")
    try:
        py_compile.compile(path, cfile=target, doraise=True)
    except py_compile.PyCompileError as error:
        sys.stderr.write(f"{path}: {error}\n")
        failures += 1
    except Exception as error:
        # A SyntaxWarning promoted to an error by -W arrives as a SyntaxError rather
        # than a PyCompileError, and it has to be reported the same way.
        sys.stderr.write(f"{path}: {type(error).__name__}: {error}\n")
        failures += 1
sys.exit(1 if failures else 0)
PYTHON
then
  printf '%s\n' "check-python-warnings: at least one file warns or does not compile" >&2
  exit 1
fi

# The second pass, so "compiles" is not only "compiles under -W". `compileall` is the
# interpreter's own check; -f forces a recompile so a cached .pyc cannot stand in for
# one, and its output goes to a throwaway cache directory so nothing is left behind.
if ! python3 - "$root" ${files[@]+"${files[@]}"} <<'PYTHON'
import compileall
import sys

sys.exit(0 if compileall.compile_dir(
    sys.argv[1], quiet=1, force=True, legacy=False,
    rx=__import__("re").compile(r"/(\.build|__pycache__)/"),
) else 1)
PYTHON
then
  printf '%s\n' "check-python-warnings: compileall reported a file that does not compile" >&2
  exit 1
fi

printf '%s\n' "check-python-warnings: no warnings"
