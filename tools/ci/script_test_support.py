"""Shared helpers for the shell-script tests under tools/.

The CI tools in this repository are bash scripts, so their tests drive them as
subprocesses. Keeping the process plumbing, the exit-code contract, and the
temporary-repository builder here means every script test asserts the same
contract:

    exit 0  the gate passed
    exit 1  the gate refused the input and explained why on stderr
    exit 2  the gate was called incorrectly (usage error)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ACCEPTED = 0
REFUSED = 1
USAGE = 2

GIT_IDENTITY = (
    "-c",
    "user.name=Rovia CI",
    "-c",
    "user.email=ci@rovia.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "init.defaultBranch=main",
)


def run_script(
    script: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a repository script and capture its combined result."""
    process_environment = dict(os.environ)
    for name in (
        "ROVIA_RELEASE_TAG",
        "ROVIA_RELEASE_ARTIFACT",
        "ROVIA_RELEASE_SBOM",
        "ROVIA_RELEASE_CHECKSUMS",
        "ROVIA_RELEASE_MANIFEST",
        "ROVIA_KEYCHAIN_PASSWORD",
        "ROVIA_IOS_DIST_CERT_BASE64",
        "ROVIA_IOS_DIST_CERT_PASSWORD",
        "ROVIA_IOS_APP_PROFILE_BASE64",
        "ROVIA_IOS_TUNNEL_PROFILE_BASE64",
        "ROVIA_RUNNER_IDENTITY",
    ):
        process_environment.pop(name, None)
    if environment:
        for name, value in environment.items():
            if value is None:
                process_environment.pop(name, None)
            else:
                process_environment[name] = value
    return subprocess.run(
        ["bash", str(script), *arguments],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        env=process_environment,
    )


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def assert_refused(test, result, needle: str) -> None:
    """Assert the gate refused the input and named the reason."""
    test.assertEqual(
        result.returncode,
        REFUSED,
        f"expected a refusal, got exit {result.returncode}:\n{combined(result)}",
    )
    test.assertIn(needle, combined(result), f"refusal did not explain itself:\n{combined(result)}")


def assert_accepted(test, result) -> None:
    test.assertEqual(
        result.returncode,
        ACCEPTED,
        f"expected the gate to pass, got exit {result.returncode}:\n{combined(result)}",
    )


def assert_usage_error(test, result) -> None:
    test.assertEqual(
        result.returncode,
        USAGE,
        f"expected a usage error, got exit {result.returncode}:\n{combined(result)}",
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# The real upstream projects, because the SBOM derives an engine's license from
# the source the lock names, and a fixture pointing at an invented URL would
# have no license to derive. These are the mappings the generator enforces:
# libXray is MIT, Xray-core is MPL-2.0, and sing-box is GPL-3.0-or-later.
ENGINE_SOURCES = {
    "xray": "https://github.com/XTLS/libXray",
    "Xray-core": "https://github.com/XTLS/Xray-core",
    "sing-box": "https://github.com/SagerNet/sing-box",
}
ENGINE_LICENSES = {
    "xray": "MIT",
    "Xray-core": "MPL-2.0",
    "sing-box": "GPL-3.0-or-later",
}


def approved_candidate(engine: str = "xray", artifact_name: str = "engine.bin") -> dict:
    """A fully approved candidate entry; the artifact is written by the caller."""
    return {
        "enabled": True,
        "source": ENGINE_SOURCES.get(engine, f"https://github.com/rovia-invalid/{engine}"),
        "version": "1.0.0",
        "commit": "a" * 40,
        "sourceArchiveSha256": "b" * 64,
        "artifact": artifact_name,
        "sha256": "0" * 64,
        "goVersion": "1.24.0",
        "toolchain": "go1.24.0 darwin/amd64",
        "architectures": ["arm64"],
        "buildFlags": ["-trimpath"],
        "linkedFrameworks": ["Network.framework"],
        "approval": "approved",
        "license": ENGINE_LICENSES.get(engine, "MIT"),
    }


def pending_candidate(engine: str = "sing-box") -> dict:
    """A candidate that is tracked but not approved, like the shipped lock."""
    return {
        "enabled": False,
        "source": ENGINE_SOURCES.get(engine, f"https://github.com/{engine.replace('-', '_')}/{engine}"),
        "version": None,
        "commit": None,
        "sourceArchiveSha256": None,
        "artifact": None,
        "sha256": None,
        "goVersion": None,
        "toolchain": None,
        "architectures": [],
        "buildFlags": [],
        "linkedFrameworks": [],
        "approval": "pending",
        "license": ENGINE_LICENSES.get(engine, "MIT"),
    }


def engine_lock(
    production: list[str] | None = None,
    xray: dict | None = None,
    sing_box: dict | None = None,
    **overrides,
) -> dict:
    lock = {
        "schemaVersion": 1,
        "runtimePolicy": {
            "maxGoRuntimesPerProcess": 1,
            "allowedProductionEngine": "xray",
        },
        "productionEngines": [] if production is None else production,
        "candidates": {
            "xray": xray if xray is not None else approved_candidate(),
            "sing-box": sing_box if sing_box is not None else pending_candidate(),
        },
    }
    lock.update(overrides)
    return lock


def write_approved_lock(directory: Path, name: str = "engines.lock.json", production=("xray",)) -> Path:
    """Write a release-ready lock whose single approved engine exists on disk."""
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "engine.bin"
    artifact.write_bytes(b"rovia-engine-fixture")
    xray = approved_candidate()
    xray["sha256"] = sha256_file(artifact)
    lock_path = directory / name
    lock_path.write_text(
        json.dumps(engine_lock(production=list(production), xray=xray), indent=2) + "\n",
        encoding="utf-8",
    )
    return lock_path


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *GIT_IDENTITY, *arguments],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


# -- workflow inspection ---------------------------------------------------
#
# The publishing policy is a security policy, so it is checked per step rather
# than by searching a file for a word: a step is the only place a workflow can
# run a command or reference an action, so scoping the search to steps is what
# lets the policy say something about behaviour. The scanner below needs no YAML
# library so the check cannot be skipped for want of a dependency.
#
# Inside a step the scan is deliberately fail-closed. A step's own text — its
# name, its keys, and its comments, not only its run: body — is searched, so a
# step may not mention a publishing tool even in a comment, and a token nested
# under an unrecognised key is still found. The cost is a false positive
# somewhere inside a step that has to be reworded; the benefit is that an upload
# cannot hide from the check by being indented, named, or annotated. Content
# outside a step is not inspected, which is why the forbidden words are listed
# once here and asserted in one place rather than searched for in prose.



@dataclass(frozen=True)
class Step:
    name: str
    uses: str
    run: str
    text: str

    def publishes(self) -> bool:
        if any(self.uses.startswith(prefix + "@") or self.uses == prefix for prefix in FORBIDDEN_PUBLISHING_USES):
            return True
        body = f"{self.run}\n{self.text}"
        return any(token in body for token in FORBIDDEN_PUBLISHING_COMMANDS)


FORBIDDEN_PUBLISHING_USES = (
    "actions/upload-artifact",
    "actions/upload-release-asset",
    "softprops/action-gh-release",
    "ncipollo/release-action",
    "actions/create-release",
)

FORBIDDEN_PUBLISHING_COMMANDS = (
    "gh release",
    "gh api",
    "xcrun notarytool",
    "xcrun altool",
    "notarytool",
    "altool",
    "fastlane",
    "pilot",
    "deliver",
    "transporter",
)


def policy_forbidden_tokens() -> list[str]:
    return list(FORBIDDEN_PUBLISHING_USES) + list(FORBIDDEN_PUBLISHING_COMMANDS)


STEP_START_MARKER = "steps:"
INLINE_KEY = re.compile(r"^(name|uses|run):\s*(.*)$")
BLOCK_KEYS = ("name", "uses", "run")
BLOCK_VALUES = {"|", ">", "|-", ">-", "|+", ">+"}
IDENTITY = "- "


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def workflow_steps(text: str) -> list[Step]:
    """Return the workflow's steps, in order, with their name, uses, and run.

    Only keys at a step's own indentation are read. A ``name:`` under a nested
    mapping such as ``with:`` or ``env:`` is not a step name, which is the
    mistake a text search over the file would make.
    """
    lines = text.splitlines()
    steps: list[Step] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.strip() != STEP_START_MARKER:
            continue
        indent = _indent(line)
        key_indent = indent + 4
        key_pattern = re.compile(
            r"^ {%d}(%s):\s*(.*)$" % (key_indent, "|".join(BLOCK_KEYS))
        )
        current: dict[str, str] | None = None
        body: list[str] = []
        pending: str | None = None
        while index < len(lines):
            entry = lines[index]
            if entry.strip() and _indent(entry) <= indent:
                break
            entry_indent = _indent(entry)
            if entry.strip().startswith(IDENTITY) and entry_indent == indent + 2:
                if current is not None:
                    steps.append(Step(text="\n".join(body), **current))
                current = {"name": "", "uses": "", "run": ""}
                body = [entry]
                pending = None
                inline = INLINE_KEY.match(entry.strip()[2:].strip())
                if inline and inline.group(2).strip() not in BLOCK_VALUES:
                    current[inline.group(1)] = inline.group(2).strip()
                index += 1
                continue
            if current is not None:
                body.append(entry)
                match = key_pattern.match(entry)
                if match:
                    key, value = match.group(1), match.group(2).strip()
                    if key in ("name", "uses"):
                        current[key] = value
                        pending = None
                    else:
                        pending = "run"
                        current["run"] = "" if value in BLOCK_VALUES else value
                elif pending == "run" and entry_indent > key_indent:
                    current["run"] = (current["run"] + "\n" + entry).strip("\n")
                else:
                    pending = None
            index += 1
        if current is not None:
            steps.append(Step(text="\n".join(body), **current))
    return steps


def publishing_steps(steps: list[Step]) -> list[str]:
    """Return the names of steps that would publish or upload an artifact."""
    return [step.name for step in steps if step.publishes()]


def init_git_root(root: Path, commit: bool = True) -> str | None:
    """Create a throwaway repository and return its commit, if any."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "--quiet")
    git(root, "add", "-A")
    if not commit:
        return None
    result = git(root, "commit", "--quiet", "--allow-empty", "-m", "fixture")
    if result.returncode != 0:
        raise AssertionError(f"could not create the fixture commit: {result.stdout}{result.stderr}")
    head = git(root, "rev-parse", "HEAD")
    return head.stdout.strip() if head.returncode == 0 else None


def app_info_plist(bundle_identifier: str, short_version: str, version: str, executable: str = "Rovia") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"\t<key>CFBundleExecutable</key>\n\t<string>{executable}</string>\n"
        f"\t<key>CFBundleIdentifier</key>\n\t<string>{bundle_identifier}</string>\n"
        f"\t<key>CFBundleName</key>\n\t<string>Rovia</string>\n"
        "\t<key>CFBundlePackageType</key>\n\t<string>APPL</string>\n"
        f"\t<key>CFBundleShortVersionString</key>\n\t<string>{short_version}</string>\n"
        f"\t<key>CFBundleVersion</key>\n\t<string>{version}</string>\n"
        "</dict>\n</plist>\n"
    )


def write_ipa(path: Path, plist: str, identifier: str = "Rovia") -> Path:
    """Write a minimal but structurally valid IPA around a payload Info.plist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"Payload/{identifier}.app/Info.plist", plist)
        archive.writestr(f"Payload/{identifier}.app/{identifier}", b"Mach-O fixture")
    return path
