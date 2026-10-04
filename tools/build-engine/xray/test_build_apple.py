#!/usr/bin/env python3
"""Tests for tools/build-engine/xray/build-apple.sh.

The build script is the only path from the engine lock to a binary, so its
refusals are the review surface: anything that is not exactly one approved,
enabled, fully pinned xray candidate must be refused before a build command,
a download, or a toolchain probe runs. Every test below stops in the gating
phase — none of them touches the network, a Go toolchain, or the canonical
build directory.

The build path itself is exercised by the engine-proof workflow, which runs
the script against the repository lock on a clean runner.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ci"))

import script_test_support as gate  # noqa: E402

REPO_ROOT = gate.REPO_ROOT
SCRIPT = REPO_ROOT / "tools/build-engine/xray/build-apple.sh"
REPOSITORY_LOCK = REPO_ROOT / "engines.lock.json"


class BuildAppleRefusalTests(unittest.TestCase):
    def write_lock(self, directory: Path, lock: dict) -> Path:
        path = directory / "engines.lock.json"
        path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        return path

    def approved_lock(self, directory: Path) -> Path:
        lock = gate.engine_lock(production=["xray"])
        lock["candidates"]["xray"]["sha256"] = None
        return self.write_lock(directory, lock)

    def run_build(self, *arguments: str, lock: Path | None = None):
        return gate.run_script(
            SCRIPT,
            *arguments,
            *(("--lock", str(lock)) if lock is not None else ()),
        )

    def test_unknown_option_is_a_usage_error(self):
        result = self.run_build("--frobnicate")
        gate.assert_usage_error(self, result)

    def test_missing_lock_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            result = self.run_build(lock=Path(name) / "engines.lock.json")
            gate.assert_refused(self, result, "engines.lock.json is required")

    def test_unreadable_lock_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = directory / "engines.lock.json"
            lock.write_text("{ not json", encoding="utf-8")
            result = self.run_build(lock=lock)
            gate.assert_refused(self, result, "not valid JSON")

    def test_an_empty_production_list_is_refused_before_anything_runs(self):
        with tempfile.TemporaryDirectory() as name:
            lock = self.write_lock(Path(name), gate.engine_lock(production=[]))
            result = self.run_build(lock=lock)
            gate.assert_refused(self, result, "No approved Xray lock entry is available")

    def test_a_non_xray_production_engine_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = self.write_lock(Path(name), gate.engine_lock(production=["sing-box"]))
            result = self.run_build(lock=lock)
            gate.assert_refused(self, result, "builds only xray")

    def test_a_pending_candidate_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["approval"] = "pending"
            result = self.run_build(lock=self.write_lock(Path(name), lock))
            gate.assert_refused(self, result, "not approved and enabled")

    def test_a_disabled_candidate_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["enabled"] = False
            result = self.run_build(lock=self.write_lock(Path(name), lock))
            gate.assert_refused(self, result, "not approved and enabled")

    def test_a_missing_pin_field_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["sourceArchiveSha256"] = None
            result = self.run_build(lock=self.write_lock(Path(name), lock))
            gate.assert_refused(self, result, "missing sourceArchiveSha256")

    def test_a_short_commit_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["commit"] = "abc123"
            result = self.run_build(lock=self.write_lock(Path(name), lock))
            gate.assert_refused(self, result, "40-character hexadecimal commit")

    def test_a_toolchain_without_a_gomobile_pin_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["toolchain"] = "go1.24.0 darwin/amd64"
            result = self.run_build(lock=self.write_lock(Path(name), lock))
            gate.assert_refused(self, result, "does not pin a gomobile version")

    def test_an_artifact_path_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["toolchain"] = (
                "go1.24.0 darwin/amd64 + gomobile v0.0.0-20260908204917-8b95e45f8d3e"
            )
            lock["candidates"]["xray"]["artifact"] = "../outside.zip"
            result = self.run_build(lock=self.write_lock(Path(name), lock))
            gate.assert_refused(self, result, "must stay inside the output directory")


if __name__ == "__main__":
    unittest.main()
