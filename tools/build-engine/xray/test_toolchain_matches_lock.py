#!/usr/bin/env python3
"""Tests for tools/build-engine/xray/toolchain-matches-lock.sh.

The probe decides whether a digest comparison against the lock is meaningful.
It is the load-bearing seam of the two-tier reproducibility rule, so its
refusals are pinned: a missing lock, an unparseable toolchain string, and an
unknown structure are usage errors, never a silent "match".
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
SCRIPT = REPO_ROOT / "tools/build-engine/xray/toolchain-matches-lock.sh"


class ToolchainMatchesLockTests(unittest.TestCase):
    def test_unknown_option_is_a_usage_error(self):
        result = gate.run_script(SCRIPT, "--frobnicate")
        gate.assert_usage_error(self, result)

    def test_a_missing_lock_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as name:
            result = gate.run_script(SCRIPT, "--lock", str(Path(name) / "engines.lock.json"))
            self.assertEqual(result.returncode, 2, gate.combined(result))
            self.assertIn("engines.lock.json is required", gate.combined(result))

    def test_an_unparseable_toolchain_pin_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["toolchain"] = "no versions here"
            path = directory / "engines.lock.json"
            path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
            result = gate.run_script(SCRIPT, "--lock", str(path))
            self.assertEqual(result.returncode, 2, gate.combined(result))
            self.assertIn("unparseable", gate.combined(result))

    def test_the_repository_lock_gets_a_structured_answer(self):
        # The probe must answer, whichever way the machine compares; a crash is
        # not an answer. The match direction itself is machine-dependent.
        result = gate.run_script(SCRIPT)
        self.assertIn(result.returncode, (0, 1), gate.combined(result))
        self.assertTrue(
            "toolchain matches the lock" in result.stdout
            or "toolchain differs from the lock" in result.stdout,
            gate.combined(result),
        )


if __name__ == "__main__":
    unittest.main()
