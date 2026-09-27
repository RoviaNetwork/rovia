#!/usr/bin/env bash
# Verify the metadata of a processed iOS bundle.
#
# "The build succeeded" is not evidence that the bundle is usable. A processed
# Info.plist can still contain an unexpanded build variable, a missing
# CFBundleExecutable, a version that cannot be used for distribution, or no
# Packet Tunnel extension at all, and none of those stop xcodebuild. This gate
# reads the bundle that was actually built and refuses the defects that a
# release must not ship.
#
# Usage:
#   verify-bundle-metadata.sh <bundle> [--expect-version VERSION]
#                             [--expect-identifier IDENTIFIER]
#
# Exit status: 0 the bundle is usable, 1 a defect was found, 2 usage error.
set -euo pipefail

bundle=""
expect_version=""
expect_identifier=""

usage() {
  cat <<'USAGE'
usage: verify-bundle-metadata.sh <bundle> [--expect-version VERSION] [--expect-identifier ID]

  <bundle>                 built .app bundle
  --expect-version         required CFBundleShortVersionString
  --expect-identifier      required CFBundleIdentifier
  -h, --help               print this message
USAGE
}

usage_error() {
  printf '%s\n' "verify-bundle-metadata: $1" >&2
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
    --expect-version) require_value "--expect-version" "$#"; expect_version="$2"; shift 2 ;;
    --expect-version=*) expect_version="${1#*=}"; shift ;;
    --expect-identifier) require_value "--expect-identifier" "$#"; expect_identifier="$2"; shift 2 ;;
    --expect-identifier=*) expect_identifier="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    --*) usage_error "unknown option: $1" ;;
    *)
      if [[ -n "$bundle" ]]; then
        usage_error "unexpected argument: $1"
      fi
      bundle="$1"
      shift
      ;;
  esac
done

if [[ -z "$bundle" ]]; then
  usage_error "a bundle path is required"
fi

if [[ ! -d "$bundle" ]]; then
  printf '%s\n' "verify-bundle-metadata: bundle does not exist: $bundle" >&2
  exit 1
fi

python3 - "$bundle" "$expect_version" "$expect_identifier" <<'PY'
import plistlib
import re
import sys
from pathlib import Path

bundle = Path(sys.argv[1])
expect_version = sys.argv[2]
expect_identifier = sys.argv[3]
EXTENSION_NAME = "RoviaTunnel"
APP_PACKAGE_TYPE = "APPL"
EXTENSION_PACKAGE_TYPE = "XPC!"
BUILD_VARIABLE = re.compile(r"\$\(|\$\{")


def fail(message):
    print(f"verify-bundle-metadata: {message}", file=sys.stderr)
    raise SystemExit(1)


def report(message):
    print(f"verify-bundle-metadata: {message}")


def load(path: Path) -> dict:
    if not path.is_file():
        fail(f"{path.name} is missing: {path}")
    try:
        with path.open("rb") as stream:
            document = plistlib.load(stream)
    except Exception as error:  # plistlib raises several unrelated types
        fail(f"{path} is not a readable property list: {error}")
    if not isinstance(document, dict):
        fail(f"{path} is not a property-list dictionary")
    return document


def required_string(document, key, where, package_type=None):
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{where} has no {key}")
    if BUILD_VARIABLE.search(value):
        fail(f"{where} {key} contains an unexpanded build variable: {value}")
    if package_type is not None and document.get("CFBundlePackageType") != package_type:
        fail(f"{where} CFBundlePackageType must be {package_type}, found {document.get('CFBundlePackageType')!r}")
    return value


app_plist = bundle / "Info.plist"
document = load(app_plist)
where = "the application bundle"

identifier = required_string(document, "CFBundleIdentifier", where)
executable = required_string(document, "CFBundleExecutable", where)
required_string(document, "CFBundlePackageType", where, APP_PACKAGE_TYPE)
short_version = required_string(document, "CFBundleShortVersionString", where)
build = required_string(document, "CFBundleVersion", where)

if not re.fullmatch(r"[0-9]+(\.[0-9]+)*", short_version):
    fail(f"the application bundle CFBundleShortVersionString is not a dotted version: {short_version}")
if not re.fullmatch(r"[0-9]+", build):
    fail(f"the application bundle CFBundleVersion must be numeric, found {build!r}")
if not (bundle / executable).is_file():
    fail(f"the application bundle CFBundleExecutable {executable} has no binary in the bundle")
if expect_version and short_version != expect_version:
    fail(f"the application bundle version {short_version} is not the expected {expect_version}")
if expect_identifier and identifier != expect_identifier:
    fail(f"the application bundle identifier {identifier} is not the expected {expect_identifier}")

extension = bundle / "PlugIns" / f"{EXTENSION_NAME}.appex"
if not extension.is_dir():
    fail(f"the Packet Tunnel extension {EXTENSION_NAME}.appex is not embedded in the bundle")
extension_document = load(extension / "Info.plist")
extension_where = "the Packet Tunnel extension"
extension_identifier = required_string(
    extension_document, "CFBundleIdentifier", extension_where, EXTENSION_PACKAGE_TYPE
)
extension_executable = required_string(extension_document, "CFBundleExecutable", extension_where)
extension_version = required_string(extension_document, "CFBundleShortVersionString", extension_where)
extension_build = required_string(extension_document, "CFBundleVersion", extension_where)
if not re.fullmatch(r"[0-9]+", extension_build):
    fail(f"the Packet Tunnel extension CFBundleVersion must be numeric, found {extension_build!r}")
if not extension_identifier.startswith(identifier + "."):
    fail(
        f"the extension identifier {extension_identifier} is not a child of the application "
        f"identifier {identifier}"
    )
if extension_version != short_version or extension_build != build:
    fail(
        f"the Packet Tunnel extension version {extension_version} ({extension_build}) does not match "
        f"the application version {short_version} ({build})"
    )
if not (extension / extension_executable).is_file():
    fail(f"the Packet Tunnel extension CFBundleExecutable {extension_executable} has no binary in the bundle")

entitlements = sorted(path.name for path in bundle.parent.glob("*.entitlements"))
report(
    f"{bundle.name}: {identifier} version {short_version} ({build}) executable {executable}, "
    f"{EXTENSION_NAME} {extension_identifier} embedded"
)
if entitlements:
    report(f"adjacent entitlement files: {', '.join(entitlements)}")
PY
