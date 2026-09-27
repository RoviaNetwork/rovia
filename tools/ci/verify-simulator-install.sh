#!/usr/bin/env bash
# Install and launch a built app on a simulator, and prove it started.
#
# A build that cannot be installed is not a usable artifact, and a build that
# installs but never launches is not evidence of a working app. This gate does
# both, on a real simulator, and leaves no process running behind it.
#
# It is not evidence about a Packet Tunnel Provider lifecycle or a physical
# device; those require hardware and a signed profile.
#
# Usage:
#   verify-simulator-install.sh <app-bundle> [--device UDID | --device-name NAME]
#
# Exit status: 0 installed and launched, 1 the install or launch failed, 2 usage error.
set -euo pipefail

bundle=""
device=""
device_name=""

usage() {
  cat <<'USAGE'
usage: verify-simulator-install.sh <app-bundle> [--device UDID | --device-name NAME]

  <app-bundle>            built .app bundle to install
  --device UDID           simulator identifier (default: resolve the newest available iPhone)
  --device-name NAME      simulator name to resolve instead of the newest iPhone
  -h, --help              print this message
USAGE
}

usage_error() {
  printf '%s\n' "verify-simulator-install: $1" >&2
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
    --device) require_value "--device" "$#"; device="$2"; shift 2 ;;
    --device=*) device="${1#*=}"; shift ;;
    --device-name) require_value "--device-name" "$#"; device_name="$2"; shift 2 ;;
    --device-name=*) device_name="${1#*=}"; shift ;;
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
  usage_error "an app bundle path is required"
fi
if [[ -n "$device" && -n "$device_name" ]]; then
  usage_error "--device and --device-name are mutually exclusive"
fi
if [[ ! -d "$bundle" ]]; then
  printf '%s\n' "verify-simulator-install: app bundle does not exist: $bundle" >&2
  exit 1
fi

python3 - "$bundle" "$device" "$device_name" <<'PY'
import json
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

bundle = Path(sys.argv[1])
requested = sys.argv[2]
requested_name = sys.argv[3]
LAUNCH_TIMEOUT_SECONDS = 120


def run(*arguments, check=True):
    result = subprocess.run(["xcrun", "simctl", *arguments], capture_output=True, text=True)
    if check and result.returncode != 0:
        print(
            f"verify-simulator-install: simctl {' '.join(arguments)} failed: "
            f"{(result.stdout + result.stderr).strip()}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return result


def fail(message):
    print(f"verify-simulator-install: {message}", file=sys.stderr)
    raise SystemExit(1)


def report(message):
    print(f"verify-simulator-install: {message}")


listing = json.loads(run("list", "devices", "available", "--json").stdout)
runtimes = listing.get("devices", {})


def resolve():
    if requested:
        for devices in runtimes.values():
            for device in devices:
                if device.get("udid") == requested:
                    return requested, device.get("name", "unknown")
        fail(f"no available simulator with identifier {requested}")
    for runtime in sorted(runtimes, reverse=True):
        for device in runtimes[runtime]:
            name = device.get("name", "")
            if not device.get("isAvailable"):
                continue
            if requested_name:
                if name == requested_name:
                    return device["udid"], name
            elif name.startswith("iPhone"):
                return device["udid"], name
    fail(
        "no available iPhone simulator"
        + (f" named {requested_name}" if requested_name else "")
        + "; a simulator run cannot be claimed without one"
    )


udid, name = resolve()
with (bundle / "Info.plist").open("rb") as stream:
    identifier = plistlib.load(stream).get("CFBundleIdentifier")
if not identifier:
    fail("the app bundle has no CFBundleIdentifier")

state = run("list", "devices", "--json")
del state
if run("bootstatus", udid, "-b", check=False).returncode != 0:
    run("boot", udid, check=False)
    if run("bootstatus", udid, "-b", check=False).returncode != 0:
        fail(f"simulator {name} ({udid}) did not finish booting")
report(f"simulator {name} ({udid}) is booted")

run("uninstall", udid, identifier, check=False)
run("install", udid, str(bundle))
installed = run("get_app_container", udid, identifier, check=False)
if installed.returncode != 0 or not installed.stdout.strip():
    fail(f"the app container for {identifier} is not present after installation")
report(f"installed {identifier} at {installed.stdout.strip()}")

launch = run("launch", udid, identifier, check=False)
if launch.returncode != 0:
    fail(f"{identifier} did not launch: {(launch.stdout + launch.stderr).strip()}")
# simctl launch prints "<bundle identifier>: <pid>". A simulator app runs as a host
# process, so the identifier is checked with a signal-0 liveness probe rather than
# by trusting the exit status alone.
process = launch.stdout.strip()
match = re.search(r":\s*(\d+)\s*$", process)
if not match:
    fail(f"simctl launch did not report a process identifier: {process!r}")
pid = int(match.group(1))
deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
while True:
    if subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0:
        break
    if time.monotonic() >= deadline:
        fail(f"{identifier} exited immediately after launch (pid {pid})")
    time.sleep(1)
report(f"launched {identifier} as pid {pid} and the process is alive")

if run("terminate", udid, identifier, check=False).returncode != 0:
    fail(f"{identifier} could not be terminated after the launch check")
report(f"terminated {identifier} after the launch check")
PY
