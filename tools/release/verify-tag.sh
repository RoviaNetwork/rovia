#!/usr/bin/env bash
# Verify that a release tag is well formed before anything is signed.
#
# The grammar lives in tools/release/tag-grammar.sh and is shared with the
# provenance manifest and the release-input verifier, so a tag that passes here
# cannot fail later after a build has been archived.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=tools/release/tag-grammar.sh
source "$script_root/tools/release/tag-grammar.sh"

if [[ $# -ne 1 ]]; then
  printf '%s\n' "usage: $0 <tag>" >&2
  exit 2
fi

tag="$1"
if [[ -z "$tag" ]]; then
  printf '%s\n' "verify-tag: a release tag is required" >&2
  exit 1
fi

if ! rovia_tag_is_valid "$tag"; then
  printf '%s\n' "verify-tag: invalid release tag: $tag" >&2
  printf '%s\n' "verify-tag: expected vMAJOR.MINOR.PATCH[-PRERELEASE][+BUILD] with no leading zeros" >&2
  exit 1
fi

printf '%s\n' "verify-tag: $tag is a valid release tag"
