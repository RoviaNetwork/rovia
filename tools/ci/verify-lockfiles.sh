#!/usr/bin/env bash
# Verify the repository's lock files.
#
# Two things can silently break reproducibility without breaking the build:
#
#   a local SwiftPM package quietly gains an external dependency with no
#   Package.resolved, so the same tag resolves different code on a clean
#   machine; and
#   the engine lock disappears or drifts from the single-runtime policy.
#
# Every external dependency must have a Package.resolved whose pins carry an
# exact revision, and the engine lock must exist and still declare the MVP
# policy. Engine approval and artifact verification belong to
# tools/ci/verify-engine-checksums.sh, which runs separately.
#
# Usage:
#   verify-lockfiles.sh [--root PATH]
#
# Exit status: 0 accepted, 1 refused, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
root="$script_root"

usage() {
  cat <<'USAGE'
usage: verify-lockfiles.sh [--root PATH]

  --root PATH    repository root to verify (default: this repository)
  -h, --help     print this message
USAGE
}

usage_error() {
  printf '%s\n' "verify-lockfiles: $1" >&2
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
  printf '%s\n' "verify-lockfiles: repository root does not exist: $root" >&2
  exit 1
fi

python3 - "$root" "$script_root/tools/ci/local-packages.txt" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
package_list = Path(sys.argv[2])

LOCK_NAME = "engines.lock.json"
PIN_REVISION = re.compile(r"^[0-9a-fA-F]{40}$")
PACKAGE_CALL = re.compile(r"\.package\s*\(", re.S)
ARGUMENT_LABEL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*:")
# The arguments SwiftPM accepts on a package dependency. ``path`` is a local
# dependency; the rest identify a remote revision that has to be locked.
LOCAL_ARGUMENTS = {"path"}
EXTERNAL_ARGUMENTS = {
    "url",
    "id",
    "name",
    "from",
    "exact",
    "branch",
    "revision",
}
KNOWN_ARGUMENTS = LOCAL_ARGUMENTS | EXTERNAL_ARGUMENTS | {"traits", "productFilter"}


def fail(message):
    print(f"rovia: {message}", file=sys.stderr)
    raise SystemExit(1)


def report(message):
    print(f"rovia: {message}")


def argument_span(text: str, start: int) -> str | None:
    """Return the balanced parenthesised argument list that follows ``start``."""
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == '"':
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == '"':
                    break
                index += 1
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
        index += 1
    return None


def strip_strings(text: str) -> str:
    """Blank out quoted literals so a URL is not read as an argument label."""
    result: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != '"':
            result.append(text[index])
            index += 1
            continue
        result.append('""')
        index += 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
                continue
            if text[index] == '"':
                break
            index += 1
        index += 1
    return "".join(result)


def strip_comments(text: str) -> str:
    """Blank out Swift comments so an example is not read as a declaration.

    A manifest may document the form it deliberately does not use, and
    ``// .package(magic: true)`` in a comment would otherwise be refused as an
    unrecognised dependency. The scan has to know about string literals: a URL
    contains ``//``, so a stripper that is not string-aware truncates the
    manifest at the first remote dependency and silently stops reading the rest.
    Comment characters are replaced by spaces so offsets stay meaningful.
    """
    result: list[str] = []
    index = 0
    depth = 0
    while index < len(text):
        if text[index] == '"':
            # A string literal runs to its closing quote, honouring escapes.
            result.append(text[index])
            index += 1
            while index < len(text):
                result.append(text[index])
                if text[index] == "\\" and index + 1 < len(text):
                    index += 1
                    result.append(text[index])
                    index += 1
                    continue
                if text[index] == '"':
                    index += 1
                    break
                index += 1
            continue
        if text.startswith("//", index):
            while index < len(text) and text[index] != "\n":
                result.append(" ")
                index += 1
            continue
        if text.startswith("/*", index):
            depth += 1
            result.append("  ")
            index += 2
            while index < len(text) and depth:
                if text.startswith("/*", index):
                    depth += 1
                    result.append("  ")
                    index += 2
                    continue
                if text.startswith("*/", index):
                    depth -= 1
                    result.append("  ")
                    index += 2
                    continue
                result.append("\n" if text[index] == "\n" else " ")
                index += 1
            if depth:
                fail("a block comment is not closed: /*")
            continue
        result.append(text[index])
        index += 1
    return "".join(result)


def external_dependencies(text: str) -> tuple[list[str], list[str]]:
    """Classify every ``.package(...)`` declaration in a manifest.

    A declaration that mentions ``path:`` is a sibling package inside this
    repository and needs no lock file. A declaration that names a remote source
    needs a Package.resolved with exact revisions. Anything else is refused: a
    new SwiftPM form must not be mistaken for a local dependency.
    """
    external: list[str] = []
    local: list[str] = []
    for match in PACKAGE_CALL.finditer(strip_comments(text)):
        arguments = argument_span(text, match.end() - 1)
        if arguments is None:
            fail(f"a .package declaration is not closed: {match.group(0)!r}")
        labels = set(ARGUMENT_LABEL.findall(strip_strings(arguments)))
        unknown = labels - KNOWN_ARGUMENTS
        if unknown:
            fail(
                f"an unrecognised .package form uses {sorted(unknown)}; add it to "
                "tools/ci/verify-lockfiles.sh instead of assuming it is local"
            )
        if labels & LOCAL_ARGUMENTS:
            local.append(arguments.strip())
        elif labels & EXTERNAL_ARGUMENTS:
            external.append(arguments.strip())
        else:
            fail(f"a .package declaration names no dependency source: {arguments.strip()!r}")
    return external, local


def listed_packages():
    if not package_list.is_file():
        fail(f"the local package list is missing: {package_list}")
    entries = [
        line.strip()
        for line in package_list.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not entries:
        fail(f"the local package list is empty: {package_list}")
    return entries


packages = listed_packages()

for relative in packages:
    manifest = root / relative / "Package.swift"
    if not manifest.is_file():
        fail(f"the local package manifest is missing: {relative}/Package.swift")
    text = strip_comments(manifest.read_text(encoding="utf-8"))
    if not re.search(r'name:\s*"[^"]+"', text):
        fail(f"{relative}/Package.swift does not declare a package name")

lock_path = root / LOCK_NAME
if not lock_path.is_file():
    fail(f"{LOCK_NAME} is required")
try:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
except ValueError as error:
    fail(f"{LOCK_NAME} is not valid JSON: {error}")
if not isinstance(lock, dict):
    fail(f"{LOCK_NAME} must contain a JSON object")
if lock.get("schemaVersion") != 1:
    fail(f"{LOCK_NAME} has an unsupported schema version: {lock.get('schemaVersion')!r}")
if not isinstance(lock.get("runtimePolicy"), dict):
    fail(f"{LOCK_NAME} is missing runtimePolicy")
if not isinstance(lock.get("productionEngines"), list):
    fail(f"{LOCK_NAME} is missing productionEngines")
if not isinstance(lock.get("candidates"), dict):
    fail(f"{LOCK_NAME} is missing candidates")


def verify_resolved(relative, resolved_path):
    try:
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
    except ValueError as error:
        fail(f"{relative}/Package.resolved is not valid JSON: {error}")
    pins = resolved.get("pins")
    if not isinstance(pins, list) or not pins:
        fail(f"{relative}/Package.resolved declares no pins")
    for pin in pins:
        state = pin.get("state") if isinstance(pin, dict) else None
        if not isinstance(state, dict):
            fail(f"{relative}/Package.resolved has a pin without state")
        if state.get("branch"):
            fail(
                f"{relative}/Package.resolved pins a branch for {pin.get('identity')!r}; "
                "an exact revision is required"
            )
        if state.get("version") and not state.get("revision"):
            fail(
                f"{relative}/Package.resolved pins a version for {pin.get('identity')!r} "
                "without a revision"
            )
        revision = state.get("revision")
        if not isinstance(revision, str) or not PIN_REVISION.fullmatch(revision):
            fail(
                f"{relative}/Package.resolved does not pin an exact revision for "
                f"{pin.get('identity')!r}"
            )
        report(
            f"{relative}/Package.resolved pins {pin.get('identity')!r} at revision {revision}"
        )


locked = 0
local_dependencies = 0
for relative in packages:
    manifest = (root / relative / "Package.swift").read_text(encoding="utf-8")
    external, local = external_dependencies(manifest)
    local_dependencies += len(local)
    if not external:
        continue
    resolved_path = root / relative / "Package.resolved"
    if not resolved_path.is_file():
        fail(
            f"{relative} declares an external dependency without a Package.resolved; "
            "an unlocked dependency breaks reproducibility"
        )
    verify_resolved(relative, resolved_path)
    locked += 1
    for declaration in external:
        report(f"{relative} depends on {declaration.splitlines()[0]}")

report(
    f"{len(packages)} local package manifests verified, {locked} with locked external "
    f"dependencies, {local_dependencies} local path dependencies"
)
PY
