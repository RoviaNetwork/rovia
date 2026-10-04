#!/usr/bin/env bash
# Build the pinned Xray engine artifact for Apple platforms.
#
# The build is gated on the engine lock, not on what a machine happens to
# have: only a candidate that is approved, enabled, and fully pinned — exact
# commit, verified source archive digest, Go toolchain version, gomobile
# version — is built. Each refusal names the input that is missing so the
# next step knows what it has to satisfy. A build never "upgrades" a lock to
# make itself pass.
#
# What the script does, in order:
#
#   1. reads the lock and refuses anything that is not exactly one approved,
#      enabled, fully pinned xray candidate;
#   2. checks the Go toolchain against the lock and installs the pinned
#      gomobile if the one on PATH was built from another revision;
#   3. downloads the pinned source archive and verifies its digest against
#      the lock before a single build command runs;
#   4. builds LibXray.xcframework with gomobile (-trimpath, no build id);
#   5. packs the framework into a deterministic zip (sorted entries, fixed
#      timestamps, fixed permissions) and writes it to the path the lock
#      names in `artifact`;
#   6. prints the artifact digest. When the lock already records a digest,
#      a mismatch is a refusal: the lock pins bytes, not intentions.
#
# Usage:
#   build-apple.sh [--lock PATH] [--out DIR] [--keep-work]
#
# Exit status: 0 only when the pinned, approved engine was actually built.
set -euo pipefail

script_root="$(cd "$(dirname "$0")/../../.." && pwd)"
lock="$script_root/engines.lock.json"
out_dir="$script_root"
keep_work=0

usage() {
  cat <<'USAGE'
usage: build-apple.sh [--lock PATH] [--out DIR] [--keep-work]

  --lock PATH   engine lock to build from (default: <repository>/engines.lock.json)
  --out DIR     directory for the built artifact (default: <repository>)
  --keep-work   keep the temporary work directory (source + xcframework)
  -h, --help    print this message
USAGE
}

usage_error() {
  printf '%s\n' "build-apple: $1" >&2
  usage >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lock)
      [[ $# -lt 2 ]] && usage_error "--lock requires a value"
      lock="$2"
      shift 2
      ;;
    --lock=*)
      lock="${1#*=}"
      shift
      ;;
    --out)
      [[ $# -lt 2 ]] && usage_error "--out requires a value"
      out_dir="$2"
      shift 2
      ;;
    --out=*)
      out_dir="${1#*=}"
      shift
      ;;
    --keep-work)
      keep_work=1
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

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ -f "$lock" ]] || fail "engines.lock.json is required"

# --- 1. The lock decides what may be built ---------------------------------

lock_report="$(mktemp -t rovia-build-apple)"
python3 - "$lock" "$lock_report" <<'PY'
import json
import re
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])


def fail(message):
    print(f"build-apple: {message}", file=sys.stderr)
    raise SystemExit(1)


try:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
except ValueError as error:
    fail(f"the engine lock is not valid JSON: {error}")

engines = lock.get("productionEngines")
candidates = lock.get("candidates")
if not isinstance(engines, list) or not isinstance(candidates, dict):
    fail("the engine lock has no productionEngines or candidates")
if not engines:
    # This refusal is part of the documented foundation state; the wording is
    # pinned by tools/ci/test_ci_docs.py and docs/development/.
    fail("No approved Xray lock entry is available; refusing to build a floating engine")
if engines != ["xray"]:
    fail(f"the App Store MVP builds only xray, not {engines}")
entry = candidates.get("xray")
if not isinstance(entry, dict) or entry.get("approval") != "approved" or entry.get("enabled") is not True:
    fail("the xray candidate is not approved and enabled")
for key in ("version", "commit", "sourceArchiveSha256", "artifact", "goVersion", "toolchain"):
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"the xray candidate is missing {key}")
if not re.fullmatch(r"[0-9a-fA-F]{40}", entry["commit"]):
    fail("the xray commit is not a 40-character hexadecimal commit")
if not re.fullmatch(r"[0-9a-fA-F]{64}", entry["sourceArchiveSha256"]):
    fail("the xray sourceArchiveSha256 is not a 64-character hexadecimal digest")

toolchain = entry["toolchain"]
match = re.search(r"gomobile\s+(v[0-9A-Za-z.+-]+)", toolchain)
if not match:
    fail("the xray toolchain does not pin a gomobile version")
gomobile_version = match.group(1)

source = entry.get("source", "")
if not isinstance(source, str) or not source.startswith("https://github.com/"):
    fail("the xray source is not a https://github.com/ URL")

recorded_sha = entry.get("sha256")
if recorded_sha is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(recorded_sha)):
    fail("the xray sha256 is neither null nor a 64-character hexadecimal digest")

report_path.write_text(
    "\n".join(
        [
            entry["version"],
            entry["commit"],
            entry["sourceArchiveSha256"],
            entry["artifact"],
            entry["goVersion"],
            gomobile_version,
            source.rstrip("/"),
            recorded_sha or "",
            toolchain,
        ]
    )
    + "\n",
    encoding="utf-8",
)
PY

lock_fields=()
while IFS= read -r field; do
  lock_fields+=("$field")
done < "$lock_report"
rm -f "$lock_report"
engine_version="${lock_fields[0]}"
engine_commit="${lock_fields[1]}"
source_sha256="${lock_fields[2]}"
artifact_relpath="${lock_fields[3]}"
lock_go_version="${lock_fields[4]}"
gomobile_version="${lock_fields[5]}"
engine_source="${lock_fields[6]}"
recorded_sha256="${lock_fields[7]}"
engine_toolchain="${lock_fields[8]}"

case "$artifact_relpath" in
  /*|*..*)
    fail "build-apple: the artifact path must stay inside the output directory: $artifact_relpath"
    ;;
esac

# --- 2. Toolchain: the lock's versions, not the machine's -------------------

command -v go >/dev/null 2>&1 || fail "build-apple: no Go toolchain is available"
actual_go="$(go version | awk '{print $3}')"
if [[ "$actual_go" != "$lock_go_version" ]]; then
  fail "build-apple: the lock pins $lock_go_version, found $actual_go"
fi

# Byte-identical output is a property of the whole toolchain, not of Go alone:
# the gobind glue is compiled by the host's clang against the host's SDK, so a
# different Xcode or host architecture produces a different artifact. The lock
# records the reference toolchain; whether this machine's output is comparable
# with the lock's digest is decided by the shared probe, and the build report
# must say which of the two claims is being made.
toolchain_matches_lock=1
if ! "$script_root/tools/build-engine/xray/toolchain-matches-lock.sh" --lock "$lock" >&2; then
  toolchain_matches_lock=0
fi

gomobile_mod_version() {
  go version -m "$1" 2>/dev/null | awk '$1 == "mod" && $2 == "golang.org/x/mobile" {print $3}'
}

ensure_gomobile() {
  local binary
  binary="$(command -v gomobile || true)"
  if [[ -n "$binary" ]] && [[ "$(gomobile_mod_version "$binary")" == "$gomobile_version" ]]; then
    printf '%s\n' "$binary"
    return 0
  fi
  local gobin
  gobin="$(go env GOBIN)"
  if [[ -z "$gobin" ]]; then
    gobin="$(go env GOPATH)/bin"
  fi
  # The pinned gomobile is a build input, exactly like the pinned source:
  # installing the locked revision is what keeps two builds comparable.
  # gobind must come from the same x/mobile revision, or the generated glue
  # and the binder disagree.
  GOBIN="$gobin" go install "golang.org/x/mobile/cmd/gomobile@$gomobile_version" >&2
  GOBIN="$gobin" go install "golang.org/x/mobile/cmd/gobind@$gomobile_version" >&2
  binary="$gobin/gomobile"
  [[ -x "$binary" ]] || return 1
  [[ "$(gomobile_mod_version "$binary")" == "$gomobile_version" ]] || return 1
  printf '%s\n' "$binary"
}

gomobile_bin="$(ensure_gomobile)" \
  || fail "build-apple: could not provide gomobile $gomobile_version (pinned by the lock toolchain)"

# --- 3. Source: the pinned commit, verified before use ----------------------

# The build always runs from one canonical absolute path: gobind stamps the
# main module's directory into go.o, so two builds only agree on their bytes
# when they agree on that path. The mkdir is the lock — a live build refuses
# a concurrent one, a stale lock from a dead process is broken and retaken.
work="/private/tmp/rovia-libxray-build"
if ! mkdir "$work" 2>/dev/null; then
  holder="$(cat "$work/pid" 2>/dev/null || true)"
  if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
    fail "build-apple: another build (pid $holder) holds $work"
  fi
  rm -rf "$work"
  mkdir "$work" || fail "build-apple: could not take $work"
fi
printf '%s\n' "$$" > "$work/pid"
cleanup() {
  if [[ "$keep_work" -eq 0 ]]; then
    rm -rf "$work"
  else
    printf '%s\n' "build-apple: work directory kept: $work" >&2
  fi
}
trap cleanup EXIT

archive="$work/libxray-src.tar.gz"
archive_url="$engine_source/archive/$engine_commit.tar.gz"
curl -fsSL --retry 3 -o "$archive" "$archive_url" \
  || fail "build-apple: could not download $archive_url"
actual_source_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
if [[ "$actual_source_sha" != "$source_sha256" ]]; then
  fail "build-apple: the source archive digest does not match the engine lock: $archive_url"
fi

src_dir="$work/src"
mkdir -p "$src_dir"
# The archive holds a single top-level directory named after the commit;
# stripping it keeps the layout stable if upstream ever renames the root.
tar -xzf "$archive" -C "$src_dir" --strip-components 1

# --- 4. Build: gomobile bind, trimmed paths, no build id --------------------

(
  cd "$src_dir"
  GOFLAGS=-mod=readonly "$gomobile_bin" bind \
    -target ios,iossimulator,macos \
    -iosversion 15.0 \
    -trimpath \
    -ldflags=-buildid= \
    -o LibXray.xcframework \
    .
) || fail "build-apple: gomobile bind failed for libXray $engine_version ($engine_commit)"

framework="$src_dir/LibXray.xcframework"
for slice in ios-arm64 ios-arm64_x86_64-simulator; do
  [[ -d "$framework/$slice" ]] || fail "build-apple: the framework is missing the $slice slice"
done

# gomobile stamps mtimes into the ar members, an epoch into every plist, and
# emits the slice list in map order. Normalise all three so the bytes are a
# property of the pinned source, not of the clock.
python3 "$script_root/tools/build-engine/xray/determinize-xcframework.py" \
  "$framework" --version "$engine_version" \
  || fail "build-apple: could not determinize the built framework"

# --- 5. Pack: one deterministic zip -----------------------------------------

mkdir -p "$out_dir"
artifact_path="$out_dir/$artifact_relpath"
mkdir -p "$(dirname "$artifact_path")"

python3 - "$framework" "$artifact_path" <<'PY'
import sys
import zipfile
from pathlib import Path

framework = Path(sys.argv[1])
artifact = Path(sys.argv[2])

# Fixed timestamps and permissions, sorted entries, no extra fields: two runs
# over the same framework tree must produce the same bytes, or the lock's
# digest would pin a machine, not a build.
FIXED_DATE = (1980, 1, 1, 0, 0, 0)

entries = []
for path in framework.rglob("*"):
    arcname = Path(framework.name) / path.relative_to(framework)
    entries.append((path, str(arcname)))
entries.sort(key=lambda pair: pair[1])

with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for path, arcname in entries:
        if path.is_symlink():
            # A framework's macOS slice links Versions/Current to A; storing
            # the link as content would break the slice's layout. The zip
            # keeps the link itself, which is also the deterministic answer.
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
            info.external_attr = (0o120777 << 16)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, str(path.readlink()).encode())
        elif path.is_dir():
            info = zipfile.ZipInfo(arcname + "/", date_time=FIXED_DATE)
            info.external_attr = (0o755 << 16) | 0x10
            zf.writestr(info, b"")
        else:
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
            info.external_attr = (0o644 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
PY

artifact_sha256="$(shasum -a 256 "$artifact_path" | awk '{print $1}')"

# --- 6. Report: the digest is the deliverable --------------------------------

printf '%s\n' "build-apple: built libXray $engine_version ($engine_commit)"
printf '%s\n' "build-apple: artifact: $artifact_path"
printf '%s\n' "build-apple: sha256: $artifact_sha256"

if [[ -n "$recorded_sha256" ]] && [[ "$toolchain_matches_lock" -eq 1 ]] && [[ "$recorded_sha256" != "$artifact_sha256" ]]; then
  fail "build-apple: the built artifact does not match the engine lock sha256: $recorded_sha256"
fi
if [[ -z "$recorded_sha256" ]]; then
  printf '%s\n' "build-apple: the lock records no sha256 yet; record the digest above in engines.lock.json"
fi
