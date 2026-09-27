#!/usr/bin/env python3
"""Tests for tools/reproducibility/manifest.sh.

The provenance manifest is what makes a release artifact traceable: which
commit, which engine lock, which SBOM, which artifact hash, which tag. Every
field it can silently degrade has a test here, and every missing input has a
refusal test, because a manifest that omits a field looks exactly like one that
was never verified.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools/ci"))

import script_test_support as gate  # noqa: E402

SCRIPT = REPO_ROOT / "tools/reproducibility/manifest.sh"
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
VERSION = "0.1.0"
TAG = "v0.1.0"


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.directory)], check=False)
        self.root = self.directory / "repository"
        self.commit = gate.init_git_root(self.root)
        self.artifact = self.directory / "export" / "Rovia.ipa"
        gate.write_ipa(
            self.artifact, gate.app_info_plist("io.rovia.client", VERSION, "7")
        )
        self.sbom = self.directory / "build" / "SBOM.spdx.json"
        self.sbom.parent.mkdir(parents=True, exist_ok=True)
        self.sbom.write_text('{"spdxVersion": "SPDX-2.3"}\n', encoding="utf-8")
        self.manifest = self.directory / "export" / "build-manifest.json"

    def write_lock_in(self, root: Path, production=(), approval="pending") -> Path:
        path = root / "engines.lock.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runtimePolicy": {
                        "maxGoRuntimesPerProcess": 1,
                        "allowedProductionEngine": "xray",
                    },
                    "productionEngines": list(production),
                    "candidates": {
                        "xray": {
                            "enabled": bool(production),
                            "version": "25.6.3",
                            "approval": approval,
                        }
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def write_lock(self, *arguments, **keywords) -> Path:
        return self.write_lock_in(self.root, *arguments, **keywords)

    def run_manifest(self, *arguments: str, environment: dict | None = None):
        return gate.run_script(SCRIPT, "--root", str(self.root), *arguments, environment=environment)

    def manifest_document(self, *arguments: str) -> dict:
        if not (self.root / "engines.lock.json").is_file():
            self.write_lock()
        result = self.run_manifest(
            "--artifact", str(self.artifact), "--sbom", str(self.sbom), "--tag", TAG, *arguments
        )
        gate.assert_accepted(self, result)
        return json.loads(self.manifest.read_text(encoding="utf-8"))

    # -- recorded provenance ----------------------------------------------

    def test_manifest_records_a_utc_timestamp(self):
        generated = self.manifest_document()["generatedAt"]
        self.assertRegex(generated, UTC_TIMESTAMP)

    def test_manifest_records_the_source_commit(self):
        self.assertEqual(self.manifest_document()["gitCommit"], self.commit)

    def test_manifest_records_the_release_tag_and_version(self):
        document = self.manifest_document()
        self.assertEqual(document["releaseTag"], TAG)
        self.assertEqual(document["version"], VERSION)

    def test_manifest_records_the_artifact_name_size_and_hash(self):
        document = self.manifest_document()
        self.assertEqual(document["artifact"]["name"], "Rovia.ipa")
        self.assertEqual(document["artifact"]["bytes"], self.artifact.stat().st_size)
        self.assertEqual(document["artifact"]["sha256"], gate.sha256_file(self.artifact))

    def test_manifest_records_the_sbom_hash(self):
        document = self.manifest_document()
        self.assertEqual(document["sbom"]["name"], "SBOM.spdx.json")
        self.assertEqual(document["sbom"]["sha256"], gate.sha256_file(self.sbom))

    def test_manifest_records_the_engine_lock_hash(self):
        lock = self.write_lock()
        document = self.manifest_document()
        self.assertEqual(document["engineLockSha256"], gate.sha256_file(lock))

    def test_manifest_records_the_runner_identity(self):
        self.write_lock()
        result = self.run_manifest(
            "--artifact", str(self.artifact), "--tag", TAG, "--runner", "run-4711/ubuntu"
        )
        gate.assert_accepted(self, result)
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["runner"], "run-4711/ubuntu")

    def test_manifest_reads_the_runner_identity_from_the_environment(self):
        self.write_lock()
        result = self.run_manifest("--artifact", str(self.artifact), "--tag", TAG)
        gate.assert_accepted(self, result)
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["runner"], "unavailable")

    def test_manifest_says_unavailable_rather_than_inventing_a_runner(self):
        self.write_lock()
        result = self.run_manifest(
            "--artifact",
            str(self.artifact),
            "--tag",
            TAG,
            environment={"ROVIA_RUNNER_IDENTITY": "  "},
        )
        gate.assert_accepted(self, result)
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["runner"], "unavailable")

    def test_manifest_records_the_enabled_engines(self):
        self.write_lock(production=["xray"], approval="approved")
        self.assertEqual(self.manifest_document()["enabledEngines"], ["xray"])

    def test_manifest_records_no_engines_for_the_foundation_lock(self):
        self.write_lock()
        self.assertEqual(self.manifest_document()["enabledEngines"], [])

    def test_manifest_records_the_toolchain_or_says_it_is_unavailable(self):
        document = self.manifest_document()
        for key in ("platform", "swift", "xcode"):
            with self.subTest(field=key):
                self.assertTrue(document[key])

    def test_manifest_is_versioned_and_deterministic_in_shape(self):
        self.write_lock()
        document = self.manifest_document()
        self.assertEqual(document["schemaVersion"], 2)
        self.assertEqual(
            sorted(document),
            [
                "artifact",
                "enabledEngines",
                "engineLockSha256",
                "generatedAt",
                "gitCommit",
                "packageResolved",
                "platform",
                "releaseTag",
                "runner",
                "sbom",
                "schemaVersion",
                "swift",
                "version",
                "xcode",
            ],
        )

    def test_manifest_ends_with_a_newline_and_is_sorted(self):
        self.write_lock()
        self.manifest_document()
        text = self.manifest.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(
            list(json.loads(text)),
            sorted(json.loads(text)),
        )

    def test_manifest_records_a_git_commit_when_the_root_has_one(self):
        self.write_lock()
        document = self.manifest_document()
        self.assertRegex(document["gitCommit"], r"^[0-9a-f]{40}$")

    def test_manifest_leaves_the_commit_null_without_a_repository(self):
        plain = self.directory / "plain"
        plain.mkdir()
        self.write_lock_in(plain)
        result = self.run_manifest(
            "--root", str(plain), "--artifact", str(self.artifact), "--tag", TAG
        )
        gate.assert_accepted(self, result)
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertIsNone(document["gitCommit"])

    # -- refusals ---------------------------------------------------------

    def test_missing_artifact_is_refused(self):
        self.write_lock()
        result = self.run_manifest("--artifact", str(self.directory / "absent.ipa"), "--tag", TAG)
        gate.assert_refused(self, result, "artifact does not exist")

    def test_empty_artifact_is_refused(self):
        self.write_lock()
        empty = self.directory / "empty.ipa"
        empty.write_bytes(b"")
        result = self.run_manifest("--artifact", str(empty), "--tag", TAG)
        gate.assert_refused(self, result, "artifact is empty")

    def test_missing_engine_lock_is_refused(self):
        result = self.run_manifest("--artifact", str(self.artifact), "--tag", TAG)
        gate.assert_refused(self, result, "engines.lock.json is required")

    def test_invalid_engine_lock_is_refused(self):
        (self.root / "engines.lock.json").write_text("{oops", encoding="utf-8")
        result = self.run_manifest("--artifact", str(self.artifact), "--tag", TAG)
        gate.assert_refused(self, result, "engines.lock.json")

    def test_missing_sbom_is_refused(self):
        self.write_lock()
        result = self.run_manifest(
            "--artifact",
            str(self.artifact),
            "--sbom",
            str(self.directory / "absent.spdx.json"),
            "--tag",
            TAG,
        )
        gate.assert_refused(self, result, "SBOM does not exist")

    def test_malformed_tag_is_refused(self):
        self.write_lock()
        result = self.run_manifest("--artifact", str(self.artifact), "--tag", "1.0.0")
        gate.assert_refused(self, result, "invalid release tag")

    def test_version_and_tag_must_agree(self):
        self.write_lock()
        result = self.run_manifest(
            "--artifact", str(self.artifact), "--tag", TAG, "--version", "0.2.0"
        )
        gate.assert_refused(self, result, "does not match the release tag")

    def test_unknown_flag_is_a_usage_error(self):
        self.write_lock()
        gate.assert_usage_error(self, self.run_manifest("--invent-provenance"))

    def test_no_arguments_is_a_usage_error(self):
        gate.assert_usage_error(self, gate.run_script(SCRIPT))

    def test_positional_artifact_is_still_accepted(self):
        self.write_lock()
        result = self.run_manifest(str(self.artifact), "--tag", TAG)
        gate.assert_accepted(self, result)
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["artifact"]["name"], "Rovia.ipa")

    def test_explicit_output_path_is_honoured(self):
        self.write_lock()
        output = self.directory / "provenance" / "manifest.json"
        result = self.run_manifest(
            "--artifact", str(self.artifact), "--tag", TAG, "--output", str(output)
        )
        gate.assert_accepted(self, result)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
