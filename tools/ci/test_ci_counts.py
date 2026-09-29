"""Thematic split of the former tools/ci/test_ci_checks.py.

Shared fixtures and loaders live in ci_check_support.py; this file
holds LiveCountDerivationTests.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from ci_check_support import (
    REPO_ROOT,
    accessibility_identifier_counts,
    flat,
    json_input_groups,
    json_inputs,
    local_package_manifest_count,
    read_record,
    require_the_count_check_fails,
    sbom_component_counts,
    semantic_probe_negative_count,
    shell_script_count,
    signing_identity_position,
    tracked_top_level_count,
    unexecuted_gate_count,
    word_for,
    workflow_step_counts,
)


class LiveCountDerivationTests(unittest.TestCase):
    """The ten live counts in the documents, each read from its real source.

    The record said "no other count in the documents is hand-written and
    ungated" and that was false. Ten counts were accurate and ungated: they were
    transcribed from a run and nothing re-read them, so accuracy was a
    coincidence of timing rather than a property of the tree. Each one below is
    derived from the thing it describes, and a mutation test proves the binding
    is real rather than a string that happens to be present.
    """

    def record(self):
        return read_record()

    # -- the ten -----------------------------------------------------------

    def test_the_json_input_counts_are_the_files_on_disk(self):
        total, schemas, fixtures = json_input_groups()
        # The record's line names the total, the schema count and the fixture
        # count, and names the one file that is neither.
        self.assertIn(f"over {total} files", self.record())
        self.assertIn(f"{schemas} schemas", self.record())
        self.assertIn(f"{fixtures} fixtures", self.record())
        self.assertEqual(
            total - schemas - fixtures,
            1,
            f"expected exactly one non-schema non-fixture JSON file, got "
            f"{[str(p) for p in json_inputs() if p.parts[0] not in ('schemas', 'fixtures')]}",
        )

    def test_the_accessibility_identifier_counts_come_from_the_audit(self):
        containers, elements, reaching = accessibility_identifier_counts()
        self.assertIn(
            f"`{reaching}` declared constants, `{containers}` container identifiers, "
            f"`{elements}` element identifiers, `{reaching}` reaching a view",
            self.record(),
            "the record does not state the accessibility counts the audit prints",
        )

    def test_the_sbom_component_and_relationship_counts_come_from_the_generator(self):
        components, relationships = sbom_component_counts()
        record = self.record()
        self.assertIn(f"`{components} components`", record)
        # The record states the count and then its own breakdown, so the number is
        # matched up to the colon rather than to the cell edge.
        self.assertIn(
            f"| Relationships | {relationships}:",
            record,
            "the record does not state the SBOM relationship count the generator "
            "produced",
        )

    def test_the_workflow_step_counts_come_from_the_workflows(self):
        counts = workflow_step_counts()
        self.assertEqual(
            sorted(counts), ["ci.yml", "engine-repro.yml", "release-ios.yml"]
        )
        for name, (jobs, steps) in counts.items():
            with self.subTest(workflow=name):
                self.assertIn(
                    f"`{name}` {jobs} job{'s' if jobs != 1 else ''} / {steps} steps",
                    self.record(),
                    f"the record does not state {name}'s {jobs} jobs / {steps} steps",
                )

    def test_the_shell_script_count_comes_from_the_tree(self):
        count = shell_script_count()
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"`{count} shell scripts parse`", self.record())
        # Every other place the record states the count is tied to the same figure.
        # It used to carry a second, hand-written one — 15, against a tree of 16 —
        # in the `bash -n` row, and nothing held it.
        stated = re.findall(
            r"(\d+)\s+scripts?(?:,\s*no syntax error)?", record
        )
        for number in stated:
            with self.subTest(number=number):
                self.assertEqual(
                    count, int(number),
                    f"the record states {number} scripts where the tree holds {count}",
                )

    def test_the_local_package_manifest_count_comes_from_the_package_list(self):
        count = local_package_manifest_count()
        self.assertIn(
            f"`{count} local package manifests verified", self.record()
        )

    def test_the_tracked_entry_count_comes_from_git(self):
        self.assertIn(f"{tracked_top_level_count()} tracked top-level entries", self.record())

    def test_the_signing_step_position_comes_from_the_workflow(self):
        position, total = signing_identity_position()
        self.assertIn(f"at position {position} of {total}", self.record())

    def test_the_unexecuted_gate_count_comes_from_the_readiness_document(self):
        self.assertIn(f"The {word_for(unexecuted_gate_count())} unexecuted gates", self.record())

    def test_the_semantic_probe_negative_count_comes_from_the_validator(self):
        self.assertIn(
            f"the validator runs {semantic_probe_negative_count()} negative cases",
            self.record(),
        )

    # -- the working directory --------------------------------------------

    def test_the_derivations_do_not_depend_on_the_working_directory(self):
        """Every derivation is called from a directory that is not the repo root.

        The suite runs from the repository root and from `tools/ci` — the second
        is how a developer runs it, and it is how the runner invokes it. A
        derivation that shells out with an absolute script path but a relative
        default inside that script works from one and not the other, so each one
        is called here with the process moved somewhere unrelated.
        """
        expected = {
            "accessibility": accessibility_identifier_counts(),
            "json": json_input_groups(),
            "sbom": sbom_component_counts(),
            "workflow": workflow_step_counts(),
            "shell": (shell_script_count(),),
            "manifests": (local_package_manifest_count(),),
            "signing": signing_identity_position(),
            "gates": (unexecuted_gate_count(),),
        }
        with tempfile.TemporaryDirectory() as elsewhere:
            previous = os.getcwd()
            try:
                os.chdir(elsewhere)
                # Assert the chdir happened. Comparing an empty tuple with an empty
                # tuple cannot fail, and without this the whole test would pass
                # having read nothing from anywhere but the repository root — which
                # is the case it exists to rule out.
                self.assertEqual(
                    os.path.realpath(elsewhere), os.path.realpath(os.getcwd()),
                    f"the chdir did not take effect; cwd is {os.getcwd()}",
                )
                self.assertNotEqual(
                    os.path.realpath(str(REPO_ROOT)), os.path.realpath(os.getcwd()),
                    "the test is running from the repository root, so it cannot "
                    "show that the derivations are working-directory independent",
                )
                observed = {
                    "accessibility": accessibility_identifier_counts(),
                    "json": json_input_groups(),
                    "sbom": sbom_component_counts(),
                    "workflow": workflow_step_counts(),
                    "shell": (shell_script_count(),),
                    "manifests": (local_package_manifest_count(),),
                    "signing": signing_identity_position(),
                    "gates": (unexecuted_gate_count(),),
                }
            finally:
                os.chdir(previous)
        for name in expected:
            with self.subTest(derivation=name):
                self.assertEqual(
                    expected[name], observed[name],
                    f"{name} read differently from {elsewhere!r}, so it depends on "
                    "the working directory",
                )

    # The thematic split lives in five modules; the nested run executes all
    # five, and the count below is their sum.
    SPLIT_MODULES = (
        "test_ci_changelog",
        "test_ci_toolchain",
        "test_ci_workflows",
        "test_ci_counts",
        "test_ci_docs",
    )

    def test_the_whole_split_passes_when_it_is_run_from_outside_the_repository(self):
        """Every test in the split family, run from a directory outside the repository.

        The chdir test above covers the derivations. This runs all five split
        modules the way a developer or a CI job might, so a dependency nothing
        else owns — a relative path in a test that reads a script, a `git`
        call that resolves the repository from the process directory — fails
        here rather than for the next person who runs the files from elsewhere.

        It used to run only this class, while four places in the repository
        described it as running "the whole file". That was a claim about more
        than the test did, and the git call above is exactly the kind of
        dependency it would not have caught. It runs the split family now, and
        the nested run's own count is checked so "the whole split" stays true.

        `ROVIA_CWD_PROBE` marks the nested run, which is what stops this
        recursing: the nested copy skips this test rather than spawning a run
        that spawns another.
        """
        if os.environ.get("ROVIA_CWD_PROBE"):
            self.skipTest("this is the nested run; it must not spawn another")
        with tempfile.TemporaryDirectory() as elsewhere:
            # The module lives beside this file, not in the directory the nested
            # run starts from, so its directory goes on the path explicitly.
            environment = dict(
                os.environ,
                ROVIA_CWD_PROBE="1",
                PYTHONPATH=os.pathsep.join(
                    [str(Path(__file__).resolve().parent), os.environ.get("PYTHONPATH", "")]
                ).rstrip(os.pathsep),
            )
            result = subprocess.run(
                [sys.executable, "-m", "unittest", *self.SPLIT_MODULES],
                capture_output=True,
                text=True,
                cwd=elsewhere,
                env=environment,
            )
            self.assertEqual(
                0, result.returncode,
                "the suite failed when run from "
                f"{elsewhere!r}:\n{result.stdout[-2000:]}\n{result.stderr[-800:]}",
            )
            # "The whole split" has to mean the whole split. The nested run
            # discovered its own count; this requires it to be every test in
            # the five modules apart from this one, which is the only one that
            # cannot run there. A nested run quietly narrowed to fewer modules
            # would keep passing while the claim in the repository stayed wider
            # than the check.
            reported = re.search(r"(?m)^Ran (\d+) tests?", result.stderr)
            self.assertIsNotNone(
                reported, f"the nested run reported no count:\n{result.stderr[-1500:]}"
            )
            import importlib

            discovered = sum(
                unittest.defaultTestLoader.loadTestsFromModule(
                    importlib.import_module(name)
                ).countTestCases()
                for name in self.SPLIT_MODULES
            )
            # Every test in the split, including this one: unittest counts a
            # skipped test in the total, so the nested run reports the whole
            # split and skips only the copy of this test that would recurse.
            self.assertEqual(
                discovered, int(reported.group(1)),
                f"the nested run executed {reported.group(1)} tests but the split "
                f"holds {discovered}; 'the whole split' is no longer "
                "what the check does",
            )

    # -- the mutation proof ----------------------------------------------

    def test_every_derived_count_fails_when_the_document_disagrees(self):
        """All ten, each against the test that actually holds it.

        The version this replaces asserted a substring was absent from a mutated
        copy, and then asserted inside `assertRaises` that the same substring was
        absent again — the second assertion being the complement of the first, so
        it passed for any input and demonstrated nothing about the ten real
        checks. It also named none of them and covered six of the ten.

        Each case below names the real test method, substitutes the number the
        document states, and runs that method against the mutated record. If a
        named test passes while the document is wrong, the count it holds is not
        bound to the document and this fails.
        """
        record = self.record()
        containers, elements, reaching = accessibility_identifier_counts()
        total_json, schemas, fixtures = json_input_groups()
        components, relationships = sbom_component_counts()
        steps = workflow_step_counts()
        position, step_total = signing_identity_position()
        gates = unexecuted_gate_count()
        cases = [
            (
                "json inputs",
                "test_the_json_input_counts_are_the_files_on_disk",
                f"over {total_json} files",
                "over 1 files",
            ),
            (
                "accessibility identifiers",
                "test_the_accessibility_identifier_counts_come_from_the_audit",
                f"`{reaching}` declared constants, `{containers}` container identifiers",
                "`1` declared constants, `1` container identifiers",
            ),
            (
                "sbom components",
                "test_the_sbom_component_and_relationship_counts_come_from_the_generator",
                f"`{components} components`",
                "`1 components`",
            ),
            (
                "sbom relationships",
                "test_the_sbom_component_and_relationship_counts_come_from_the_generator",
                f"| Relationships | {relationships}:",
                "| Relationships | 1:",
            ),
            (
                "workflow steps",
                "test_the_workflow_step_counts_come_from_the_workflows",
                f"`ci.yml` 1 job / {steps['ci.yml'][1]} steps",
                "`ci.yml` 1 job / 1 steps",
            ),
            (
                "shell scripts",
                "test_the_shell_script_count_comes_from_the_tree",
                f"`{shell_script_count()} shell scripts parse`",
                "`1 shell scripts parse`",
            ),
            (
                "package manifests",
                "test_the_local_package_manifest_count_comes_from_the_package_list",
                f"`{local_package_manifest_count()} local package manifests verified",
                "`1 local package manifests verified`",
            ),
            (
                "tracked entries",
                "test_the_tracked_entry_count_comes_from_git",
                f"{tracked_top_level_count()} tracked top-level entries",
                "1 tracked top-level entries",
            ),
            (
                "signing step position",
                "test_the_signing_step_position_comes_from_the_workflow",
                f"at position {position} of {step_total}",
                "at position 1 of 1",
            ),
            (
                "unexecuted gates",
                "test_the_unexecuted_gate_count_comes_from_the_readiness_document",
                f"The {word_for(gates)} unexecuted gates",
                "The one unexecuted gates",
            ),
        ]
        for label, test_name, stated, wrong in cases:
            with self.subTest(count=label):
                self.assertIn(
                    stated, record,
                    f"the record no longer states {stated!r}, so {test_name} has "
                    "nothing to fail on",
                )
                mutant = record.replace(stated, wrong)
                self.assertNotEqual(mutant, record, f"{label}: substitution did not apply")
                # Raises AssertionError unless the named test fails on the mutant.
                require_the_count_check_fails(test_name, mutant)

    def test_the_probe_count_is_bound_to_the_record_too(self):
        """The eleventh check, held by its own test rather than by the table above.

        The probe count is read from the validator's four probe functions, which
        costs a subprocess and an import, so it has its own test. It is listed
        here because a count that no mutation covers is a count that is not
        proven to be bound.
        """
        name = "test_the_semantic_probe_negative_count_comes_from_the_validator"
        stated = f"the validator runs {semantic_probe_negative_count()} negative cases"
        record = self.record()
        self.assertIn(stated, record)
        require_the_count_check_fails(
            name, record.replace(stated, "the validator runs 1 negative cases")
        )

    def test_the_mutation_check_rejects_a_test_that_cannot_fail(self):
        """The mutation check must notice a real test that was made vacuous.

        An earlier version of the mutation test could not have detected this: it
        asserted a substring was missing, so it passed whatever the real checks
        did. If one of the ten is replaced with an assertion that always holds,
        this has to fail rather than keep reporting the count as bound.
        """
        # Stand in for a test whose assertion cannot fail. The real method is
        # restored in the `finally`, so the swap cannot leak into the rest of the
        # suite and mask a genuine failure.
        real_test = LiveCountDerivationTests.test_the_shell_script_count_comes_from_the_tree
        self.assertTrue(
            real_test.__name__.endswith("_comes_from_the_tree"),
            "the method being replaced is not the shell-script count test, so "
            "this would be checking something else",
        )
        try:
            LiveCountDerivationTests.test_the_shell_script_count_comes_from_the_tree = (
                lambda self, *a, **k: None
            )
            require_the_count_check_fails(
                "test_the_shell_script_count_comes_from_the_tree",
                self.record().replace(f"`{shell_script_count()} shell scripts parse`", "`1 shell scripts parse`"),
            )
        except AssertionError as error:
            self.assertIn(
                "passed against a record that states the wrong count", str(error)
            )
        else:
            self.fail(
                "an always-passing stand-in for a real count test was not "
                "detected, so inverting one would go unnoticed"
            )
        finally:
            LiveCountDerivationTests.test_the_shell_script_count_comes_from_the_tree = real_test

    def test_the_mutation_check_rejects_a_deleted_test(self):
        """A count whose test was deleted is not a bound count."""
        record = self.record()
        with self.assertRaisesRegex(AssertionError, "does not exist"):
            require_the_count_check_fails(
                "test_a_count_check_that_was_deleted", record
            )

    # -- the exempt groups -------------------------------------------------

    def test_the_accessibility_audit_runs_from_outside_the_repository(self):
        """The audit script itself, invoked from a directory outside the checkout.

        The suite already pins the working directory when it calls the audit, so
        the suite passed while the script on its own still exited 1 from anywhere
        else — a relative `--app` default made it report a missing file that was
        not missing. The record claimed the suite runs from outside the repository,
        and that claim is only true if the script does too, so the script is
        invoked here with no `--app` argument and no working directory of its own.
        """
        with tempfile.TemporaryDirectory() as elsewhere:
            result = subprocess.run(
                [sys.executable,
                 str(REPO_ROOT / "tools/ci/audit-accessibility-identifiers.py")],
                capture_output=True,
                text=True,
                cwd=elsewhere,
            )
            self.assertEqual(
                0, result.returncode,
                f"the audit failed from {elsewhere!r}, so the record's claim that it "
                f"runs from outside the repository is not true:\n"
                f"{result.stdout[-800:]}{result.stderr[-800:]}",
            )
            # And it reported the same three counts it reports from the root, so
            # it audited the same directory rather than finding nothing.
            self.assertEqual(
                accessibility_identifier_counts(),
                tuple(
                    int(value)
                    for value in re.findall(
                        r"(?:container identifiers|element identifiers|constants "
                        r"reaching a view): (\d+)",
                        result.stdout,
                    )
                ),
                "the audit reported different counts from outside the repository",
            )

    def test_the_exempt_groups_are_exactly_the_two_stated(self):
        """Two groups cannot be derived, and the record must say which two.

        The before/after tables in each pass section describe a tree that has
        since moved, and the copy count costs a 20-90 second instrumented run
        every time it is measured. Everything else in the record is derived,
        which is a claim worth gating: a fourth silent group is a live count
        nobody is reading.
        """
        # Matched against the raw text, not the flattened one: the lookaheads are
        # anchored on newlines, and flattening removes every newline, so the
        # section would swallow the rest of the record and the "no other group"
        # check would be reading unrelated prose.
        raw = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(encoding="utf-8")
        self.assertIn("exempt from derivation", self.record())
        exempt = re.search(
            r"### Which counts are exempt from derivation(.+?)(?=\n#{1,3} |\n\*\*|\Z)",
            raw,
            re.S,
        )
        self.assertIsNotNone(exempt, "the record has no exempt-groups section")
        body = flat(exempt.group(1))
        self.assertIn("before/after tables", body)
        self.assertIn("instrumented copy count", body)
        for forbidden in ("wall-clock", "elapsed", "timestamp", "uuid", "namespace"):
            self.assertNotIn(
                forbidden,
                body.lower(),
                f"{forbidden} appears in the exempt-groups section, so a new group "
                "has been added without being stated as one",
            )
        # And the count of stated groups is two, so a third cannot be added by
        # editing prose alone.
        self.assertEqual(
            len(re.findall(r"\d+\. \*\*", body)), 2, f"the exempt section does not list exactly two groups: {body[:400]}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
