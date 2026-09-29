#!/usr/bin/env bash
# Fetch the pinned rovia-core sources for gates that read core text.
#
# The app builds core as a pinned SPM dependency and never assumes a sibling
# checkout; the text gates (trace leaks, redacted contracts, evaluator
# duplication) need the same sources as files, so this script downloads the
# tarball of the tag in tools/ci/core-pin.txt, verifies its SHA-256, and
# unpacks it into a cache. Prints the resulting directory.
#
# Usage:
#   ROVIA_CORE_ROOT="$(tools/ci/fetch-core.sh)"   # uses cache when fresh
#   tools/ci/fetch-core.sh --check                  # verify cache, no network
#
# Exit status: 0 directory printed, 1 fetch or verification failure.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
pin_file="$script_root/tools/ci/core-pin.txt"
cache_base="${XDG_CACHE_HOME:-$HOME/.cache}/rovia-core"

fail() {
  printf '%s\n' "fetch-core: $1" >&2
  exit 1
}

# shellcheck disable=SC1090
tag="$(sed -n 's/^ROVIA_CORE_TAG=//p' "$pin_file")"
expected_sha="$(sed -n 's/^ROVIA_CORE_TARBALL_SHA256=//p' "$pin_file")"
test -n "$tag" || fail "no ROVIA_CORE_TAG in tools/ci/core-pin.txt"
test -n "$expected_sha" || fail "no ROVIA_CORE_TARBALL_SHA256 in tools/ci/core-pin.txt"

cache_dir="$cache_base/$tag"
marker="$cache_dir/.fetch-core-ok"

if [ "${1:-}" = "--check" ]; then
  test -f "$marker" || fail "no verified core checkout for $tag; run tools/ci/fetch-core.sh"
  printf '%s\n' "$cache_dir"
  exit 0
fi

if [ -f "$marker" ]; then
  printf '%s\n' "$cache_dir"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
archive="$tmp/core.tar.gz"
curl -sfSL "https://github.com/RoviaNetwork/rovia-core/archive/refs/tags/$tag.tar.gz" \
  -o "$archive" || fail "could not download rovia-core $tag"
actual_sha=$(shasum -a 256 "$archive" | cut -d' ' -f1)
test "$actual_sha" = "$expected_sha" \
  || fail "tarball SHA mismatch for $tag: got $actual_sha"
rm -rf "$cache_dir"
mkdir -p "$cache_dir"
tar xzf "$archive" -C "$cache_dir" --strip-components=1 \
  || fail "could not unpack rovia-core $tag"
test -f "$cache_dir/core/config/Package.swift" \
  || fail "unpacked tree has no core/config/Package.swift"
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$marker"
printf '%s\n' "$cache_dir"
