#!/usr/bin/env bash
# Fail on anything that must not reach a public repository: a secret, a machine
# path that names the developer, or a build artifact that got committed.
#
# Every other gate in this directory checks a property of the code. This one checks a
# property of the *publication*, which is why it exists: a repository that is about to
# be handed to external reviewers has to be able to say that nothing in it is somebody's
# certificate, somebody's home directory, or last week's DerivedData. That is a claim
# about what will be published, so it is checked against the set of files git would
# publish, not against everything sitting in the working directory.
#
# That distinction is the whole design. A gate that walked the working tree would fail
# on any Mac, because macOS writes a .DS_Store into a directory as soon as anyone
# opens it in Finder, and .DS_Store is correctly in .gitignore. A gate that always fails
# is a gate that gets deleted, and then the claim it was holding is gone with nothing
# left to notice.
#
# So the file set comes from `git ls-files --cached --others --exclude-standard`: the
# tracked files plus the untracked ones git does not ignore. That is precisely the set
# a `git push` would carry, and it works with zero commits, which matters because this
# gate has to run before the first one.
#
# Three checks against that set:
#
#   1. Secrets. High-signal token shapes only.
#   2. Machine paths. An absolute path under /Users or /home names one developer and
#      breaks on everyone else's machine. Placeholder names are allowed, because a
#      negative test needs a path shape and "someone" is not a person.
#   3. Artifacts and oversized files.
#
# And a fourth, against `.gitignore` rather than the file set, because a clean tree can
# also be a lucky tree: the ignore rules have to cover these classes so the next
# contributor's clone is clean for a reason.
#
# Usage:
#   check-repository-hygiene.sh [--root PATH]
#
# Exit status: 0 nothing found, 1 something found, 2 usage error.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../.." && pwd)"
root="$script_root"

usage() {
  cat <<'USAGE'
usage: check-repository-hygiene.sh [--root PATH]

  --root PATH   repository root to check (default: this repository)
  -h, --help    print this message

Checks the set of files git would publish: a secret shape, a machine-specific path, a
build artifact, or a file over 4 MiB is a failure, as is a .gitignore that no longer
covers one of the artifact classes below.

Refuses to report success if it published nothing to look at: a gate that checked
nothing must not look like a gate that passed.
USAGE
}

usage_error() {
  printf '%s\n' "check-repository-hygiene: $1" >&2
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

if [[ ! -d "$root" ]]; then
  printf '%s\n' "check-repository-hygiene: $root is not a directory" >&2
  exit 2
fi

if ! command -v git >/dev/null 2>&1; then
  printf '%s\n' "check-repository-hygiene: git is not on PATH" >&2
  printf '%s\n' "check-repository-hygiene: refusing to report success from a check that did not run" >&2
  exit 1
fi

# The publishable set, relative to the root. Falls back to a plain walk when the root
# is not a git repository at all, so the gate still works in a copy of the tree that has
# no .git — which is how its own tests exercise it, and how a reviewer exercises it.
if git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
  published=()
  published_count=0
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    published+=("$path")
    published_count=$((published_count + 1))
  done < <(git -C "$root" ls-files --cached --others --exclude-standard | LC_ALL=C sort)
  basis="git ls-files (cached plus untracked, excluding ignored)"
else
  published=()
  published_count=0
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    published+=("${path#"$root"/}")
    published_count=$((published_count + 1))
  done < <(find "$root" \( -name .git -o -name .build -o -name DerivedData \
              -o -name __pycache__ -o -name .superpowers \) -prune -o \
              -type f -print | LC_ALL=C sort)
  basis="filesystem walk (the root is not a git repository)"
fi

# The count is a scalar as well as derivable from the array. On the macOS default bash
# 3.2, `set -u` plus an EXIT trap that runs a command turns an unbound array expansion
# into exit 0 rather than exit 1, and the runner's `if !` reads that as success.
if [[ $published_count -eq 0 ]]; then
  printf '%s\n' "check-repository-hygiene: no publishable files under $root" >&2
  printf '%s\n' "check-repository-hygiene: refusing to report success from a check that checked nothing" >&2
  exit 1
fi

printf '%s\n' "check-repository-hygiene: ${published_count} publishable files, via ${basis}"

# This gate and its test are excluded from the secret scan, because a scanner written
# as source contains the shapes it searches for. The exclusion is two paths, named here
# and asserted by the gate's own test, so it cannot quietly widen.
skip_secrets=(
  "tools/ci/check-repository-hygiene.sh"
  "tools/ci/test_check_repository_hygiene.py"
)

scan=()
for path in ${published[@]+"${published[@]}"}; do
  case "$path" in
    *.png|*.jpg|*.jpeg|*.gif|*.ico|*.pdf|*.zip|*.gz) continue ;;
  esac
  in_skip=0
  for skip in ${skip_secrets[@]+"${skip_secrets[@]}"}; do
    if [[ "$path" == "$skip" ]]; then
      in_skip=1
      break
    fi
  done
  if [[ $in_skip -eq 1 ]]; then
    continue
  fi
  scan+=("$root/$path")
done

failures=0

# High-signal credential shapes. Deliberately not a generic "password = value" rule:
# this repository's tests, documentation and CI fixtures all contain the words
# password, token and secret legitimately, and a rule that flagged those would be
# turned off within a day. These are shapes with no legitimate occurrence here.
secret_pattern='BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}'

# A machine path names one developer. Placeholder first names are the exception,
# because a negative test needs the shape and "someone" is not a person.
machine_pattern='/(Users|home)/[A-Za-z0-9._-]+/'
placeholder_names='someone|example|user|me|test|runner|builder|ci'

if [[ ${#scan[@]} -gt 0 ]]; then
  while IFS= read -r hit; do
    [[ -n "$hit" ]] || continue
    printf '%s\n' "check-repository-hygiene: possible secret: $hit" >&2
    failures=$((failures + 1))
  done < <(grep -nE "$secret_pattern" ${scan[@]+"${scan[@]}"} 2>/dev/null || true)

  while IFS= read -r hit; do
    [[ -n "$hit" ]] || continue
    printf '%s\n' "check-repository-hygiene: possible machine-specific path: $hit" >&2
    failures=$((failures + 1))
  done < <(grep -nE "$machine_pattern" ${scan[@]+"${scan[@]}"} 2>/dev/null \
    | grep -vE "/(Users|home)/($placeholder_names)(/|$)" || true)
fi

# Artifacts, checked against the publishable set rather than the working tree: a
# .DS_Store that .gitignore already excludes is not something a push would carry, and
# failing on it would train the reader to ignore this gate.
artifact_pattern='(^|/)\.DS_Store$|\.pyc$|\.p12$|\.mobileprovision$|\.cer$|\.pem$|\.key$|\.dia$|\.o$|\.swiftmodule$|\.pcm$|\.xcuserstate$|(^|/)\.env$'

for path in ${published[@]+"${published[@]}"}; do
  if [[ "$path" =~ $artifact_pattern ]]; then
    printf '%s\n' "check-repository-hygiene: build artifact would be published: $path" >&2
    failures=$((failures + 1))
  fi
  size="$(wc -c <"$root/$path" 2>/dev/null || printf '0')"
  if [[ "$size" -gt 4194304 ]]; then
    printf '%s\n' "check-repository-hygiene: file larger than 4 MiB would be published: $path (${size} bytes)" >&2
    failures=$((failures + 1))
  fi
done

# .gitignore has to cover the classes above. The file set being clean is a fact about
# this commit; the rules covering it are a fact about the next one.
required_ignores=(
  '.DS_Store'
  'DerivedData/'
  'build/'
  '.build/'
  '.swiftpm/'
  'xcuserdata/'
  '*.xcuserstate'
  '__pycache__/'
  '*.pyc'
  '*.p12'
  '*.mobileprovision'
  '*.cer'
  '*.key'
  '*.pem'
  '.env'
  '/LibXray.xcframework/'
  '/Libbox.xcframework/'
  '/.superpowers/'
  '/docs/superpowers/'
)

if [[ ! -f "$root/.gitignore" ]]; then
  printf '%s\n' "check-repository-hygiene: $root/.gitignore does not exist" >&2
  exit 1
fi

while IFS= read -r entry; do
  if ! grep -qxF "$entry" "$root/.gitignore"; then
    printf '%s\n' "check-repository-hygiene: .gitignore does not cover '$entry'" >&2
    failures=$((failures + 1))
  fi
done < <(printf '%s\n' ${required_ignores[@]+"${required_ignores[@]}"})

if [[ $failures -ne 0 ]]; then
  printf '%s\n' "check-repository-hygiene: $failures problem(s) found" >&2
  exit 1
fi

printf '%s\n' "check-repository-hygiene: no secrets, machine paths, or artifacts would be published"
