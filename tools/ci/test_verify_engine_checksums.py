#!/usr/bin/env python3
"""Tests for tools/ci/verify-engine-checksums.sh.

The engine lock is the only thing standing between the build and an unreviewed
proxy binary, so the verifier has two modes with opposite obligations:

* foundation mode may accept an empty lock, because the current slice ships no
  production engine, but any entry that is present must be complete;
* release mode must find exactly one approved Xray entry with a full commit
  SHA and a matching artifact hash, and must fail closed on every missing,
  partial, or ambiguous input.

Every refusal case below is a permanent negative test: each one asserts both
the exit code and the reason the gate gave.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import script_test_support as gate  # noqa: E402

REPO_ROOT = gate.REPO_ROOT
SCRIPT = REPO_ROOT / "tools/ci/verify-engine-checksums.sh"
REPOSITORY_LOCK = REPO_ROOT / "engines.lock.json"


class VerifyEngineChecksumsTests(unittest.TestCase):
    def write_lock(self, directory: Path, lock: dict, name: str = "engines.lock.json") -> Path:
        path = directory / name
        path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        return path

    def approved_lock(self, directory: Path) -> Path:
        lock = gate.engine_lock(production=["xray"])
        artifact = directory / "engine.bin"
        artifact.write_bytes(b"rovia-engine-fixture")
        lock["candidates"]["xray"]["sha256"] = gate.sha256_file(artifact)
        return self.write_lock(directory, lock)

    def run_lock(self, *arguments: str, lock: Path | None = None, cwd: Path | None = None):
        return gate.run_script(
            SCRIPT,
            *arguments,
            "--lock",
            str(lock or REPOSITORY_LOCK),
            cwd=cwd,
        )

    # -- foundation mode -------------------------------------------------

    def test_repository_lock_passes_in_foundation_mode(self):
        result = self.run_lock("--mode", "foundation")
        gate.assert_accepted(self, result)
        self.assertIn("no production engine is enabled", result.stdout)

    def test_foundation_mode_reports_an_approved_engine(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            result = self.run_lock("--mode", "foundation", lock=self.approved_lock(directory))
            gate.assert_accepted(self, result)
            self.assertIn("xray", result.stdout)

    def test_foundation_mode_refuses_a_missing_lock(self):
        with tempfile.TemporaryDirectory() as name:
            result = self.run_lock("--mode", "foundation", lock=Path(name) / "engines.lock.json")
            gate.assert_refused(self, result, "engines.lock.json is required")

    def test_foundation_mode_refuses_unreadable_json(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            path = directory / "engines.lock.json"
            path.write_text("{not json", encoding="utf-8")
            gate.assert_refused(self, self.run_lock(lock=path), "engines.lock.json is not valid JSON")

    def test_foundation_mode_refuses_an_unsupported_schema_version(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock()
            lock["schemaVersion"] = 2
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "unsupported schema version",
            )

    def test_foundation_mode_refuses_more_than_one_go_runtime(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock()
            lock["runtimePolicy"]["maxGoRuntimesPerProcess"] = 2
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "exactly one Go runtime per process",
            )

    def test_foundation_mode_refuses_a_disallowed_production_engine(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock()
            lock["runtimePolicy"]["allowedProductionEngine"] = "sing-box"
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "must allow only xray",
            )

    def test_foundation_mode_refuses_a_non_list_production_engine_field(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock()
            lock["productionEngines"] = "xray"
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "productionEngines must be a list",
            )

    def test_foundation_mode_refuses_two_production_engines(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray", "sing-box"])
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "exactly one production engine",
            )

    def test_foundation_mode_refuses_an_unknown_production_engine(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["wireguard"])
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "exactly one production engine",
            )

    def test_foundation_mode_refuses_an_enabled_engine_without_an_artifact(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "artifact does not exist",
            )

    def test_foundation_mode_refuses_a_disabled_candidate(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["enabled"] = False
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "candidate is not enabled",
            )

    def test_foundation_mode_refuses_a_pending_candidate(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["approval"] = "pending"
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "not approved",
            )

    def test_foundation_mode_refuses_an_unknown_approval_value(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["approval"] = "self-approved"
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "approval",
            )

    def test_foundation_mode_refuses_a_short_commit(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["commit"] = "abc1234"
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "40-character hexadecimal commit",
            )

    def test_foundation_mode_refuses_a_missing_commit(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["commit"] = None
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "is missing commit",
            )

    def test_foundation_mode_refuses_a_short_artifact_hash(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = gate.engine_lock(production=["xray"])
            lock["candidates"]["xray"]["sha256"] = "deadbeef"
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "64-character hexadecimal digest",
            )

    def test_foundation_mode_refuses_an_artifact_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = self.approved_lock(directory)
            document = json.loads(lock.read_text(encoding="utf-8"))
            document["candidates"]["xray"]["sha256"] = "c" * 64
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, document)),
                "checksum does not match",
            )

    def test_foundation_mode_refuses_empty_architecture_lists(self):
        for key in ("architectures", "buildFlags", "linkedFrameworks"):
            with self.subTest(field=key), tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
                lock["candidates"]["xray"][key] = []
                gate.assert_refused(
                    self,
                    self.run_lock(lock=self.write_lock(directory, lock)),
                    key,
                )

    def test_foundation_mode_refuses_an_approved_engine_missing_from_production_engines(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["productionEngines"] = []
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "not listed in productionEngines",
            )

    def test_foundation_mode_refuses_a_second_approved_engine_missing_from_production_engines(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["productionEngines"] = ["xray"]
            lock["candidates"]["sing-box"]["approval"] = "approved"
            lock["candidates"]["sing-box"]["enabled"] = True
            gate.assert_refused(
                self,
                self.run_lock(lock=self.write_lock(directory, lock)),
                "sing-box",
            )

    def test_foundation_mode_allows_a_pending_candidate_that_is_not_enabled(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["productionEngines"] = []
            lock["candidates"]["xray"] = gate.approved_candidate()
            lock["candidates"]["xray"]["enabled"] = False
            lock["candidates"]["xray"]["approval"] = "pending"
            gate.assert_accepted(self, self.run_lock(lock=self.write_lock(directory, lock)))

    # -- release mode ----------------------------------------------------

    def test_release_mode_accepts_exactly_one_approved_engine(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            gate.assert_accepted(self, self.run_lock("--mode", "release", lock=self.approved_lock(directory)))

    def test_release_mode_refuses_an_empty_engine_lock(self):
        gate.assert_refused(
            self,
            self.run_lock("--mode", "release", lock=REPOSITORY_LOCK),
            "release requires exactly one approved xray engine",
        )

    def test_release_mode_refuses_a_missing_lock(self):
        with tempfile.TemporaryDirectory() as name:
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=Path(name) / "engines.lock.json"),
                "engines.lock.json is required",
            )

    def test_release_mode_refuses_two_engines(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["productionEngines"] = ["xray", "sing-box"]
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=self.write_lock(directory, lock)),
                "exactly one production engine",
            )

    def test_release_mode_refuses_a_pending_approval(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["candidates"]["xray"]["approval"] = "pending"
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=self.write_lock(directory, lock)),
                "not approved",
            )

    def test_release_mode_refuses_a_short_commit(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["candidates"]["xray"]["commit"] = "a" * 12
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=self.write_lock(directory, lock)),
                "40-character hexadecimal commit",
            )

    def test_release_mode_refuses_a_missing_artifact(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            (directory / "engine.bin").unlink()
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=self.write_lock(directory, lock)),
                "artifact does not exist",
            )

    def test_release_mode_refuses_a_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            (directory / "engine.bin").write_bytes(b"tampered")
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=self.write_lock(directory, lock)),
                "checksum does not match",
            )

    def test_release_mode_refuses_an_approved_engine_missing_from_production_engines(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads(self.approved_lock(directory).read_text(encoding="utf-8"))
            lock["productionEngines"] = []
            gate.assert_refused(
                self,
                self.run_lock("--mode", "release", lock=self.write_lock(directory, lock)),
                "not listed in productionEngines",
            )

    # -- reporting and usage ---------------------------------------------

    def test_github_output_reports_a_disabled_engine(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "github-output"
            result = self.run_lock(
                "--mode",
                "foundation",
                "--github-output",
                str(output),
            )
            gate.assert_accepted(self, result)
            self.assertEqual(
                output.read_text(encoding="utf-8").split(),
                ["enabled=false", "engine=none"],
            )

    def test_github_output_reports_an_enabled_engine(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            output = directory / "github-output"
            result = self.run_lock(
                "--mode",
                "foundation",
                "--github-output",
                str(output),
                lock=self.approved_lock(directory),
            )
            gate.assert_accepted(self, result)
            self.assertEqual(
                output.read_text(encoding="utf-8").split(),
                ["enabled=true", "engine=xray"],
            )

    def test_unknown_mode_is_a_usage_error(self):
        gate.assert_usage_error(self, self.run_lock("--mode", "production"))

    def test_missing_mode_value_is_a_usage_error(self):
        gate.assert_usage_error(self, self.run_lock("--mode"))

    def test_unknown_flag_is_a_usage_error(self):
        gate.assert_usage_error(self, self.run_lock("--allow-anything"))

    def test_github_output_is_optional(self):
        with tempfile.TemporaryDirectory() as name:
            gate.assert_refused(
                self,
                self.run_lock("--github-output", str(Path(name) / "missing-directory/output")),
                "github output",
            )

    def test_no_argument_defaults_to_foundation_mode(self):
        gate.assert_accepted(self, self.run_lock())


if __name__ == "__main__":
    unittest.main(verbosity=2)
