#!/usr/bin/env python3
"""Tests for tools/ci/verify-release-inputs.sh.

A signed release is the one place where a missing input turns into a shipped
artifact. This verifier is the fail-closed gate in front of it, so the tests
build a complete, valid release input set with the repository's own tools
(SBOM generator, SBOM checker, manifest generator, engine lock) and then remove
or corrupt exactly one input at a time. Every case asserts the exit code and the
reason, so a gate cannot be weakened into silence.

The fixture never contacts Apple, never signs anything, and never needs a
production engine: the throwaway repository root carries a synthetic approved
lock whose "engine artifact" is a text file.
"""

from __future__ import annotations

import inspect
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import script_test_support as gate  # noqa: E402

REPO_ROOT = gate.REPO_ROOT
SCRIPT = REPO_ROOT / "tools/ci/verify-release-inputs.sh"
SBOM_TOOL = REPO_ROOT / "tools/reproducibility/generate-sbom.py"
SBOM_CHECK = REPO_ROOT / "tools/reproducibility/check-sbom.py"
MANIFEST_TOOL = REPO_ROOT / "tools/reproducibility/manifest.sh"

APP_IDENTIFIER = "io.rovia.client"
VERSION = "0.1.0"
TAG = "v0.1.0"

# The fixture represents a repository that has an Apple Developer team
# configured. This repository does not, and tools/release/ExportOptions.plist
# says so with an unresolved $(ROVIA_TEAM_ID); a separate test below requires
# that file to be refused, so the fixture cannot quietly become the real thing.
FIXTURE_TEAM_ID = "A1B2C3D4E5"

SECRET_NAMES = (
    "ROVIA_KEYCHAIN_PASSWORD",
    "ROVIA_IOS_DIST_CERT_BASE64",
    "ROVIA_IOS_DIST_CERT_PASSWORD",
    "ROVIA_IOS_APP_PROFILE_BASE64",
    "ROVIA_IOS_TUNNEL_PROFILE_BASE64",
)

SECRETS = {
    "ROVIA_KEYCHAIN_PASSWORD": "rovia-keychain-secret",
    "ROVIA_IOS_DIST_CERT_BASE64": "rovia-cert-secret",
    "ROVIA_IOS_DIST_CERT_PASSWORD": "rovia-cert-password",
    "ROVIA_IOS_APP_PROFILE_BASE64": "rovia-app-profile-secret",
    "ROVIA_IOS_TUNNEL_PROFILE_BASE64": "rovia-tunnel-profile-secret",
}


class ReleaseInputsTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.directory)], check=False)
        self.root = self.directory / "repository"
        self.lock = gate.write_approved_lock(self.root)
        self.commit = gate.init_git_root(self.root)
        self.sbom = self.directory / "build" / "SBOM.spdx.json"
        self.checksums = self.directory / "build" / "SHA256SUMS"
        self.manifest = self.directory / "export" / "build-manifest.json"
        self.artifact = self.build_artifact()
        self.build_sbom()
        self.build_manifest()
        self.build_checksums()
        self.export_options = self.build_export_options()

    def build_artifact(self, plist: str | None = None):
        path = self.directory / "export" / "Rovia.ipa"
        if plist is None:
            plist = gate.app_info_plist(APP_IDENTIFIER, VERSION, "7")
        return gate.write_ipa(path, plist)

    def rebuild_artifact(self, plist: str) -> None:
        """Replace the artifact and re-derive the inputs that hash it."""
        self.artifact.unlink(missing_ok=True)
        self.build_artifact(plist=plist)
        self.build_manifest()
        self.build_checksums()

    def build_export_options(self, team_id: str = FIXTURE_TEAM_ID) -> Path:
        path = self.root / "tools" / "release" / "ExportOptions.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            plistlib.dumps(
                {
                    "method": "app-store",
                    "teamID": team_id,
                    "stripSwiftSymbols": True,
                    "compileBitcode": False,
                }
            ).decode("utf-8"),
            encoding="utf-8",
        )
        return path

    def build_sbom(self):
        self.sbom.parent.mkdir(parents=True, exist_ok=True)
        commands = [
            [sys.executable, str(SBOM_TOOL), str(REPO_ROOT), str(self.sbom)],
            [sys.executable, str(SBOM_CHECK), str(self.sbom)],
        ]
        for command in commands:
            result = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def build_manifest(self):
        result = gate.run_script(
            MANIFEST_TOOL,
            "--root",
            str(self.root),
            "--artifact",
            str(self.artifact),
            "--sbom",
            str(self.sbom),
            "--tag",
            TAG,
            "--runner",
            "fixture-runner/ios",
        )
        self.assertEqual(result.returncode, 0, gate.combined(result))
        self.assertTrue(self.manifest.is_file(), f"{self.manifest} was not written")

    def build_checksums(self):
        self.checksums.parent.mkdir(parents=True, exist_ok=True)
        self.checksums.write_text(
            f"{gate.sha256_file(self.artifact)}  Rovia.ipa\n", encoding="utf-8"
        )

    def verify(
        self,
        *extra: str,
        tag: str = TAG,
        artifact: Path | None = None,
        sbom: Path | None = None,
        checksums: Path | None = None,
        manifest: Path | None = None,
        root: Path | None = None,
        secrets: bool = True,
        environment: dict | None = None,
    ):
        merged = dict(SECRETS) if secrets else {}
        if environment:
            merged.update(environment)
        return gate.run_script(
            SCRIPT,
            "--root",
            str(root or self.root),
            "--tag",
            tag,
            "--artifact",
            str(artifact or self.artifact),
            "--sbom",
            str(sbom or self.sbom),
            "--checksums",
            str(checksums or self.checksums),
            "--manifest",
            str(manifest or self.manifest),
            *extra,
            environment=merged,
        )

    def edit_manifest(self, **changes):
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        for key, value in changes.items():
            field, _, leaf = key.partition("__")
            if leaf:
                document[field][leaf] = value
            else:
                document[field] = value
        self.manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # -- the complete set -------------------------------------------------

    def test_complete_release_inputs_pass(self):
        gate.assert_accepted(self, self.verify())

    def test_complete_release_inputs_pass_with_environment_variables(self):
        result = gate.run_script(
            SCRIPT,
            "--root",
            str(self.root),
            environment={
                "ROVIA_RELEASE_TAG": TAG,
                "ROVIA_RELEASE_ARTIFACT": str(self.artifact),
                "ROVIA_RELEASE_SBOM": str(self.sbom),
                "ROVIA_RELEASE_CHECKSUMS": str(self.checksums),
                "ROVIA_RELEASE_MANIFEST": str(self.manifest),
                **SECRETS,
            },
        )
        gate.assert_accepted(self, result)

    def test_secret_presence_check_passes_with_every_secret(self):
        gate.assert_accepted(self, self.verify("--check-secrets-only"))

    def test_release_inputs_are_verified_against_the_fixture_commit(self):
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["gitCommit"], self.commit)

    # -- missing inputs ---------------------------------------------------

    def test_missing_tag_is_refused(self):
        gate.assert_refused(self, self.verify(tag=""), "release tag is required")

    def test_malformed_tag_is_refused(self):
        for tag in ("0.1.0", "release-1", "v1.2", "v1.2.3.4", "v1.2.3-", "v01.2.3"):
            with self.subTest(tag=tag):
                gate.assert_refused(self, self.verify(tag=tag), "invalid release tag")

    def test_missing_artifact_is_refused(self):
        self.artifact.unlink()
        gate.assert_refused(self, self.verify(), "artifact does not exist")

    def test_empty_artifact_is_refused(self):
        self.artifact.write_bytes(b"")
        gate.assert_refused(self, self.verify(), "artifact is empty")

    def test_artifact_without_a_payload_plist_is_refused(self):
        self.artifact.unlink()
        self.artifact.write_bytes(b"not a zip archive")
        gate.assert_refused(self, self.verify(), "payload Info.plist")

    def test_missing_sbom_is_refused(self):
        self.sbom.unlink()
        gate.assert_refused(self, self.verify(), "SBOM does not exist")

    def test_sbom_that_is_not_spdx_is_refused(self):
        document = json.loads(self.sbom.read_text(encoding="utf-8"))
        document["spdxVersion"] = "SPDX-2.2"
        self.sbom.write_text(json.dumps(document), encoding="utf-8")
        self.edit_manifest(sbom__sha256=gate.sha256_file(self.sbom))
        gate.assert_refused(self, self.verify(), "SPDX-2.3")

    def test_missing_checksums_file_is_refused(self):
        self.checksums.unlink()
        gate.assert_refused(self, self.verify(), "checksum file does not exist")

    def test_missing_manifest_is_refused(self):
        self.manifest.unlink()
        gate.assert_refused(self, self.verify(), "provenance manifest does not exist")

    def test_missing_engine_lock_is_refused(self):
        (self.root / "engines.lock.json").unlink()
        gate.assert_refused(self, self.verify(), "engines.lock.json is required")

    def test_missing_bundle_version_is_refused(self):
        self.rebuild_artifact(
            gate.app_info_plist(APP_IDENTIFIER, VERSION, "7").replace(
                "\t<key>CFBundleVersion</key>\n\t<string>7</string>\n", ""
            )
        )
        gate.assert_refused(self, self.verify(), "CFBundleVersion")

    def test_non_numeric_bundle_version_is_refused(self):
        self.rebuild_artifact(gate.app_info_plist(APP_IDENTIFIER, VERSION, "7.0-beta"))
        gate.assert_refused(self, self.verify(), "CFBundleVersion")

    def test_unexpanded_build_variables_are_refused(self):
        self.rebuild_artifact(gate.app_info_plist("$(PRODUCT_BUNDLE_IDENTIFIER)", VERSION, "7"))
        gate.assert_refused(self, self.verify(), "unexpanded build variable")

    # -- mismatches -------------------------------------------------------

    def test_tag_and_artifact_version_must_match(self):
        gate.assert_refused(self, self.verify(tag="v0.2.0"), "does not match the release tag")

    def test_manifest_tag_must_match(self):
        self.edit_manifest(releaseTag="v9.9.9", version="9.9.9")
        gate.assert_refused(self, self.verify(), "manifest release tag")

    def test_manifest_version_must_match(self):
        self.edit_manifest(version="9.9.9")
        gate.assert_refused(self, self.verify(), "manifest version")

    def test_manifest_artifact_hash_must_match(self):
        self.edit_manifest(artifact__sha256="d" * 64)
        gate.assert_refused(self, self.verify(), "manifest artifact hash")

    def test_manifest_engine_lock_hash_must_match(self):
        self.edit_manifest(engineLockSha256="e" * 64)
        gate.assert_refused(self, self.verify(), "manifest engine lock hash")

    def test_manifest_sbom_hash_must_match(self):
        self.edit_manifest(sbom__sha256="f" * 64)
        gate.assert_refused(self, self.verify(), "manifest SBOM hash")

    def test_manifest_without_a_source_commit_is_refused(self):
        self.edit_manifest(gitCommit=None)
        gate.assert_refused(self, self.verify(), "source commit")

    def test_manifest_without_a_runner_identity_is_refused(self):
        self.edit_manifest(runner=None)
        gate.assert_refused(self, self.verify(), "runner identity")

    def test_manifest_that_says_the_runner_is_unavailable_is_refused(self):
        self.edit_manifest(runner="unavailable")
        gate.assert_refused(self, self.verify(), "runner identity")

    def test_sbom_missing_a_local_package_is_refused(self):
        document = json.loads(self.sbom.read_text(encoding="utf-8"))
        document["packages"] = [
            package
            for package in document["packages"]
            if package["SPDXID"] != "SPDXRef-Package-RoviaRouting"
        ]
        self.sbom.write_text(json.dumps(document), encoding="utf-8")
        self.edit_manifest(sbom__sha256=gate.sha256_file(self.sbom))
        result = self.verify()
        self.assertEqual(result.returncode, 1, gate.combined(result))
        self.assertIn("core/routing", gate.combined(result))

    def test_manifest_with_an_unknown_schema_version_is_refused(self):
        self.edit_manifest(schemaVersion=1)
        gate.assert_refused(self, self.verify(), "schemaVersion")

    def test_manifest_without_a_recorded_engine_is_refused(self):
        self.edit_manifest(enabledEngines=[])
        gate.assert_refused(self, self.verify(), "engine")

    def test_checksum_entry_must_match_the_artifact(self):
        self.checksums.write_text(f"{'0' * 64}  Rovia.ipa\n", encoding="utf-8")
        gate.assert_refused(self, self.verify(), "checksum")

    def test_checksum_file_without_the_artifact_entry_is_refused(self):
        self.checksums.write_text(f"{gate.sha256_file(self.sbom)}  SBOM.spdx.json\n", encoding="utf-8")
        gate.assert_refused(self, self.verify(), "checksum")

    def test_engine_lock_without_an_approved_engine_is_refused(self):
        (self.root / "engines.lock.json").write_text(
            (REPO_ROOT / "engines.lock.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        gate.assert_refused(self, self.verify(), "release requires exactly one approved xray engine")

    def test_engine_lock_without_the_approved_artifact_is_refused(self):
        (self.root / "engine.bin").unlink()
        self.edit_manifest()
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("engine", gate.combined(result).lower())

    # -- secrets ----------------------------------------------------------

    def test_each_missing_secret_is_refused(self):
        for name in SECRET_NAMES:
            with self.subTest(secret=name):
                gate.assert_refused(self, self.verify(secrets=False, environment={name: None}), name)

    def test_blank_secret_is_refused(self):
        gate.assert_refused(
            self,
            self.verify(secrets=False, environment={"ROVIA_KEYCHAIN_PASSWORD": "   "}),
            "ROVIA_KEYCHAIN_PASSWORD",
        )

    def test_secret_presence_check_refuses_a_missing_secret(self):
        for name in SECRET_NAMES:
            with self.subTest(secret=name):
                result = self.verify("--check-secrets-only", secrets=False, environment={name: None})
                gate.assert_refused(self, result, name)

    def test_secret_values_are_never_printed(self):
        result = self.verify(secrets=False, environment={"ROVIA_KEYCHAIN_PASSWORD": None})
        output = gate.combined(result)
        for value in SECRETS.values():
            self.assertNotIn(value, output)

    def test_a_missing_artifact_is_refused_even_with_every_secret(self):
        self.artifact.unlink()
        gate.assert_refused(self, self.verify(), "artifact does not exist")

    # -- usage ------------------------------------------------------------

    def test_usage_error_without_arguments(self):
        gate.assert_usage_error(self, gate.run_script(SCRIPT))

    def test_unknown_flag_is_a_usage_error(self):
        gate.assert_usage_error(self, self.verify("--skip-everything"))

    def test_flag_without_a_value_is_a_usage_error(self):
        gate.assert_usage_error(self, self.verify("--tag"))


class ExportOptionsTests(ReleaseInputsTests):
    """The signing identity, checked before the gate says anything else.

    ReleaseInputsTests is the base rather than a fresh fixture because these cases
    are about what the gate refuses on the way in, and a refusal that needs a
    complete artifact set to reach is a refusal nobody will hit in practice.
    """

    PREFLIGHT = REPO_ROOT / "tools/release/verify-export-options.sh"
    REPO_PLIST = REPO_ROOT / "tools/release/ExportOptions.plist"

    def preflight(self, *extra: str, plist: Path | None = None):
        return gate.run_script(
            self.PREFLIGHT, "--plist", str(plist or self.REPO_PLIST), *extra
        )

    def test_this_repository_has_no_team_id_and_says_so(self):
        # The whole point: the plist in the tree is unresolved, and no test
        # fabricates a team to make the release path look further along.
        result = self.preflight()
        self.assertEqual(result.returncode, 1, gate.combined(result))
        self.assertIn("unresolved teamID", result.stderr)
        self.assertIn("$(ROVIA_TEAM_ID)", result.stderr)
        self.assertIn("manual gate that has not been executed", result.stderr)

    def test_the_repository_plist_holds_no_literal_team_id(self):
        document = plistlib.loads(self.REPO_PLIST.read_bytes())
        self.assertEqual(document["teamID"], "$(ROVIA_TEAM_ID)")
        self.assertNotRegex(document["teamID"], r"^[A-Z0-9]{10}$")

    def test_a_resolved_team_id_is_accepted_and_still_claims_nothing_about_signing(self):
        result = self.preflight(plist=self.export_options)
        self.assertEqual(result.returncode, 0, gate.combined(result))
        self.assertIn(f"teamID is resolved ({FIXTURE_TEAM_ID})", result.stdout)
        # Accepting a team ID is not evidence that signing works.
        self.assertIn("not that signing works", result.stdout)

    def test_an_unresolved_reference_is_refused_however_it_is_spelled(self):
        for value, expected in (
            ("$(ROVIA_TEAM_ID)", "unresolved teamID"),
            ("${ROVIA_TEAM_ID}", "unresolved teamID"),
            ("", "has no teamID"),
            ("   ", "has no teamID"),
            ("A1B2C3D4", "malformed teamID"),
            ("a1b2c3d4e5", "malformed teamID"),
            ("REPLACE-ME", "malformed teamID"),
        ):
            with self.subTest(teamID=value):
                plist = self.build_export_options(value)
                result = self.preflight(plist=plist)
                self.assertEqual(result.returncode, 1, gate.combined(result))
                self.assertIn(expected, result.stderr)

    def test_a_missing_team_id_key_is_refused(self):
        plist = self.build_export_options(FIXTURE_TEAM_ID)
        document = plistlib.loads(plist.read_bytes())
        del document["teamID"]
        plist.write_bytes(plistlib.dumps(document))
        result = self.preflight(plist=plist)
        self.assertEqual(result.returncode, 1, gate.combined(result))
        self.assertIn("has no teamID", result.stderr)

    def test_the_file_must_exist(self):
        result = self.preflight(plist=self.root / "tools" / "release" / "absent.plist")
        self.assertEqual(result.returncode, 1, gate.combined(result))
        self.assertIn("does not exist", result.stderr)

    def test_a_required_team_id_must_match_the_file(self):
        result = self.preflight(
            "--require-team-id", "Z9Y8X7W6V5", plist=self.export_options
        )
        self.assertEqual(result.returncode, 1, gate.combined(result))
        self.assertIn("Z9Y8X7W6V5 was required", result.stderr)

    def test_a_team_id_cannot_be_split_or_globbed_into_several_arguments(self):
        # The preflight invocation used to be built with an unquoted
        # ${ROVIA_TEAM_ID:+--require-team-id "$ROVIA_TEAM_ID"} expansion, which
        # word-splits and glob-expands. A value of "* wild word" would have
        # reached the tool as three arguments, and a value of "*" would have been
        # replaced by the file list in the working directory. The arguments are
        # now an array, so whatever the value holds arrives as one argument and
        # the tool's own format rule is what rejects it.
        for hostile in ("*", "* wild word", "A1B2C3D4E5 extra", "a b c d e f", "--plist"):
            with self.subTest(teamID=hostile):
                result = gate.run_script(
                    self.PREFLIGHT,
                    "--plist", str(self.export_options),
                    "--require-team-id", hostile,
                )
                self.assertEqual(result.returncode, 1, gate.combined(result))
                self.assertIn(
                    "is not a team ID", result.stderr,
                    f"{hostile!r} was accepted, or reached the tool as several "
                    "arguments",
                )

    def test_the_gate_builds_its_preflight_arguments_as_an_array(self):
        # Source-derived, so the fix cannot be undone by a later edit that
        # reintroduces the inline expansion.
        source = SCRIPT.read_text(encoding="utf-8")
        # Comments are dropped: the comment above the fixed line quotes the
        # expansion it replaced, and a check that trips on its own explanation is
        # a check nobody keeps.
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertIn('preflight_arguments=(--plist "$export_options")', code)
        self.assertIn('preflight_arguments+=(--require-team-id "$ROVIA_TEAM_ID")', code)
        self.assertIn('verify-export-options.sh" "${preflight_arguments[@]}"', code)
        self.assertNotIn(
            '${ROVIA_TEAM_ID:+--require-team-id', code,
            "the unquoted expansion is back in the gate's executable code",
        )

    def test_a_plist_path_with_a_space_is_read_as_one_path(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        spaced = directory / "Export Options.plist"
        spaced.write_bytes(
            plistlib.dumps({"method": "app-store", "teamID": "A1B2C3D4E5"})
        )
        result = gate.run_script(self.PREFLIGHT, "--plist", str(spaced))
        self.assertEqual(result.returncode, 0, gate.combined(result))
        # And through the release gate, which resolves the plist from --root.
        root = directory / "repo"
        (root / "tools" / "release").mkdir(parents=True)
        shutil.copy(spaced, root / "tools" / "release" / spaced.name)
        result = gate.run_script(
            SCRIPT, "--check-secrets-only", "--root", str(root)
        )
        self.assertNotEqual(
            result.returncode,
            0,
            "a plist path containing a space was not found, so the path was split",
        )
        self.assertIn("does not exist", gate.combined(result))

    def test_a_malformed_required_team_id_is_refused_before_the_file_is_read(self):
        result = self.preflight(
            "--require-team-id", "not-a-team", plist=self.export_options
        )
        self.assertEqual(result.returncode, 1, gate.combined(result))
        self.assertIn("is not a team ID", result.stderr)

    def test_release_inputs_refuses_on_the_signing_identity_before_the_secrets_message(self):
        # Gate order, asserted on the source as well as on the output: a gate
        # that reports "all signing secrets are present" while the team ID is
        # unresolved has told the operator it is ready to sign.
        #
        # The fixture root is given the placeholder the real repository ships,
        # because a repository whose export options are still unresolved is the
        # state this gate exists for.
        self.build_export_options("$(ROVIA_TEAM_ID)")
        result = self.verify("--check-secrets-only")
        self.assertEqual(result.returncode, 1, gate.combined(result))
        combined = gate.combined(result)
        self.assertIn("refusing before any readiness check", combined)
        self.assertNotIn("all signing secrets are present", combined)

    def test_the_team_id_check_precedes_the_secret_check_in_the_source(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertLess(
            source.index("verify-export-options.sh"),
            source.index("all signing secrets are present"),
            "the signing-identity check must run before the readiness message",
        )
        self.assertLess(
            source.index("verify-export-options.sh"),
            source.index("missing_secret=0"),
            "the signing-identity check must run before the secret check",
        )

    def test_release_inputs_accepts_a_root_whose_team_id_is_resolved(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, gate.combined(result))
        self.assertIn("all signing secrets are present", result.stdout)
        self.assertIn(f"teamID is resolved ({FIXTURE_TEAM_ID})", result.stdout)


class ExportOptionsDocumentationTests(unittest.TestCase):
    """The record's row about this gate, derived from this module.

    The row said 52 tests in `ExportOptionsTests`. That is the loader's count for
    the class, and 41 of those 41 are inherited from `ReleaseInputsTests` — the
    secrets, tag, artifact, SBOM, checksums, and manifest refusals, none of which
    are about export options. Reading "52 tests" as the coverage of this gate
    overstates it by more than four times, which is the failure a count written
    from a test-run total instead of from the class has.
    """

    RECORD = "docs/development/foundation-verification.md"
    ROW = "| Export-options team-ID gate |"

    def counts(self):
        """(defined here, inherited from the base, discovered for the class)."""
        defined = sorted(
            name
            for name, value in vars(ExportOptionsTests).items()
            if name.startswith("test_") and callable(value)
        )
        inherited = sorted(
            name
            for name, value in vars(ReleaseInputsTests).items()
            if name.startswith("test_") and callable(value)
        )
        discovered = len(
            unittest.defaultTestLoader.loadTestsFromTestCase(ExportOptionsTests)._tests
        )
        return defined, inherited, discovered

    def test_the_row_states_the_defined_and_discovered_counts(self):
        # The three numbers are read, not asserted against constants. An earlier
        # version asserted 11 and 41 here, which meant adding a test to this class
        # failed a documentation test — the shape of problem that teaches people
        # not to add tests. The history: 11 defined when the row was written, 41
        # inherited from the base, 52 discovered.
        defined, inherited, discovered = self.counts()
        self.assertTrue(defined, "no export-options tests are defined")
        self.assertTrue(inherited, "no tests are inherited from the base class")
        # The three numbers have to be consistent, or the row is describing
        # something that does not exist.
        self.assertEqual(
            discovered, len(defined) + len(inherited),
            "the discovered count is not the defined plus the inherited, so the "
            "class is picking up tests from somewhere the row cannot account for",
        )
        row = next(
            line
            for line in (REPO_ROOT / self.RECORD).read_text(encoding="utf-8").splitlines()
            if line.startswith(self.ROW)
        )
        flat = re.sub(r"\s+", " ", row)
        self.assertIn(
            f"{len(defined)} tests in `ExportOptionsTests`",
            flat,
            "the row does not state how many tests this gate's class defines",
        )
        self.assertIn(
            f"{discovered} discovered, including {len(inherited)} inherited from "
            "`ReleaseInputsTests`",
            flat,
            "the row does not state the discovered count and how much of it is "
            "inherited from the base class",
        )

    def test_ci_md_states_this_suites_test_count(self):
        # ci.md carried a hand-written count of this suite, which was 93 when it
        # was last checked and wrong twice since. It is now compared with the
        # loader's count of the whole module, which is the number the sentence is
        # about — "this script has N tests", not "the export-options class has N".
        total = self.module_test_count()
        ci = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        self.assertIn(
            f"`tools/ci/verify-release-inputs.sh` has {total} tests",
            re.sub(r"\s+", " ", ci),
            f"ci.md does not state this suite's {total} tests",
        )

    def module_test_count(self):
        """How many tests this module holds, from the loader rather than a list."""
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        return suite.countTestCases()

    def test_the_inherited_tests_are_not_about_export_options(self):
        # The reason the two numbers differ: every inherited method is a refusal
        # about some other input, and none of them touches a plist or a team ID.
        _, inherited, _ = self.counts()
        for name in inherited:
            with self.subTest(test=name):
                source = inspect.getsource(getattr(ReleaseInputsTests, name))
                for unrelated in ("ExportOptions", "teamID", "ROVIA_TEAM_ID"):
                    self.assertNotIn(
                        unrelated,
                        source,
                        f"{name} is inherited into the export-options class and "
                        f"does mention {unrelated}, so the split is not clean",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
