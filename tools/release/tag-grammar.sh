# Shared release tag grammar.
#
# Three gates have to agree on what a release tag looks like: the tag check, the
# provenance manifest, and the release-input verifier. A tag that one of them
# accepts and another rejects turns into a build that is archived and then
# refused, so the grammar lives here and is sourced rather than restated.
#
# The grammar is the release subset of semantic versioning 2.0.0:
#
#   vMAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]
#
# with no leading zeros in MAJOR, MINOR, PATCH, or in any numeric prerelease
# identifier. The leading-zero rule inside the prerelease is why this is code
# and not one regular expression: `1.2.3-01` looks like a prerelease to a shape
# check and is not a valid semver identifier.
#
# Usage:
#   source "$(dirname "$0")/tag-grammar.sh"
#   rovia_tag_is_valid "$tag"   # 0 when the tag is a release tag
#   rovia_tag_version "$tag"    # prints the version part, without the v
#
# This file is sourced, not executed.

rovia_tag_is_valid() {
  local tag="${1-}"
  [[ "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || return 1
  local prerelease="${BASH_REMATCH[4]-}"
  [[ -n "$prerelease" ]] || return 0
  prerelease="${prerelease#-}"
  local -a identifiers
  local identifier
  IFS='.' read -r -a identifiers <<< "$prerelease"
  for identifier in "${identifiers[@]}"; do
    if [[ "$identifier" =~ ^[0-9]+$ ]]; then
      if [[ ${#identifier} -gt 1 && "${identifier:0:1}" == "0" ]]; then
        return 1
      fi
    fi
  done
  return 0
}

rovia_tag_version() {
  local version="${1#v}"
  printf '%s\n' "${version%%[-+]*}"
}
