#!/usr/bin/env python3
"""Tests for tools/reproducibility/generate-sbom.py and check-sbom.py.

The SBOM is the artifact a reviewer reads instead of trusting the build, so the
invariants are checked as code (check-sbom.py) and the checker is itself tested
against hand-written bad documents. Anything the checker cannot see is a
release-quality problem, so the negative cases are written out rather than
implied.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "tools/reproducibility/generate-sbom.py"
CHECKER = REPO_ROOT / "tools/reproducibility/check-sbom.py"
PACKAGE_LIST = REPO_ROOT / "tools/ci/local-packages.txt"

spec = importlib.util.spec_from_file_location("check_sbom", CHECKER)
assert spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

generator_spec = importlib.util.spec_from_file_location("generate_sbom", GENERATOR)
assert generator_spec.loader is not None
generator = importlib.util.module_from_spec(generator_spec)
generator_spec.loader.exec_module(generator)

UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SPDX_ID = re.compile(r"^SPDXRef-[A-Za-z0-9.\-]+$")
CREATOR = re.compile(r"^(Person|Organization|Tool): \S.*$")


def generate(*arguments: str, root: Path = REPO_ROOT) -> dict:
    with tempfile.TemporaryDirectory() as name:
        output = Path(name) / "SBOM.spdx.json"
        result = subprocess.run(
            [sys.executable, str(GENERATOR), str(root), str(output), *arguments],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(f"SBOM generation failed: {result.stdout}{result.stderr}")
        return json.loads(output.read_text(encoding="utf-8"))


def approved_lock(directory: Path) -> Path:
    artifact = directory / "engine.bin"
    artifact.write_bytes(b"rovia-engine-fixture")
    lock = {
        "schemaVersion": 1,
        "runtimePolicy": {"maxGoRuntimesPerProcess": 1, "allowedProductionEngine": "xray"},
        "productionEngines": ["xray"],
        "candidates": {
            "xray": {
                "enabled": True,
                "source": "https://github.com/XTLS/libXray",
                "version": "25.6.3",
                "commit": "0123456789abcdef0123456789abcdef01234567",
                "sourceArchiveSha256": "a" * 64,
                "artifact": "engine.bin",
                "sha256": "b" * 64,
                "goVersion": "1.24.0",
                "toolchain": "go1.24.0 darwin/arm64",
                "architectures": ["arm64"],
                "buildFlags": ["-trimpath"],
                "linkedFrameworks": ["Network.framework"],
                "approval": "approved",
                "license": "MIT",
            },
            "sing-box": {"enabled": False, "approval": "pending", "license": "GPL-3.0-or-later"},
        },
    }
    path = directory / "engines.lock.json"
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return path


class GenerateSbomTests(unittest.TestCase):
    def setUp(self):
        self.document = generate()

    def test_generated_document_passes_the_checker(self):
        self.assertEqual(checker.problems(self.document), [])

    def test_spdx_version_and_data_license(self):
        self.assertEqual(self.document["spdxVersion"], "SPDX-2.3")
        self.assertEqual(self.document["dataLicense"], "CC0-1.0")
        self.assertEqual(self.document["SPDXID"], "SPDXRef-DOCUMENT")

    def test_created_timestamp_is_utc_with_a_z_suffix(self):
        created = self.document["creationInfo"]["created"]
        self.assertRegex(created, UTC_TIMESTAMP)
        self.assertNotIn("+", created)
        self.assertNotIn(".", created)

    def test_creators_are_valid_spdx_actors(self):
        creators = self.document["creationInfo"]["creators"]
        self.assertTrue(creators)
        for creator in creators:
            self.assertRegex(creator, CREATOR)
        self.assertTrue(
            any(creator.startswith("Tool: rovia-sbom-") for creator in creators),
            f"no versioned tool creator in {creators}",
        )

    def test_document_namespace_is_an_absolute_uri_without_a_fragment(self):
        namespace = self.document["documentNamespace"]
        self.assertTrue(namespace.startswith("https://"), namespace)
        self.assertNotIn("#", namespace)

    def test_document_namespace_is_unique_per_run(self):
        other = generate()
        self.assertNotEqual(
            self.document["documentNamespace"], other["documentNamespace"]
        )

    def test_document_namespace_is_stable_when_a_run_identifier_is_supplied(self):
        first = generate("--namespace-id", "11111111-1111-4111-8111-111111111111")
        second = generate("--namespace-id", "11111111-1111-4111-8111-111111111111")
        self.assertEqual(first["documentNamespace"], second["documentNamespace"])
        self.assertIn("11111111-1111-4111-8111-111111111111", first["documentNamespace"])

    def test_document_includes_the_app_and_the_extension(self):
        names = {package["name"] for package in self.document["packages"]}
        self.assertIn("Rovia", names)
        self.assertIn("RoviaTunnel", names)
        identifiers = {package["SPDXID"] for package in self.document["packages"]}
        self.assertIn("SPDXRef-App-io.rovia.client", identifiers)
        self.assertIn("SPDXRef-Extension-io.rovia.client.tunnel", identifiers)

    def test_document_includes_every_local_swift_package(self):
        expected = [
            line.strip()
            for line in PACKAGE_LIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(expected, "the local package list is empty")
        identifiers = {
            package["SPDXID"].removeprefix("SPDXRef-Package-")
            for package in self.document["packages"]
            if package["SPDXID"].startswith("SPDXRef-Package-")
        }
        for relative in expected:
            manifest = (REPO_ROOT / relative / "Package.swift").read_text(encoding="utf-8")
            match = re.search(r'name:\s*"([^"]+)"', manifest)
            self.assertIsNotNone(match, f"no package name in {relative}/Package.swift")
            self.assertIn(match.group(1), identifiers, f"{relative} is missing from the SBOM")

    def test_app_and_extension_versions_come_from_the_project(self):
        packages = {package["SPDXID"]: package for package in self.document["packages"]}
        self.assertEqual(packages["SPDXRef-App-io.rovia.client"]["versionInfo"], "0.1.0")
        self.assertEqual(packages["SPDXRef-Extension-io.rovia.client.tunnel"]["versionInfo"], "0.1.0")

    def test_no_engine_component_is_reported_for_the_foundation_lock(self):
        identifiers = {package["SPDXID"] for package in self.document["packages"]}
        self.assertFalse([value for value in identifiers if value.startswith("SPDXRef-Engine-")])

    def test_enabled_engines_are_reported_with_provenance(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = approved_lock(directory)
            document = generate("--lock", str(lock))
            packages = {
                package["SPDXID"]: package for package in document["packages"]
            }
            engine = packages.get("SPDXRef-Engine-xray-25.6.3")
            self.assertIsNotNone(engine, sorted(packages))
            self.assertIn("0123456789abcdef0123456789abcdef01234567", engine["comment"])
            self.assertEqual(
                engine["checksums"], [{"algorithm": "SHA256", "checksumValue": "b" * 64}]
            )
            self.assertEqual(checker.problems(document), [])

    def test_unapproved_candidates_are_not_reported_as_engines(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = json.loads((REPO_ROOT / "engines.lock.json").read_text(encoding="utf-8"))
            lock["candidates"]["xray"]["enabled"] = True
            lock["candidates"]["xray"]["approval"] = "pending"
            path = directory / "engines.lock.json"
            path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            document = generate("--lock", str(path))
            identifiers = {package["SPDXID"] for package in document["packages"]}
            self.assertFalse([value for value in identifiers if value.startswith("SPDXRef-Engine-")])

    def test_approved_engine_missing_from_production_engines_is_still_listed(self):
        # The SBOM is an inventory. An approved, enabled candidate that the lock
        # verifier refuses must still appear, or a reviewer reads a document
        # that hides a binary the build inputs ship.
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            lock = approved_lock(directory)
            document = json.loads(lock.read_text(encoding="utf-8"))
            document["productionEngines"] = []
            lock.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            generated = generate("--lock", str(lock))
            identifiers = {package["SPDXID"] for package in generated["packages"]}
            self.assertIn("SPDXRef-Engine-xray-25.6.3", identifiers)
            self.assertEqual(checker.problems(generated), [])
            refusal = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "tools/ci/verify-engine-checksums.sh"),
                    "--mode",
                    "release",
                    "--lock",
                    str(lock),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(refusal.returncode, 1)
            self.assertIn("not listed in productionEngines", refusal.stdout + refusal.stderr)

    def test_packages_carry_the_required_spdx_fields(self):
        for package in self.document["packages"]:
            with self.subTest(spdx_id=package["SPDXID"]):
                self.assertRegex(package["SPDXID"], SPDX_ID)
                self.assertTrue(package["name"])
                self.assertTrue(package["downloadLocation"])
                self.assertIn("filesAnalyzed", package)
                self.assertIsInstance(package["filesAnalyzed"], bool)
                self.assertTrue(package["copyrightText"])
                self.assertTrue(package["licenseConcluded"])
                self.assertTrue(package["licenseDeclared"])

    def test_spdx_ids_are_unique(self):
        identifiers = [package["SPDXID"] for package in self.document["packages"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_relationships_reference_elements_that_exist(self):
        self.assertEqual(checker.problems(self.document), [])
        known = {self.document["SPDXID"]} | {
            package["SPDXID"] for package in self.document["packages"]
        }
        for relationship in self.document["relationships"]:
            self.assertIn(relationship["spdxElementId"], known)
            self.assertIn(relationship["relatedSpdxElement"], known)

    def test_document_describes_the_app_and_relinks_every_component(self):
        self.assertEqual(self.document["documentDescribes"], ["SPDXRef-App-io.rovia.client"])
        related = set()
        for relationship in self.document["relationships"]:
            related.add(relationship["spdxElementId"])
            related.add(relationship["relatedSpdxElement"])
        for package in self.document["packages"]:
            self.assertIn(package["SPDXID"], related, f"{package['SPDXID']} is orphaned")

    def test_swift_packages_are_static_links_of_the_app(self):
        relationships = {
            (item["spdxElementId"], item["relationshipType"], item["relatedSpdxElement"])
            for item in self.document["relationships"]
        }
        self.assertIn(
            ("SPDXRef-App-io.rovia.client", "STATIC_LINK", "SPDXRef-Package-RoviaConfig"),
            relationships,
        )
        self.assertIn(
            ("SPDXRef-App-io.rovia.client", "CONTAINS", "SPDXRef-Extension-io.rovia.client.tunnel"),
            relationships,
        )

    def test_the_document_is_byte_reproducible_when_both_run_fields_are_fixed(self):
        # This test used to overwrite creationInfo.created with a fixed string and
        # then compare, which is a statement about the document minus its
        # timestamp. The timestamp is the field that made two runs differ, so
        # overwriting it hid the defect it was supposed to catch. The comparison
        # is now over the bytes the tool actually wrote.
        with tempfile.TemporaryDirectory() as name:
            digests = []
            for index in range(2):
                output = Path(name) / f"run{index}.spdx.json"
                environment = dict(os.environ, SOURCE_DATE_EPOCH="1700000000")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(GENERATOR),
                        str(REPO_ROOT),
                        str(output),
                        "--namespace-id",
                        "22222222-2222-4222-8222-222222222222",
                    ],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                digests.append(hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(
                digests[0],
                digests[1],
                "two runs with a fixed namespace and a fixed SOURCE_DATE_EPOCH "
                "produced different bytes",
            )

    def test_a_fixed_namespace_alone_does_not_make_the_document_reproducible(self):
        # The claim the record used to make. It is false, and the tool now says
        # so on stderr rather than letting a reader infer reproducibility from a
        # fixed namespace.
        with tempfile.TemporaryDirectory() as name:
            environment = {
                key: value
                for key, value in os.environ.items()
                if key != "SOURCE_DATE_EPOCH"
            }
            output = Path(name) / "SBOM.spdx.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    str(REPO_ROOT),
                    str(output),
                    "--namespace-id",
                    "22222222-2222-4222-8222-222222222222",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("not byte-reproducible", result.stderr)
            self.assertIn("SOURCE_DATE_EPOCH", result.stderr)

    def test_created_accepts_seconds_and_an_rfc_3339_instant(self):
        for argument, expected in (
            ("1700000000", "2023-11-14T22:13:20Z"),
            ("2023-11-14T22:13:20Z", "2023-11-14T22:13:20Z"),
            ("0", "1970-01-01T00:00:00Z"),
        ):
            with self.subTest(created=argument):
                document = generate("--created", argument)
                self.assertEqual(document["creationInfo"]["created"], expected)

    def test_created_wins_over_source_date_epoch(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "SBOM.spdx.json"
            environment = dict(os.environ, SOURCE_DATE_EPOCH="1700000000")
            result = subprocess.run(
                [sys.executable, str(GENERATOR), str(REPO_ROOT), str(output),
                 "--created", "0"],
                cwd=str(REPO_ROOT), capture_output=True, text=True, env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["creationInfo"]["created"],
                "1970-01-01T00:00:00Z",
            )

    def test_a_malformed_created_is_refused(self):
        for argument in ("yesterday", "2023-11-14", "2023-11-14T22:13:20+01:00", ""):
            with self.subTest(created=argument):
                result = subprocess.run(
                    [sys.executable, str(GENERATOR), str(REPO_ROOT), "/dev/null",
                     "--created", argument],
                    cwd=str(REPO_ROOT), capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("RFC 3339", result.stderr)

    def test_cli_rejects_the_wrong_argument_count(self):
        for arguments in ([], [str(REPO_ROOT)]):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(GENERATOR), *arguments],
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_cli_rejects_an_unknown_option(self):
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                str(REPO_ROOT),
                "/tmp/unused.spdx.json",
                "--invent-components",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


class CheckSbomTests(unittest.TestCase):
    def setUp(self):
        self.document = generate()

    def assertProblem(self, mutate, needle: str):
        document = copy.deepcopy(self.document)
        mutate(document)
        problems = checker.problems(document)
        self.assertTrue(
            any(needle in problem for problem in problems),
            f"expected a {needle!r} problem, got {problems}",
        )

    def test_valid_document_has_no_problems(self):
        self.assertEqual(checker.problems(self.document), [])

    def test_rejects_an_unsupported_spdx_version(self):
        self.assertProblem(lambda d: d.update(spdxVersion="SPDX-2.2"), "spdxVersion")

    def test_rejects_a_non_utc_timestamp(self):
        self.assertProblem(
            lambda d: d["creationInfo"].update(created="2026-09-25T10:00:00+00:00"),
            "UTC",
        )
        self.assertProblem(
            lambda d: d["creationInfo"].update(created="2026-09-25 10:00:00Z"),
            "UTC",
        )

    def test_rejects_an_invalid_creator(self):
        self.assertProblem(
            lambda d: d["creationInfo"].update(creators=["rovia-sbom"]),
            "creator",
        )

    def test_rejects_a_tool_creator_without_a_version(self):
        self.assertProblem(
            lambda d: d["creationInfo"].update(
                creators=["Organization: Rovia contributors", "Tool: rovia-sbom"]
            ),
            "versioned tool creator",
        )

    def test_accepts_a_tool_creator_whose_version_is_a_prerelease(self):
        for creator in ("Tool: rovia-sbom-0.2.0", "Tool: rovia-sbom-1.0.0-rc.1"):
            with self.subTest(creator=creator):
                document = copy.deepcopy(self.document)
                document["creationInfo"]["creators"] = [
                    "Organization: Rovia contributors",
                    creator,
                ]
                self.assertEqual(
                    [p for p in checker.problems(document) if "tool creator" in p],
                    [],
                )

    def test_rejects_a_namespace_with_a_fragment(self):
        self.assertProblem(
            lambda d: d.update(documentNamespace="https://rovia.invalid/spdx#1"),
            "documentNamespace",
        )

    def test_rejects_a_duplicate_spdx_id(self):
        def mutate(document):
            document["packages"].append(copy.deepcopy(document["packages"][0]))

        self.assertProblem(mutate, "duplicate")

    def test_rejects_a_dangling_relationship(self):
        self.assertProblem(
            lambda d: d["relationships"].append(
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Missing",
                }
            ),
            "unknown SPDX identifier",
        )

    def test_rejects_a_duplicate_relationship(self):
        self.assertProblem(
            lambda d: d["relationships"].append(copy.deepcopy(d["relationships"][0])),
            "duplicate relationship",
        )

    def test_relationship_types_match_the_spdx_2_3_enum(self):
        # The enum is written out here so a typo or a copy-paste duplicate is a
        # test failure rather than a silently smaller set of accepted types.
        expected = {
            "AMENDS", "ANCESTOR_OF", "BUILD_DEPENDENCY_OF", "BUILD_TOOL_OF",
            "CONTAINED_BY", "CONTAINS", "COPY_OF", "DATA_FILE_OF", "DEPENDENCY_OF",
            "DEPENDENCY_MANIFEST_OF", "DEPENDS_ON", "DESCENDANT_OF", "DESCRIBED_BY",
            "DESCRIBES", "DEV_DEPENDENCY_OF", "DISTRIBUTION_ARTIFACT", "DOCUMENTATION_OF",
            "DYNAMIC_LINK", "EXAMPLE_OF", "EXPANDED_FROM_ARCHIVE", "FILE_ADDED",
            "FILE_DELETED", "FILE_MODIFIED", "GENERATED_FROM", "GENERATES",
            "HAS_PREREQUISITE", "METAFILE_OF", "OPTIONAL_COMPONENT_OF",
            "OPTIONAL_DEPENDENCY_OF", "OTHER", "PACKAGE_OF", "PATCH_APPLIED", "PATCH_FOR",
            "PREREQUISITE_FOR", "PROVIDED_DEPENDENCY_OF", "REQUIREMENT_DESCRIPTION_FOR",
            "RUNTIME_DEPENDENCY_OF", "SPECIFICATION_FOR", "STATIC_LINK", "TEST_CASE_OF",
            "TEST_DEPENDENCY_OF", "VARIANT_OF",
        }
        self.assertEqual(set(checker.SPDX_RELATIONSHIP_TYPES), expected)
        self.assertEqual(len(checker.SPDX_RELATIONSHIP_TYPES), len(expected))
        self.assertIn("DOCUMENTATION_OF", checker.SPDX_RELATIONSHIP_TYPES)

    def test_rejects_the_foundation_placeholder_namespace(self):
        # The old generator emitted this namespace for every document, which
        # made two SBOMs indistinguishable.
        self.assertProblem(
            lambda d: d.update(documentNamespace="https://rovia.invalid/spdx/foundation"),
            "per-document identifier",
        )
        self.assertProblem(
            lambda d: d.update(documentNamespace="https://rovia.invalid/spdx"),
            "per-document identifier",
        )

    def test_rejects_a_package_without_a_copyright(self):
        def mutate(document):
            document["packages"][0].pop("copyrightText")

        self.assertProblem(mutate, "copyrightText")

    def test_rejects_a_missing_app_component(self):
        def mutate(document):
            document["packages"] = [
                package
                for package in document["packages"]
                if package["SPDXID"] != "SPDXRef-App-io.rovia.client"
            ]
            document["documentDescribes"] = ["SPDXRef-Package-RoviaConfig"]
            document["relationships"] = [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-RoviaConfig",
                }
            ]

        self.assertProblem(mutate, "application component")

    def test_rejects_a_missing_extension_component(self):
        def mutate(document):
            document["packages"] = [
                package
                for package in document["packages"]
                if package["SPDXID"] != "SPDXRef-Extension-io.rovia.client.tunnel"
            ]

        self.assertProblem(mutate, "extension component")

    def test_rejects_an_invalid_relationship_type(self):
        self.assertProblem(
            lambda d: d["relationships"][0].update(relationshipType="INCLUDES"),
            "relationshipType",
        )

    def test_cli_reports_problems_with_a_nonzero_exit_code(self):
        document = copy.deepcopy(self.document)
        document["spdxVersion"] = "SPDX-1.2"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "SBOM.spdx.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("spdxVersion", result.stdout + result.stderr)

    def test_cli_accepts_the_repository_sbom(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "SBOM.spdx.json"
            subprocess.run(
                [sys.executable, str(GENERATOR), str(REPO_ROOT), str(path)],
                cwd=str(REPO_ROOT),
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_requires_a_path(self):
        result = subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_repository_coverage_check_is_reachable_from_the_cli(self):
        document = generate()
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            path = directory / "SBOM.spdx.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(path), "--repository", str(REPO_ROOT)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            missing = copy.deepcopy(document)
            missing["packages"] = [
                package
                for package in missing["packages"]
                if package["SPDXID"] != "SPDXRef-Package-RoviaRouting"
            ]
            path.write_text(json.dumps(missing), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(path), "--repository", str(REPO_ROOT)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("core/routing", result.stdout + result.stderr)

    def test_coverage_check_reports_a_missing_package_list(self):
        document = generate()
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            found = checker.check_package_coverage(document, directory)
            self.assertTrue(any("local package list is missing" in problem for problem in found))


class SbomCommandDocumentationTests(unittest.TestCase):
    """The documented SBOM commands must be the commands that exist.

    A gate nobody can invoke correctly is not a gate, and a flag the tool has
    but the document does not mention is a flag the next reader has to
    rediscover from the source. Both directions are checked here against the
    tools' own --help output.
    """

    SECTION = "## SBOM commands"

    def setUp(self):
        self.documented = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        self.assertIn(self.SECTION, self.documented)

    def help_text(self, script: Path) -> str:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_every_documented_flag_is_accepted_by_a_tool(self):
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", self.section())) - {"--help"}
        for expected in ("--lock", "--namespace-id", "--repository"):
            self.assertIn(expected, flags, f"{expected} is not documented in {self.SECTION}")
        accepted = self.help_text(GENERATOR) + self.help_text(CHECKER)
        for flag in sorted(flags):
            with self.subTest(flag=flag):
                self.assertIn(flag, accepted, f"{flag} is documented but no tool accepts it")

    def test_every_tool_flag_is_documented(self):
        documented = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", self.section()))
        for script in (GENERATOR, CHECKER):
            for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", self.help_text(script))):
                with self.subTest(script=script.name, flag=flag):
                    self.assertIn(flag, documented, f"{script.name} accepts {flag} but it is not documented")

    def section(self) -> str:
        return self.documented.split(self.SECTION, 1)[1].split("\n## ", 1)[0]


class LocalPackageListTests(unittest.TestCase):
    def test_package_list_file_exists_and_is_not_empty(self):
        self.assertTrue(PACKAGE_LIST.is_file(), f"{PACKAGE_LIST} is missing")
        entries = [
            line.strip()
            for line in PACKAGE_LIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertGreaterEqual(len(entries), 7)

    def test_every_listed_package_manifest_exists(self):
        for relative in self.local_packages():
            self.assertTrue(
                (REPO_ROOT / relative / "Package.swift").is_file(),
                f"{relative}/Package.swift is missing but listed in {PACKAGE_LIST.name}",
            )

    def test_every_package_manifest_is_listed(self):
        listed = set(self.local_packages())
        discovered = {
            str(path.parent.relative_to(REPO_ROOT))
            for path in REPO_ROOT.glob("**/Package.swift")
            if ".build" not in path.parts
        }
        self.assertEqual(discovered, listed)

    def local_packages(self):
        return [
            line.strip()
            for line in PACKAGE_LIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]


class EngineLicenseTests(unittest.TestCase):
    """An engine's declared license is derived, not defaulted.

    The generator used to write MIT into every component, which meant a
    GPL-3.0-or-later engine would have been published as MIT. These cases pin
    the derivation and the two refusals.
    """

    def lock_with(self, candidate: dict, name: str = "engine") -> dict:
        return {
            "schemaVersion": 1,
            "runtimePolicy": {"maxGoRuntimesPerProcess": 1, "allowedProductionEngine": "xray"},
            "productionEngines": [name],
            "candidates": {name: candidate},
        }

    def candidate(self, **overrides) -> dict:
        entry = {
            "enabled": True,
            "source": "https://github.com/SagerNet/sing-box",
            "version": "1.11.0",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "sourceArchiveSha256": "a" * 64,
            "artifact": "engine.bin",
            "sha256": "b" * 64,
            "goVersion": "1.24.0",
            "toolchain": "go1.24.0 darwin/arm64",
            "architectures": ["arm64"],
            "buildFlags": ["-trimpath"],
            "linkedFrameworks": [],
            "approval": "approved",
            "license": "GPL-3.0-or-later",
        }
        entry.update(overrides)
        return entry

    def emit(self, lock: dict):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root / "engines.lock.json"
            lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
            output = root / "SBOM.spdx.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools/reproducibility/generate-sbom.py"),
                    str(REPO_ROOT),
                    str(output),
                    "--lock",
                    str(lock_path),
                ],
                capture_output=True,
                text=True,
            )
            document = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
            return result, document

    def engine(self, document: dict) -> dict:
        for package in document["packages"]:
            if package["name"] == "engine":
                return package
        self.fail("the engine component is missing from the document")

    def test_a_gpl_engine_is_emitted_as_gpl(self):
        result, document = self.emit(self.lock_with(self.candidate()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        engine = self.engine(document)
        self.assertEqual(engine["licenseDeclared"], "GPL-3.0-or-later")
        self.assertEqual(engine["licenseConcluded"], "GPL-3.0-or-later")

    def test_a_gpl_engine_declared_mit_is_refused(self):
        # The defect: MIT was a default, so this lock used to produce a document
        # that told a reviewer the engine was MIT.
        result, document = self.emit(self.lock_with(self.candidate(license="MIT")))
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(document, "a refused lock must not leave a document behind")
        self.assertIn("declares license MIT", result.stderr)
        self.assertIn("GPL-3.0-or-later", result.stderr)

    def test_a_missing_license_is_a_hard_failure(self):
        entry = self.candidate()
        del entry["license"]
        result, document = self.emit(self.lock_with(entry))
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(document)
        self.assertIn("declares no license", result.stderr)

    def test_an_empty_license_is_a_hard_failure(self):
        result, document = self.emit(self.lock_with(self.candidate(license="   ")))
        self.assertEqual(result.returncode, 1)
        self.assertIn("declares no license", result.stderr)

    def test_an_unknown_source_cannot_be_confirmed(self):
        # A license nobody can check is not a license the SBOM should assert.
        result, document = self.emit(
            self.lock_with(self.candidate(source="https://example.invalid/engine"))
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("whose license this generator does not know", result.stderr)

    def test_the_three_upstream_licenses_are_pinned(self):
        for source, expected in (
            ("https://github.com/XTLS/libXray", "MIT"),
            ("https://github.com/XTLS/Xray-core", "MPL-2.0"),
            ("https://github.com/SagerNet/sing-box", "GPL-3.0-or-later"),
        ):
            with self.subTest(source=source):
                result, document = self.emit(
                    self.lock_with(self.candidate(source=source, license=expected))
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.engine(document)["licenseDeclared"], expected)

    def test_the_shipped_lock_declares_a_license_for_every_candidate(self):
        lock = json.loads((REPO_ROOT / "engines.lock.json").read_text(encoding="utf-8"))
        for name, entry in lock["candidates"].items():
            with self.subTest(candidate=name):
                self.assertIn("license", entry, f"{name} declares no license")
                self.assertEqual(entry["license"], generator.ENGINE_LICENSES[entry["source"]])

    def test_the_shipped_lock_agrees_with_the_generator(self):
        result, document = self.emit(
            json.loads((REPO_ROOT / "engines.lock.json").read_text(encoding="utf-8"))
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The lock enables nothing, so no engine component is emitted; what
        # matters is that this succeeded without any component needing a default.
        names = {p["name"] for p in document["packages"]}
        self.assertNotIn("xray", names)
        self.assertNotIn("sing-box", names)

    def test_the_engine_comment_names_the_license_and_its_source(self):
        result, document = self.emit(self.lock_with(self.candidate()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        comment = self.engine(document)["comment"]
        self.assertIn("GPL-3.0-or-later", comment)
        self.assertIn("https://github.com/SagerNet/sing-box", comment)
        self.assertIn("required to match the engine lock", comment)

    def test_the_schema_enum_and_the_generator_table_are_the_same_set(self):
        # The schema constrains `license` to a known identifier; the generator
        # holds the source-to-license table. If a license were added to one and
        # not the other, a lock could validate and then be refused, or worse, be
        # refused for a license the schema has never heard of.
        schema = json.loads(
            (REPO_ROOT / "schemas/engine-lock.schema.json").read_text(encoding="utf-8")
        )
        allowed = set(
            schema["$defs"]["candidate"]["properties"]["license"]["enum"]
        )
        self.assertEqual(allowed, set(generator.ENGINE_LICENSES.values()))
        self.assertIn("license", schema["$defs"]["candidate"]["required"])

    def test_the_local_packages_stay_mit(self):
        # Only the engines are derived; Rovia's own packages are MIT because
        # this repository is.
        result, document = self.emit(self.lock_with(self.candidate()))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        packages = [p for p in document["packages"] if p["name"] != "engine"]
        for package in packages:
            with self.subTest(package=package["name"]):
                self.assertEqual(package["licenseDeclared"], "MIT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
