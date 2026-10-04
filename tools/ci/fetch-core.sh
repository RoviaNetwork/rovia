#!/usr/bin/env bash
# Fetch the pinned rovia-core sources for gates that read core text.
#
# The app builds core as a pinned SPM dependency and never assumes a sibling
# checkout; the text gates (trace leaks, redacted contracts, evaluator
# duplication) need the same sources as files, so this script downloads the
# tarball of the tag in tools/ci/core-pin.txt, verifies its SHA-256, and
# unpacks it into a cache. Prints the resulting directory.
#
# Cache integrity: the marker records the exact tag AND tarball SHA the cache
# was built from. Both the normal path and --check compare the marker against
# the current pin: a pin change (or a stale/foreign cache) refetches instead
# of silently reusing. Marker presence alone is never treated as proof.
# Parallel invocations serialize on an atomic mkdir lock.
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
sentinel="core/config/Package.swift"

marker_matches_pin() {
  test -f "$marker" || return 1
  test -f "$cache_dir/$sentinel" || return 1
  recorded_tag="$(sed -n '1p' "$marker")"
  recorded_sha="$(sed -n '2p' "$marker")"
  test "$recorded_tag" = "$tag" || return 1
  test "$recorded_sha" = "$expected_sha" || return 1
  return 0
}

if [ "${1:-}" = "--check" ]; then
  marker_matches_pin \
    || fail "no verified core checkout for $tag ($expected_sha); run tools/ci/fetch-core.sh"
  printf '%s\n' "$cache_dir"
  exit 0
fi

lock_dir="$cache_base/.lock-$tag"
mkdir -p "$cache_base" || fail "could not create cache base $cache_base"
i=0
while ! mkdir "$lock_dir" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 300 ]; then
    fail "timed out waiting for the core cache lock"
  fi
  sleep 1
done
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT

if marker_matches_pin; then
  printf '%s\n' "$cache_dir"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"; rmdir "$lock_dir" 2>/dev/null || true' EXIT
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
test -f "$cache_dir/$sentinel" \
  || fail "unpacked tree has no $sentinel"
printf '%s\n%s\n' "$tag" "$expected_sha" > "$marker"
printf '%s\n' "$cache_dir"
