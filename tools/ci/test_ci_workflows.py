"""Thematic split of the former tools/ci/test_ci_checks.py.

Shared fixtures and loaders live in ci_check_support.py; this file
holds WorkflowPolicyTests.
"""
import plistlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
import script_test_support as gate
from script_test_support import (  # noqa: E402
    publishing_steps,
    workflow_steps,
)
from ci_check_support import (
    ACTION_PIN,
    MARKETING_VERSION,
    REPO_ROOT,
    SECRET_ENVIRONMENT_NAMES,
    WORKFLOWS,
    flat,
)


class WorkflowPolicyTests(unittest.TestCase):
    """The workflows are part of the security boundary, so they are tested too."""

    def workflow(self, name: str) -> str:
        path = WORKFLOWS / name
        self.assertTrue(path.is_file(), f"{path} is missing")
        return path.read_text(encoding="utf-8")

    def test_every_workflow_declares_read_only_permissions(self):
        for name in sorted(path.name for path in WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=name):
                self.assertIn("permissions:\n  contents: read", self.workflow(name))

    def test_every_third_party_action_is_pinned_to_a_commit(self):
        for name in sorted(path.name for path in WORKFLOWS.glob("*.yml")):
            for action, reference in ACTION_PIN.findall(self.workflow(name)):
                with self.subTest(workflow=name, action=action):
                    self.assertRegex(reference, r"^[0-9a-f]{40}$")

    def test_pull_request_ci_never_receives_a_secret(self):
        text = self.workflow("ci.yml")
        self.assertNotIn("secrets.", text)
        self.assertNotIn("environment:", text)

    # Gates CI reaches *through* `run-tool-tests.sh` rather than naming itself. The
    # Python gates are the two: a workflow that runs the runner runs them. They are
    # held separately because the runner is what invokes them, and an entry here is
    # satisfied by the runner's path alone.
    REACHED_THOUGH_THE_RUNNER = (
        "tools/ci/check-python-lint.sh",
        "tools/ci/check-python-warnings.sh",
    )

    LOCAL_GATES = (
        "tools/ci/check-shell-syntax.sh",
        "tools/ci/run-tool-tests.sh",
        "tools/ci/test_ci_changelog.py",
        "tools/ci/test_ci_toolchain.py",
        "tools/ci/test_ci_workflows.py",
        "tools/ci/test_ci_counts.py",
        "tools/ci/test_ci_docs.py",
        "tools/ci/verify-lockfiles.sh",
        "tools/ci/verify-engine-checksums.sh",
        "tools/ci/verify-third-party-notices.sh",
        "tools/ci/audit-accessibility-identifiers.py",
        "tools/ci/test_audit_accessibility_identifiers.py",
        "tools/ci/validate-schemas.py",
        "tools/ci/test_validate_schemas.py",
        "tools/reproducibility/generate-sbom.py",
        "tools/reproducibility/check-sbom.py",
        "tools/ci/verify-bundle-metadata.sh",
        "tools/ci/verify-simulator-install.sh",
        "tools/ci/local-packages.txt",
    )

    def workflow_gate_paths(self):
        """Every script or manifest `ci.yml` actually names."""
        return set(re.findall(
            r"tools/(?:ci|reproducibility)/[A-Za-z0-9._-]+", self.workflow("ci.yml")
        ))

    def test_the_local_gate_list_matches_the_workflow(self):
        # The list above is a claim about what CI runs. Nothing held it: an entry
        # could be deleted and the remaining entries would all still be present, so
        # the test would pass while asserting less than it did. Held in both
        # directions — an entry CI does not run is a gate that is not there, and a
        # path CI runs that the list omits is a gate nothing is holding.
        in_workflow = self.workflow_gate_paths()
        for gate_path in self.LOCAL_GATES:
            with self.subTest(gate=gate_path, direction="in the list only"):
                self.assertIn(
                    gate_path, in_workflow,
                    f"{gate_path} is in LOCAL_GATES but ci.yml does not run it",
                )
        for gate_path in sorted(in_workflow - set(self.LOCAL_GATES)):
            with self.subTest(gate=gate_path, direction="in the workflow only"):
                self.fail(
                    f"ci.yml runs {gate_path} but it is not in LOCAL_GATES, so "
                    "nothing holds it"
                )

    def test_ci_runs_every_local_gate(self):
        text = self.workflow("ci.yml")
        # The runner is in the list above, and the gates below are only reachable
        # through it, so requiring the runner is what makes them required. Asserted
        # here rather than assumed: with the runner entry removed, this list would
        # silently stop meaning anything.
        self.assertIn(
            "tools/ci/run-tool-tests.sh", text,
            "ci.yml no longer runs the runner, so the gates it reaches are not in CI",
        )
        for gate_path in self.LOCAL_GATES:
            with self.subTest(gate=gate_path):
                self.assertIn(gate_path, text)
        self.assertIn("CODE_SIGNING_ALLOWED=NO", text)

    def test_deleting_a_python_gate_from_the_runner_takes_it_out_of_ci(self):
        # The property behind `REACHED_THOUGH_THE_RUNNER`, made executable. A gate
        # named in the class constant above is not in `ci.yml`; it is in CI because
        # the runner invokes it, and the only thing that says so is the runner's own
        # text. So the reachability is checked by taking the invocation out and
        # requiring the reachability to go with it.
        runner = (REPO_ROOT / "tools/ci/run-tool-tests.sh").read_text(encoding="utf-8")
        for gate_path in self.REACHED_THOUGH_THE_RUNNER:
            with self.subTest(gate=gate_path):
                self.assertIn(
                    gate_path, runner,
                    f"{gate_path} is not invoked by the runner, so it is not in CI",
                )
                deleted = "\n".join(
                    line for line in runner.splitlines() if gate_path not in line
                )
                self.assertNotIn(
                    gate_path, deleted,
                    f"removing the lines naming {gate_path} from the runner left it named",
                )
                self.assertIn(
                    "tools/ci/run-tool-tests.sh", self.workflow("ci.yml"),
                    "ci.yml no longer runs the runner, so this proves nothing",
                )
                # With the invocation gone the gate is unreachable from the workflow:
                # nothing in ci.yml names it, and the runner no longer does either.
                self.assertNotIn(gate_path, self.workflow("ci.yml"))
                self.assertNotIn(gate_path, deleted)

    def test_ci_marketing_version_matches_the_project(self):
        version = plistlib.loads(
            (REPO_ROOT / "client/app/ios/RoviaApp/Info.plist").read_bytes()
        )["CFBundleShortVersionString"]
        declared = MARKETING_VERSION.search(self.workflow("ci.yml"))
        self.assertIsNotNone(declared, "ci.yml must declare ROVIA_MARKETING_VERSION")
        self.assertEqual(declared.group(1), version)

    def test_release_requires_secrets_before_it_builds(self):
        text = self.workflow("release-ios.yml")
        secrets_step = text.index("verify-release-inputs.sh --check-secrets-only")
        archive_step = text.index("archivePath")
        self.assertLess(secrets_step, archive_step)
        self.assertIn("environment: ios-production", text)
        self.assertIn("verify-release-inputs.sh --tag", text)

    def test_release_does_not_publish(self):
        # Checked per step: a forbidden token in a comment or a step name is not
        # a publishing step, and a publishing step must never be found.
        steps = workflow_steps(self.workflow("release-ios.yml"))
        self.assertTrue(steps, "no steps were found in release-ios.yml")
        self.assertEqual(publishing_steps(steps), [])

    def test_engine_workflow_uses_both_verifier_modes(self):
        text = self.workflow("engine-repro.yml")
        self.assertIn("--mode foundation", text)
        self.assertIn("--mode release", text)
        self.assertIn("--github-output", text)
        self.assertNotIn("python3 -c", text)

    def test_engine_workflow_builds_and_verifies_a_stub_engine(self):
        text = self.workflow("engine-repro.yml")
        steps = {step.name: step for step in workflow_steps(text)}
        self.assertIn("Build pinned Xray artifact", steps)
        self.assertEqual(steps["Build pinned Xray artifact"].run.strip(), "./tools/build-engine/xray/build-apple.sh")
        self.assertEqual(steps["Build pinned Xray artifact"].uses, "")
        self.assertIn("Verify the artifact", steps)
        self.assertEqual(steps["Verify the artifact"].run.strip(), "./tools/reproducibility/verify-xray.sh")
        for name in ("Build pinned Xray artifact", "Verify the artifact", "Verify the engine lock in release mode"):
            with self.subTest(step=name):
                self.assertIn(
                    "steps.engine.outputs.enabled == 'true'",
                    steps[name].text,
                    f"{name} must only run when the lock enables an engine",
                )

    def test_engine_build_stub_refuses_without_an_approved_lock(self):
        stub = REPO_ROOT / "tools/build-engine/xray/build-apple.sh"
        with tempfile.TemporaryDirectory() as name:
            gate.assert_refused(
                self,
                gate.run_script(stub, "--lock", str(Path(name) / "engines.lock.json")),
                "engines.lock.json is required",
            )
        gate.assert_refused(
            self, gate.run_script(stub), "refusing to build a floating engine"
        )
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            gate.write_approved_lock(directory)
            approved = gate.run_script(stub, "--lock", str(directory / "engines.lock.json"))
            # The stub must not succeed even with a fully approved lock: the
            # deterministic build recipe does not exist yet.
            self.assertNotEqual(approved.returncode, 0, gate.combined(approved))
            self.assertIn("not implemented yet", gate.combined(approved))

    def test_engine_build_stub_rejects_a_usage_error(self):
        stub = REPO_ROOT / "tools/build-engine/xray/build-apple.sh"
        gate.assert_usage_error(self, gate.run_script(stub, "--lock"))
        gate.assert_usage_error(self, gate.run_script(stub, "--invent"))

    def test_release_workflow_installs_the_pinned_validator_before_its_schema_tests(self):
        text = self.workflow("release-ios.yml")
        install = text.index("check-jsonschema==0.38.2")
        for step in ("test_validate_schemas.py", "validate-schemas.py"):
            with self.subTest(step=step):
                self.assertLess(install, text.index(step))
        self.assertIn("python3 -m venv", text)

    def test_release_workflow_runs_the_accessibility_self_test(self):
        text = self.workflow("release-ios.yml")
        self.assertIn("tools/ci/audit-accessibility-identifiers.py", text)
        self.assertIn("tools/ci/test_audit_accessibility_identifiers.py", text)

    def test_release_workflow_does_not_pass_a_secret_twice_in_one_step(self):
        # A secret may legitimately reach two steps: the early presence check and
        # the final gate. Declaring it twice in one step, or under two names, is
        # the defect this rules out. The signing steps use their own short local
        # names for security and xcodebuild; only the gate steps have to use the
        # names the gate reads.
        text = self.workflow("release-ios.yml")
        for step in workflow_steps(text):
            declared = re.findall(r"(\w+):\s*\$\{\{\s*secrets\.(\w+)\s*\}\}", step.text)
            with self.subTest(step=step.name):
                self.assertLessEqual(
                    len(declared),
                    len(set(declared)),
                    f"{step.name} declares the same secret twice or under two names: {declared}",
                )
                if "verify-release-inputs.sh" not in step.run:
                    continue
                for name, _ in declared:
                    self.assertIn(
                        name,
                        SECRET_ENVIRONMENT_NAMES,
                        f"{step.name} passes {name}, which the release gate does not read",
                    )

    def test_release_workflow_checks_the_decoded_profiles_and_cleans_them_up(self):
        text = self.workflow("release-ios.yml")
        profiles = [step for step in workflow_steps(text) if "provisioning profiles" in step.name.lower()]
        self.assertEqual(len(profiles), 1)
        self.assertIn("test -s", profiles[0].run)
        cleanup = [step for step in workflow_steps(text) if step.name.startswith("Cleanup")]
        self.assertEqual(len(cleanup), 1)
        self.assertIn("rovia-app.mobileprovision", cleanup[0].run)
        self.assertIn("rovia-tunnel.mobileprovision", cleanup[0].run)

    SIGNING_STEPS_AFTER_IDENTITY = (
        "Create temporary keychain",
        "Import distribution certificate",
        "Install provisioning profiles",
        "Archive",
        "Export IPA",
    )

    def release_workflow_step_names(self):
        return [step.name for step in workflow_steps(self.workflow("release-ios.yml"))]

    def test_the_export_identity_gate_precedes_every_signing_step_in_the_workflow(self):
        # The whole point of the preflight is that nothing is created before the
        # signing identity is known to be resolved. A keychain, an imported
        # certificate, an installed profile, an archive, and an export are all
        # consequences of signing, so the identity check has to come first.
        names = self.release_workflow_step_names()
        self.assertIn("Require a resolved signing identity", names)
        identity = names.index("Require a resolved signing identity")
        for step in self.SIGNING_STEPS_AFTER_IDENTITY:
            with self.subTest(step=step):
                self.assertIn(step, names, f"{step} is not in the release workflow")
                self.assertLess(
                    identity,
                    names.index(step),
                    f"the signing-identity check must precede {step}",
                )
        # And it has to be before the release gate's own final verification, so
        # the workflow cannot report every input present while the identity is
        # unresolved.
        self.assertLess(identity, names.index("Verify every release input"))
        # The step must run the preflight rather than restate it, and it must
        # point at the plist that is actually in the tree.
        step = workflow_steps(self.workflow("release-ios.yml"))[identity]
        self.assertIn("tools/release/verify-export-options.sh", step.run)
        self.assertIn("tools/release/ExportOptions.plist", step.run)

    def test_the_readiness_disclosure_quotes_real_workflow_step_numbers(self):
        # The disclosure said "Steps 12 and 13" for Archive and Export IPA; they
        # are 13 and 14, because a step was inserted above them. A step number in
        # prose is a fact about a file that changes, so it is read out of the
        # workflow rather than trusted.
        names = self.release_workflow_step_names()
        readiness = (REPO_ROOT / "docs/development/release-readiness.md").read_text(
            encoding="utf-8"
        )
        for step, following in (("Archive", "Export IPA"),):
            with self.subTest(step=step):
                self.assertIn(step, names)
                self.assertIn(following, names)
                expected = names.index(step) + 1
                number = expected + 1
                pair = f"Steps {expected} and {number}"
                self.assertIn(
                    pair,
                    flat(readiness),
                    f"{step} and {following} are steps {expected} and {number}, not "
                    f"what the disclosure says",
                )
        # And the row that carries the numbers must be the archive/export row,
        # identified by its title. Not by its number: hosted CI moved into the
        # document's `## Closed` section, every open row moved down by one, and this
        # test raised a bare StopIteration because it still asked for row 3. A row
        # number in a test is the same hazard as a row number in prose, which is why the
        # numbers inside the row are read from the workflow and the row itself is found
        # by its title.
        title = "**Archive and export**"
        row = next(
            line for line in readiness.splitlines() if title in line and line.startswith("| ")
        )
        self.assertIn(
            f"Steps {names.index('Archive') + 1} and {names.index('Export IPA') + 1}",
            row,
            "the archive row does not quote the step numbers the workflow has",
        )

    def test_ci_documents_the_signing_identity_step_at_its_workflow_position(self):
        ci = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        names = self.release_workflow_step_names()
        position = names.index("Require a resolved signing identity")
        self.assertIn(
            f"{position + 1}. `Require a resolved signing identity`",
            flat(ci),
            "ci.md must document the step at the position it holds in the workflow",
        )
        self.assertIn("verify-export-options.sh", flat(ci))
        self.assertIn("$(ROVIA_TEAM_ID)", flat(ci))
        self.assertIn(
            "before a keychain exists or anything is built", flat(ci)
        )

    def test_documented_release_order_matches_the_workflow(self):
        text = self.workflow("release-ios.yml")
        documented = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        order = [step.name for step in workflow_steps(text)]
        positions = []
        for name in order:
            self.assertIn(name, documented, f"{name} is not described in docs/development/ci.md")
            positions.append(documented.index(name))
        self.assertEqual(
            positions,
            sorted(positions),
            "docs/development/ci.md describes the release steps in a different order than the workflow runs them",
        )

    def test_the_validator_virtualenv_is_git_ignored(self):
        # Every workflow builds .ci-schema-validator inside the checkout. A
        # virtualenv is a build input, not source: committing one would put a
        # vendored interpreter in the history and let a local run change what a
        # reviewer sees.
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in sorted(path.name for path in WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=name):
                self.assertIn(".ci-schema-validator", self.workflow(name))
        self.assertIn(".ci-schema-validator", ignore)
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", ".ci-schema-validator/bin/check-jsonschema"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            "git would not ignore .ci-schema-validator, so a local validator "
            "virtualenv could be committed",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
