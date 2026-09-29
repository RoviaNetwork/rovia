#!/usr/bin/env python3
"""Tests for tools/ci/verify-lockfiles.sh.

An unlocked external dependency is the quiet way a network client stops being
reproducible: the manifest still looks local while SwiftPM resolves a remote
revision that can change under a tag. This verifier requires every external
dependency to have a reviewed Package.resolved with exact revisions, and
requires the engine lock to exist and declare the single-runtime policy.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools/ci"))

import script_test_support as gate  # noqa: E402

SCRIPT = REPO_ROOT / "tools/ci/verify-lockfiles.sh"
PACKAGE_LIST = REPO_ROOT / "tools/ci/local-packages.txt"


def package_entries():
    return [
        line.strip()
        for line in PACKAGE_LIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


class VerifyLockfilesTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.directory)], check=False)
        self.root = self.directory / "repository"
        for relative in package_entries():
            manifest = self.root / relative / "Package.swift"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                '// swift-tools-version: 6.0\n'
                'import PackageDescription\n'
                "let package = Package(\n"
                '    name: "Fixture",\n'
                "    targets: []\n"
                ")\n",
                encoding="utf-8",
            )
        self.lock = self.root / "engines.lock.json"
        self.lock.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runtimePolicy": {
                        "maxGoRuntimesPerProcess": 1,
                        "allowedProductionEngine": "xray",
                    },
                    "productionEngines": [],
                    "candidates": {"xray": {"enabled": False, "approval": "pending"}},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def run_lockfiles(self, *arguments: str):
        return gate.run_script(SCRIPT, "--root", str(self.root), *arguments)

    def write_resolved(self, relative: str, document) -> None:
        path = self.root / relative / "Package.resolved"
        if isinstance(document, str):
            path.write_text(document, encoding="utf-8")
        else:
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def add_external_dependency(self, relative: str = "platform/apple", form: str = "url") -> None:
        declarations = {
            "url": '.package(url: "https://github.com/apple/swift-argument-parser", from: "1.5.0")',
            "url-named": '.package(name: "ArgumentParser", url: "https://github.com/apple/swift-argument-parser", from: "1.5.0")',
            "id": '.package(id: "apple.swift-argument-parser", from: "1.5.0")',
            "id-revision": '.package(id: "apple.swift-argument-parser", exact: "1.5.2")',
            "local": '.package(path: "../routing")',
            "local-named": '.package(name: "RoviaRouting", path: "../routing")',
        }
        manifest = self.root / relative / "Package.swift"
        manifest.write_text(
            '// swift-tools-version: 6.0\n'
            "import PackageDescription\n"
            "let package = Package(\n"
            '    name: "Fixture",\n'
            f"    dependencies: [{declarations[form]}],\n"
            "    targets: [\n"
            '        .target(name: "Fixture", dependencies: [.product(name: "ArgumentParser", package: "swift-argument-parser")]),\n'
            "    ]\n"
            ")\n",
            encoding="utf-8",
        )

    def pinned_resolved(self) -> dict:
        return {
            "pins": [
                {
                    "identity": "swift-argument-parser",
                    "kind": "remoteSourceControl",
                    "location": "https://github.com/apple/swift-argument-parser",
                    "state": {"revision": "a" * 40},
                }
            ],
            "version": 3,
        }

    # -- the repository ----------------------------------------------------

    def test_repository_passes(self):
        gate.assert_accepted(self, gate.run_script(SCRIPT))

    def test_repository_declares_every_local_package(self):
        listed = set(package_entries())
        discovered = {
            str(path.parent.relative_to(REPO_ROOT))
            for path in REPO_ROOT.glob("**/Package.swift")
            if ".build" not in path.parts
        }
        self.assertEqual(discovered, listed)

    # -- engine lock -------------------------------------------------------

    def test_missing_engine_lock_is_refused(self):
        self.lock.unlink()
        gate.assert_refused(self, self.run_lockfiles(), "engines.lock.json is required")

    def test_invalid_engine_lock_json_is_refused(self):
        self.lock.write_text("{oops", encoding="utf-8")
        gate.assert_refused(self, self.run_lockfiles(), "engines.lock.json is not valid JSON")

    def test_unsupported_engine_lock_schema_version_is_refused(self):
        document = json.loads(self.lock.read_text(encoding="utf-8"))
        document["schemaVersion"] = 7
        self.lock.write_text(json.dumps(document), encoding="utf-8")
        gate.assert_refused(self, self.run_lockfiles(), "unsupported schema version")

    def test_missing_runtime_policy_is_refused(self):
        document = json.loads(self.lock.read_text(encoding="utf-8"))
        del document["runtimePolicy"]
        self.lock.write_text(json.dumps(document), encoding="utf-8")
        gate.assert_refused(self, self.run_lockfiles(), "runtimePolicy")

    def test_missing_production_engine_list_is_refused(self):
        document = json.loads(self.lock.read_text(encoding="utf-8"))
        del document["productionEngines"]
        self.lock.write_text(json.dumps(document), encoding="utf-8")
        gate.assert_refused(self, self.run_lockfiles(), "productionEngines")

    # -- package manifests -------------------------------------------------

    def test_missing_package_manifest_is_refused(self):
        (self.root / "platform/apple/Package.swift").unlink()
        gate.assert_refused(self, self.run_lockfiles(), "platform/apple/Package.swift")

    def test_package_manifest_without_a_name_is_refused(self):
        (self.root / "platform/apple/Package.swift").write_text(
            '// swift-tools-version: 6.0\nimport PackageDescription\n', encoding="utf-8"
        )
        gate.assert_refused(self, self.run_lockfiles(), "name")

    # -- external dependencies --------------------------------------------

    def test_every_external_dependency_form_requires_a_resolved_file(self):
        for form in ("url", "url-named", "id", "id-revision"):
            with self.subTest(form=form):
                shutil.rmtree(self.root, ignore_errors=True)
                self.setUp()
                self.add_external_dependency(form=form)
                gate.assert_refused(self, self.run_lockfiles(), "Package.resolved")

    def test_every_external_dependency_form_is_accepted_when_pinned(self):
        for form in ("url", "url-named", "id", "id-revision"):
            with self.subTest(form=form):
                shutil.rmtree(self.root, ignore_errors=True)
                self.setUp()
                self.add_external_dependency(form=form)
                self.write_resolved("platform/apple", self.pinned_resolved())
                gate.assert_accepted(self, self.run_lockfiles())

    def test_local_path_dependencies_are_not_external(self):
        for form in ("local", "local-named"):
            with self.subTest(form=form):
                shutil.rmtree(self.root, ignore_errors=True)
                self.setUp()
                self.add_external_dependency(form=form)
                result = self.run_lockfiles()
                gate.assert_accepted(self, result)
                self.assertIn("0 with locked external dependencies", result.stdout)

    def test_repository_dependencies_are_local(self):
        # The shipped packages reference their siblings by path, so treating
        # every .package call as external would demand a lock file for them.
        for relative in package_entries():
            manifest = (REPO_ROOT / relative / "Package.swift").read_text(encoding="utf-8")
            for declaration in re.findall(r"\.package\([^)]*\)", manifest, re.S):
                with self.subTest(manifest=relative, declaration=declaration.strip()):
                    self.assertIn("path:", declaration)

    def test_an_unrecognised_dependency_form_is_refused(self):
        manifest = self.root / "platform/apple/Package.swift"
        manifest.write_text(
            '// swift-tools-version: 6.0\n'
            "import PackageDescription\n"
            "let package = Package(\n"
            '    name: "Fixture",\n'
            "    dependencies: [.package(magic: true)],\n"
            "    targets: []\n"
            ")\n",
            encoding="utf-8",
        )
        gate.assert_refused(self, self.run_lockfiles(), "unrecognised .package")

    # -- commented declarations -------------------------------------------

    def write_manifest_with_comments(self, relative: str, comments: str) -> None:
        manifest = self.root / relative / "Package.swift"
        manifest.write_text(
            '// swift-tools-version: 6.0\n'
            "import PackageDescription\n"
            "let package = Package(\n"
            '    name: "Fixture",\n'
            f"{comments}"
            "    targets: []\n"
            ")\n",
            encoding="utf-8",
        )

    def test_a_package_call_in_a_line_comment_is_ignored(self):
        self.write_manifest_with_comments(
            "platform/apple",
            '    // Example only, never shipped: .package(url: "https://example.invalid/left-pad", from: "1.0.0")\n'
            '    // .package(magic: true)\n',
        )
        result = self.run_lockfiles()
        gate.assert_accepted(self, result)
        self.assertIn("0 with locked external dependencies", result.stdout)

    def test_a_package_call_in_a_block_comment_is_ignored(self):
        self.write_manifest_with_comments(
            "platform/apple",
            "    /*\n"
            '     .package(url: "https://example.invalid/left-pad", from: "1.0.0")\n'
            "     .package(id: \"example.invalid.left-pad\", exact: \"1.0.0\")\n"
            "     .package(magic: true)\n"
            "    */\n",
        )
        result = self.run_lockfiles()
        gate.assert_accepted(self, result)
        self.assertIn("0 with locked external dependencies", result.stdout)

    def test_a_nested_block_comment_is_ignored_to_its_end(self):
        self.write_manifest_with_comments(
            "platform/apple",
            "    /* outer /* inner .package(url: \"https://example.invalid/a\", from: \"1.0.0\") */\n"
            '     still a comment: .package(magic: true) */\n',
        )
        result = self.run_lockfiles()
        gate.assert_accepted(self, result)
        self.assertIn("0 with locked external dependencies", result.stdout)

    def test_a_declaration_after_a_block_comment_is_still_read(self):
        self.write_manifest_with_comments(
            "platform/apple",
            "    /* a comment mentioning .package(magic: true) */\n"
            '    dependencies: [.package(url: "https://github.com/apple/swift-argument-parser", from: "1.5.0")],\n',
        )
        gate.assert_refused(self, self.run_lockfiles(), "Package.resolved")

    def test_a_scheme_in_a_string_is_not_read_as_a_comment(self):
        # "https://" contains "//". A comment stripper that is not string-aware
        # truncates the manifest at the first URL and stops reading declarations.
        self.add_external_dependency(form="url")
        gate.assert_refused(self, self.run_lockfiles(), "Package.resolved")
        self.write_resolved("platform/apple", self.pinned_resolved())
        gate.assert_accepted(self, self.run_lockfiles())

    def test_a_scheme_in_a_commented_string_is_not_read_as_a_dependency(self):
        self.write_manifest_with_comments(
            "platform/apple",
            '    // see "https://example.invalid/left-pad" for the package we removed\n',
        )
        result = self.run_lockfiles()
        gate.assert_accepted(self, result)
        self.assertIn("0 with locked external dependencies", result.stdout)

    def test_external_dependency_without_a_resolved_file_is_refused(self):
        self.add_external_dependency()
        gate.assert_refused(self, self.run_lockfiles(), "Package.resolved")

    def test_external_dependency_with_a_branch_revision_is_refused(self):
        self.add_external_dependency()
        self.write_resolved(
            "platform/apple",
            {
                "pins": [
                    {
                        "identity": "swift-argument-parser",
                        "kind": "remoteSourceControl",
                        "location": "https://github.com/apple/swift-argument-parser",
                        "state": {"revision": "a" * 40, "branch": "main"},
                    }
                ],
                "version": 3,
            },
        )
        gate.assert_refused(self, self.run_lockfiles(), "branch")

    def test_external_dependency_with_a_version_range_is_refused(self):
        self.add_external_dependency()
        self.write_resolved(
            "platform/apple",
            {
                "pins": [
                    {
                        "identity": "swift-argument-parser",
                        "kind": "remoteSourceControl",
                        "location": "https://github.com/apple/swift-argument-parser",
                        "state": {"version": "1.5.0"},
                    }
                ],
                "version": 3,
            },
        )
        gate.assert_refused(self, self.run_lockfiles(), "revision")

    def test_external_dependency_with_a_pinned_revision_passes(self):
        self.add_external_dependency()
        self.write_resolved("platform/apple", self.pinned_resolved())
        gate.assert_accepted(self, self.run_lockfiles())

    def test_resolved_file_with_invalid_json_is_refused(self):
        self.add_external_dependency()
        self.write_resolved("platform/apple", "{oops")
        gate.assert_refused(self, self.run_lockfiles(), "Package.resolved")

    def test_resolved_file_without_pins_is_refused(self):
        self.add_external_dependency()
        self.write_resolved("platform/apple", {"pins": [], "version": 3})
        gate.assert_refused(self, self.run_lockfiles(), "pins")

    def test_pinned_external_dependencies_are_announced(self):
        self.add_external_dependency()
        self.write_resolved("platform/apple", self.pinned_resolved())
        result = self.run_lockfiles()
        gate.assert_accepted(self, result)
        self.assertIn("swift-argument-parser", result.stdout)

    # -- usage -------------------------------------------------------------

    def test_unknown_flag_is_a_usage_error(self):
        gate.assert_usage_error(self, self.run_lockfiles("--allow-unlocked"))

    def test_missing_root_is_a_usage_error(self):
        result = gate.run_script(SCRIPT, "--root")
        gate.assert_usage_error(self, result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
