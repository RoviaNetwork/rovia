"""Thematic split of the former tools/ci/test_ci_checks.py.

Shared fixtures and loaders live in ci_check_support.py; this file
holds CheckShellSyntaxTests, DuplicateDefinitionTests, PreCommitConfigTests, PythonLintGateTests, PythonWarningsGateTests, VerifyBundleMetadataTests, VerifyTagTests, WorkflowStepScannerTests, swiftpm_counts, swiftpm_total.
"""
import ast
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import script_test_support as gate
from script_test_support import (  # noqa: E402
    policy_forbidden_tokens,
    publishing_steps,
    workflow_steps,
)
from ci_check_support import (
    APP_IDENTIFIER,
    BUNDLE_SCRIPT,
    REPO_ROOT,
    SHELL_SCRIPT,
    TAG_SCRIPT,
    TUNNEL_IDENTIFIER,
    WORKFLOWS,
    _bound_names,
    duplicate_definitions,
    local_packages,
    pyflakes_argv,
)


class DuplicateDefinitionTests(unittest.TestCase):
    """No module or class in `tools/` may define the same name twice.

    A scripted edit in an earlier pass left later copies of definitions shadowing
    earlier ones in one test file. Every test passed, because the shadowed copy was
    the one that ran and the first copy was still referenced. How many duplicates
    that was is not recorded and is not claimed here; this repository has no
    commits and the only pre-cleanup copy of the file was an overwritten `/tmp`
    backup.

    `pyflakes` is not sufficient on its own, and the reason is narrower than "it
    misses redefinitions". It *does* report a redefined `def`, `class` or `import`
    even when the earlier binding is used — verified, not assumed. It is silent
    about every rebound assignment: `X = 1; X = 2` with `X` used, `X: int = 1;
    X: int = 2`, `A, B = 1, 2; A, B = 3, 4`, a `for A in ...` followed by
    `A = 3`, and a `with ... as A` followed by `A = 3`. The first of those was the
    shape of the dead constants removed in that pass.
    """

    def python_sources(self):
        return sorted(
            path
            for path in (REPO_ROOT / "tools").rglob("*.py")
            if "__pycache__" not in path.parts
        )

    def test_no_duplicate_definitions_anywhere_under_tools(self):
        duplicates = []
        for path in self.python_sources():
            duplicates.extend(
                f"{scope} defines {name!r} at {first} and again at {second}"
                for scope, name, first, second in duplicate_definitions(
                    path.read_text(encoding="utf-8"), str(path.relative_to(REPO_ROOT))
                )
            )
        self.assertEqual(
            [], duplicates, "duplicate definitions: " + "; ".join(duplicates)
        )

    def test_a_rebound_name_whose_first_copy_is_used_is_caught_and_pyflakes_is_not(self):
        """The gap, stated as the tool actually behaves.

        pyflakes reports a redefinition of a `def`, a `class` or an `import` even
        when the earlier binding is used, so a duplicated function would have been
        caught. It says nothing about a name that is *rebound*:

            V = 1
            V = 2
            def caller(): return V

        That is silent, because the earlier value is used and the later one wins.
        The three unreferenced `LINT_GATE`/`LINT_VERSION` pairs removed in this
        pass were exactly this shape, and a caller of the first value would have
        been none the wiser. So the guard covers it and the demonstration runs
        pyflakes to show it does not.
        """
        source = (
            "GATE = 'first'\n"
            "\n"
            "GATE = 'second'\n"
            "\n"
            "def caller():\n"
            "    return GATE\n"
        )
        # The first copy is genuinely used, which is the condition that makes
        # pyflakes stay quiet.
        self.assertIn("return GATE", source)
        self.assertEqual(
            [("<test>", "GATE", 1, 3)],
            duplicate_definitions(source),
            "the scanner missed a rebound name whose first copy is used",
        )
        # And a duplicated `def` is caught too, even though pyflakes would also
        # catch that one, so the guard is not narrower than the shape it replaces.
        self.assertEqual(
            [("<test>", "helper", 1, 7)],
            duplicate_definitions(
                "def helper(f):\n    return 1\n\n"
                "def caller():\n    return helper(True)\n\n"
                "def helper(f):\n    return 2\n"
            ),
        )
        # pyflakes must actually run for this to be a demonstration: a subprocess
        # that failed to start reports empty stdout too, so a silence-only check
        # would pass whether or not pyflakes ever looked at the file. An earlier
        # version of this test made exactly that mistake and proved nothing.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rebound.py"
            target.write_text(source, encoding="utf-8")
            # The same resolution the lint gate uses: the interpreter when pyflakes is
            # importable, `uvx` otherwise. Calling `uvx` here directly was the second
            # run to fail on a GitHub-hosted macOS runner for the same reason as the
            # gate did - a runner has no `uvx` - and this test shells out to the linter
            # rather than through the gate, so fixing the gate alone left it broken.
            result = subprocess.run(
                pyflakes_argv() + [str(target)], capture_output=True, text=True
            )
            self.assertEqual(
                0, result.returncode, f"pyflakes did not run: {result.stderr.strip()[:300]}"
            )
            self.assertEqual(
                "", result.stdout.strip(),
                "pyflakes flagged the rebound name, so the gap this test rests on "
                "is closed upstream and the claim here is stale",
            )

    def test_a_duplicate_inside_a_class_is_reported_against_the_class(self):
        source = (
            "class Gate(unittest.TestCase):\n"
            "    def test_one(self):\n"
            "        self.assertTrue(True)\n"
            "\n"
            "    def test_one(self):\n"
            "        self.assertTrue(True)\n"
        )
        self.assertEqual(
            [("gate.py.Gate", "test_one", 2, 5)],
            duplicate_definitions(source, "gate.py"),
            "a duplicate inside a class is reported against that class, not the module",
        )

    def test_no_module_level_constant_is_unreferenced(self):
        """Every module-level constant under `tools/` is read somewhere.

        Three dead constants were removed by hand in earlier passes and one more
        in this one — `CONFIG_FIXTURE_DIR` in `validate-schemas.py`, left behind
        because a function that takes `root` as a parameter rebuilt the same path
        from its argument. Dead constants are not harmless: they are paths and
        patterns that look like the single place something is configured, and a
        reader changing one has changed nothing. `pyflakes` does not report a
        module-level constant that is simply never read, so nothing else would
        notice a new one.

        A name counts as referenced if it is loaded anywhere in `tools/`, in its
        own module or in any other. That matters because the module-level
        constants beside the one removed here are loaded by name *through the
        module* — `checker.CONFIG_SCHEMA_PATH` in the schema tests — so a guard
        that read only the defining file reported every one of them as dead. How
        many there are depends on how a reference is counted, which is why this
        paragraph states none: the count is not derived here and a hand-written
        one in the docstring of the guard against hand-written counts is worse
        than no count. A name read only from inside a function still counts as
        read.
        """
        loaded = set()
        for path in self.python_sources():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    loaded.add(node.id)
                elif isinstance(node, ast.Attribute):
                    loaded.add(node.attr)
        unreferenced = []
        for path in self.python_sources():
            relative = path.relative_to(REPO_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    continue
                for name, _ in _bound_names(node):
                    if name not in loaded:
                        unreferenced.append(f"{relative} defines {name}")
        self.assertEqual(
            [], unreferenced,
            "these module-level constants are never read, so they are a place a "
            "reader can change to no effect: " + "; ".join(unreferenced),
        )

    def test_every_binding_shape_that_counts_as_a_definition_is_reported(self):
        """Each shape, so widening the check later cannot quietly drop one."""
        # The expected names, not a count: a tuple or starred target binds more
        # than one name, so `A, B = 1, 2` colliding twice is two collisions and
        # saying otherwise would under-report the shape.
        shapes = {
            "annotated assignment": ("X: int = 1\n\nX: int = 2\n", {"X"}),
            "tuple target": ("A, B = 1, 2\n\nA, B = 3, 4\n", {"A", "B"}),
            "list target": ("A = [1]\n\nA = [2]\n", {"A"}),
            "starred target": ("A, *B = [1, 2]\n\nA, *B = [3, 4]\n", {"A", "B"}),
            "augmented assignment": ("A = 1\n\nA += 2\n", {"A"}),
            "import alias": ("import os as operating\n\nimport sys as operating\n", {"operating"}),
            "from import alias": ("from os import sep as s\n\nfrom sys import argv as s\n", {"s"}),
        }
        for label, (source, expected) in shapes.items():
            with self.subTest(shape=label):
                found = duplicate_definitions(source)
                self.assertTrue(
                    found, f"a duplicated {label} was not reported at all"
                )
                self.assertEqual(
                    expected, {name for _, name, _, _ in found},
                    f"the duplicated {label} reported {sorted(found)}",
                )
                for _, _, _, second in found:
                    self.assertEqual(
                        3, second,
                        f"the duplicated {label} was reported at the wrong line",
                    )

    def test_a_name_reused_in_two_different_classes_is_not_a_duplicate(self):
        # Two classes may each define `setUp`; that is normal and is not a
        # duplicate, so the check must not fire on the whole tree for it.
        source = (
            "class A(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        pass\n"
            "\n"
            "class B(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        pass\n"
        )
        self.assertEqual([], duplicate_definitions(source, "two.py"))

    def test_a_name_reused_by_a_loop_handle_or_handler_is_not_a_duplicate(self):
        """The exclusions, stated so they cannot be lost or widened by accident.

        Two loops binding the same name, two handles, two caught names: ordinary
        code. Reporting them would make this check fail on correct files, and the
        usual response to that is an exclusion list nobody reads — so the
        exclusions are written down here instead.
        """
        ordinary = (
            "def rows(items):\n"
            "    for item in items:\n"
            "        pass\n"
            "    for item in items:\n"
            "        pass\n"
            "    return item\n"
            "\n"
            "def reads(paths):\n"
            "    with open(paths[0]) as handle:\n"
            "        pass\n"
            "    with open(paths[1]) as handle:\n"
            "        pass\n"
            "    return handle\n"
            "\n"
            "def fails(rows_):\n"
            "    try:\n"
            "        pass\n"
            "    except KeyError as error:\n"
            "        pass\n"
            "    except ValueError as error:\n"
            "        return error\n"
        )
        self.assertEqual(
            [], duplicate_definitions(ordinary, "ordinary.py"),
            "ordinary reuse of a name was reported as a duplicate definition",
        )


class VerifyTagTests(unittest.TestCase):
    def run_tag(self, *arguments: str):
        return gate.run_script(TAG_SCRIPT, *arguments)

    def test_valid_tags_are_accepted(self):
        for tag in (
            "v0.1.0",
            "v1.20.300",
            "v0.1.0-beta.1",
            "v0.1.0-rc.1+build.5",
            "v1.2.3-0",
            "v1.2.3-0.3.7",
            "v1.2.3-x-y-z.92",
        ):
            with self.subTest(tag=tag):
                gate.assert_accepted(self, self.run_tag(tag))

    def test_invalid_tags_are_refused(self):
        for tag in (
            "",
            "0.1.0",
            "v1.2",
            "v1.2.3.4",
            "v01.2.3",
            "v1.02.3",
            "v1.2.03",
            "v1.2.3-",
            "release-1",
            "v1.2.3 ",
        ):
            with self.subTest(tag=tag):
                self.assertNotEqual(self.run_tag(tag).returncode, 0)

    def test_prerelease_identifiers_reject_numeric_leading_zeros(self):
        # Semantic versioning forbids leading zeros in numeric prerelease
        # identifiers. A shell regex cannot express that, so the grammar lives in
        # one place and every gate uses it.
        for tag in (
            "v1.2.3-01",
            "v1.2.3-alpha.01",
            "v1.2.3-1.02",
            "v1.2.3-0.01",
        ):
            with self.subTest(tag=tag):
                self.assertNotEqual(self.run_tag(tag).returncode, 0)

    def test_missing_argument_is_a_usage_error(self):
        gate.assert_usage_error(self, self.run_tag())

    def test_extra_argument_is_a_usage_error(self):
        gate.assert_usage_error(self, self.run_tag("v1.2.3", "v1.2.4"))

    def test_every_gate_shares_one_tag_grammar(self):
        grammar = REPO_ROOT / "tools/release/tag-grammar.sh"
        self.assertTrue(grammar.is_file(), f"{grammar} is missing")
        for script in ("tools/release/verify-tag.sh", "tools/reproducibility/manifest.sh", "tools/ci/verify-release-inputs.sh"):
            with self.subTest(script=script):
                text = (REPO_ROOT / script).read_text(encoding="utf-8")
                self.assertIn("tag-grammar.sh", text, f"{script} must share the tag grammar")
                self.assertNotIn("(0|[1-9][0-9]*)", text, f"{script} inlines its own tag regex")

    def test_manifest_and_release_gate_agree_with_the_tag_grammar(self):
        for tag in ("v1.2.3-01", "v1.2.3.4", "v01.2.3", "v1.2.3-0.3.7"):
            with self.subTest(tag=tag):
                with tempfile.TemporaryDirectory() as name:
                    directory = Path(name)
                    gate.write_approved_lock(directory)
                    artifact = gate.write_ipa(
                        directory / "Rovia.ipa", gate.app_info_plist("io.rovia.client", "1.2.3", "1")
                    )
                    result = gate.run_script(
                        REPO_ROOT / "tools/reproducibility/manifest.sh",
                        "--root",
                        str(directory),
                        "--artifact",
                        str(artifact),
                        "--tag",
                        tag,
                    )
                    accepted = result.returncode == 0
                    self.assertEqual(
                        accepted,
                        tag == "v1.2.3-0.3.7",
                        f"manifest.sh accepted {tag}: {gate.combined(result)}",
                    )


class WorkflowStepScannerTests(unittest.TestCase):
    """The publishing policy must inspect steps, not search the file for words."""

    SAMPLE = """name: sample

jobs:
  build:
    runs-on: macos-15
    steps:
      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
      - name: Build
        run: |
          xcodebuild -scheme RoviaApp build
      - name: Publish
        uses: actions/upload-artifact@v4
        with:
          name: Rovia
"""

    def setUp(self):
        self.steps = workflow_steps(self.SAMPLE)

    def test_step_scanner_finds_every_step(self):
        self.assertEqual([step.name for step in self.steps], ["Checkout", "Build", "Publish"])

    def test_step_scanner_reads_uses_and_run(self):
        publish = self.steps[2]
        self.assertEqual(publish.uses, "actions/upload-artifact@v4")
        self.assertEqual(self.steps[1].run.strip(), "xcodebuild -scheme RoviaApp build")

    def test_step_scanner_ignores_content_outside_steps(self):
        steps = workflow_steps(
            "name: gh release is forbidden\non: push\njobs:\n  a:\n    steps:\n"
            "      - name: Test\n        run: echo ok\n"
        )
        self.assertEqual([step.name for step in steps], ["Test"])

    def test_a_forbidden_token_inside_a_step_is_reported(self):
        # The scanner is deliberately fail-closed inside a step: a step may not
        # name a publishing tool even in a comment or a display name, because a
        # step is exactly where an upload could be added. Content outside any
        # step is not a step and is not reported.
        for body in (
            "      - name: Upload\n        # never run gh release here\n        run: echo ok\n",
            "      - name: Do not use altool\n        run: echo ok\n",
        ):
            with self.subTest(body=body):
                steps = workflow_steps(f"jobs:\n  a:\n    steps:\n{body}")
                self.assertEqual(len(steps), 1)
                self.assertEqual(len(publishing_steps(steps)), 1, body)

    def test_a_run_body_hidden_in_a_nested_key_is_still_reported(self):
        # Anything the scanner cannot attribute to a step is a gap, so a
        # publishing action cannot hide from it by changing indentation.
        steps = workflow_steps(
            "jobs:\n  a:\n    steps:\n      - name: Build\n        with:\n"
            "          args: gh release create v1.0.0\n        run: echo ok\n"
        )
        self.assertEqual(publishing_steps(steps), ["Build"])

    def test_step_scanner_reports_no_steps_when_there_are_none(self):
        self.assertEqual(workflow_steps("name: empty\njobs: {}\n"), [])

    def test_upload_artifact_in_a_step_is_reported(self):
        self.assertEqual(publishing_steps(self.steps), ["Publish"])

    def test_a_clean_workflow_has_no_publishing_step(self):
        clean = workflow_steps(self.SAMPLE.replace("      - name: Publish\n        uses: actions/upload-artifact@v4\n        with:\n          name: Rovia\n", ""))
        self.assertEqual(publishing_steps(clean), [])

    def test_release_upload_via_gh_is_reported(self):
        steps = workflow_steps(
            "jobs:\n  a:\n    steps:\n      - name: Upload\n        run: gh release create v1.0.0 out.ipa\n"
        )
        self.assertEqual(publishing_steps(steps), ["Upload"])

    def test_notary_and_altool_in_a_step_are_reported(self):
        for command in (
            "xcrun notarytool submit out.ipa",
            "xcrun altool --upload-app",
            "notarytool history",
            "altool -F out.zip",
        ):
            with self.subTest(command=command):
                steps = workflow_steps(
                    f"jobs:\n  a:\n    steps:\n      - name: Distribute\n        run: {command}\n"
                )
                self.assertEqual(publishing_steps(steps), ["Distribute"])

    def test_the_documented_policy_names_the_same_forbidden_set(self):
        forbidden = policy_forbidden_tokens()
        self.assertTrue(forbidden)
        for token in ("actions/upload-artifact", "gh release", "notarytool", "altool"):
            with self.subTest(token=token):
                self.assertIn(token, forbidden)


class PreCommitConfigTests(unittest.TestCase):
    """`.pre-commit-config.yaml` exists because pre-commit.ci is installed.

    With no configuration the app does not skip - it posts `error during ci config`
    and leaves a failing status on every pull request. Adding the file to make that
    status go away would be the wrong fix, and it is checkable: the hooks have to be
    hooks that run, on this tree, today.

    Most of these assertions exist because two hooks in this file were silently
    inert when first written, and both would have passed every test that only
    asserted the hook id was present:

    * `check-merge-conflict` reads the git directory, and returns success without
      opening a single file unless it finds MERGE_HEAD or is passed
      `--assume-in-merge`. Standalone - which is how pre-commit.ci invokes it, and
      how it is verified here - it therefore never fires.
    * `check-added-large-files` intersects its input with
      `git diff --staged --diff-filter=A`, so it only inspects files added in this
      one commit. A build product committed small and grown by a later commit is
      never checked, which is the case that matters.

    A hook that cannot fail is worse than a hook that is absent, because the
    configuration then reads as coverage. The two assertions below are the guard.
    """

    def setUp(self):
        self.path = REPO_ROOT / ".pre-commit-config.yaml"
        self.assertTrue(self.path.is_file(), "the pre-commit configuration is missing")
        self.text = self.path.read_text(encoding="utf-8")

    def test_the_config_asks_merge_conflict_to_read_the_files_it_is_given(self):
        # Without the flag the hook exits 0 before reading anything whenever the
        # repository is not mid-merge, which is the normal case.
        self.assertRegex(
            self.text,
            r"id: check-merge-conflict\s*\n\s*args: \[[^\]]*--assume-in-merge[^\]]*\]",
            "check-merge-conflict is declared without --assume-in-merge, so it "
            "returns success without reading a file unless a merge is in progress",
        )

    def test_the_config_makes_the_size_ceiling_apply_to_every_file(self):
        # Without the flag the hook only sees files added in this commit, so the
        # ceiling says nothing about a file that grew after it was committed.
        self.assertRegex(
            self.text,
            r"id: check-added-large-files\s*\n\s*args: \[[^\]]*--enforce-all[^\]]*\]",
            "check-added-large-files is declared without --enforce-all, so it only "
            "inspects files newly added in this commit",
        )

    def test_every_hook_repository_is_pinned(self):
        # pre-commit.ci reads this file from the pull request, so a floating ref
        # would let a pull request decide what runs in CI. Same argument that pins
        # every action in .github/workflows, asserted by WorkflowPolicyTests.
        revisions = re.findall(r"^\s*rev:\s*(\S+)\s*$", self.text, re.MULTILINE)
        self.assertTrue(revisions, "no hook repository is declared")
        for revision in revisions:
            with self.subTest(rev=revision):
                self.assertNotRegex(revision, r"^(v?\d|main|master|latest)$")

    def test_every_local_hook_names_a_script_that_exists_and_runs(self):
        entries = re.findall(r"^\s*entry:\s*(\S+)\s*$", self.text, re.MULTILINE)
        self.assertTrue(entries, "no local hook is declared")
        for entry in entries:
            with self.subTest(entry=entry):
                target = REPO_ROOT / entry
                self.assertTrue(target.is_file(), f"{entry} does not exist")
                self.assertTrue(
                    os.access(target, os.X_OK), f"{entry} is not executable"
                )

    def test_the_local_hooks_are_the_gates_the_hosted_runner_already_runs(self):
        """pre-commit and CI must not drift into checking different things.

        The point of the local hooks is to reach the same defects earlier, not to add
        a second opinion. A pre-commit-only gate is a gate nobody runs in CI, and a
        CI-only gate is one nobody runs before committing.

        Three of the runner's four gates are here. The fourth, the pyflakes gate, is
        deliberately absent and the set is asserted at three so it cannot be added back
        by accident: it resolves pyflakes only from a pinned route, and the
        pre-commit.ci container has neither an interpreter that can import pyflakes nor
        `uvx` on PATH, so it runs and refuses. Re-adding it here would either give the
        same claim two meanings or produce a gate that reports success without running.
        The gate is not lost - `ios-ci` builds a virtualenv with pyflakes==3.2.0 and puts
        it on PATH before calling the script, and `run-tool-tests.sh` reaches it locally.
        """
        self.assertIn(
            "refusing to report success from a linter that did not run", self.text,
            "the reason the pyflakes gate is absent is not recorded in the config, so "
            "the next person to add it back has to rediscover it by reading a run log",
        )
        # No attempt is made here to assert the absence of the file name: the
        # configuration has to *mention* the script to explain why it is not wired,
        # and a test that forbade the mention would forbid the explanation. The
        # `entry:` set above is the assertion that matters - a hook is wired by
        # naming an entry, so an entry outside that set is not wired.
        declared = set(re.findall(r"^\s*entry:\s*(\S+)\s*$", self.text, re.MULTILINE))
        self.assertEqual(
            declared,
            {
                "tools/ci/check-repository-hygiene.sh",
                "tools/ci/check-python-warnings.sh",
                "tools/ci/check-shell-syntax.sh",
            },
            "the pre-commit local hooks and the hosted gates have diverged; one of "
            "the two is not checking what the other checks",
        )
        # Three of the four are named by `run-tool-tests.sh` rather than by the
        # workflow, and that indirection is deliberate: the runner is one step and the
        # gates belong together, and a local machine gets the same set by running the
        # runner. So a gate counts as covered if either the workflow or the runner
        # names it - the same distinction `WorkflowPolicyTests` already draws with
        # REACHED_THOUGH_THE_RUNNER, and for the same reason.
        workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        runner = (REPO_ROOT / "tools/ci/run-tool-tests.sh").read_text(encoding="utf-8")
        # Named `script`, not `gate`: `gate` is the module alias
        # `script_test_support as gate` used throughout this file, and shadowing it
        # with a loop variable is what pyflakes correctly reported on the first run
        # of this test.
        for script in declared:
            with self.subTest(script=script):
                self.assertTrue(
                    script in workflow or script in runner,
                    f"{script} is a pre-commit hook but neither ci.yml nor "
                    "run-tool-tests.sh executes it, so it is not a CI gate at all",
                )

    def test_the_documented_exclusions_stay_excluded(self):
        """The two hooks left out on purpose, and the reason, stay in the file.

        92 tracked files carry trailing whitespace, and cleaning it is a 92-file
        mechanical diff unrelated to this configuration. That decision is recorded in
        the file's comments so it is not re-made silently - and if either hook is
        added later, this fails and forces the diff and the record to be updated
        together.
        """
        self.assertIn("trailing-whitespace", self.text)
        self.assertIn("end-of-file-fixer", self.text)
        # The pattern is compiled here rather than passed as a string, and that is the
        # second version's correction. AssertNotRegex has no `flags` parameter, so the
        # first attempt passed the flag positionally, where it was taken as `msg`: the
        # pattern was compiled without MULTILINE, `^` and `$` matched only the ends of
        # the whole string, and the assertion passed for every configuration including
        # the one it exists to reject. Adding the hook back is what exposed it.
        for hook in ("trailing-whitespace", "end-of-file-fixer"):
            with self.subTest(hook=hook):
                self.assertNotRegex(
                    self.text,
                    re.compile(rf"^\s*- id: {re.escape(hook)}\s*$", re.MULTILINE),
                    f"{hook} is declared. It is excluded on purpose because cleaning "
                    "92 files is a separate change, not part of this one; adding it "
                    "means making that diff and updating this record together",
                )


class CheckShellSyntaxTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.directory)], check=False)

    def test_repository_shell_scripts_parse(self):
        gate.assert_accepted(self, gate.run_script(SHELL_SCRIPT))

    def test_repository_actually_contains_shell_scripts(self):
        scripts = sorted((REPO_ROOT / "tools").glob("**/*.sh"))
        self.assertGreaterEqual(len(scripts), 6, scripts)

    def test_broken_script_is_refused(self):
        (self.directory / "good.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\n", encoding="utf-8")
        (self.directory / "broken.sh").write_text("#!/usr/bin/env bash\nif [ ; then\n", encoding="utf-8")
        result = gate.run_script(SHELL_SCRIPT, "--root", str(self.directory))
        gate.assert_refused(self, result, "broken.sh")

    def test_syntax_error_in_a_nested_script_is_refused(self):
        nested = self.directory / "tools" / "deep"
        nested.mkdir(parents=True)
        (nested / "broken.sh").write_text("echo ${\n", encoding="utf-8")
        result = gate.run_script(SHELL_SCRIPT, "--root", str(self.directory))
        gate.assert_refused(self, result, "broken.sh")

    def test_directory_without_scripts_is_refused(self):
        (self.directory / "notes.md").write_text("nothing to check\n", encoding="utf-8")
        result = gate.run_script(SHELL_SCRIPT, "--root", str(self.directory))
        gate.assert_refused(self, result, "no shell scripts")

    def test_build_directories_are_ignored(self):
        build = self.directory / "tools" / ".build"
        build.mkdir(parents=True)
        (build / "broken.sh").write_text("if [ ; then\n", encoding="utf-8")
        (self.directory / "good.sh").write_text("echo ok\n", encoding="utf-8")
        gate.assert_accepted(self, gate.run_script(SHELL_SCRIPT, "--root", str(self.directory)))

    def test_the_validator_virtualenv_is_pruned(self):
        # A virtualenv holds vendored scripts this repository does not own, in
        # the same way a build directory does.
        venv = self.directory / ".ci-schema-validator" / "bin"
        venv.mkdir(parents=True)
        (venv / "vendored.sh").write_text("if [ ; then\n", encoding="utf-8")
        (self.directory / "good.sh").write_text("echo ok\n", encoding="utf-8")
        gate.assert_accepted(self, gate.run_script(SHELL_SCRIPT, "--root", str(self.directory)))

    def test_unknown_flag_is_a_usage_error(self):
        gate.assert_usage_error(self, gate.run_script(SHELL_SCRIPT, "--allow-anything"))


class VerifyBundleMetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.directory)], check=False)
        self.app = self.build_app()

    def build_app(
        self,
        app_identifier: str = APP_IDENTIFIER,
        tunnel_identifier: str = TUNNEL_IDENTIFIER,
        short_version: str = "0.1.0",
        version: str = "1",
        executable: str = "Rovia",
        include_extension: bool = True,
        raw_app_plist: bytes | None = None,
    ) -> Path:
        app = self.directory / "RoviaApp.app"
        if app.exists():
            shutil.rmtree(app)
        app.mkdir(parents=True, exist_ok=True)
        if raw_app_plist is not None:
            (app / "Info.plist").write_bytes(raw_app_plist)
        else:
            (app / "Info.plist").write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleExecutable": executable,
                        "CFBundleIdentifier": app_identifier,
                        "CFBundleName": "Rovia",
                        "CFBundlePackageType": "APPL",
                        "CFBundleShortVersionString": short_version,
                        "CFBundleVersion": version,
                        "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
                    }
                )
            )
        if executable:
            (app / executable).write_bytes(b"Mach-O fixture")
        if include_extension:
            extension = app / "PlugIns" / "RoviaTunnel.appex"
            extension.mkdir(parents=True, exist_ok=True)
            (extension / "Info.plist").write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleExecutable": "RoviaTunnel",
                        "CFBundleIdentifier": tunnel_identifier,
                        "CFBundleName": "RoviaTunnel",
                        "CFBundlePackageType": "XPC!",
                        "CFBundleShortVersionString": short_version,
                        "CFBundleVersion": version,
                    }
                )
            )
            (extension / "RoviaTunnel").write_bytes(b"Mach-O fixture")
        return app

    def verify(self, *arguments: str):
        return gate.run_script(BUNDLE_SCRIPT, *arguments)

    def test_valid_app_and_extension_pass(self):
        gate.assert_accepted(self, self.verify(str(self.app)))

    def test_missing_bundle_is_refused(self):
        gate.assert_refused(
            self, self.verify(str(self.directory / "absent.app")), "does not exist"
        )

    def test_a_directory_that_is_not_a_bundle_is_refused(self):
        gate.assert_refused(self, self.verify(str(self.directory)), "Info.plist")

    def test_missing_info_plist_is_refused(self):
        (self.app / "Info.plist").unlink()
        gate.assert_refused(self, self.verify(str(self.app)), "Info.plist")

    def test_unreadable_info_plist_is_refused(self):
        (self.app / "Info.plist").write_bytes(b"not a plist")
        gate.assert_refused(self, self.verify(str(self.app)), "Info.plist")

    def test_unexpanded_build_variables_are_refused(self):
        self.build_app(app_identifier="$(PRODUCT_BUNDLE_IDENTIFIER)")
        gate.assert_refused(self, self.verify(str(self.app)), "unexpanded build variable")

    def test_missing_bundle_executable_is_refused(self):
        self.build_app(executable="")
        gate.assert_refused(self, self.verify(str(self.app)), "CFBundleExecutable")

    def test_bundle_executable_without_a_binary_is_refused(self):
        (self.app / "Rovia").unlink()
        gate.assert_refused(self, self.verify(str(self.app)), "CFBundleExecutable")

    def test_missing_extension_is_refused(self):
        self.build_app(include_extension=False)
        gate.assert_refused(self, self.verify(str(self.app)), "RoviaTunnel.appex")

    def test_extension_with_an_unexpanded_identifier_is_refused(self):
        self.build_app(tunnel_identifier="$(PRODUCT_BUNDLE_IDENTIFIER)")
        gate.assert_refused(self, self.verify(str(self.app)), "unexpanded build variable")

    def test_extension_that_is_not_a_prefix_of_the_app_identifier_is_refused(self):
        self.build_app(tunnel_identifier="io.rovia.other.tunnel")
        gate.assert_refused(self, self.verify(str(self.app)), "extension identifier")

    def test_empty_bundle_identifier_is_refused(self):
        self.build_app(app_identifier="")
        gate.assert_refused(self, self.verify(str(self.app)), "CFBundleIdentifier")

    def test_mismatched_versions_are_refused(self):
        app = self.app / "PlugIns" / "RoviaTunnel.appex"
        (app / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleExecutable": "RoviaTunnel",
                    "CFBundleIdentifier": TUNNEL_IDENTIFIER,
                    "CFBundleName": "RoviaTunnel",
                    "CFBundlePackageType": "XPC!",
                    "CFBundleShortVersionString": "0.2.0",
                    "CFBundleVersion": "9",
                }
            )
        )
        gate.assert_refused(self, self.verify(str(self.app)), "version")

    def test_non_numeric_bundle_version_is_refused(self):
        self.build_app(version="1.0-beta")
        gate.assert_refused(self, self.verify(str(self.app)), "CFBundleVersion")

    def test_empty_short_version_is_refused(self):
        self.build_app(short_version="")
        gate.assert_refused(self, self.verify(str(self.app)), "CFBundleShortVersionString")

    def test_non_bundle_package_type_is_refused(self):
        document = plistlib.loads((self.app / "Info.plist").read_bytes())
        document["CFBundlePackageType"] = "FMWK"
        (self.app / "Info.plist").write_bytes(plistlib.dumps(document))
        gate.assert_refused(self, self.verify(str(self.app)), "CFBundlePackageType")

    def test_expected_version_can_be_required(self):
        gate.assert_accepted(self, self.verify(str(self.app), "--expect-version", "0.1.0"))
        gate.assert_refused(self, self.verify(str(self.app), "--expect-version", "9.9.9"), "9.9.9")

    def test_expected_identifier_can_be_required(self):
        gate.assert_accepted(
            self, self.verify(str(self.app), "--expect-identifier", APP_IDENTIFIER)
        )
        gate.assert_refused(
            self, self.verify(str(self.app), "--expect-identifier", "io.rovia.other"),
            "io.rovia.other",
        )


def swiftpm_counts():
    """{package: test count}, counted from the suites rather than remembered.

    The record said 140 across seven packages, and the number was stale the moment
    the mapped-address and degenerate-domain work added tests. Counting the suites'
    own test lists is the only derivation available without running `swift test`
    from a documentation check, and it is a count of tests that exist, not a figure
    carried forward. Per package as well as in total, because the per-package rows
    were hand-written from a run while only the total was bound.
    """
    counts = {}
    for relative in local_packages():
        directory = REPO_ROOT / relative / "Tests"
        if not directory.is_dir():
            continue
        total = 0
        for suite in sorted(directory.rglob("*.swift")):
            source = suite.read_text(encoding="utf-8")
            # Every `func test…` is one test method, including the helper
            # classes' cases; a suite with none contributes nothing.
            total += len(re.findall(r"\bfunc (test\w*)\s*\(", source))
        counts[relative] = total
    return counts


def swiftpm_total():
    return sum(swiftpm_counts().values())


class PythonLintGateTests(unittest.TestCase):
    """The five tests that hold `tools/ci/check-python-lint.sh` in place.

    They live in their own class so the count in the documents is derived from the
    class rather than from a filter over the module. A sixth test added here is
    counted the moment it is written, and the document check then fails until the
    documents are updated — which is the binding a name-based heuristic cannot
    provide.
    """

    LINT_GATE = "tools/ci/check-python-lint.sh"
    LINT_VERSION = "3.2.0"
    def test_the_lint_gate_is_a_gate_with_a_pinned_version(self):
        # The record claimed "pyflakes clean" as executed evidence. pyflakes is not
        # installed for any system interpreter on this machine, and an unpinned
        # `uvx pyflakes` resolves to 4.0.0 while the record named 3.2.0 — so the
        # claim was not reproducible and its version was wrong.
        script = REPO_ROOT / self.LINT_GATE
        self.assertTrue(script.is_file(), f"{self.LINT_GATE} does not exist")
        self.assertTrue(
            os.access(script, os.X_OK), f"{self.LINT_GATE} is not executable"
        )
        source = script.read_text(encoding="utf-8")
        self.assertIn(f'PYFLAKES_VERSION="{self.LINT_VERSION}"', source)
        self.assertIn('uvx "pyflakes==${PYFLAKES_VERSION}"', source)
        self.assertNotIn(
            "uvx pyflakes\n", source,
            "an unpinned uvx pyflakes resolves to whatever is newest",
        )
        self.assertIn(
            "refusing to report success from a linter that did not run", source
        )

    def test_the_lint_gate_is_invoked_by_the_test_runner(self):
        # A gate listed in a document is a claim; a gate the runner invokes is a
        # gate.
        runner = (REPO_ROOT / "tools/ci/run-tool-tests.sh").read_text(encoding="utf-8")
        self.assertIn("check-python-lint.sh", runner)
        self.assertIn("the Python lint gate reported findings", runner)

    def test_the_lint_gate_refuses_a_file_with_a_finding(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            (root / "tools" / "ci").mkdir(parents=True)
            (root / "tools" / "ci" / "lintprobe.py").write_text(
                "import os\n\n\ndef f():\n    return 1\n", encoding="utf-8"
            )
            result = subprocess.run(
                [str(REPO_ROOT / self.LINT_GATE), "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("imported but unused", result.stdout + result.stderr)

    def test_the_lint_gate_refuses_when_there_is_nothing_to_lint(self):
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            (root / "tools").mkdir(parents=True)
            result = subprocess.run(
                [str(REPO_ROOT / self.LINT_GATE), "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode, 1,
                "an empty tree is not a clean tree",
            )
            self.assertIn("no Python files", result.stderr)

    def test_the_documents_record_the_exact_lint_command(self):
        command = "./tools/ci/check-python-lint.sh"
        pinned = f"pyflakes=={self.LINT_VERSION}"
        for document in (
            "docs/development/ci.md",
            "docs/development/foundation-verification.md",
        ):
            body = (REPO_ROOT / document).read_text(encoding="utf-8")
            with self.subTest(document=document):
                self.assertIn(command, body, f"{document} does not name the command")
                self.assertIn(
                    pinned, body,
                    f"{document} does not state the pinned version",
                )
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("pyflakes 4.0.0", record)

class PythonWarningsGateTests(unittest.TestCase):
    """The tests that hold `tools/ci/check-python-warnings.sh` in place.

    A twin of `PythonLintGateTests`. The warnings gate was added with one test — the
    one that proved it refuses a file with an invalid escape sequence — and that left
    its wiring, its empty-tree refusal and its documentation held by nothing: deleting
    the invocation from `run-tool-tests.sh`, deleting the guard, or deleting the
    `ci.md` row all left the suite green. The lint gate's own class holds all three,
    which is the standard this one follows.
    """

    GATE = "tools/ci/check-python-warnings.sh"
    RUNNER = "tools/ci/run-tool-tests.sh"

    def gate_source(self):
        return (REPO_ROOT / self.GATE).read_text(encoding="utf-8")

    def test_the_gate_exists_and_is_executable(self):
        gate = REPO_ROOT / self.GATE
        self.assertTrue(gate.is_file(), f"{self.GATE} does not exist")
        self.assertTrue(os.access(gate, os.X_OK), f"{self.GATE} is not executable")

    def test_the_runner_invokes_the_gate(self):
        # Without this the gate is a script nobody runs, and CI loses it silently:
        # `test_ci_runs_every_local_gate` only requires `run-tool-tests.sh`, so
        # deleting the line from the runner removes the gate from CI with every test
        # green.
        runner = (REPO_ROOT / self.RUNNER).read_text(encoding="utf-8")
        self.assertIn(
            self.GATE, runner,
            f"{self.RUNNER} does not invoke {self.GATE}, so the gate is not run",
        )
        self.assertIn(
            "the Python warnings gate reported findings", runner,
            f"{self.RUNNER} invokes {self.GATE} without failing on its findings",
        )

    def test_the_gate_refuses_when_there_is_nothing_to_check(self):
        # A gate that checked nothing must not look like a gate that passed, and the
        # refusal has to survive the failure mode that makes it fail open: on the
        # macOS default bash 3.2, `set -u` plus an EXIT trap that runs a command turns
        # an unbound array expansion into exit 0, and the runner's `if !` reads that
        # as success. So both the well-formed empty tree and the same tree with the
        # shell guard cut out are required to exit non-zero — the second one is
        # refused by the interpreter step rather than by the guard.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools" / "ci").mkdir(parents=True)
            empty = subprocess.run(
                [str(REPO_ROOT / self.GATE), "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                1, empty.returncode,
                "the gate accepted an empty tree: "
                f"{empty.stdout}{empty.stderr}",
            )
            self.assertIn(
                "no Python files", empty.stdout + empty.stderr,
                "the refusal did not say what it refused",
            )

            # The guard cut out of a copy: the script must still refuse, and not
            # through `set -u` aborting.
            source = self.gate_source()
            begin = source.index("if [[ $file_count -eq 0 ]]; then")
            finish = source.index("\nfi\n", begin) + len("\nfi\n")
            unguarded = root / "unguarded.sh"
            unguarded.write_text(source[:begin] + source[finish:])
            unguarded.chmod(0o755)
            stripped = subprocess.run(
                [str(unguarded), "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                0, stripped.returncode,
                "with the empty-tree guard removed the gate succeeded, which is the "
                "unbound-array failure: bash 3.2 exits 0 there and the runner's "
                f"`if !` reads it as success\n{stripped.stdout}{stripped.stderr}",
            )

    def test_the_documents_name_the_gate(self):
        # A gate in a script but not in a document is a gate a reader cannot run.
        for document in ("docs/development/ci.md", "CHANGELOG.md"):
            body = (REPO_ROOT / document).read_text(encoding="utf-8")
            with self.subTest(document=document):
                self.assertIn(
                    self.GATE, body, f"{document} does not name {self.GATE}"
                )
        ci = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        self.assertIn(
            "check-python-lint.sh", ci,
            "ci.md no longer names the lint gate, so the pair is not described",
        )
        # The runner's own description has to mention both gates it ends with, and
        # neither may be listed twice in the command block.
        self.assertIn(
            "then both Python gates", ci,
            "ci.md no longer says the runner ends with both Python gates, so "
            "removing the warnings gate from the runner would leave the document "
            "describing a runner that does not exist",
        )
        command_block = ci[ci.index("```text"): ci.index("```", ci.index("```text") + 7)]
        for gate_path in (self.GATE, "tools/ci/check-python-lint.sh"):
            with self.subTest(gate=gate_path):
                self.assertEqual(
                    1, command_block.count(gate_path),
                    f"ci.md's command block names {gate_path} "
                    f"{command_block.count(gate_path)} times; it should be once",
                )

    def test_the_gate_refuses_a_file_with_an_invalid_escape_sequence(self):
        """The gate added for the class it covers, proved on a file that has it.

        The class: an invalid escape sequence in a docstring. pyflakes reports nothing
        about it, the warning appeared on stderr during a normal run, and this
        repository had one. The gate has to refuse such a file, and it has to pass on
        the tree — a gate that refuses everything is not a gate.
        """
        gate = REPO_ROOT / "tools/ci/check-python-warnings.sh"
        self.assertTrue(gate.is_file(), f"{gate} does not exist")
        self.assertTrue(os.access(gate, os.X_OK), f"{gate} is not executable")
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / "tools" / "ci"
            tree.mkdir(parents=True)
            offender = tree / "offender.py"
            offender.write_text(
                '"""A docstring with \\w and \\d in it, which is not a raw string."""\n'
                "\n"
                "def f():\n"
                "    return 1\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(gate), "--root", str(Path(directory))],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                1, result.returncode,
                "the warnings gate accepted a file with an invalid escape sequence: "
                f"{result.stdout}{result.stderr}",
            )
            self.assertIn(
                "offender.py", result.stdout + result.stderr,
                "the gate failed without naming the file that warned",
            )
            self.assertIn(
                "escape sequence", result.stdout + result.stderr,
                "the gate did not report what it objected to",
            )
        # And it passes on this repository, so the refusal above is the gate working
        # rather than a gate that refuses everything.
        clean = subprocess.run([str(gate)], capture_output=True, text=True)
        self.assertEqual(
            0, clean.returncode,
            f"the warnings gate failed on this repository: {clean.stdout}{clean.stderr}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
