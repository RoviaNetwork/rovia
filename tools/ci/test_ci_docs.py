"""Thematic split of the former tools/ci/test_ci_checks.py.

Shared fixtures and loaders live in ci_check_support.py; this file
holds PrivacyAndOwnershipTests.
"""
import inspect
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import script_test_support as gate
from test_ci_toolchain import PythonLintGateTests, swiftpm_counts, swiftpm_total
from ci_check_support import (
    PACKAGE_LIST,
    app_test_count,
    local_packages,
    word_for,
    DATED_SUMMARY_MARKER,
    DOCUMENT_LIMITS,
    GATE_LIMITS,
    HISTORICAL_COUNT_CLAIMS,
    REPO_ROOT,
    SUITE_COUNT_DOCUMENTS,
    flat,
    pyflakes_argv,
    record_sections,
    suite_count_subjects,
)


class PrivacyAndOwnershipTests(unittest.TestCase):
    """The privacy and ownership documents are part of the release boundary."""

    def setUp(self):
        self.privacy = (REPO_ROOT / "PRIVACY.md").read_text(encoding="utf-8")
        self.security = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.codeowners = (REPO_ROOT / "CODEOWNERS").read_text(encoding="utf-8")

    def test_privacy_document_exists_and_covers_the_required_topics(self):
        self.assertTrue((REPO_ROOT / "PRIVACY.md").is_file())
        for heading in (
            "## Data inventory",
            "## Data flows",
            "## Retention and deletion",
            "## Export",
            "## Redaction, and where it can fail",
            "## Network egress and third parties",
            "## App Store privacy questions",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.privacy)

    def test_privacy_document_states_the_diagnostic_fields(self):
        for field in (
            "inputSummary",
            "hasHost",
            "finalDecision",
            "selectedGroup",
            "selectedServer",
            "reasonCode",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.privacy)

    def test_privacy_document_names_the_storage_boundaries(self):
        for boundary in ("Keychain", "App Group", "engine lock", "Memory only"):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, self.privacy)

    def test_privacy_document_does_not_claim_a_typed_destination(self):
        # The debugger has no text input at all: the only input is a menu over the
        # built-in synthetic samples, and the view says so on screen. A privacy
        # document that describes a typed destination describes a feature that
        # does not exist, and it describes it as the one thing redaction cannot
        # cover.
        view = (REPO_ROOT / "client/app/ios/RoviaApp/RoutingDebuggerView.swift").read_text(
            encoding="utf-8"
        )
        for field in ("TextField", "textField", "SecureField", "searchable", "NSTextView"):
            with self.subTest(field=field):
                self.assertNotIn(
                    field,
                    view,
                    f"the debugger has no {field}, so it cannot accept a typed destination",
                )
        self.assertIn("built-in sample", view)
        self.assertIn("Nothing is typed, stored, or sent anywhere", view)

        model = (REPO_ROOT / "client/app/ios/RoviaApp/AppModel.swift").read_text(encoding="utf-8")
        self.assertIn("content.debugSample(id: id) != nil", model)
        snapshot = (REPO_ROOT / "client/app/ios/RoviaApp/AppSnapshot.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("debugSamples: [DebugSampleSummary]", snapshot)
        self.assertIn("var isSampleData: Bool = true", snapshot)

    def test_privacy_document_says_the_debugger_uses_built_in_samples(self):
        for phrase in (
            "built-in synthetic sample",
            "no destination is typed",
            "nothing to redact",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.privacy)
        for stale in (
            "A destination the user types into the debugger",
            "the explicit input the user typed",
            "debugger evaluates exactly the input the user supplied",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(
                    stale,
                    self.privacy,
                    "the debugger takes a built-in sample, not user input",
                )

    def test_no_document_claims_a_typed_destination_or_a_user_supplied_input(self):
        # The debugger takes a built-in sample. One document saying so is not
        # enough: a second document that describes a typed destination would
        # reintroduce the claim, and the privacy document is the one a reviewer
        # reads.
        # Every markdown file in the repository that is not a generated ledger.
        # The list used to be nine hand-picked documents, and three findings came
        # from files that were not on it: a threat model that described a typed
        # input, a spike list that named the wrong refusal, and a legal document
        # nobody had checked. Enumerating the tree means a new document is covered
        # the day it is written.
        # `.superpowers/` is the planning ledger, which is gitignored and outside
        # the repository: it quotes superseded wording on purpose, to record what
        # was corrected. Holding a historical ledger to today's wording would mean
        # rewriting history every time a claim is fixed.
        excluded = re.compile(r"^(\.superpowers/|docs/superpowers/)")
        documents = sorted(
            str(path.relative_to(REPO_ROOT))
            for path in REPO_ROOT.rglob("*.md")
            if not excluded.match(str(path.relative_to(REPO_ROOT)))
            and ".build" not in path.parts
            and "node_modules" not in path.parts
        )
        for required in (
            "docs/security/threat-model.md",
            "docs/architecture/next-spikes.md",
            "PRIVACY.md",
        ):
            self.assertIn(required, documents, f"{required} is not covered by the wording test")
        for absent in (
            "docs/security/threat-model.md",
            "docs/architecture/next-spikes.md",
            "docs/legal/app-store-distribution.md",
        ):
            self.assertTrue(
                (REPO_ROOT / absent).is_file(), f"{absent} does not exist to be checked"
            )
        # The Swift sources count too: a comment that says the user types a
        # destination is the same stale claim in the place a reader is most
        # likely to meet it.
        sources = [
            str(path.relative_to(REPO_ROOT))
            for path in sorted((REPO_ROOT / "client").rglob("*.swift"))
            if ".build" not in path.parts
        ]
        self.assertTrue(sources, "no client sources were found")
        stale = (
            "a destination the user types",
            "the user types into the debugger",
            "the explicit input the user typed",
            "input the user supplied in the debugger",
            "typed destination the user",
        )
        for document in documents + sources:
            path = REPO_ROOT / document
            self.assertTrue(path.is_file(), f"{document} is missing")
            text = path.read_text(encoding="utf-8")
            for phrase in stale:
                with self.subTest(document=document, phrase=phrase):
                    self.assertNotIn(
                        phrase.lower(),
                        text.lower(),
                        f"{document} describes a typed destination the debugger does not have",
                    )
        # And the bridge and the snapshot say what is true instead.
        bridge = (REPO_ROOT / "client/app/ios/RoviaApp/CanonicalRouteBridge.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("The user types nothing", bridge)
        self.assertIn("has no text field", bridge)
        snapshot = (REPO_ROOT / "client/app/ios/RoviaApp/AppSnapshot.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("it holds no destination at all", snapshot)

    def suite_test_counts(self):
        """How many tests each tool suite actually has, computed by loading it.

        The count comes from the loader rather than from a list in this file, so
        adding a test does not mean remembering to update a number here as well as
        in the document.
        """
        import importlib.util

        counts = {}
        for suite_path in sorted((REPO_ROOT / "tools").rglob("test_*.py")):
            if ".build" in suite_path.parts or "__pycache__" in suite_path.parts:
                continue
            spec = importlib.util.spec_from_file_location(suite_path.stem, suite_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # countTestCases() walks nested suites; len() would count the
            # TestCase classes instead of the tests in them.
            counts[str(suite_path.relative_to(REPO_ROOT))] = (
                unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
            )
        return counts

    def gate_module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "app_dependencies_gate", REPO_ROOT / "tools/ci/test_app_dependencies.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_foundation_record_counts_agree_with_the_suites(self):
        # The dated record is evidence, and evidence with the wrong count in it is
        # worse than none: a reader checks one number and stops.
        #
        # This test is self-referential: the counts for the split modules are
        # their own. Adding a test here means updating the record together,
        # and the test fails if only one of them moved.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        counts = self.suite_test_counts()
        self.assertGreaterEqual(len(counts), 9)
        for suite, count in counts.items():
            with self.subTest(suite=suite):
                self.assertRegex(
                    record,
                    rf"\| `{re.escape(suite)}` \| {count} \|",
                    f"the record does not state {count} tests for {suite}",
                )
        total = sum(counts.values())
        # The file count is derived rather than written here. It was a literal `9`, and
        # a literal is a number a contributor has to remember to bump: adding a test
        # file made the record wrong and the failure was a puzzle rather than a
        # message. `counts` is the loader's own dict, so the count of it is the count.
        for claim in (
            rf"\*\*{len(counts)} files, {total} tests, 0 failures\*\*",
            rf"\| \*\*Total\*\* \| \*\*{swiftpm_total()}\*\* \| \*\*0\*\* \|",
            # Derived from the test target's own `func test…` methods, the same
            # way the SwiftPM totals are, rather than transcribed from a run.
            rf"`Executed {app_test_count()} tests, with 0 failures`",
        ):
            with self.subTest(claim=claim):
                self.assertRegex(record, claim)

    def test_every_suite_count_in_every_document_is_the_derived_one(self):
        """Occurrence-complete, the way the lint-gate count is.

        The record stated a suite's test count in two places and only one was held:
        the check matched the table-row form, so `15 tests, 0 failures` on line 182
        drifted to 15 while the table on line 97 was still correct and every test
        passed. A second occurrence of any count is a second claim.

        So this walks every line of every document listed in
        `SUITE_COUNT_DOCUMENTS`, and for each line that names one of the subjects in
        `suite_count_subjects()` and states a number of tests, requires that number
        to be one of the derived counts for that subject. A claim about what a
        document used to say is listed in `HISTORICAL_COUNT_CLAIMS` instead, and
        each of those is required to still be present, so the exemption list cannot
        grow into a place live claims are excused.
        """
        subjects = suite_count_subjects(self.suite_test_counts())
        self.assertTrue(subjects, "no subjects were derived, so this check is vacuous")
        # Read raw and flatten per line. Flattening first and splitting after makes
        # the whole document one line, so every subject matched every count — the
        # first version of this test reported the entire record as disagreeing.
        documents = {
            name: (REPO_ROOT / name).read_text(encoding="utf-8")
            for name in SUITE_COUNT_DOCUMENTS
            if (REPO_ROOT / name).is_file()
        }
        self.assertTrue(documents, "none of the documents exist")
        historical = {
            name: {phrase for owner, phrase in HISTORICAL_COUNT_CLAIMS
                   if owner == name for phrase in [flat(phrase)]}
            for name in documents
        }

        claims = 0
        wrong = []
        for name, body in sorted(documents.items()):
            # A paragraph, not a line. `ci.md` writes "The suite runs 27 tests" in a
            # sentence that does not name the suite — it is named earlier in the same
            # paragraph — so a line-scoped check passes it by not seeing the subject,
            # and that claim was ungated. Paragraphs are separated by blank lines and
            # table rows, which is where a new subject is introduced.
            for block in re.split(r"\n[ \t]*\n", body):
                for row in re.split(r"(?m)^(?=\|)", block):
                    passage = flat(row)
                    if " test" not in passage and "Tests" not in passage:
                        continue
                    # Each count is judged against the subject named *nearest
                    # before it*, not against every subject the passage mentions: a
                    # paragraph that introduces one suite and later names another
                    # states a count for each, and testing them against the set of
                    # subjects in the passage pairs them wrongly.
                    mentions = sorted(
                        (passage.index(subject), subject)
                        for subject in subjects
                        if subject in passage
                    )
                    if not mentions:
                        continue
                    for found in re.finditer(r"\b(\d{1,3}) tests?\b", passage):
                        claims += 1
                        before = [m for m in mentions if m[0] < found.start()]
                        if before:
                            subject = before[-1][1]
                        else:
                            # Nothing named it before the claim, so the subject is
                            # the first name that follows it in the same paragraph.
                            # Both orders occur: `ci.md` introduces the suite two
                            # paragraphs earlier and states the count later, while
                            # the record names the suite in the sentence after the
                            # count. Attributing only forwards checked the first and
                            # skipped the second.
                            after = [m for m in mentions if m[0] > found.start()]
                            if not after:
                                continue
                            subject = after[0][1]
                        if int(found.group(1)) in subjects[subject]:
                            continue
                        if any(
                            phrase and phrase in passage
                            for phrase in historical[name]
                        ):
                            continue
                        wrong.append(
                            f"{name}: {passage.strip()[:90]} — {subject} holds "
                            f"{sorted(subjects[subject])}, the passage says "
                            f"{found.group(1)}"
                        )
        self.assertGreater(
            claims, 0, "no suite count was found in any document, so this is vacuous"
        )
        self.assertEqual(
            [], wrong,
            "these suite counts disagree with the loader: " + "; ".join(wrong),
        )

    def test_every_historical_count_claim_is_still_present(self):
        """The exemption list has to be live too.

        Otherwise a line could be deleted, its exemption left behind, and the list
        become a set of strings that no longer exempt anything while still reading
        as though it did.
        """
        for name, phrase in HISTORICAL_COUNT_CLAIMS:
            with self.subTest(claim=phrase[:44]):
                self.assertIn(
                    phrase,
                    flat((REPO_ROOT / name).read_text(encoding="utf-8")),
                    f"{name} no longer states {phrase!r}, so its entry in "
                    "HISTORICAL_COUNT_CLAIMS is exempting nothing",
                )

    def test_the_record_carries_its_own_retraction_of_the_reproducibility_claim(self):
        # The record claimed a fixed --namespace-id reproduced the bytes, and the
        # same pass retracted it further down. A retraction that can be deleted
        # without failing anything is not a retraction, so the retracted claim has
        # to still be there, marked, and contradicted.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        flat_record = flat(record)
        self.assertIn(
            "on its own it does not reproduce the bytes", flat_record,
            "the superseded namespace cell is not marked where the table states it",
        )
        self.assertIn(
            "**This claimed byte-reproducibility, and it was false.**", record,
            "the record no longer carries the retraction of the claim",
        )
        # And the retraction has to say why the test that seemed to check it did
        # not, or a reader is left with two claims and no reason to prefer one.
        for because in (
            "overwrote `creationInfo.created` in both documents before comparing",
            "A document is byte-reproducible only when `--namespace-id` **and**",
        ):
            with self.subTest(because=because):
                self.assertIn(
                    because, flat_record,
                    "the retraction does not say why the test that seemed to check "
                    "the claim could not have caught it",
                )
        # The false claim must not survive anywhere unretracted.
        for document in ("docs/development/ci.md", "docs/development/reproducibility.md"):
            body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
            with self.subTest(document=document):
                self.assertNotIn(
                    "a fixed value for a byte-reproducible document", body
                )
                self.assertRegex(
                    body, r"not byte-reproducible|only when.{0,40}both",
                    f"{document} does not say what has to be fixed for the document "
                    "to be reproducible",
                )

    # The readiness rows each planned control cites, against the current numbering.
    # Hosted CI moved into the document's `## Closed` section, so every open row moved
    # down by one and the citations moved with them. Each entry here is re-pointed by
    # what the control is about rather than by arithmetic, because a mechanical shift is
    # how a citation ends up naming a gate that is about something else - which is
    # precisely what this table exists to prevent, so it has to be held the same way.
    UNEXECUTED_CONTROLS = {
        "Golden routing fixtures shared with Android": ("9",),
        "Fuzz targets for share-link and subscription parsing": None,
        "CI secret scanning and workflow review": ("7", "6"),
        "Dependency review and advisory monitoring": ("7",),
        "Physical-device tunnel tests for lifecycle": ("4",),
        "Independent reproducibility check for the engine artifact": ("5",),
    }

    ROW_CITATION = re.compile(r"release-readiness\.md` row (\d+)")

    def threat_model(self):
        return (REPO_ROOT / "docs/security/threat-model.md").read_text(encoding="utf-8")

    def threat_model_section(self, heading: str) -> str:
        """One bolded section of the threat model, bounded by the next heading.

        Unbounded, the "planned" list ran on into the residual-risk bullets, which
        are also `- ` lines and are not controls at all.
        """
        text = self.threat_model()
        self.assertIn(heading, text, f"the threat model has no {heading} section")
        body = text.split(heading, 1)[1]
        # The next heading of either kind ends the section: `**In place and
        # executed here**` is followed by the bold planned heading, not by a `##`,
        # so bounding only on `## ` ran the executed list into the planned one.
        following = re.search(r"(?m)^(## |\*\*)", body)
        return body[: following.start()] if following else body

    def section_bullets(self, heading: str):
        """(title, whole bullet) for each `- ` line, wrapped and joined.

        The title is the first sentence of the bullet, so a control can be named by
        a prefix of it — the physical-device entry carries a list after the comma.
        """
        bullets = []
        for raw in re.split(r"(?m)^- ", self.threat_model_section(heading)):
            joined = " ".join(raw.split())
            if joined:
                bullets.append((joined.split(".", 1)[0], joined))
        return bullets

    def bullet_for(self, heading: str, control: str) -> str:
        """The one bullet that is this control, or a failure naming both candidates."""
        matches = [bullet for title, bullet in self.section_bullets(heading)
                   if title.startswith(control)]
        self.assertEqual(
            len(matches), 1,
            f"{control} matched {len(matches)} bullets under {heading}: "
            f"{[title for title, _ in self.section_bullets(heading) if title.startswith(control)]}",
        )
        return matches[0]

    def test_no_document_claims_an_unexecuted_control_in_the_present_tense(self):
        # The threat model listed six controls that do not exist in the present
        # tense, next to two that do, with nothing to tell a reader which was
        # which. Each is now labelled, and a present-tense claim about any of them
        # fails here.
        self.assertTrue(
            self.section_bullets("**In place and executed here**"),
            "the threat model has no executed section",
        )
        for control, rows in self.UNEXECUTED_CONTROLS.items():
            with self.subTest(control=control):
                planned = self.bullet_for("**Planned, not implemented**", control)
                executed = self.section_bullets("**In place and executed here**")
                for title, _ in executed:
                    self.assertFalse(
                        title.startswith(control),
                        f"{control} is listed as executed and it was never executed",
                    )
                # The citation has to be this control's own, in this control's own
                # bullet. A section-wide search is what let a wrong row through.
                cited = self.ROW_CITATION.findall(planned)
                if rows is None:
                    self.assertEqual(
                        cited, [],
                        f"{control} cites {cited} but no row of the disclosure "
                        "covers it, so the citation points at an unrelated gate",
                    )
                    self.assertIn(
                        "No row of `release-readiness.md`", planned,
                        f"{control} has no row and has to say so rather than leave a "
                        "reader to wonder",
                    )
                else:
                    self.assertEqual(
                        cited, list(rows),
                        f"{control} must cite row(s) {' and '.join(rows)} of the "
                        f"disclosure in its own bullet, and it cites {cited}",
                    )
        readiness = (REPO_ROOT / "docs/development/release-readiness.md").read_text(
            encoding="utf-8"
        )
        for control, rows in self.UNEXECUTED_CONTROLS.items():
            for row in rows or ():
                with self.subTest(control=control, row=row):
                    self.assertRegex(
                        readiness, rf"(?m)^\| {row} \|",
                        f"{control} cites row {row}, which the disclosure does not have",
                    )

    def test_the_unexecuted_control_list_and_the_threat_model_cannot_diverge(self):
        # What this adds, precisely. The other direction is already covered: the
        # present-tense test resolves each control in this list through
        # bullet_for(), so a control that stopped being listed as planned fails
        # there. That is kept as defence in depth — the two tests fail for
        # different reasons if the list and the document disagree, and one of them
        # should not depend on the other's helper.
        #
        # The direction that was genuinely open is the reverse: a control the
        # document lists as planned that this list does not know about. Nothing
        # checked it, because both existing checks iterate what they know. That is
        # how "Golden routing fixtures shared with Android" could be moved into the
        # executed section unnoticed — it was not in the list, so no check asked
        # where it was.
        planned_titles = [title for title, _ in
                          self.section_bullets("**Planned, not implemented**")]
        known = set(self.UNEXECUTED_CONTROLS)
        # The matched control, not the bullet title: one control's bullet carries
        # a list after a comma, so the title is longer than the name this test
        # knows it by.
        listed = {
            control
            for title in planned_titles
            for control in known
            if title.startswith(control)
        }
        self.assertEqual(
            listed, known,
            "the controls this test knows about and the controls the threat model "
            f"calls planned are different: test {sorted(known)}, document "
            f"{sorted(listed)}",
        )
        # And nothing may sit in the planned section that this list has not
        # classified, so a new control cannot appear unclassified.
        for title in planned_titles:
            with self.subTest(planned_control=title):
                self.assertTrue(
                    any(title.startswith(control) for control in known),
                    f"{title} is in the planned section and this test does not know "
                    "whether it is a real control, so nothing checks it",
                )

    def test_the_legal_document_states_the_engine_decision_in_conditional_terms(self):
        # It said engine versions "are pinned and shipped with the app release",
        # which is the opposite of the tree: the lock enables none. PRIVACY.md
        # already recorded this document as holding the note for the day one is
        # added, so the document was contradicting the privacy answer.
        legal = (REPO_ROOT / "docs/legal/app-store-distribution.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "Engine versions are pinned and shipped with the app release.", legal
        )
        self.assertIn("when an engine is added", legal)
        self.assertIn("No engine is pinned or shipped today", legal)
        self.assertIn("enables none", flat(legal))
        self.assertIn("can establish a tunnel" if False else "cannot establish a tunnel", flat(legal))
        # And it has to stay in step with the privacy answer it is referenced from.
        privacy = (REPO_ROOT / "PRIVACY.md").read_text(encoding="utf-8")
        self.assertIn("docs/legal/app-store-distribution.md", privacy)
        self.assertIn("no engine is bundled in this build", flat(privacy).lower())

    def test_the_documented_package_list_matches_the_package_list_file(self):
        # ios.md listed four of the seven entries, which read as though the engine
        # adapters and the Apple platform layer were untested. They are not.
        entries = local_packages()
        self.assertEqual(len(entries), 7, f"the package list has {len(entries)} entries")
        commands = re.findall(r"swift test --package-path ([\w./-]+)",
                              (REPO_ROOT / "docs/development/ios.md").read_text(
                                  encoding="utf-8"
                              ))
        self.assertEqual(
            sorted(commands),
            sorted(entries),
            "the commands in ios.md are not the entries in "
            f"{PACKAGE_LIST}: documented {sorted(commands)}, file {sorted(entries)}",
        )

    def test_the_recorded_swiftpm_table_is_what_the_suites_hold(self):
        # The per-package rows were transcribed from a run while only the total was
        # bound, so a package could gain tests and its row would stay as it was.
        counts = swiftpm_counts()
        self.assertEqual(len(counts), 7, f"the package list yielded {sorted(counts)}")
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        for package, count in counts.items():
            with self.subTest(package=package):
                self.assertRegex(
                    record,
                    rf"\| `{re.escape(package)}` \| {count} \| 0 \|",
                    f"the record's row for {package} does not state the {count} "
                    "tests its suites hold",
                )
        self.assertRegex(
            record,
            rf"\| \*\*Total\*\* \| \*\*{sum(counts.values())}\*\* \| \*\*0\*\* \|",
        )

    def test_the_before_and_after_tables_are_labelled_as_single_observations(self):
        # The remaining numbers in the record are the before/after tables inside
        # each pass section. Their "before" values describe the tree as it was in
        # that pass and cannot be derived from anything, because the tree has moved
        # on. So they are not derived: they are single observations, and the
        # requirement is that they are read as history rather than as live claims.
        # This checks each such table sits under a pass heading and that the record
        # says what these tables are.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        heading = ""
        tables = 0
        for line in record.splitlines():
            if line.startswith("### "):
                heading = line[4:].strip()
            if line.startswith("| Thing | Before | After |") or line.startswith(
                "| Tool | Before | After |"
            ):
                tables += 1
                self.assertRegex(
                    heading, r"pass",
                    f"a before/after table sits under {heading!r}, which is not a "
                    "pass section, so its numbers read as live claims",
                )
        # No threshold on how many there are: the count of these tables is not a
        # claim anyone should be gated on, and a threshold is exactly the kind of
        # hand-written number this pass has been removing.
        self.assertGreater(
            tables, 0, "the record has no before/after table, so this check is vacuous"
        )
        self.assertIn(
            "single observations from the run that pass recorded",
            flat(record),
            "the record does not say that its before/after tables are single "
            "observations rather than derived figures",
        )

    def test_the_before_after_tool_test_total_is_the_derived_total(self):
        # "Tool tests 364 -> 570" transcribed the run total by hand. It drifted from
        # the roll-up, and because it was a *stale* transcription it slipped past a
        # test that only refused the *current* number in that position — which is
        # worse than no test, because the test looked like it covered the cell. So
        # the cell states the number and this requires it to be the derived one.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        total = sum(self.suite_test_counts().values())
        # Three of these tables exist, one per pass that changed the count, and the
        # earlier two are snapshots of what was true then. They are not wrong and
        # are not rewritten: a record that is edited to agree with the present is
        # not a record. The live one is the last, and that is the figure held.
        rows = [
            line for line in record.splitlines()
            if line.startswith("| Tool tests |")
        ]
        self.assertGreaterEqual(
            len(rows), 1, "the record has no tool-test before/after row"
        )
        cells = [cell.strip() for cell in rows[-1].strip("|").split("|")]
        self.assertEqual(3, len(cells), f"the tool-test row has {len(cells)} cells")
        self.assertEqual(
            str(total), cells[2],
            "the last before/after table states a tool-test total of "
            f"{cells[2]!r} where the suites hold {total}",
        )
    def test_the_documented_gate_counts_agree_with_the_gate(self):
        # Mutation counts are the gate's own evidence of coverage. A document
        # that says "43 mutations" while the module holds 47 is describing a gate
        # nobody built.
        #
        # Each group is required with its label attached, not as a bare digit: a
        # document full of numbers will contain a "2" and a "9" by accident, and
        # `assertIn(str(len(table)), record)` was satisfied by any of them.
        gate = self.gate_module()
        groups = (
            ("package-dependency", len(gate.PACKAGE_MUTATIONS)),
            ("second route evaluator", len(gate.EVALUATOR_MUTATIONS)),
            ("raw trace", len(gate.TRACE_MUTATIONS)),
            ("contract", len(gate.CONTRACT_MUTATIONS)),
        )
        total = sum(count for _, count in groups)
        shapes = len(gate.LEGITIMATE_SHAPES)
        self.assertEqual(total, sum(
            len(table)
            for table in (
                gate.PACKAGE_MUTATIONS,
                gate.EVALUATOR_MUTATIONS,
                gate.TRACE_MUTATIONS,
                gate.CONTRACT_MUTATIONS,
            )
        ))
        self.assertEqual(len(gate.LEAK_CHANNELS), 9)
        # 47 mutations plus 7 legitimate shapes, never "47 of which are shapes":
        # the shapes are not a subset of the mutations, they are the cases the
        # check has to leave alone, and adding one does not make a gate stricter.
        composition = f"{total} mutations plus {shapes} legitimate shapes"
        for document in ("docs/development/ci.md", "docs/development/ios.md",
                         "docs/development/foundation-verification.md"):
            body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
            with self.subTest(document=document):
                self.assertIn(composition, body)
                # Any "N of which are shapes" in a sentence that also states the
                # current total, not just the exact string: "47 mutations, 7 of
                # which are shapes" folds the shapes in just as "47 of which are
                # shapes" does.
                self.assertIsNone(
                    re.search(rf"\b{total}\b[^.]*\bof which are shapes\b", body),
                    f"{document} folds the legitimate shapes into the mutation count",
                )
        for label, count in groups:
            for document in ("docs/development/ci.md", "docs/development/ios.md",
                             "docs/development/foundation-verification.md"):
                body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
                with self.subTest(document=document, group=label):
                    self.assertRegex(
                        body,
                        rf"{count} (?:\w+ ){{0,5}}{label}",
                        f"{document} does not state {count} {label} mutations with "
                        "the group named",
                    )

    def test_the_documented_tree_copy_count_is_a_measured_figure_inside_a_derived_bracket(self):
        # The copy count is a different number from the mutation count: every
        # mutation case pays for one workspace, and so does every test method
        # that needs a broken repository. Measuring it exactly means counting
        # Workspace instantiations through a suite that runs in the 20-90 second
        # range recorded below, so the documents state the measured figure and
        # mark it as measured, and this test enforces only
        # what can be derived cheaply: the figure has to sit inside the bracket
        # the mutation and test counts imply. A document cannot claim fewer
        # copies than there are mutations, and cannot claim more than one copy
        # per mutation plus one per test.
        gate = self.gate_module()
        mutations = sum(
            len(table)
            for table in (
                gate.PACKAGE_MUTATIONS,
                gate.EVALUATOR_MUTATIONS,
                gate.TRACE_MUTATIONS,
                gate.CONTRACT_MUTATIONS,
                gate.LEGITIMATE_SHAPES,
            )
        )
        suite = unittest.defaultTestLoader.loadTestsFromModule(gate)
        tests = suite.countTestCases()
        lower, upper = mutations, mutations + tests
        for document in ("docs/development/ci.md", "docs/development/ios.md",
                         "docs/development/foundation-verification.md"):
            body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
            with self.subTest(document=document):
                stated = [
                    int(number)
                    for number in re.findall(
                        r"(\d+) tree copies|copies the tree (\d+) times", body
                    )
                    for number in number if number
                ]
                self.assertTrue(stated, f"{document} states no copy count")
                for number in stated:
                    self.assertGreaterEqual(
                        number, lower,
                        f"{document} claims {number} tree copies, fewer than the "
                        f"{lower} mutation and shape cases that each pay for one",
                    )
                    self.assertLessEqual(
                        number, upper,
                        f"{document} claims {number} tree copies, more than one per "
                        f"mutation case plus one per test ({upper})",
                    )
                # And it has to say how the figure was obtained, because
                # "instrumenting shutil.copytree" is the wrong method: copytree
                # recurses, so that run makes 6486 calls for 69 copies.
                self.assertRegex(
                    body,
                    r"measured|obtain|counting",
                    f"{document} states a copy count without saying how it was "
                    "obtained",
                )
                self.assertIn(
                    "Workspace",
                    body,
                    f"{document} does not say the figure counts Workspace "
                    "instantiations, which is what was actually measured",
                )

    OVERCLAIM_GATE = "tools/ci/test_app_dependencies.py"

    def overclaim_subjects(self):
        """Every file the overclaim blocklist is applied to.

        The gate itself and the documents that describe it. `README.md` and
        `SECURITY.md` are not here: neither mentions the gate, and listing a file
        that does not discuss it would make the record's count read better than
        the coverage is.
        """
        return [
            self.OVERCLAIM_GATE,
            "docs/development/foundation-verification.md",
            "docs/development/ci.md",
            "docs/development/ios.md",
            "CHANGELOG.md",
            "PRIVACY.md",
        ]

    def test_no_gate_claims_unconditional_coverage(self):
        # Two families of overclaim, and the list is written without quoting any
        # of them, because a blocklist that contains its own entries is a test
        # that fails the next time someone greps the repository:
        #
        #   * the absolute claim — the gate cannot be defeated by any change
        #   * the rename claim — the gate cannot be defeated by renaming
        #
        # The subjects are the gate itself and the documents that describe it;
        # see overclaim_subjects() for the list and for why README.md and
        # SECURITY.md are not in it.
        forbidden = (
            "unevadable",
            "cannot be evaded",
            "no change could get past",
            "evaded by renaming",
            "rename-proof",
            "impossible to evade",
        )
        for subject in self.overclaim_subjects():
            body = (REPO_ROOT / subject).read_text(encoding="utf-8").lower()
            for phrase in forbidden:
                with self.subTest(subject=subject, phrase=phrase):
                    self.assertNotIn(
                        phrase,
                        body,
                        f"{subject} claims the gate cannot be evaded; the gate's own "
                        "limits section says otherwise",
                    )

    RUNTIME_RANGE = re.compile(r"(\d+)[^\d]{1,3}(\d+) seconds across the runs")
    # The gate's own runtime sentences, in every phrasing they have used. The
    # canonical form above requires "across the runs", so a sentence saying
    # "28-34 seconds the suite already spends" matched nothing and the stale pair
    # sat in the record while this test passed. Matching *any* "N-M seconds" fixed
    # that and introduced a worse failure: an unrelated "1-2 seconds" anywhere in
    # these three documents would fail a gate about the suite's runtime, and the
    # only way out would have been to weaken the pattern again.
    #
    # So it is anchored on the subject instead of the number. Each alternative
    # below is a phrase the record has actually used; a new phrasing has to be
    # added here, which is a visible edit rather than a silent loosening. The
    # trade-off is recorded in `foundation-verification.md` beside the other ones.
    #
    # Two of these four alternatives are catch-all phrases and two are anchored on
    # the gate's subject, and the difference is recorded rather than glossed.
    #
    # The subject alternatives — "gate runtime range reads", "gate runs in the" —
    # name the gate, so a span belonging to something else is not read. The phrase
    # alternatives — "seconds across the runs", "seconds the suite already spends" —
    # do not, and cannot: the sentences the documents actually use are phrased
    # around the cost of *measuring* something ("Measuring it costs the N-M seconds
    # across the runs recorded in this repository's verification record"), where
    # the subject is the measurement rather than the gate. Anchoring them would
    # mean rewriting the documents to fit the check, so they stay as phrases and
    # the false-positive they carry is written down in the record instead.
    #
    # A third alternative once matched `N-M second range` by phrase alone. It was
    # both a catch-all that read "the 2-3 second range of the retry", and dead: it
    # matched nothing in these documents. The subject-anchored alternative that
    # replaced it also picked up a sentence the others miss.
    #
    # `RUNTIME_SPAN_KINDS` names the classification, and a test proves each entry
    # of it is true, so a catch-all cannot sit here described as subject-anchored.
    RUNTIME_SPAN_KINDS = {
        "across the runs": "phrase",
        "the suite already spends": "phrase",
        "gate runtime range reads": "subject",
        "gate runs in the": "subject",
    }
    RUNTIME_SPAN = re.compile(
        r"(?:"
        r"(\d+)[^\d]{1,3}(\d+)\s+seconds across the runs"
        r"|(\d+)[^\d]{1,3}(\d+)\s+seconds the suite already spends"
        r"|gate runtime range reads (\d+)[^\d]{1,3}(\d+) second"
        r"|gate runs in the (\d+)[^\d]{1,3}(\d+) second"
        r")"
    )
    # Two sentences per alternative, in that alternative's own wording: one whose
    # subject is the gate, and one whose subject is something else entirely. Both
    # are required to be probed, so an alternative is shown to be live by a
    # sentence it reads and, if it claims to be subject-anchored, to be narrow by a
    # sentence it does not. The gate sentences carry the agreed range, so an
    # alternative that stops reading them is caught here rather than by the
    # documents drifting.
    RUNTIME_SPAN_SUBJECTS = {
        "across the runs": {
            "gate": "The gate takes 20-90 seconds across the runs recorded here.",
            "other": "The fuzzer takes 3-4 seconds across the runs of the fuzz suite.",
        },
        "the suite already spends": {
            "gate": "That is 20-90 seconds the suite already spends.",
            "other": "The linter takes 3-4 seconds the suite already spends.",
        },
        "gate runtime range reads": {
            "gate": "The gate runtime range reads 20-90 seconds in every document.",
            "other": "The retry range reads 3-4 seconds on a slow link.",
        },
        "gate runs in the": {
            "gate": "The gate runs in the 20-90 seconds measured here.",
            "other": "The retry runs in the 3-4 seconds expected on a slow link.",
        },
    }
    RUNTIME_AGREED_RANGE = (20, 90)

    def test_the_other_subject_probe_is_what_makes_other_mean_other(self):
        """The one assertion with no proof, proved for all four alternatives.

        `assertNotIn("gate", sentences["other"].lower())` is the only thing that
        distinguishes the other-subject sentence from the gate-subject one for the
        two catch-all alternatives: both sentences contain a span of the right
        shape, so if the other-subject sentence happened to name the gate, nothing
        else in the probe would notice. An assertion nothing can falsify is not a
        check.

        So for each alternative the other-subject sentence is replaced with the
        gate-subject one, and the probe is required to fail — with a message naming
        the assertion. Every alternative is covered, and the message requirement is
        what distinguishes "the probe failed" from "the probe failed *because the
        other-subject sentence was not another subject*".
        """
        import copy

        probe_name = (
            "test_every_alternative_is_probed_with_a_gate_and_another_subject"
        )
        for phrase in sorted(self.RUNTIME_SPAN_KINDS):
            with self.subTest(alternative=phrase):
                saved = copy.deepcopy(self.RUNTIME_SPAN_SUBJECTS)
                try:
                    # The other-subject sentence is made to name the gate, keeping
                    # its span intact. Prefixing rather than substituting: two of
                    # the four gate sentences do not contain the word "gate"
                    # themselves, so substituting one in would leave those two
                    # unmutated and this would only prove the assertion for two
                    # alternatives.
                    self.RUNTIME_SPAN_SUBJECTS[phrase]["other"] = (
                        "This is the gate's own measurement: " + saved[phrase]["other"]
                    )
                    probe = PrivacyAndOwnershipTests(probe_name)
                    with self.assertRaises(AssertionError) as caught:
                        getattr(probe, probe_name)()
                finally:
                    # Restored here rather than through addCleanup: the positive
                    # check below runs in this same test, and a class attribute
                    # still carrying the mutation would fail it for the wrong
                    # reason.
                    self.RUNTIME_SPAN_SUBJECTS.clear()
                    self.RUNTIME_SPAN_SUBJECTS.update(saved)
                self.assertIn(
                    "names the gate", str(caught.exception),
                    f"the probe failed for {phrase!r}, but not because the "
                    f"other-subject sentence was not another subject: "
                    f"{caught.exception}",
                )
        # And the probe passes with the real sentences, so the failure above was
        # the mutation and not a probe that always fails.
        PrivacyAndOwnershipTests(probe_name).test_every_alternative_is_probed_with_a_gate_and_another_subject()

    def test_an_unrelated_second_range_is_not_read_as_the_gate_runtime(self):
        """The `second range` shape, which no alternative matches any more.

        An alternative once matched `N-M second range` by phrase alone, so "the
        2-3 second range of the retry" was read as a gate runtime. It was replaced
        by a subject-anchored alternative. This keeps the shape out, so a future
        alternative that reintroduces it fails here.
        """
        unrelated = (
            "The upload takes 1-2 seconds on this connection.\n"
            "The 2-3 second range of the retry is expected on a slow link.\n"
            "A 30-45 second range of telemetry arrives each morning.\n"
            "The gate runs in the 20-90 second range measured here.\n"
        )
        matched = self.RUNTIME_SPAN.findall(unrelated)
        self.assertEqual(
            1, len(matched),
            f"expected only the sentence naming the gate to match, but "
            f"{len(matched)} spans matched: {matched}",
        )
        self.assertIsNotNone(
            self.RUNTIME_SPAN.search("The gate runs in the 20-90 second range measured here."),
            "the one sentence that does name the gate stopped matching, so the "
            "alternatives are too narrow",
        )

    def test_every_alternative_is_probed_with_a_gate_and_another_subject(self):
        """Each alternative, twice: once naming the gate, once naming something else.

        The record once claimed every alternative named the gate. Two of the four
        are catch-all phrases, and the claim was unfalsifiable because the corpus
        only covered the `second range` shape — the half of the corpus that lives
        in a different test was doing the gate-subject work while this test's
        docstring claimed it did both.

        Both halves are here now, and both are required to have happened for every
        alternative:

        - the gate sentence must be read, which is what makes the alternative live
          rather than present in the pattern and matching nothing;
        - the other-subject sentence must be rejected for an alternative classified
          subject-anchored, and read for one classified a catch-all phrase. That is
          what makes the classification a fact about the pattern rather than a
          description of it.
        """
        probed = {"gate": set(), "other": set()}
        for phrase, kind in sorted(self.RUNTIME_SPAN_KINDS.items()):
            sentences = self.RUNTIME_SPAN_SUBJECTS[phrase]
            for subject in ("gate", "other"):
                with self.subTest(alternative=phrase, subject=subject):
                    # The gate sentence has to carry the alternative's own wording,
                    # or it probes nothing. The other sentence must not: for a
                    # subject-anchored alternative, leaving the wording out *is* what
                    # makes it a sentence about something else. What that sentence
                    # does have to carry is a span of the right shape, so the only
                    # reason it is not read is the subject and not a missing number.
                    self.assertRegex(
                        sentences[subject], r"\d+[^\d]{1,3}\d+\s+second",
                        f"the {subject} sentence for {phrase!r} has no span in it, "
                        "so it cannot probe the pattern either way",
                    )
                    if subject == "gate":
                        self.assertIn(
                            phrase, sentences["gate"],
                            f"the gate sentence for {phrase!r} does not contain that "
                            "alternative's own wording, so it probes nothing",
                        )
                    else:
                        self.assertNotIn(
                            "gate", sentences["other"].lower(),
                            f"the other-subject sentence for {phrase!r} names the "
                            "gate, so it is not a probe of the other direction",
                        )
                        if kind == "phrase":
                            self.assertIn(
                                phrase, sentences["other"],
                                f"the other-subject sentence for the catch-all "
                                f"{phrase!r} omits that very phrase, so it is not "
                                "probing the false positive it exists to demonstrate",
                            )
                    self.addCleanup(probed[subject].discard, phrase)
                    probed[subject].add(phrase)
                    read = self.span_numbers(sentences[subject])
                    if subject == "gate":
                        self.assertEqual(
                            self.RUNTIME_AGREED_RANGE, read,
                            f"{phrase!r} does not read the sentence naming the "
                            f"gate, so it matches nothing in these documents: "
                            f"{sentences[subject]!r}",
                        )
                    elif kind == "subject":
                        self.assertIsNone(
                            read,
                            f"{phrase!r} is classified subject-anchored but reads "
                            f"{sentences[subject]!r}, which is about something else",
                        )
                    else:
                        self.assertEqual(
                            (3, 4), read,
                            f"{phrase!r} is classified a catch-all phrase but does "
                            f"not read {sentences[subject]!r}, so the "
                            "classification is stale and the record's claim about "
                            "it should change",
                        )
        # Both probes happened, for every alternative. Stated over the whole set
        # rather than per alternative so a future alternative added without its
        # two sentences fails here instead of being silently unprobed.
        for subject in ("gate", "other"):
            with self.subTest(corpus=subject):
                self.assertEqual(
                    set(self.RUNTIME_SPAN_KINDS), probed[subject],
                    f"not every alternative was probed with a {subject}-subject "
                    f"sentence; unprobed: "
                    f"{sorted(set(self.RUNTIME_SPAN_KINDS) - probed[subject])}",
                )
        # Every alternative in the pattern is classified, nothing is classified
        # that is not in the pattern, and nothing is classified without sentences.
        for phrase in self.RUNTIME_SPAN_KINDS:
            with self.subTest(classified=phrase):
                self.assertIn(
                    phrase, self.RUNTIME_SPAN.pattern,
                    f"{phrase!r} is classified but is not an alternative of the pattern",
                )
                self.assertIn(
                    phrase, self.RUNTIME_SPAN_SUBJECTS,
                    f"{phrase!r} is classified but has no probe sentences",
                )
        self.assertEqual(
            len(self.RUNTIME_SPAN_KINDS), self.RUNTIME_SPAN.groups // 2,
            f"the pattern has {self.RUNTIME_SPAN.groups // 2} alternatives and "
            f"{len(self.RUNTIME_SPAN_KINDS)} are classified",
        )

    def test_a_stale_gate_range_in_a_non_canonical_phrasing_is_still_caught(self):
        """The false-negative direction: each alternative has to be able to fail.

        The record states the gate runtime in more than one wording. If a stale
        number is introduced into any wording the pattern reads, the consistency
        check has to object. Each phrasing is mutated in turn and the check is
        required to notice, so an alternative cannot sit in the pattern matching
        nothing and being assumed to work.
        """
        phrasings = [
            "The gate runtime range reads {low}–{high} seconds in every document.",
            "It costs the {low}–{high} seconds the suite already spends.",
            "Measured across the runs, {low}–{high} seconds across the runs recorded here.",
        ]
        self.assertGreaterEqual(
            len(phrasings), 3, "fewer phrasings are listed than this check asserts"
        )
        low, high = 20, 90
        for wording in phrasings:
            for stale_low, stale_high in ((34, 52), (28, 35)):
                with self.subTest(wording=wording[:34], stale=(stale_low, stale_high)):
                    stated = wording.format(low=low, high=high)
                    self.assertEqual(
                        (low, high),
                        self.span_numbers(stated),
                        f"the pattern does not read this wording at all: {wording!r}",
                    )
                    mutated = wording.format(low=stale_low, high=stale_high)
                    self.assertNotEqual(
                        (low, high), self.span_numbers(mutated),
                        f"mutating {wording!r} did not change what the pattern reads",
                    )

    @staticmethod
    def span_numbers(text):
        """The first gate-runtime span in `text`, as a pair of integers."""
        for match in PrivacyAndOwnershipTests.RUNTIME_SPAN.finditer(flat(text)):
            values = [int(v) for v in match.groups() if v is not None]
            return tuple(values)
        return None

    def test_the_three_documents_state_the_same_gate_runtime(self):
        # ci.md said 31 seconds, ios.md said 28, and the record said 31. A
        # runtime is a measurement on one machine with variance, so a single
        # number is a claim the machine does not support; what has to hold is
        # that all three documents state the same range, and that the range
        # contains the run this record actually recorded.
        found = {}
        for document in ("docs/development/ci.md", "docs/development/ios.md",
                         "docs/development/foundation-verification.md"):
            body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
            matches = self.RUNTIME_RANGE.findall(body)
            with self.subTest(document=document):
                self.assertTrue(
                    matches, f"{document} states no gate runtime range"
                )
            found[document] = {tuple(int(value) for value in pair) for pair in matches}
        distinct = {value for values in found.values() for value in values}
        self.assertEqual(
            len(distinct),
            1,
            "the three documents state different gate runtimes: "
            + "; ".join(f"{k} {sorted(v)}" for k, v in sorted(found.items())),
        )
        low, high = distinct.pop()
        self.assertLess(low, high, f"the range {low}-{high} is not a range")
        # Every span in the three documents, whatever phrase introduces it, must
        # be that same range. A span in the right shape but the wrong numbers is
        # the case this exists for.
        stray = []
        phrasings = set()
        for document in ("docs/development/ci.md", "docs/development/ios.md",
                         "docs/development/foundation-verification.md"):
            body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
            for match in self.RUNTIME_SPAN.finditer(body):
                numbers = [
                    int(value) for value in match.groups() if value is not None
                ]
                # Which alternative matched, so the check below can require that
                # more than one phrasing is being read.
                phrasings.add(
                    next(
                        index
                        for index, value in enumerate(match.groups())
                        if value is not None
                    )
                )
                if tuple(numbers) != (low, high):
                    stray.append(
                        f"{document} states "
                        + "-".join(str(n) for n in numbers)
                        + " seconds"
                    )
        self.assertEqual(
            [], stray,
            "these gate-runtime spans disagree with the range the three documents "
            f"agree on ({low}-{high}): " + "; ".join(stray),
        )
        # The narrowed pattern has to still find the gate's spans. A pattern
        # tightened until it matches nothing would make the check above vacuous
        # while still passing, which is the failure mode of anchoring on
        # phrasing — so the number of spans it finds is itself required.
        # The narrowed pattern must still be reading more than the canonical
        # phrasing, or anchoring on the subject has quietly reduced this check to
        # the sentence the first pattern already found. Stated as "more than one
        # phrasing matched" rather than as a count, because a count here would be
        # another hand-written number to keep in step.
        self.assertGreater(
            len(phrasings), 1,
            "the narrowed runtime pattern matched only one phrasing, so the extra "
            "alternatives in it match nothing in these documents",
        )
        # The qualifier is what stops the range being read as a budget, so it
        # has to travel with the range in every document that states it — not
        # only in the one the assertion happened to be written against.
        qualifier = "measurement on one x86_64 Mac and not a bound"
        for document in ("docs/development/ci.md", "docs/development/ios.md",
                         "docs/development/foundation-verification.md"):
            with self.subTest(qualifier=document):
                self.assertIn(
                    qualifier,
                    flat((REPO_ROOT / document).read_text(encoding="utf-8")),
                    f"{document} states the range without saying it is a "
                    "measurement rather than a bound",
                )
        # The run the record's own table holds must fall inside the stated range,
        # which is what keeps the prose and the table from drifting apart.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        row = next(
            line
            for line in record.splitlines()
            if line.startswith("| `tools/ci/test_app_dependencies.py` |")
        )
        recorded = float(row.rsplit("|", 2)[1].strip())
        self.assertGreaterEqual(
            recorded, low,
            f"the record's table says {recorded}s, outside the stated {low}-{high}s range",
        )
        self.assertLessEqual(
            recorded, high,
            f"the record's table says {recorded}s, outside the stated {low}-{high}s range",
        )

    def test_the_records_blocklist_document_count_matches_the_subjects(self):
        # The record said the blocklist covered "seven documents" when the
        # subjects are the gate plus five. A count written in prose is a claim
        # about a list that lives in code, so it is compared against that list.
        subjects = self.overclaim_subjects()
        self.assertEqual(subjects[0], self.OVERCLAIM_GATE)
        documents = len(subjects) - 1
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        match = re.search(
            r"come back into the gate or into any of the (\w+)\s+documents that describe it",
            re.sub(r"\s+", " ", record),
        )
        self.assertIsNotNone(
            match, "the record no longer states how many documents the blocklist covers"
        )
        stated = match.group(1)
        acceptable = {
            str(documents),
            {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
             7: "seven", 8: "eight", 9: "nine", 10: "ten"}[documents],
        }
        self.assertIn(
            stated,
            acceptable,
            f"the record says {stated} documents; the blocklist covers {documents}",
        )
        # The fourth-pass before/after table carries the same count in a
        # different place, and a table is exactly what a reader checks instead of
        # the prose, so both have to name the same number.
        table = re.search(
            r"\| Documents in the overclaim blocklist \| (\d+) \| (\d+) \|",
            re.sub(r"\s+", " ", record),
        )
        self.assertIsNotNone(
            table,
            "the record no longer has a before/after row for the blocklist count",
        )
        before, after = int(table.group(1)), int(table.group(2))
        self.assertEqual(
            after,
            documents,
            f"the record's table says the blocklist covers {after} documents; it "
            f"covers {documents}",
        )
        # The before value is history, not something derived from the code: it is
        # the document count the third pass had, before README.md and SECURITY.md
        # were dropped. It is asserted because a placeholder there would make the
        # arrow meaningless, and it is seven rather than six because two documents
        # came out, not one — an earlier version of this test required the before
        # value to be after + 1, which was wrong by exactly the number of
        # documents the fourth pass removed.
        self.assertEqual(
            before,
            7,
            "the before column is the third pass's document count, which was 7 "
            f"before README.md and SECURITY.md were dropped, not {before}",
        )

        # The two exclusions are the reason the count is five and not seven, so
        # each has to be named where the list is defined, with why it is out.
        for absent in ("README.md", "SECURITY.md"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, subjects, f"{absent} is in the subject list")
                self.assertIn(
                    absent,
                    inspect.getdoc(self.overclaim_subjects) or "",
                    f"the exclusion of {absent} is not documented",
                )
        for subject in subjects:
            with self.subTest(subject=subject):
                self.assertTrue(
                    (REPO_ROOT / subject).is_file(),
                    f"{subject} is a blocklist subject but does not exist",
                )

    def test_the_gate_docstring_states_every_limit(self):
        gate = (REPO_ROOT / "tools/ci/test_app_dependencies.py").read_text(encoding="utf-8")
        self.assertIn("## What this gate does not claim", gate)
        for limit in GATE_LIMITS:
            with self.subTest(limit=limit):
                self.assertIn(limit, gate)

    def test_every_limit_in_the_gate_is_stated_in_the_documents_that_repeat_it(self):
        # Three documents restate the gate's limits in their own words. A limit
        # that lives in one file is a limit nobody reads, so each of these has to
        # carry the substance rather than point at the docstring and stop.
        for document, required in DOCUMENT_LIMITS.items():
            body = flat((REPO_ROOT / document).read_text(encoding="utf-8"))
            for limit in required:
                with self.subTest(document=document, limit=limit):
                    self.assertIn(limit, body)

    def test_every_leak_channel_is_named_where_channels_are_described(self):
        gate = (REPO_ROOT / "tools/ci/test_app_dependencies.py").read_text(encoding="utf-8")
        # Every literal, not just the ones ending in "(" — `logger.` is one of the
        # channels too.
        listed = re.findall(r'"([^"]+)"',
                            gate.split("LEAK_CHANNELS = (")[1].split(")")[0])
        self.assertEqual(len(listed), 9)
        described = gate.split("## What this gate does not claim")[0]
        for literal in listed:
            with self.subTest(channel=literal):
                self.assertIn(literal, described)
        for document in ("docs/development/ios.md", "docs/development/ci.md"):
            body = (REPO_ROOT / document).read_text(encoding="utf-8")
            for literal in listed:
                # The documents name the channel; the gate matches the call, so
                # `logger.` is written `logger` and `print(` is written `print`.
                with self.subTest(document=document, channel=literal):
                    self.assertIn(literal.rstrip("(."), body)

    def test_every_leak_channel_is_attributed_by_a_mutation(self):
        # A channel in the list that no mutation exercises is a channel the
        # detector might not read, and the suite would still be green. Each one
        # has to be attributable to a mutation, and the ones that are easy to
        # confuse have to be attributable on their own.
        gate = self.gate_module()
        self.assertEqual(len(gate.LEAK_CHANNELS), 9)

        class Recording:
            """Stands in for a workspace copy.

            The mutations only append and replace, so attributing a channel does
            not need twenty copies of the repository on disk. Running them for
            real is the gate's job; this test asks a narrower question.
            """

            def __init__(self) -> None:
                self.written = []

            def append(self, path, body):
                self.written.append(body)

            def replace(self, *args):
                # An edit to an existing declaration. It cannot introduce a
                # channel that was not already there, so there is nothing to
                # attribute.
                pass

        sources = []
        for label, operation in gate.TRACE_MUTATIONS.items():
            recorder = Recording()
            operation(recorder)
            sources.append((label, "".join(recorder.written)))
        for channel in gate.LEAK_CHANNELS:
            with self.subTest(channel=channel):
                attributed = [label for label, body in sources if channel in body]
                self.assertTrue(
                    attributed,
                    f"no trace mutation uses {channel}, so removing it from "
                    "LEAK_CHANNELS would fail nothing",
                )
        for channel in ("OSLog(", "logger."):
            with self.subTest(isolated=channel):
                alone = [
                    label
                    for label, body in sources
                    if channel in body and "Logger(" not in body
                ]
                self.assertTrue(
                    alone,
                    f"{channel} only ever appears beside Logger(, so the two are "
                    "proven together and either can be dropped unnoticed",
                )

    def test_the_foundation_record_states_the_gate_limits(self):
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "It promises only what it reads",
            "an operator overload is not read",
            "a stored `RuleEvaluation` is deliberately allowed",
            "reads the repository rather than the build",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, record, f"the record omits the limit: {phrase}")

    def test_privacy_document_says_the_presence_summary_is_the_only_input_echo(self):
        # What the debugger can show about an input is a presence boolean, and
        # the canonical diagnostic has nowhere to put a value. The document has to
        # say the same thing rather than describing a redaction boundary.
        self.assertIn("reported as a boolean", self.privacy)
        self.assertIn("never holds the value that was evaluated", self.privacy)
        diagnostic = (
            REPO_ROOT / "core/routing/Sources/RoviaRouting/RoutingDiagnostic.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("public var host: String { \"redacted\" }", diagnostic)

    def test_privacy_document_does_not_claim_a_store_the_app_does_not_use(self):
        # `platform/apple` implements a Keychain store and an App Group store and
        # both targets declare the App Group entitlement, so it is easy to write a
        # privacy document describing a flow that no code performs. These rows
        # must say the write does not happen yet.
        rows = {
            "Subscription URL": "Not stored in this slice",
            "Server credentials": "Not stored in this slice",
            "Non-secret canonical configuration": "Memory only in this slice",
            "Routing policy and selected server": "Memory only",
        }
        for subject, required in rows.items():
            with self.subTest(subject=subject):
                row = next(
                    line
                    for line in self.privacy.splitlines()
                    if line.startswith("|") and subject in line
                )
                self.assertIn(required, row, f"the {subject} row overstates what is stored")
        self.assertIn("no app or extension code calls it yet", self.privacy)
        self.assertIn("neither store is an enforcement", self.privacy)

    def test_privacy_document_does_not_claim_a_packet_flow_or_a_bundled_engine(self):
        provider = (REPO_ROOT / "client/app/ios/RoviaTunnel/PacketTunnelProvider.swift").read_text(
            encoding="utf-8"
        )
        # The extension never touches packetFlow, so a document that describes a
        # packet bridge as the flow is describing code that does not exist.
        self.assertNotIn("packetFlow", provider)
        self.assertIn("never reads or writes `packetFlow`", self.privacy)
        self.assertIn("No engine binary is bundled in this build", self.privacy)
        self.assertNotIn("the engine binary ships inside the app", self.privacy)
        self.assertIn("no engine is bundled in this build either", self.privacy)

    def test_privacy_document_names_the_canonical_diagnostic_and_the_raw_trace(self):
        self.assertIn("RouteEvaluator.explain", self.privacy)
        self.assertIn("RoviaConfig.RoutingDecisionTrace", self.privacy)
        self.assertIn("It is not `Codable`", self.privacy)
        # The debugger shows the redacted diagnostic; it does not hold the input.
        self.assertIn("never holds the value that was evaluated", self.privacy)
        evaluator = (REPO_ROOT / "core/routing/Sources/RoviaRouting/RouteEvaluator.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("public func explain(", evaluator)
        self.assertIn("control-response.schema.json", self.privacy)

    def test_privacy_document_links_the_threat_model_and_release_notes(self):
        self.assertIn("docs/security/threat-model.md", self.privacy)
        self.assertIn("docs/legal/app-store-distribution.md", self.privacy)

    def test_security_policy_reports_leaks_and_names_the_release_gates(self):
        self.assertIn("PRIVACY.md", self.security)
        for gate_path in (
            "tools/ci/verify-release-inputs.sh",
            "tools/ci/verify-engine-checksums.sh",
            "schemas/engine-lock.schema.json",
        ):
            with self.subTest(gate=gate_path):
                self.assertIn(gate_path, self.security)

    def security_sensitive_paths(self):
        """Security-sensitive paths, spelled without a leading or trailing slash.

        CODEOWNERS writes `/core/config/` and SECURITY.md writes `core/config/`;
        the two documents are about the same directory, so the comparison strips
        the slashes rather than asking a human to remember the convention.
        """
        return {
            path.strip("/")
            for path in re.findall(r"^- `([^`]+)`$", self.security, re.M)
        }

    def codeowner_entries(self):
        """Path -> handles, for every non-default CODEOWNERS rule.

        A rule is a line that starts with a path and is followed by handles.
        CODEOWNERS ends with prose paragraphs, and treating the first word of a
        sentence as a path would make the ownership list a list of English.
        """
        entries = {}
        for line in self.codeowners.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("*"):
                continue
            path, _, handles = line.partition(" ")
            handles = handles.split()
            if not path.startswith("/") or not handles or not handles[0].startswith("@"):
                continue
            entries[path.strip("/")] = handles
        return entries

    def test_codeowners_covers_every_security_sensitive_path(self):
        # Two directions. The third one from the version that ran under placeholder
        # handles has been dropped on purpose rather than forgotten.
        #
        #   * every security-sensitive path is owned
        #   * every path either file names is in the tree
        #
        # The dropped direction was "every path held by a security or engine handle is
        # security-sensitive". It worked by matching a handle *name* suffix, so it
        # needed distinct role handles to exist. There is now one owner, so ownership
        # carries no security signal at all and the direction cannot be restated: every
        # path is owned, so every path would have to be security-sensitive. The
        # classification now lives in one place, SECURITY.md, and this file's job is to
        # say the same paths in both documents and to check that they exist.
        listed = self.security_sensitive_paths()
        self.assertGreaterEqual(len(listed), 12)
        entries = self.codeowner_entries()

        for path in sorted(listed):
            with self.subTest(direction="sensitive but unowned", path=path):
                self.assertIn(path.strip("/"), entries,
                              f"{path} is security-sensitive but unowned")

        for path in sorted(listed | set(entries)):
            with self.subTest(direction="does not exist", path=path):
                self.assertTrue(
                    (REPO_ROOT / path.strip("/")).exists(),
                    f"{path} is listed in SECURITY.md or CODEOWNERS but is not in "
                    f"the tree; a path that does not exist reads as coverage",
                )

    def test_ownership_alone_is_not_a_security_signal(self):
        # The dropped direction, stated as its own check so the reason it was dropped
        # is held rather than only explained. With one owner, CODEOWNERS names every
        # path it lists, so if ownership implied sensitivity then every owned path
        # would be security-sensitive and the list would be the whole repository. It is
        # not, and `fixtures/` and `docs/architecture/` are the two that show it: both
        # are owned, and SECURITY.md says why neither is security-sensitive.
        entries = self.codeowner_entries()
        listed = self.security_sensitive_paths()
        for path, handles in sorted(entries.items()):
            if path in listed:
                continue
            with self.subTest(owned_but_not_sensitive=path):
                self.assertTrue(
                    handles,
                    f"{path} is listed in CODEOWNERS with no owner at all",
                )
        for path in ("fixtures", "docs/architecture"):
            with self.subTest(owned_and_not_sensitive=path):
                self.assertIn(path, entries,
                              f"{path} is owned but its ownership entry was removed")
                self.assertNotIn(
                    path, listed,
                    f"{path} became security-sensitive, which SECURITY.md has to "
                    "give a reason for",
                )

    def test_the_two_ownership_documents_state_the_same_paths(self):
        listed = self.security_sensitive_paths()
        entries = self.codeowner_entries()
        # CODEOWNERS owns more than SECURITY.md calls sensitive — documents and
        # fixtures are owned so they are not unattended — and the difference is
        # allowed. The set difference that used to be asserted here was computed from
        # handle *names*, and there is one handle now: see
        # `test_ownership_alone_is_not_a_security_signal` for why the direction was
        # dropped and what holds the reason instead.
        for path in ("core/config/", "core/routing/", "core/subscription/",
                     "client/app/ios/", "client/app/ios/RoviaTunnel/",
                     "tools/build-engine/", "tools/release/", "tools/ci/",
                     ".github/workflows/", "engines.lock.json"):
            with self.subTest(path=path):
                self.assertIn(path.strip("/"), listed,
                              f"{path} is missing from SECURITY.md")
                self.assertIn(path.strip("/"), entries,
                              f"{path} is missing from CODEOWNERS")
        for path in ("core/persistence/", "core/persistence"):
            with self.subTest(absent=path):
                self.assertNotIn(path.strip("/"), listed)
                self.assertNotIn(path.strip("/"), entries)

    def test_the_ownership_criterion_is_written_down(self):
        # A list with no stated criterion cannot be reviewed: the next person adds
        # a path on a hunch and the next removes one on a hunch.
        self.assertIn("### The criterion for this list", self.security)
        for reason in ("SecretReference", "ConfigValidation", "RoutingDecisionTrace",
                       "core/persistence/", "Packet Tunnel extension"):
            with self.subTest(reason=reason):
                self.assertIn(reason, self.security)
        self.assertIn("The criterion for the list is written down in `SECURITY.md`",
                      self.codeowners)

    OWNER = "@princeofscale"

    def ownership_handles(self):
        """Every handle named in a CODEOWNERS rule, including the default one."""
        handles = set()
        for line in self.codeowners.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for token in line.split():
                if token.startswith("@"):
                    handles.add(token)
        return handles

    def test_the_ownership_handles_name_one_real_owner(self):
        # Every handle is the repository owner, and nothing else. A handle that is not
        # that account is one of two things: an organisation team, which resolves to
        # nothing until an organisation exists, or a typo. Both read as a review
        # requirement and enforce none, which is the state this repository spent its
        # placeholder handles in.
        handles = self.ownership_handles()
        self.assertTrue(handles, "CODEOWNERS names no handle at all")
        for handle in sorted(handles):
            with self.subTest(handle=handle):
                self.assertEqual(
                    self.OWNER, handle,
                    f"{handle} is not the repository owner; a team handle enforces "
                    "no review until the organisation behind it exists",
                )

    def test_no_placeholder_namespace_survives_anywhere(self):
        # The namespace the old handles used, in either document. This is the check
        # that fails if a placeholder is ever pasted back in, and it is why the owner
        # test above can be a single comparison rather than a shape match.
        for document, name in ((self.codeowners, "CODEOWNERS"), (self.security, "SECURITY.md")):
            with self.subTest(document=name):
                self.assertNotIn(
                    "rovia-net", flat(document),
                    f"{name} still names the placeholder namespace",
                )

    def test_the_protection_that_exists_is_stated_as_precisely_as_the_gap(self):
        """Branch protection is partly real now, so "nothing is protected" is too strong.

        An active ruleset on `main` requires a pull request, forbids deletion and
        force-push, and permits only a squash merge. A document that still says
        `CODEOWNERS` is "inert until branch protection requires a review" is right
        about the review and wrong about the protection, and a reader cannot tell which
        half any given sentence means. So each document has to name both, and the two
        are asserted as two claims rather than one phrase.

        Three of these assertions exist because the first version of this test was too
        weak in ways worth recording:

        * "GitHub does not count the author's approval" explains *why* a review rule is
          unusable. It does not say the rule is off, and a document could state the
          explanation and then claim a review **is** required. The gap claim is the one
          being protected, so it is matched on its own words.
        * Calling the handles "placeholders" stopped being true when they became a real
          account. A document repeating that is describing a different problem from the
          one this repository has, which is the absence of a second approver.
        * A blanket ban on "nothing currently enforces" was too broad: the sentence is
          still true *of the review*. What is stale is the claim that nothing at all is
          protected, and that is what the positive assertions above hold.
        """
        for name in ("SECURITY.md", "CODEOWNERS", "GOVERNANCE.md", "CONTRIBUTING.md"):
            flattened = flat((REPO_ROOT / name).read_text(encoding="utf-8"))
            with self.subTest(document=name):
                # What the ruleset does.
                self.assertIn("active ruleset", flattened)
                self.assertIn("requires a pull request", flattened)
                self.assertIn("squash", flattened)
                self.assertIn("force-push", flattened)
                # What it does not do, on its own words.
                self.assertRegex(
                    flattened,
                    r"(does not require a review|not required|is not enforced|is off)",
                    f"{name} does not say that no review is enforced",
                )
                self.assertRegex(
                    flattened,
                    r"unmergeable|paralysis|blocks? every pull request",
                    f"{name} does not say why requiring a review is not an option yet",
                )
                # What the gap actually is.
                self.assertNotIn(
                    "placeholder", flattened,
                    f"{name} calls the CODEOWNERS handles placeholders; they name a "
                    "real account, and the gap is the missing approver",
                )
                self.assertRegex(
                    flattened,
                    r"independent approver|second pair of eyes|second maintainer",
                    f"{name} does not say what the gap actually is",
                )

                # A document that states the gap correctly can still be wrong in the
                # same paragraph, and the positive assertions above would not notice.
                # This is the failure mode the second CodeRabbit review was about: a
                # document that says "a review is required" *and* explains that no
                # review is enforced. The explanation is what a reader quotes; the
                # contradiction is what they act on. So every sentence that mentions
                # review and a requirement must also carry a negation, a hypothetical,
                # or an explicit statement of intent - otherwise it asserts a review
                # that does not exist.
                # Split into blocks, then into sentences. `flat()` collapses newlines,
                # so a markdown heading - which carries no terminating full stop - would
                # be glued to the sentence after it, and the negation in a heading would
                # mask a contradiction in the body. That was a real miss: appending
                # "A review is required before merging to main." directly under a
                # heading that says the list "does not enforce a review" passed.
                #
                # A heading is therefore a boundary - but it is not the *only* one
                # allowed, because splitting per line was itself a miss: a claim
                # wrapped as "A review is" / "required before merging to main." spans
                # two lines, and neither fragment contains both the subject and the
                # requirement, so the check saw nothing. Blocks join wrapped prose and
                # list-item continuations, and split only where the author started a new
                # unit.
                lines = (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()
                blocks, current = [], []
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        if current:
                            blocks.append(current)
                            current = []
                        continue
                    starts_unit = stripped.startswith("#") or re.match(
                        r"^([-*+]|\d+\.)\s", stripped
                    )
                    if starts_unit:
                        if current:
                            blocks.append(current)
                        current = [stripped]
                    else:
                        current.append(stripped)
                if current:
                    blocks.append(current)
                sentences = [
                    sentence
                    for block in blocks
                    for sentence in re.split(r"(?<=[.!?])\s+", flat(" ".join(block)))
                    if sentence.strip()
                ]
                for sentence in sentences:
                    # Case-insensitive throughout: these documents mix "Review",
                    # "review" and "REVIEW", and a check that only reads the lowercase
                    # spelling is a check with a hole shaped like capitalisation.
                    if not re.search(r"review", sentence, re.IGNORECASE):
                        continue
                    if not re.search(
                        r"\brequir|\bmust be approved|\bapprove\b",
                        sentence, re.IGNORECASE,
                    ):
                        continue
                    # Scoped to the claim actually at issue: a review enforced on the
                    # protected branch. A process rule that says a *future* change needs
                    # a human-reviewed lockfile is a different sentence about a
                    # different subject, and flagging it would be the check being wrong
                    # rather than the document.
                    if not re.search(
                        # "code-owner", "code owner" and CODEOWNERS are the same noun;
                        # only the first two were being missed.
                        r"\bmain\b|ruleset|branch protection|\bcode[- ]?owners?\b"
                        r"|\bmerge|protected|default branch",
                        sentence,
                        re.IGNORECASE,
                    ):
                        continue
                    if re.search(
                        r"\bnot\b|\bno\b|\bnothing\b|\bnever\b|\bwould\b|\bcannot\b"
                        r"|\bstatement of intent\b|\bintent\b|\bintended\b|\bif\b|\buntil\b",
                        sentence,
                        re.IGNORECASE,
                    ):
                        continue
                    self.fail(
                        f"{name} asserts a review that is not enforced: {sentence[:160]!r}"
                    )

    def test_a_required_check_is_never_described_as_ungovernable(self):
        """Where a document says the required check is enforced, it must be qualified.

        The required `swift-tests` check arrived with a sentence reading "a change
        cannot reach `main` without its own gates having run". That is true of the
        ordinary path and false in general: `gh pr merge --admin` exists, and a
        ruleset can grant a bypass. It is the same class of claim this repository has
        been removing everywhere else - a protection described as absolute where it
        is conditional, which is worse than not describing it, because it is the kind
        of sentence that stops anyone from checking.

        So every document that claims the check is required has to name the ordinary
        path, or name the administrator path, or both. Dropping the qualifier fails
        here rather than in a review three weeks later.
        """
        for name in ("SECURITY.md", "CODEOWNERS", "GOVERNANCE.md", "CONTRIBUTING.md"):
            flattened = flat((REPO_ROOT / name).read_text(encoding="utf-8"))
            with self.subTest(document=name):
                if "swift-tests" not in flattened:
                    continue
                self.assertTrue(
                    "ordinary merge" in flattened or "--admin" in flattened,
                    f"{name} states that the swift-tests check is enforced without "
                    "qualifying the path. An administrator can merge with --admin and "
                    "a ruleset can grant a bypass, so the claim is about the ordinary "
                    "path only and has to say so",
                )

    def test_a_strict_check_is_described_as_strict_wherever_it_is_claimed(self):
        """`strict_required_status_checks_policy: true` has a consequence worth writing.

        Strict means the branch must be up to date with `main` when it merges, so a
        green pull request becomes unmergeable because `main` moved. A contributor
        hits that as a merge that stops being accepted, and the rule is the reason.
        """
        readiness = flat(
            (REPO_ROOT / "docs/development/release-readiness.md").read_text(encoding="utf-8")
        )
        self.assertIn("strict", readiness)
        self.assertIn("up to date with `main`", readiness)
        for name in ("SECURITY.md", "GOVERNANCE.md", "CONTRIBUTING.md"):
            flattened = flat((REPO_ROOT / name).read_text(encoding="utf-8"))
            with self.subTest(document=name):
                if "swift-tests" not in flattened:
                    continue
                self.assertIn(
                    "up to date", flattened,
                    f"{name} claims the strict check but not what strict means",
                )

    def test_both_documents_say_no_review_is_enforced_yet(self):
        """The review gap has to be named as an open gate, not just as a caveat.

        This test previously asserted the literal phrase "inert until branch
        protection requires a review", which was true when no ruleset existed and
        became false the moment one did. Asserting a sentence about the *absence* of
        protection is how the stale claim survived in the first place: the sentence
        itself outlived the state it described. The state is asserted positively now,
        by `test_the_protection_that_exists_is_stated_as_precisely_as_the_gap`, and
        what remains here is the narrower job - both documents must tell a reader that
        the missing review is a tracked gap rather than a settled fact.
        """
        for document, name in ((self.codeowners, "CODEOWNERS"), (self.security, "SECURITY.md")):
            with self.subTest(document=name):
                self.assertRegex(
                    flat(document),
                    r"open (external )?gate|gate in|external gate",
                    f"{name} does not point at the open gate for the missing review",
                )
                # The documents describe the same gap in the same terms, so a reader
                # who sees one and not the other is not misled about the other.
                self.assertRegex(
                    flat(document),
                    r"independent approver|second pair of eyes|second maintainer",
                    f"{name} does not name the gap as the missing approver",
                )

    def test_the_readme_figures_are_what_the_loaders_say(self):
        # The README is the first thing a reader sees and the least audited document
        # in the repository, so its test counts are generated by
        # `tools/ci/update-readme-counts.py` and checked here rather than typed. A
        # number in a README that nobody re-derives goes stale quietly, and this
        # repository has a record of exactly that: counts in prose that drifted while
        # every test stayed green.
        script = REPO_ROOT / "tools" / "ci" / "update-readme-counts.py"
        self.assertTrue(script.is_file(), "the count generator does not exist")
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(
            0, result.returncode,
            "the README's figures are not what the loaders report: "
            f"{result.stdout}{result.stderr}",
        )

    def test_the_readme_makes_no_release_claim_it_cannot_support(self):
        # The README is the document most likely to drift into marketing, and the one
        # a prospective user reads before deciding whether to try the app. Each phrase
        # below is a claim a reader would otherwise have to take on trust, and each has
        # to survive in the text with the honest qualifier attached to it.
        # Lowercased on both sides: the phrases are sentence fragments and a capital
        # letter at the start of a bolded cell is a formatting choice, not a different
        # claim.
        readme = flat((REPO_ROOT / "README.md").read_text(encoding="utf-8")).lower()
        for required in (
            "pre-alpha",
            "does not establish a vpn tunnel",
            "not implemented",
            "has not happened",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)
        for forbidden in (
            "production-ready",
            "fully functional",
            "works on device",
            "app store version",
            "download the app",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, readme)

    def test_the_readme_states_the_three_verification_tiers(self):
        # Verified, not verified, and blocked are different claims, and a reader who
        # cannot tell them apart will believe the strongest one. The headings that keep
        # them apart are asserted rather than described.
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        # Matched as a substring rather than a whole line: the three tiers carry an
        # emoji before the words, and a test that had to strip decoration would be a
        # test about decoration.
        for heading in (
            "## Status",
            "Verified — implemented and tested",
            "Not verified — cannot be claimed",
            "Blocked by prerequisites outside this repository",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, readme)

    # Which contexts each `env:` block may name.
    #
    # GitHub evaluates a workflow-level `env` before any runner exists, so only
    # `github`, `inputs`, and `vars` resolve there. A job-level `env` is narrower
    # still: it adds `needs`, `strategy`, `matrix`, and `secrets`, and still has no
    # `runner`. The `runner` context exists only inside a step's `env:` and inside a
    # `run`, which is why this repository uses the `RUNNER_TEMP` environment variable
    # instead: it is a real variable, so it needs no context.
    #
    # A name outside the set is not a runtime warning. GitHub rejects the entire
    # workflow file with "Invalid workflow file … Unrecognized named-value", and the
    # run fails before creating a single job. Both levels were tried in this
    # repository's own `ci.yml` — `DERIVED_DATA: ${{ runner.temp }}` at the workflow
    # level, then at the job level — and both produced a 0-second failed run with zero
    # jobs. No local check can see it: the YAML parses, the tests pass, and the file
    # is a valid workflow by every measure available before pushing.
    WORKFLOW_LEVEL_CONTEXTS = {"github", "inputs", "vars"}
    JOB_LEVEL_CONTEXTS = WORKFLOW_LEVEL_CONTEXTS | {"needs", "strategy", "matrix", "secrets"}

    def env_blocks(self, path):
        """Every (scope, key, value) an `env:` block declares in a workflow.

        Read as source lines rather than parsed. A YAML round trip normalises the
        expression the gate exists to inspect, and `runner` is only a problem in the
        spelling that survived a round trip, so the text is the thing to read.
        """
        blocks = []
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped != "env:":
                continue
            indent = len(line) - len(line.lstrip())
            # A workflow-level env is at column 0; a job-level one is indented under
            # its job; a step-level one is indented further still. Only the first two
            # are checked, because a step's env does have `runner`.
            scope = {0: "workflow", 2: "job"}.get(indent)
            if scope is None:
                continue
            for follower in lines[index + 1:]:
                if not follower.strip() or follower.lstrip().startswith("#"):
                    continue
                follower_indent = len(follower) - len(follower.lstrip())
                if follower_indent <= indent:
                    break
                key, separator, value = follower.strip().partition(":")
                if separator and value.strip():
                    blocks.append((scope, key.strip(), value.strip()))
        return blocks

    def test_no_env_block_names_a_context_github_will_reject(self):
        """Both levels, against the set each one actually allows.

        Verified against this repository's own history: reinstating
        `DERIVED_DATA: ${{ runner.temp }}` at the workflow level, and then at the job
        level, each fails here. The first attempt at this gate checked only the
        workflow level, and the second hosted run failed for the same reason one
        level down — which is what a gate covering one of two places looks like from
        the outside.
        """
        allowed = {"workflow": self.WORKFLOW_LEVEL_CONTEXTS, "job": self.JOB_LEVEL_CONTEXTS}
        for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
            for scope, key, value in self.env_blocks(workflow):
                if "${{" not in value:
                    continue
                for context in re.findall(r"\$\{\{\s*([A-Za-z_][A-Za-z0-9_]*)", value):
                    with self.subTest(workflow=workflow.name, scope=scope, key=key):
                        self.assertIn(
                            context, allowed[scope],
                            f"{workflow.name} declares {key} = {value} in a "
                            f"{scope}-level env, and '{context}' is not available "
                            "there; GitHub rejects the whole file and the run creates "
                            "no job",
                        )

    def test_the_records_suite_figures_are_what_the_loaders_say(self):
        """The record's per-suite figures are written by a script, not by hand.

        They were re-derived by hand after every pass for weeks, and hand-derivation is
        where this repository has gone wrong: one careful regular expression rewrote a
        *historical* before/after table, replacing a figure a past pass had measured
        with today's, which is the exact error the record warns about three paragraphs
        above. `tools/ci/update-record-counts.py` writes the derived figures and leaves
        every earlier before/after table alone.
        """
        script = REPO_ROOT / "tools" / "ci" / "update-record-counts.py"
        self.assertTrue(script.is_file(), "the record updater does not exist")
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(
            0, result.returncode,
            "the record's suite figures disagree with the loaders: "
            f"{result.stdout}{result.stderr}",
        )

    def test_the_record_updater_leaves_historical_tables_alone(self):
        """The property that makes it safe to run.

        A caller can pass a different tree — a copy, a checkout — and the one thing it
        must not do is rewrite what a past pass measured. This asserts that directly, on
        a throwaway record with a distinctive historical figure in its earlier table.
        """
        script = REPO_ROOT / "tools" / "ci" / "update-record-counts.py"
        source = script.read_text(encoding="utf-8")
        self.assertIn("last_before_after_index", source)
        # Only the last table is rewritten: the function that finds it must return the
        # final index, and the historical values must still be present afterwards.
        self.assertRegex(
            source, r"indices\[-1\]",
            "the updater does not restrict itself to the last before/after table",
        )
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        historical = re.findall(r"^\| Tool tests \| \d+ \| (\d+) \|$", record, re.M)
        self.assertGreaterEqual(
            len(historical), 3,
            "the record has too few before/after tables for this check to mean anything",
        )
        self.assertGreater(
            len(set(historical)), 1,
            "every before/after table states the same figure, so the updater cannot be "
            "distinguishing a live table from a historical one",
        )

    def test_readme_points_at_the_privacy_document(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("PRIVACY.md", readme)

    def test_privacy_document_describes_the_provider_side_that_exists(self):
        # The extension implements the provider-message handler; the host side is
        # not wired in this slice. Claiming both ends would overstate what the app
        # does today.
        self.assertIn("handleAppMessage", self.privacy)
        self.assertIn("64 KiB", self.privacy)
        self.assertIn("not-implemented", self.privacy)
        self.assertNotIn("sendProviderMessage", self.privacy)
        provider = (REPO_ROOT / "client/app/ios/RoviaTunnel/PacketTunnelProvider.swift").read_text(
            encoding="utf-8"
        )
        for claim in ("handleAppMessage", "65_536"):
            with self.subTest(claim=claim):
                self.assertIn(claim, provider)

    def test_privacy_document_does_not_call_the_engine_lock_part_of_the_app(self):
        row = next(
            line
            for line in self.privacy.splitlines()
            if "engines.lock.json" in line and line.startswith("|")
        )
        self.assertIn("Not in the shipped app", row)
        self.assertIn("build input", row)

    READINESS_PATH = "docs/development/release-readiness.md"

    def readiness_disclosure_tests(self):
        """Every test method that holds the readiness disclosure.

        A method qualifies if its source reads the document by path or reaches it
        through one of the two accessors. Scanning for the path alone misses the
        tests that go through `readiness_document()` or `readiness_gates()`,
        which is how a document came to say five tests when six hold it.
        """
        found = []
        for name, method in inspect.getmembers(type(self), predicate=inspect.isfunction):
            if not name.startswith("test_"):
                continue
            source = inspect.getsource(method)
            if (
                self.READINESS_PATH in source
                or "readiness_document" in source
                or "readiness_gates" in source
            ):
                found.append(name)
        return sorted(found)

    def test_the_documents_state_how_many_tests_hold_the_readiness_disclosure(self):
        holding = self.readiness_disclosure_tests()
        self.assertTrue(
            holding, "no test holds the readiness disclosure, so nothing checks it"
        )
        # The disclosure itself and the record each have to carry the number, and
        # the number has to be the one this module actually has.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        statements = {
            "dated summary, readiness row":
                r"\| In-repo readiness disclosure \|[^|]*\| (\w+) tests",
            "fifth-pass narrative":
                r"(\w+) tests hold it, including one that requires each row",
        }
        for where, pattern in statements.items():
            match = re.search(pattern, re.sub(r"\s+", " ", record))
            with self.subTest(where=where):
                self.assertIsNotNone(
                    match, f"the record no longer states a test count in its {where}"
                )
                # Capitalised word, from the same table the rest of this file uses.
                # The literal map that was here covered 5 through 7 and raised
                # `KeyError: 8` the moment an eighth test joined the set - so the count
                # a reader is told could only ever be verified for as long as nobody
                # added a test. It fails with a sentence now instead of a traceback.
                self.assertIn(
                    match.group(1),
                    {str(len(holding)), word_for(len(holding)).capitalize()},
                    f"the record's {where} says {match.group(1)}, but "
                    f"{len(holding)} tests hold the disclosure",
                )

    def readiness_document(self):
        return (REPO_ROOT / "docs/development/release-readiness.md").read_text(
            encoding="utf-8"
        )

    def readiness_gates(self):
        """The gate rows of the readiness disclosure, as (title, body) pairs."""
        rows = []
        for line in self.readiness_document().splitlines():
            match = re.match(r"^\| (\d+) \| \*\*(.+?)\*\* \|", line)
            if match:
                rows.append((int(match.group(1)), match.group(2)))
        return rows

    def test_the_readiness_disclosure_is_in_the_repository_and_dated(self):
        # The list of unexecuted gates used to live only in a planning ledger
        # outside the repository. A disclosure nobody reviewing a change can see
        # is not a disclosure.
        path = REPO_ROOT / "docs/development/release-readiness.md"
        self.assertTrue(path.is_file(), "docs/development/release-readiness.md is missing")
        body = self.readiness_document()
        self.assertRegex(body, r"(?m)^Date: \d{4}-\d{2}-\d{2}$")
        for pointer in ("foundation-verification.md", "ci.md", "SECURITY.md"):
            with self.subTest(pointer=pointer):
                self.assertIn(pointer, body)

    def test_the_records_two_row_counts_match_the_refusal_table(self):
        # The record said "six rows" in its prose and "6" in its before/after
        # table after the table itself grew a seventh. Both are claims about the
        # table, so both are read and compared against the row count the parser
        # finds, rather than left as numbers a reader has to trust.
        expected = self.REFUSAL_ROWS
        body = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(len(self.record_refusal_table()), expected)

        statements = {
            "prose": r"each of its (\w+) rows by running the gate",
            "before/after table": r"\| Refusal rows derived from the gates \| 0 \| (\w+) \|",
        }
        for where, pattern in statements.items():
            match = re.search(pattern, body)
            with self.subTest(where=where):
                self.assertIsNotNone(
                    match, f"the record no longer states the refusal row count in its {where}"
                )
                stated = match.group(1)
                # The prose spells the number out and the table uses a digit, so
                # both renderings of the same count have to be accepted; what
                # cannot be accepted is a different count.
                acceptable = {
                    str(expected),
                    {
                        0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
                        5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
                        10: "ten",
                    }.get(expected, ""),
                }
                self.assertIn(
                    stated,
                    acceptable,
                    f"the record's {where} says {stated} rows, but the refusal table "
                    f"has {expected}",
                )

    def wording_exclusions(self):
        """The trees the wording test skips, read out of its own pattern."""
        source = Path(__file__).read_text(encoding="utf-8")
        match = re.search(r'excluded = re\.compile\(r"\^\(([^)]*)\)"', source)
        self.assertIsNotNone(match, "the wording test no longer has an exclusion pattern")
        return {
            alternative.strip().lstrip("\\").rstrip("/")
            for alternative in match.group(1).split("|")
        }

    def test_the_stated_exclusions_are_exactly_the_ones_the_wording_test_makes(self):
        # The record said the wording test excludes "only the gitignored planning
        # ledger". It excludes two trees, and one of them is not gitignored at all:
        # `docs/superpowers/` is part of the tree, and its 72 checkboxes are still
        # unticked while the ledger records all seven tasks complete. So the
        # exclusion is two planning records for two different reasons, and both the
        # set and the stated reason are checked here.
        exclusions = self.wording_exclusions()
        self.assertEqual(
            exclusions, {".superpowers", "docs/superpowers"},
            "the wording test's exclusion pattern covers "
            f"{sorted(exclusions)}, which the record does not describe",
        )
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        flat_record = flat(record)
        for tree in sorted(exclusions):
            with self.subTest(tree=tree):
                self.assertIn(
                    f"`{tree}/`", flat_record,
                    f"the record does not say that {tree} is excluded",
                )
        self.assertRegex(flat_record, r"excludes?\s+exactly two trees")
        self.assertNotIn(
            "excluding only the gitignored planning ledger", record,
            "the record still claims the ledger is the only exclusion",
        )
        # The gitignore status of each is a checkable claim, so check it.
        # A real file in each tree, not a made-up one: gitignore is a path-pattern
        # system, and the ledger is ignored by a `*` inside .superpowers/sdd/ rather
        # than by anything about .superpowers/ itself, so a probe at the top level
        # would report it as tracked.
        probes = {
            ".superpowers": ".superpowers/sdd/progress.md",
            "docs/superpowers":
                "docs/superpowers/plans/2026-09-24-rovia-foundation.md",
        }
        status = {}
        for tree in sorted(exclusions):
            self.assertIn(tree, probes, f"no probe path is recorded for {tree}")
            # `-C REPO_ROOT` rather than `cwd=`, so the check names the repository
            # it is asking about. Without it git resolves the repository from the
            # process working directory, and this suite is run from outside the
            # repository as well as inside it.
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", probes[tree]],
                capture_output=True,
            )
            status[tree] = result.returncode == 0
        self.assertTrue(
            status[".superpowers"],
            "the record says everything under .superpowers/sdd/ is gitignored and it "
            "is not",
        )
        # Both trees are ignored now. This assertion was inverted when
        # docs/superpowers/ was added to .gitignore, and the record had to be rewritten
        # with it: the sentence claiming that tree was part of the repository became
        # false while the reason for excluding it from these tests stayed true, and
        # only the ignore status said so.
        self.assertTrue(
            status["docs/superpowers"],
            "the record says docs/superpowers is gitignored, and it is not — the "
            "plans would be published with unticked checkboxes for finished work",
        )
        # The unticked checkboxes are the record's other stated reason for excluding
        # `docs/superpowers`, and that check is conditional on the plans being here.
        #
        # `docs/superpowers` is gitignored, so a fresh clone does not have it — the same
        # correction as the ledger above. The unticked count is verified where it is
        # verifiable, and the ignore status, which is verifiable everywhere, is verified
        # always. Both are needed: dropping the conditional fails every contributor, and
        # dropping the ignore check lets the plans be published unticked.
        plans = sorted((REPO_ROOT / "docs/superpowers").rglob("*.md"))
        if not plans:
            self.assertTrue(
                status["docs/superpowers"],
                "docs/superpowers has no plan files and is not gitignored, so they "
                "would be published with unticked checkboxes for finished work",
            )
            return
        unticked = sum(
            len(re.findall(r"(?m)^- \[ \]", plan.read_text(encoding="utf-8")))
            for plan in plans
        )
        self.assertGreater(
            unticked, 0,
            "the record excludes docs/superpowers because its checkboxes are unticked, "
            "and they are all ticked now, so that reason is stale",
        )
        self.assertIn(f"{unticked} of its checkboxes are still", flat_record)

    def test_every_unexecuted_gate_is_disclosed_and_named_by_a_real_path(self):
        gates = self.readiness_gates()
        self.assertEqual([number for number, _ in gates], list(range(1, len(gates) + 1)))
        self.assertGreaterEqual(
            len(gates), 9,
            "the disclosure has fewer rows than it had; a gate leaves the list by being "
            "executed, and the executed one is recorded in the document's Closed section",
        )
        body = self.readiness_document()
        readiness_lines = body.splitlines()
        for number, title in gates:
            with self.subTest(gate=number, title=title):
                # Every gate must name at least one path in the tree that would
                # have to change for it to be executed, so a row cannot drift
                # into describing something that is not here.
                index = next(
                    position for position, line in enumerate(readiness_lines)
                    if line.startswith(f"| {number} |")
                )
                row = readiness_lines[index]
                # The whole row, including its continuation lines. The rows are
                # wrapped for readability, so a rule that reads only the first physical
                # line of a row cannot see a path named further down - and the failure
                # it produces is "this gate names no path", which is a statement about
                # the checker rather than about the gate.
                row_lines = [row]
                for continuation in readiness_lines[index + 1:]:
                    if continuation.startswith("  ") and not continuation.strip().startswith("|"):
                        row_lines.append(continuation)
                    else:
                        break
                row = " ".join(part.strip() for part in row_lines)
                paths = re.findall(r"`([A-Za-z0-9._/-]+)`", row)
                if not paths:
                    # A gate about work that has not started has no path to
                    # point at, and the row has to say so rather than name
                    # something unrelated.
                    self.assertRegex(
                        row,
                        r"no path in this repository|nothing here that would have to change",
                        f"gate {number} names no path and does not say why",
                    )
                    continue
                for referenced in paths:
                    if referenced.endswith((".yml", ".sh", ".py", ".plist", ".json", ".md")):
                        with self.subTest(gate=number, path=referenced):
                            self.assertTrue(
                                (REPO_ROOT / referenced).exists(),
                                f"gate {number} names {referenced}, which does not exist",
                            )

    def test_the_readiness_disclosure_covers_the_gates_the_code_knows_about(self):
        # Source-derived: each of these is a gate this repository can see but not
        # run, named by the file that would have to change.
        # Hosted CI execution and the four configured security controls are
        # deliberately absent: they ran, or they are set, and the evidence is recorded
        # in that document's own `## Closed` section with the API response that shows
        # it. A gate leaves this set by being executed, so the way to re-add one is to
        # delete the evidence, not to edit this dict - which is the direction a reviewer
        # would have to notice.
        #
        # The advisories gate is here under a narrower name than it used to carry. It
        # was "Third-party advisories, dependency review, and secret scanning", and it
        # stayed open after secret scanning, push protection, Dependabot security
        # updates, automated security fixes, and private vulnerability reporting had all
        # been enabled, because the gate names a bundle and only part of the bundle
        # moved. What is genuinely unclosed is dependency review and the absence of a
        # written advisory-response process, and the gate says that.
        required = {
            "Signing, provisioning, and the Apple team identity":
                "tools/release/ExportOptions.plist",
            "Archive and export": ".github/workflows/release-ios.yml",
            "Upload, TestFlight, and App Store submission": "CODEOWNERS",
            "Physical-device VPN behaviour": "tools/ci/verify-simulator-install.sh",
            "A production engine": "engines.lock.json",
            "Required review, and environment approvals": "CODEOWNERS",
            "Dependency review and an advisory-response process":
                "tools/ci/verify-lockfiles.sh",
            "Upstream SPDX tooling": "tools/reproducibility/check-sbom.py",
            "Android": "engines.lock.json",
        }
        titles = {title for _, title in self.readiness_gates()}
        for title, path in required.items():
            with self.subTest(gate=title):
                self.assertIn(title, titles, f"{title} is not disclosed as unexecuted")
                self.assertTrue(
                    (REPO_ROOT / path).exists(),
                    f"{title} is disclosed against {path}, which does not exist",
                )

    def test_the_readiness_disclosure_makes_no_claim_about_an_unexecuted_gate(self):
        body = flat(self.readiness_document())
        # Each row is a refusal or an absence, never a pass.
        for _, title in self.readiness_gates():
            with self.subTest(gate=title):
                self.assertNotRegex(body.lower(), rf"{re.escape(title.lower())} (passed|succeeded)")
        # "no *human* review is currently required" is deliberately not "no review":
        # the ruleset does require a review-free gate to pass, and a document that
        # collapsed the two would describe a repository with no CI, which stopped
        # being true when `swift-tests` became a required status check. Both halves
        # are asserted so neither can be dropped.
        for phrase in (
            "It is not evidence about a tunnel",
            "no human review is currently required on any path",
            "requires the `swift-tests` status check to pass",
            "The refusal of a gate is a result, not a gap",
            "It is not a VPN",
            "This is row 7, not a control",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)
        # The old ledger-only disclosure is not the only copy any more.
        self.assertIn("Everything below is unexecuted", body)

    def environment_row(self, label: str) -> str:
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        row = next(
            (line for line in record.splitlines() if line.startswith(f"| {label} |")),
            None,
        )
        self.assertIsNotNone(row, f"the environment table has no {label} row")
        return row

    def test_the_recorded_uv_row_is_what_uv_reports(self):
        # The record transcribed `uv` by hand and produced "0.11.8 (8e961dd9
        # 2026-04-27)" where `uv --version` says
        # "uv 0.11.8 (0e961dd9a 2026-04-27 x86_64-apple-darwin)": a dropped leading
        # zero, a dropped trailing character, and no platform at all. A record
        # transcribed by hand cannot be checked; this row has to carry the tool's
        # own words.
        if shutil.which("uv") is None:
            self.skipTest("uv is not on PATH, so the recorded row cannot be checked")
        reported = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True
        ).stdout.strip()
        payload = reported.removeprefix("uv ").strip()
        row = self.environment_row("`uv` / `uvx`")
        self.assertIn(
            payload, row,
            f"the record's uv row does not carry what uv reports ({payload}); it "
            f"says {row!r}",
        )

    # What the environment table is, and is not.
    #
    # It records the toolchain the local evidence was produced on. It is not a
    # repository invariant, and holding it against whatever toolchain happens to be
    # running the test made that mistake concrete: the fourth hosted CI run failed with
    # "the record's Swift row does not carry the version the tool reports (6.1.2)" and
    # "…Xcode row… (16.4)", because a GitHub macOS runner legitimately has a different
    # Xcode than the machine that wrote the record. A table that only one machine can
    # satisfy is a table about that machine, and a gate on it is a gate that can only be
    # green in one place.
    #
    # What IS a repository invariant is the versions the project pins: the linter and
    # the schema validator. Those are compared against what actually runs, everywhere.
    # Rows the project pins, so they are repository invariants rather than
    # observations. `pyflakes_argv()` because that is how the linter is actually run:
    # hard-coding one route would fail on whichever machine lacks it.
    # The `--version` flag lives in the row, not at the call site, so each row is a
    # complete command. It was dropped from the linter row while this was being
    # restructured, and the symptom was a linter that reported no version because it
    # had been run over the whole of tools/.
    PINNED_TOOL_ROWS = (
        ("`uv` / `uvx`", lambda: ["uv", "--version"]),
        ("Python linter", lambda: pyflakes_argv() + ["--version"]),
    )

    def test_the_pinned_tool_versions_are_what_actually_runs(self):
        # The versions this repository chooses. A gate that runs a different pyflakes
        # than the one it pins is not the gate that was reviewed, so this is compared
        # against the running tool rather than against a record row.
        for label, resolve in self.PINNED_TOOL_ROWS:
            command = resolve()
            if shutil.which(command[0]) is None:
                continue
            with self.subTest(row=label):
                # Both streams, and the interpreter's own echo line dropped: `python3
                # -m pyflakes --version` writes the interpreter path and the `-m` form
                # to stderr before the version, so the first version-shaped token in the
                # raw output is the interpreter's — "3.14" out of python3.14 — and
                # comparing that against the linter row would be comparing two
                # unrelated versions.
                result = subprocess.run(command, capture_output=True, text=True)
                lines = [
                    line for line in (result.stdout + result.stderr).splitlines()
                    if line.strip() and " -m " not in line
                ]
                version = re.search(r"\d+\.\d+(?:\.\d+)?", "\n".join(lines))
                self.assertIsNotNone(
                    version,
                    f"{' '.join(command)} reported no version in "
                    f"{(result.stdout + result.stderr).strip()[:120]!r}",
                )
                self.assertIn(version.group(0), self.environment_row(label),
                              f"the record's {label} row does not carry the version "
                              f"that actually runs ({version.group(0)})")

    def test_the_toolchain_table_is_stated_as_a_local_observation(self):
        # The rows the project does not control — Xcode, Swift, Python, macOS — are
        # observations, and the record has to say so rather than presenting them as
        # requirements. Without this, a contributor on a different toolchain reads the
        # table as a statement of what the project needs, which it is not: the project's
        # own floor is `swift-tools-version: 6.0` and a 17.0 deployment target, both of
        # which the hosted runner satisfies with an older Xcode.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            flat(record),
            r"evidence about (this repository|one machine|this machine)",
            "the record does not scope its own evidence to a machine",
        )
        header = record.split("## Environment, exactly as reported", 1)[-1][:1200]
        self.assertRegex(
            flat(header),
            r"(local|this machine|observed|one machine|not a requirement|differs)",
            "the environment table is not labelled as an observation of one machine",
        )
        for label in ("Xcode", "Swift", "Python"):
            with self.subTest(row=label):
                self.assertTrue(
                    number := self.environment_row(label)
                    and re.search(r"\d+\.\d+", self.environment_row(label)),
                    f"the {label} row states no version at all",
                )
                self.assertIsNotNone(number)

    def test_the_derived_data_claim_is_stated_without_naming_a_run_directory(self):
        # Naming one run's directory left the record pointing at a path the next
        # run had already abandoned. The load-bearing part is that derived data
        # lives outside the checkout, and that is what this requires.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        stale = re.findall(r"rovia-t\d+[a-z]?-derived-data", record)
        self.assertEqual(
            stale, [], f"the record still names a per-run derived data path: {stale}"
        )
        self.assertIn(
            "Derived data goes in a fresh directory under `$TMPDIR` on every run", record
        )
        self.assertIn(
            "outside the checkout, which is what", flat(record),
        )
        # The claim has to be true of the path the record now names, not only
        # asserted in prose.
        temporary = Path(os.environ.get("TMPDIR", "/tmp")).resolve()
        self.assertFalse(
            temporary == REPO_ROOT or REPO_ROOT in temporary.parents,
            "TMPDIR is inside the checkout, so the claim cannot hold",
        )
        self.assertIn("TMPDIR", record)
        # And CI keeps the same property.
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("runner.temp", workflow)

    def lint_gate_tests(self):
        """Every test in the lint gate's own class.

        Not a heuristic. The gate is held by a class, and the count is the number
        of its test methods, so a test added to that class is counted by
        construction — which a name-and-source filter can never promise. The filter
        this replaced, `"lint" in name or "pyflakes" in source`, would under-count a
        gate test named without either marker and the documents would still pass.
        """
        return sorted(
            name
            for name, _ in inspect.getmembers(
                PythonLintGateTests, predicate=inspect.isfunction
            )
            if name.startswith("test_")
        )

    def lint_gate_count(self):
        return len(self.lint_gate_tests())

    def count_words(self, number: int):
        words = {
            1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
            7: "seven", 8: "eight", 9: "nine", 10: "ten",
        }
        spelled = words.get(number, str(number))
        return {str(number), spelled, spelled.capitalize()}

    def lint_count_occurrences(self, text: str):
        """Every "N tests hold it/this" in a text, each one classified.

        Returns [(is_quoted, word, line_number)]. Every occurrence is classified
        rather than the first one matched: `re.search` reads one, so a wrong count
        later in a document passed.

        A claim is *quoted* when an odd number of double quotes precedes it on its
        line, which is how a report writes `"Six tests hold it"` while describing
        the error rather than repeating it.
        """
        occurrences = []
        for number, line in enumerate(text.splitlines(), 1):
            for match in re.finditer(r"\b(\w+) tests hold (?:it|this)\b", line):
                quoted = line[: match.start()].count('"') % 2 == 1
                occurrences.append((quoted, match.group(1), number))
        return occurrences

    def lint_count_documents(self):
        """Every document that states how many tests hold the lint gate.

        The local task ledger is read when it is there and skipped when it is not, and
        that is a correction rather than a convenience. The ledger lives under
        `.superpowers/`, which is gitignored because it is the development harness's own
        output rather than project documentation, so it is absent from every fresh clone
        — and reading it unconditionally made this test fail for any contributor and for
        the first hosted CI run, with
        `FileNotFoundError: … /.superpowers/sdd/2026-09-24-rovia-hardening/progress.md`.
        A test that only passes on the machine that wrote it is a test about that machine.

        The document that is published is required, and the asymmetry is the point: a
        stale count in `ci.md` is a claim a reader is shown, and a stale count in a
        gitignored ledger is shown to nobody.
        """
        documents = {
            "docs/development/ci.md": (REPO_ROOT / "docs/development/ci.md").read_text(
                encoding="utf-8"
            ),
        }
        ledger = REPO_ROOT / ".superpowers/sdd/2026-09-24-rovia-hardening"
        for name in ("progress.md", "task-7-report.md"):
            path = ledger / name
            if path.is_file():
                documents[name] = path.read_text(encoding="utf-8")
        return documents

    def test_the_published_lint_count_document_is_required(self):
        # The companion to the skip above, so the skip cannot quietly become the only
        # behaviour: if `ci.md` stopped existing, "no document disagrees" would be
        # vacuously true.
        self.assertIn("docs/development/ci.md", self.lint_count_documents())
        self.assertTrue(
            (REPO_ROOT / "docs/development/ci.md").is_file(),
            "the published document stating the lint-gate count is missing",
        )

    def test_the_documented_lint_test_count_matches_the_gate_class(self):
        holding = self.lint_gate_tests()
        self.assertTrue(holding, "the lint gate class holds no tests")
        expected = self.lint_gate_count()
        acceptable = self.count_words(expected)
        for document, text in self.lint_count_documents().items():
            occurrences = self.lint_count_occurrences(text)
            with self.subTest(document=document):
                self.assertTrue(
                    occurrences,
                    f"{document} makes no claim about the lint gate count, so there "
                    "is nothing to check and the claim has gone missing",
                )
                live = 0
                for quoted, word, line in occurrences:
                    if quoted:
                        # A quoted count is a historical error being described. It
                        # may differ — that is the point of quoting it — but the
                        # document must also make a live claim, so a quote can
                        # never be the only statement.
                        continue
                    live += 1
                    self.assertIn(
                        word, acceptable,
                        f"{document}:{line} says {word!r} where the gate class holds "
                        f"{expected} ({holding})",
                    )
                self.assertGreater(
                    live, 0,
                    f"{document} states the lint gate count only inside a quotation, "
                    "so a quoted error could be the only claim",
                )

    def test_the_count_check_distinguishes_a_claim_from_a_quotation(self):
        # Both cases, directly. A non-quoted wrong count is caught; a quoted wrong
        # count is not, because a quotation is a quotation — and the live-claim
        # requirement is what stops a document consisting only of quotations.
        acceptable = self.count_words(self.lint_gate_count())
        self.assertIn("five", acceptable, "this pass's own count should be five")
        # (line, is it quoted, is the count then acceptable)
        for line, expect_quoted, expect_accepted in (
            ("Five tests hold it.", False, True),
            ("five tests hold it", False, True),
            ("Six tests hold it.", False, False),
            ("Four tests hold this", False, False),
            ('"Six tests hold it"', True, None),
            ('The old line read "Six tests hold it" and was wrong.', True, None),
        ):
            with self.subTest(line=line):
                found = self.lint_count_occurrences(line)
                self.assertEqual(len(found), 1, f"{line!r} matched {len(found)} times")
                quoted, word, _ = found[0]
                self.assertEqual(quoted, expect_quoted)
                if expect_accepted is None:
                    # A quotation may differ from the live count; that is what
                    # quoting it is for.
                    self.assertNotIn(word, acceptable)
                else:
                    self.assertEqual(
                        word in acceptable, expect_accepted,
                        f"{line!r} was classified as {'acceptable' if expect_accepted else 'wrong'}",
                    )

    def test_a_lint_gate_test_cannot_be_added_without_being_counted(self):
        # The negative case the class was introduced for. A method added to the
        # class is counted the moment it exists, so the document check then fails
        # until the documents are updated — there is no naming convention to
        # satisfy and nothing to remember.
        before = self.lint_gate_count()

        def added(self):
            """A gate test that does not exist yet."""

        added.__name__ = "test_a_gate_test_named_nothing_like_lint_or_pyflakes"
        setattr(PythonLintGateTests, added.__name__, added)
        self.addCleanup(
            delattr, PythonLintGateTests, added.__name__
        )
        after = self.lint_gate_count()
        self.assertEqual(
            after, before + 1,
            "a method added to the gate class was not counted, so a sixth gate test "
            "could be written and the documents would still pass",
        )
        self.assertIn(added.__name__, self.lint_gate_tests())
        # And the count the documents must match has moved with it.
        self.assertNotIn(str(after), self.count_words(before))

    def test_the_release_readiness_document_is_pointed_at_from_the_policy(self):
        self.assertIn("docs/development/release-readiness.md", self.security)
        ci = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        self.assertIn("docs/development/release-readiness.md", ci)
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("docs/development/release-readiness.md", record)

    RELEASE_GATE_CHECKS = (
        ("signing identity", "tools/release/verify-export-options.sh"),
        ("signing secrets", "missing_secret=0"),
        ("tag grammar", "rovia_tag_is_valid"),
        ("input files exist", 'require_file "artifact"'),
        ("engine lock", "--mode release --lock"),
        ("artifact", "# -- the artifact itself"),
        ("checksums", "# -- checksums"),
        ("SBOM", "# -- SBOM"),
        ("provenance manifest", "# -- provenance manifest"),
    )

    ORDER_NEEDLES = {
        "signing identity": "signing identity",
        "signing secrets": "signing secret",
        "tag grammar": "tag grammar",
        "input files exist": "existence",
        "engine lock": "engine lock",
        "artifact": "artifact",
        "checksums": "checksum",
        "SBOM": "SBOM",
        "provenance manifest": "provenance manifest",
    }

    def derived_release_gate_order(self):
        """The order verify-release-inputs.sh runs its checks, read from the body.

        The header comment is deliberately not consulted: it is prose, and prose
        is what drifted. Each marker is located in the executable body, and the
        order is the order the markers appear in.
        """
        body = (REPO_ROOT / "tools/ci/verify-release-inputs.sh").read_text(
            encoding="utf-8"
        )
        # Drop the header comment block so a marker mentioned in the prose
        # cannot be mistaken for the place the check runs.
        body = body.split("set -euo pipefail", 1)[1]
        positions = []
        for name, marker in self.RELEASE_GATE_CHECKS:
            index = body.find(marker)
            self.assertNotEqual(
                index, -1, f"the marker for {name} is not in the gate body: {marker}"
            )
            positions.append((name, index))
        for (earlier, first), (_, second) in zip(positions, positions[1:]):
            self.assertLess(
                first,
                second,
                f"{earlier} runs after the check that follows it, so the derived "
                "order is wrong",
            )
        return [name for name, _ in positions]

    def test_the_documented_release_gate_order_matches_the_script(self):
        # CHANGELOG.md and ci.md both listed the engine lock last. It has never
        # been last: the script runs verify-engine-checksums.sh before it opens
        # the artifact. A release gate described in the wrong order is a gate
        # nobody can reason about when it refuses.
        order = self.derived_release_gate_order()
        self.assertEqual(order[0], "signing identity")
        self.assertLess(
            order.index("engine lock"),
            order.index("artifact"),
            "the engine lock is checked before the artifact is opened",
        )
        self.assertLess(order.index("engine lock"), order.index("provenance manifest"))

        # Both documents must state the order inside the passage that states it.
        # A whole-document search for the first mention of "engine lock" finds
        # the sentence that introduces the gate, not the one that orders it, so
        # the comparison is bounded to the order statement.
        for document, anchor in (
            ("CHANGELOG.md", "a release-input gate that checks"),
            ("docs/development/ci.md", "The order those refusals happen in"),
        ):
            raw = (REPO_ROOT / document).read_text(encoding="utf-8")
            with self.subTest(document=document):
                self.assertIn(anchor, raw, f"{document} has no order statement")
                start = raw.index(anchor)
                # The statement runs to the next blank line or the next list
                # item, whichever comes first. Cutting at the first sentence
                # would stop inside the anchor's own sentence, and cutting at
                # the end of the document would sweep in prose that names the
                # engine lock before the order statement does.
                tail = raw[start:]
                end = len(raw)
                for pattern in (r"\n[ \t]*\n", r"\n[ \t]*(?:-[ \t]|\d+\. )"):
                    match = re.search(pattern, tail)
                    if match:
                        end = min(end, start + match.start())
                statement = flat(raw[start:end])
                positions = []
                for name in order:
                    needle = self.ORDER_NEEDLES[name]
                    self.assertIn(
                        needle,
                        statement,
                        f"{document} does not name the {name} check in its order "
                        "statement",
                    )
                    positions.append((name, statement.index(needle)))
                for (earlier, first), (later, second) in zip(positions, positions[1:]):
                    self.assertLess(
                        first,
                        second,
                        f"{document} names {later} before {earlier} in its order "
                        "statement, which is not the order the gate runs",
                    )
                # And the correction has to be stated, not just implied.
                self.assertIn(
                    "before the artifact is opened",
                    statement if document.endswith("ci.md") else flat(
                        (REPO_ROOT / document).read_text(encoding="utf-8")
                    ),
                    f"{document} does not say the engine lock precedes the artifact",
                )

    def test_the_script_header_documents_the_order_it_actually_runs(self):
        # The shell header is comment lines, so the markers come off before the
        # text is flattened: flattening "#   3. the artifact ... exist and\n#      are
        # non-empty" without stripping them leaves "exist and # are non-empty",
        # which no phrase can match.
        header = "\n".join(
            re.sub(r"^#\s?", "", line)
            for line in (
                (REPO_ROOT / "tools/ci/verify-release-inputs.sh")
                .read_text(encoding="utf-8")
                .split("set -euo pipefail", 1)[0]
                .splitlines()
            )
        )
        for number, name in enumerate(self.derived_release_gate_order()):
            needle = {
                "signing identity": "signing identity",
                "signing secrets": "signing secret",
                "tag grammar": "release tag is well formed",
                "input files exist": "all exist and are non-empty",
                "engine lock": "engine lock is exactly one approved Xray entry",
                "artifact": "readable IPA",
                "checksums": "SHA256SUMS file lists the artifact",
                "SBOM": "the SBOM is SPDX 2.3",
                "provenance manifest": "provenance manifest was written",
            }[name]
            with self.subTest(check=name, number=number):
                self.assertIn(
                    needle,
                    flat(header),
                    f"the header does not describe the {name} check, which runs "
                    f"at position {number}",
                )
        self.assertIn(
            "The engine lock used to be documented as the last check", flat(header)
        )

    REFUSAL_ROWS = 7

    def record_refusal_table(self):
        """The refusal table, and only the refusal table.

        The unbounded version of this split on the section heading and then read
        every ``| ` row below it, which swallowed a later table in the same
        document — a before/after table in the remediation history — and reported
        a row for it. The table therefore ends at the first line that is not a
        table row, and the row count is pinned.
        """
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        _, _, block = record.partition("### Gates that refuse, on purpose")
        self.assertNotEqual(block, "", "the refusal table heading is missing")
        rows = {}
        for line in block.splitlines():
            if not line.startswith("|"):
                if rows:
                    break
                continue
            if line.startswith("| ---") or line.startswith("| Command"):
                continue
            command, _, result = line[2:].partition(" | ")
            rows[command.strip()] = result.strip()
        return rows

    SUMMARY_HEADING = (
        "Release, provenance, security, and ownership remediation — dated summary"
    )

    def test_the_in_repo_record_carries_the_release_and_security_remediation(self):
        # The remediation was done and written up in a planning ledger outside the
        # repository. A disclosure nobody reviewing a change can see is not a
        # disclosure, and the in-repo record is where it has to live.
        record = flat(
            (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(self.SUMMARY_HEADING, record)
        for topic, marker in (
            ("the export-options team-ID gate", "verify-export-options.sh"),
            ("the team-ID ordering", "Require a resolved signing identity"),
            ("the derived engine licenses", "libXray MIT, Xray-core MPL-2.0"),
            ("the bidirectional ownership check", "Bidirectional ownership"),
            ("the in-repo readiness disclosure", "docs/development/release-readiness.md"),
            ("the derived counts", "Derived counts"),
        ):
            with self.subTest(topic=topic):
                self.assertIn(marker, record, f"the record does not cover {topic}")

        # It has to be dated in its own right, not only by the record header.
        headings = record_sections()
        # Sections are found structurally now. This used to filter headings by name —
        # "remediation pass" or "remediation — dated summary" — and the record's actual
        # last section, "Runtime-pattern anchoring and changelog coverage — dated
        # summary", contains neither phrase, so it was missing from the list and the
        # invariant below was being decided by a section that was not last. A pass
        # section is a section whose title carries the marker, whatever it is called.
        # Each pass this record has must be present. There is no count and no floor:
        # the list of which passes exist is `EXPECTED_PASS_SECTIONS`, compared in both
        # directions by the test beside this one, and a floor over a derived list is a
        # hand-written number that goes stale.
        for expected in (
            "Second remediation pass",
            "Third remediation pass",
            "Fourth remediation pass",
            "Fifth remediation pass",
        ):
            with self.subTest(pass_section=expected):
                self.assertIn(expected, headings, f"{expected} is no longer in the record")
        # No floor on how many pass sections there are. It was `>= 5` over a list
        # built by a name filter, so it counted the sections that happened to say
        # "remediation"; a floor is a hand-written number about a derived list, and
        # the pinned list is the statement of which passes exist.

        # The summary's own date, and it has to match the record's date.
        text = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        header_date = re.search(r"(?m)^Date: (\d{4}-\d{2}-\d{2})$", text)
        self.assertIsNotNone(header_date, "the record carries no Date line")
        # Every dated summary, not only the first one. There are now two, and a
        # check written for one would either fail on the second or be weakened
        # until it checked neither.
        summaries = [
            heading
            for heading in headings
            if heading.endswith("dated summary")
        ]
        self.assertIn(
            self.SUMMARY_HEADING, summaries,
            f"the record does not have a {self.SUMMARY_HEADING!r} section",
        )
        for heading in summaries:
            with self.subTest(summary=heading):
                _, _, after = text.partition(heading)
                summary_date = re.search(r"(?m)^Date: (\d{4}-\d{2}-\d{2})$", after)
                self.assertIsNotNone(
                    summary_date,
                    f"the {heading!r} section carries no Date line, so it is not "
                    "dated in its own right",
                )
                self.assertEqual(
                    summary_date.group(1),
                    header_date.group(1),
                    f"the {heading!r} section and the record disagree about the date",
                )

        # The *last section in the document* has to be a dated summary, so a pass
        # cannot be appended without a summary of its own whatever it is called. The
        # check is on the document's last `###` heading, not on a filtered list, so
        # it cannot be decided by an earlier section — which is what happened when the
        # list was built by name and the real last section was not in it.
        self.assertTrue(
            headings, "the record has no sections at all"
        )
        self.assertTrue(
            headings[-1].endswith(DATED_SUMMARY_MARKER),
            f"the last section of the record is {headings[-1]!r}, which is not a "
            "dated summary; a pass was appended without one",
        )
        self.assertTrue(
            self.SUMMARY_HEADING in headings,
            f"the roll-up section {self.SUMMARY_HEADING!r} is not a section of the "
            "record any more",
        )

    def test_the_record_does_not_call_the_lint_gate_the_runner_s_last_step(self):
        # It is not: the warnings gate runs after it. The record said it was, and
        # nothing held the sentence, so the fix is a test as well as an edit.
        record = (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
            encoding="utf-8"
        )
        flat_record = flat(record)
        self.assertNotIn(
            "invoked by `run-tool-tests.sh` as its last step", flat_record,
            "the record still calls the lint gate the runner's last step; the "
            "warnings gate runs after it",
        )
        # Both gates are named, and the one that is last is named as such.
        for gate_path in ("tools/ci/check-python-lint.sh", "tools/ci/check-python-warnings.sh"):
            with self.subTest(gate=gate_path):
                self.assertIn(
                    gate_path, flat_record,
                    f"the record does not name {gate_path}",
                )
        self.assertIn(
            "the last step of `run-tool-tests.sh`", flat_record,
            "the record does not say which gate is last",
        )
        # And which one is last is read from the runner, not from the sentence.
        runner = (REPO_ROOT / "tools/ci/run-tool-tests.sh").read_text(encoding="utf-8")
        self.assertLess(
            runner.index("check-python-lint.sh"),
            runner.index("check-python-warnings.sh"),
            "the runner invokes the warnings gate before the lint gate, so the "
            "record's claim about which is last is wrong",
        )

    def test_the_refusal_table_is_what_the_gates_actually_do(self):
        # This table was a prose claim about five refusals, and two of them went
        # stale the moment the signing-identity check became step 0: the gate
        # stopped naming missing secrets and started refusing on the team ID.
        # A refusal table is the one place where being confidently wrong is
        # worst, because a reader concludes the rest of the gate was checked.
        rows = self.record_refusal_table()
        self.assertEqual(
            len(rows),
            self.REFUSAL_ROWS,
            f"the refusal table has {len(rows)} rows, not {self.REFUSAL_ROWS}; a row "
            "is missing, or a later table is being read as part of this one",
        )
        record = flat(
            (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            "test_the_refusal_table_is_what_the_gates_actually_do", record
        )

        release = REPO_ROOT / "tools/ci/verify-release-inputs.sh"
        team = "$(ROVIA_TEAM_ID)"

        # Row 1: the full run refuses on the signing identity, before secrets.
        with self.subTest(row="release inputs, full run"):
            result = gate.run_script(release, "--tag", "v0.1.0")
            self.assertEqual(result.returncode, 1, gate.combined(result))
            self.assertIn(team, result.stderr)
            self.assertIn("refusing before any readiness check", result.stderr)
            self.assertNotIn(
                "required signing secret", result.stderr,
                "the secret check must not be reached while the team ID is unresolved",
            )
            row = next(v for k, v in rows.items() if "verify-release-inputs.sh --tag" in k)
            self.assertIn("$(ROVIA_TEAM_ID)", row)
            self.assertIn("signing identity", row)

        # Row 2: the same refusal for --check-secrets-only, so the recorded
        # "all signing secrets are present" cannot be read as this repository's
        # behaviour.
        with self.subTest(row="release inputs, secrets only"):
            result = gate.run_script(release, "--check-secrets-only")
            self.assertEqual(result.returncode, 1, gate.combined(result))
            self.assertIn(team, result.stderr)
            self.assertNotIn("all signing secrets are present", result.stdout + result.stderr)
            row = next(
                v for k, v in rows.items()
                if "--check-secrets-only` against this repository" in k
            )
            self.assertIn("not** reachable here", row)
            self.assertIn("no team", row)

        # Row 3: the readiness message is reachable only with a literal team.
        with self.subTest(row="readiness needs a literal team"):
            environment = {
                "ROVIA_EXPORT_OPTIONS": str(self.fixture_export_options()),
            }
            environment.update(
                {
                    "ROVIA_KEYCHAIN_PASSWORD": "placeholder",
                    "ROVIA_IOS_DIST_CERT_BASE64": "placeholder",
                    "ROVIA_IOS_DIST_CERT_PASSWORD": "placeholder",
                    "ROVIA_IOS_APP_PROFILE_BASE64": "placeholder",
                    "ROVIA_IOS_TUNNEL_PROFILE_BASE64": "placeholder",
                }
            )
            result = gate.run_script(
                release, "--check-secrets-only", environment=environment
            )
            self.assertEqual(result.returncode, 0, gate.combined(result))
            self.assertIn("all signing secrets are present", result.stdout)
            row = next(
                v for k, v in rows.items()
                if "against a root whose `ExportOptions.plist`" in k
            )
            self.assertIn("all signing secrets are present", row)
            self.assertIn("only in the test fixture", row)

        # Row 4: the preflight's own refusal.
        with self.subTest(row="export options preflight"):
            result = gate.run_script(REPO_ROOT / "tools/release/verify-export-options.sh")
            self.assertEqual(result.returncode, 1, gate.combined(result))
            self.assertIn(f"unresolved teamID: {team}", result.stderr)
            row = next(
                v for k, v in rows.items() if "verify-export-options.sh" in k
            )
            self.assertIn("unresolved teamID", row)

        # Row 5: the engine build refusal.
        with self.subTest(row="engine build"):
            result = gate.run_script(
                REPO_ROOT / "tools/build-engine/xray/build-apple.sh",
                "--lock", str(REPO_ROOT / "engines.lock.json"),
            )
            self.assertEqual(result.returncode, 1, gate.combined(result))
            self.assertIn("No approved Xray lock entry is available", result.stderr)
            row = next(
                v for k, v in rows.items() if "build-apple.sh" in k
            )
            self.assertIn("No approved Xray lock entry is available", row)

        # Row 6: the engine checksum verifier in release mode.
        with self.subTest(row="engine release mode"):
            result = gate.run_script(
                REPO_ROOT / "tools/ci/verify-engine-checksums.sh",
                "--mode", "release", "--lock", str(REPO_ROOT / "engines.lock.json"),
            )
            self.assertEqual(result.returncode, 1, gate.combined(result))
            self.assertIn("the engine lock enables none", result.stderr)
            row = next(
                v for k, v in rows.items() if "verify-engine-checksums.sh --mode release" in k
            )
            self.assertIn("the engine lock enables none", row)

        # Row 7: the engine reproducibility verifier.
        with self.subTest(row="verify-xray"):
            result = gate.run_script(
                REPO_ROOT / "tools/reproducibility/verify-xray.sh"
            )
            self.assertEqual(result.returncode, 1, gate.combined(result))
            self.assertIn(
                "No approved Xray artifact exists", result.stderr
            )
            self.assertIn("refusing to claim reproducibility", result.stderr)
            row = next(v for k, v in rows.items() if "verify-xray.sh" in k)
            self.assertIn("No approved Xray artifact exists", row)
            self.assertIn("refusing to claim reproducibility", row)

        # Every row is derived: the count of rows and the count of subtests
        # above have to agree, so "every row" cannot quietly become "most rows".
        self.assertEqual(self.REFUSAL_ROWS, 7)

    def fixture_export_options(self):
        """A throwaway export options plist holding a literal team ID."""
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        path = directory / "ExportOptions.plist"
        path.write_bytes(
            plistlib.dumps(
                {"method": "app-store", "teamID": "A1B2C3D4E5", "stripSwiftSymbols": True}
            )
        )
        return path

    def test_security_policy_points_at_the_document_that_lists_external_gates(self):
        pointer = next(
            line
            for line in self.security.splitlines()
            if "external gates" in line.lower()
        )
        for path in re.findall(r"`(docs/[^`]+)`", pointer):
            with self.subTest(path=path):
                self.assertTrue((REPO_ROOT / path).is_file(), f"{path} does not exist")
        ci = (REPO_ROOT / "docs/development/ci.md").read_text(encoding="utf-8")
        for external_gate in (
            "Signing, provisioning, archive, and export",
            "A physical-device VPN",
            "A production engine",
            "Branch protection",
            "Upstream SPDX tooling",
        ):
            with self.subTest(gate=external_gate):
                self.assertIn(
                    external_gate, ci, f"{external_gate} is not listed as an open external gate"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
