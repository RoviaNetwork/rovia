"""Thematic split of the former tools/ci/test_ci_checks.py.

Shared fixtures and loaders live in ci_check_support.py; this file
holds ChangelogShapeTests.
"""
import re
import unittest

import ci_check_support
from ci_check_support import (
    DATED_SUMMARY_MARKER,
    PASS_SECTION_NARRATIVE,
    RECORD,
    REPO_ROOT,
    dated_summary_sections,
    flat,
    owner_of,
    pass_sections,
    read_record,
    record_replaced,
    record_section_subjects,
    record_sections,
    run_one,
)


class ChangelogShapeTests(unittest.TestCase):
    """The changelog's structure, so a merge cannot quietly produce a second one.

    A duplicated `### Added` heading and a blank line inside a bullet list are both
    invisible in a rendered diff and both make the file harder to trust: a reader
    cannot tell which section a change belongs to. The changelog is the one
    document whose shape is part of its meaning, so its shape is checked.

    No heading name is required, so a future release may add sections freely. What
    is required is that each section name appears once, that the sections are in
    order of first appearance, and that no bullet list is split by a blank line.
    """

    def changelog(self):
        return (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    # Every pass section the record holds, both the narrative ones and the dated
    # summaries, as subjects with the marker stripped. The comparison is in both
    # directions: a section removed fails, and a section added fails until it is
    # listed here. The previous list held only the four dated summaries, so the
    # narrative pass sections were not pinned at all and a new one could be appended
    # without anything noticing.
    EXPECTED_PASS_SECTIONS = (
        "Second remediation pass",
        "Third remediation pass",
        "Fourth remediation pass",
        "Fifth remediation pass",
        "Thirteenth remediation pass — a false reproducibility claim, and four reconciliations",
        "Fourteenth remediation pass — five documents that had drifted from the tree",
        "Release, provenance, security, and ownership remediation",
        "Lint-gate count and count-completeness remediation",
        "Working-directory, derivation and changelog-shape remediation",
        "Runtime-pattern anchoring and changelog coverage",
        "Publication pass — an open-source repository",
    )

    def test_every_expected_pass_section_is_still_in_the_record(self):
        """The reverse direction: a pass section cannot simply be deleted.

        The changelog-per-pass check reads the record to find out which passes it
        owes an entry for, so deleting a pass section made its own obligation
        disappear and everything still passed — the check could not fail on the
        one edit it exists to catch. The passes are pinned here, the way the
        release dated summary already is, so a removal is a failure rather than a
        quieter requirement.

        A new pass has to be added to this list. That is a deliberate cost: adding
        a pass to the record without adding it here fails, which is the direction
        that was missing.
        """
        present = record_section_subjects()
        missing = [
            expected
            for expected in self.EXPECTED_PASS_SECTIONS
            if expected not in present
        ]
        self.assertEqual(
            [], missing,
            "these pass sections are no longer in the record, so their changelog "
            f"entries are now orphans and the record is shorter than it was: {missing}",
        )
        # The other direction, which is what makes the list a gate on additions: a
        # pass section in the record that this list does not name, whether a dated
        # summary titled without the word "remediation" or a narrative pass, has no
        # changelog entry required behind it until the list is updated.
        present_subjects = [
            heading[: -len(DATED_SUMMARY_MARKER)]
            if heading.endswith(DATED_SUMMARY_MARKER)
            else heading
            for heading in pass_sections()
        ]
        unpinned = [
            subject
            for subject in present_subjects
            if subject not in self.EXPECTED_PASS_SECTIONS
        ]
        self.assertEqual(
            [], unpinned,
            "these pass sections are in the record but not in "
            "EXPECTED_PASS_SECTIONS, so nothing requires a changelog entry for "
            f"them: {unpinned}",
        )

    def test_every_changelog_entry_for_a_pass_has_a_pass_section_behind_it(self):
        """The other direction: an entry with nothing behind it is a failure.

        The entry is not what a reader is sent to; the record is. An entry for a
        pass the record no longer describes points at nothing, and the
        per-pass check cannot see it because it starts from the record. So the
        orphan is caught from the other end, by requiring that a pass subject
        named in the changelog still has a section in the record.
        """
        record = flat(
            (REPO_ROOT / "docs/development/foundation-verification.md").read_text(
                encoding="utf-8"
            )
        )
        # The record must still hold each pinned pass subject in full. If it does
        # not, the changelog entries written for that pass are naming something
        # the record no longer describes, which is the orphan the per-pass check
        # cannot see: it starts from the record, so a missing section removes the
        # requirement rather than breaking it.
        for expected in self.EXPECTED_PASS_SECTIONS:
            nouns = [
                word
                for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", expected)
                if word.lower() not in {"and", "remediation", "count"}
            ]
            self.assertTrue(nouns, f"{expected!r} has no distinctive noun")
            if not all(noun.lower() in record.lower() for noun in nouns):
                with self.subTest(pass_section=expected):
                    # Expected: the record does not hold it, so the changelog
                    # entries naming it are orphans and this must be reported
                    # rather than tolerated.
                    self.fail(
                        f"the record no longer contains {expected!r} in full, so "
                        "the changelog entries naming it point at nothing"
                    )

    def test_appending_a_section_fails_the_check_that_owns_each_property(self):
        """Three mutations, each against the check that owns that property.

        The detection used to filter headings by name, so a dated summary whose title
        omitted "remediation" was not found and appending one passed silently. And the
        pinned list held only the dated summaries, so a narrative pass section had no
        entry behind it either.

        Each mutation is applied to a copy of the record through the same seam the other
        record checks use, and only the check that owns the property is required to
        fail:

        - a dated summary titled without "remediation", and a narrative pass section,
          must fail the pinned-list check, in both directions — present-but-unlisted
          is an addition the list does not know about;
        - a section that is neither must fail the check that the record's last section
          is a dated summary, since a pass appended without a summary breaks it.

        Stated as a limit rather than claimed: the changelog-per-pass check is not
        required to fail here. It matches a pass subject to the changelog by its
        distinctive words, and a new title can share those with an existing entry, so
        it is a second requirement on a pass, not the one that gates its addition.
        """
        original = (REPO_ROOT / RECORD).read_text(encoding="utf-8")
        pinned = "test_every_expected_pass_section_is_still_in_the_record"
        last_section = "test_the_in_repo_record_carries_the_release_and_security_remediation"
        mutations = {
            "a dated summary titled without the word remediation": (
                pinned,
                "\n### Coverage of the packaging scripts — dated summary\n\n"
                "Date: 2026-09-26\n\nBody.\n",
            ),
            "a narrative pass section": (
                pinned,
                "\n### Fifteenth remediation pass — something new\n\nBody.\n",
            ),
            "a section that is neither a narrative pass nor a dated summary": (
                last_section,
                "\n### Working tree\n\nBody.\n",
            ),
        }
        for label, (check, addition) in mutations.items():
            with self.subTest(append=label):
                with record_replaced(RECORD, original + addition):
                    self.assertFalse(
                        run_one(owner_of(check), check),
                        f"appending {label} did not fail {check}",
                    )
        # And the record as it stands passes both, so the failures above were the
        # mutations and not checks that always fail.
        for check in (pinned, last_section):
            with self.subTest(unmutated=check):
                self.assertTrue(
                    run_one(owner_of(check), check),
                    f"{check} fails against the record as it stands",
                )

    def test_a_hyphenated_ordinal_pass_section_inserted_mid_document_fails(self):
        r"""A narrative pass, inserted in the middle, must be caught — and by the pinned list.

        Raw, because this docstring quotes the old pattern and `\w` is not a valid
        escape in a non-raw string: on 3.12+ that is a SyntaxWarning and is scheduled
        to become a SyntaxError, which would stop this module importing and take the
        pinned-list and ordinal-pattern gates down with it. The warnings-as-errors
        gate added for it is in `check-python-warnings.sh`.

        The pattern read the ordinal as `\w+`, and `\w` excludes the hyphen, so
        "Twenty-second remediation pass" was not a pass section to it. Appending one
        mid-document was then detected by nothing: not the pass list, not the pinned
        list, and not the last-`###` invariant, which only looks at the end of the
        document.

        The last-section invariant is explicitly shown *not* to be what catches it —
        the mutation leaves the last section a dated summary, so if only that check
        responded the test would pass for the wrong reason. The pinned list is the
        check required to fail.
        """
        original = read_record(RECORD, flatten=False)
        lines = original.splitlines(keepends=True)
        anchor = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("### Fourth remediation pass")
        )
        insertion = (
            "### Twenty-second remediation pass — an ordinal with a hyphen\n\nBody.\n\n"
        )
        mutated = "".join(lines[:anchor]) + insertion + "".join(lines[anchor:])

        # Not the invariant under test: the document's last section is untouched.
        self.assertTrue(
            record_sections(mutated)[-1].endswith(DATED_SUMMARY_MARKER),
            "the mutation changed the last section, so the last-section invariant "
            "could be what catches it",
        )
        self.assertTrue(
            any("Twenty-second" in heading for heading in pass_sections(mutated)),
            "the hyphenated ordinal is still not a pass section to the pattern",
        )

        pinned = "test_every_expected_pass_section_is_still_in_the_record"
        last_section = (
            "test_the_in_repo_record_carries_the_release_and_security_remediation"
        )
        with record_replaced(RECORD, mutated):
            self.assertFalse(
                run_one(owner_of(pinned), pinned),
                "inserting a hyphenated narrative pass did not fail the pinned list",
            )
            # The last-section invariant passes here, which is the point: this
            # mutation is caught by the pinned list alone.
            self.assertTrue(
                run_one(owner_of(last_section), last_section),
                "the last-section invariant was not supposed to catch this",
            )

    def test_a_non_pass_section_inserted_mid_document_still_passes(self):
        """The other direction, for the same insertion.

        If anything shaped like "something something remediation pass" were treated as
        a pass, the pinned list would demand a changelog entry for a section that is
        not one. So the negative cases are required to be left alone.
        """
        original = read_record(RECORD, flatten=False)
        lines = original.splitlines(keepends=True)
        anchor = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("### Fourth remediation pass")
        )
        pinned = "test_every_expected_pass_section_is_still_in_the_record"
        for title in (
            "Not-a-pass remediation pass",
            "A remediation pass",
            "Second remediation passage",
            "What this pass cost",
            "How to read a remediation pass",
        ):
            with self.subTest(section=title):
                mutated = (
                    "".join(lines[:anchor])
                    + f"### {title}\n\nBody.\n\n"
                    + "".join(lines[anchor:])
                )
                self.assertFalse(
                    any(title in heading for heading in pass_sections(mutated)),
                    f"{title!r} is treated as a pass section",
                )
                with record_replaced(RECORD, mutated):
                    self.assertTrue(
                        run_one(owner_of(pinned), pinned),
                        f"a non-pass section titled {title!r} failed the pinned list",
                    )

    def test_the_case_insensitive_flag_is_what_keeps_the_record_sections_found(self):
        """The flag is load-bearing, and this is the dependency the comment names.

        The pattern lists its ordinals in lower case and the record capitalises them —
        "Second remediation pass" — so the compile is case-insensitive. Nothing said
        so. Remove the flag and the pattern matches no section in this record, every
        narrative pass drops out of the pass list, and nothing fails: the pinned
        comparison is satisfied by the sections it still finds, and the last-`###`
        invariant only ever looked at the end. A pass would then be in the record,
        absent from the list, and the gates would be green.

        So the flag is removed here and the disappearance is required. The first
        version of this test also asserted that lower-casing the record changes
        nothing, which is false: the pinned list holds the capitalised subjects, so a
        lower-cased title fails that comparison — a second, independent coupling,
        which this states rather than denies.
        """
        original = read_record(RECORD, flatten=False)
        with_flag = {
            heading
            for heading in pass_sections(original)
            if heading[0].isupper() and heading.lower().endswith("remediation pass")
        }
        self.assertGreaterEqual(
            len(with_flag), 1,
            "the record holds no capitalised narrative pass section, so this check "
            "is vacuous",
        )
        pattern = PASS_SECTION_NARRATIVE
        try:
            ci_check_support.PASS_SECTION_NARRATIVE = re.compile(
                pattern.pattern, pattern.flags & ~re.IGNORECASE
            )
            without_flag = {
                heading
                for heading in pass_sections(original)
                if heading[0].isupper() and heading.lower().endswith("remediation pass")
            }
        finally:
            ci_check_support.PASS_SECTION_NARRATIVE = pattern
        # Not an equality between the two: the whole point is that they differ, and
        # removing the flag must leave the capitalised sections invisible. The first
        # version of this test asserted they were equal, which is the opposite of the
        # dependency and made it fail for the right reason at the wrong line.
        self.assertEqual(
            set(), without_flag,
            f"the lower-case pattern still found {sorted(without_flag)} among the "
            f"record's capitalised sections {sorted(with_flag)}, so removing the "
            "flag did not take and the dependency is not held",
        )
        self.assertTrue(
            with_flag, "the record holds no capitalised narrative pass section"
        )
        # And the record's capitalisation is a real fact, not an accident of this
        # run: it is what the comment cites as the reason for the flag.
        for heading in with_flag:
            with self.subTest(section=heading[:34]):
                self.assertTrue(
                    heading[0].isupper(),
                    f"{heading!r} does not begin with a capital, so the comment's "
                    "reason for the case-insensitive flag does not hold for it",
                )

    def test_every_dated_pass_section_has_a_changelog_entry(self):
        """The changelog cannot skip a pass the record dates.

        The record's dated pass sections are the summary of what a review is
        supposed to have changed. A pass recorded there and absent from the
        changelog is a pass nobody reading release notes would find, and the
        omission is invisible: nothing in either file contradicts the other.

        Matching is by the pass's own subject rather than by its heading, so
        renaming a section does not silently satisfy or break the requirement.
        """
        # Through the seam, so a mutation test can append a pass section to this
        # record and require this check to fail. Reading the file here is why the
        # first version of that test saw a record with no appended section.
        dated = dated_summary_sections()
        self.assertTrue(
            dated, "the record has no dated pass section, so this check is vacuous"
        )
        changelog = flat(self.changelog()).lower()
        missing = []
        for heading in dated:
            subject = heading[: -len(DATED_SUMMARY_MARKER)]
            # The distinctive words of the subject, longest first, with the
            # connective words dropped: "Release, provenance, security, and
            # ownership remediation" has to be found from its nouns.
            words = [
                word
                for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", subject)
                if word.lower() not in {"and", "remediation"}
            ]
            self.assertTrue(
                words, f"{heading!r} has no distinctive word to look for"
            )
            # Every one of the subject's words, not a majority and not any one.
            # "Any" was satisfied by an earlier entry sharing a single word, and
            # "a majority" by an entry that kept two of three, so a partial
            # deletion of an entry passed. All of them means an entry has to
            # describe the whole pass or the check objects.
            absent = [word for word in words if word.lower() not in changelog]
            if absent:
                missing.append(f"{heading} (the changelog never says {absent})")
        self.assertEqual(
            [], missing,
            "these dated pass sections have no changelog entry: " + "; ".join(missing),
        )

    def test_no_section_name_appears_twice(self):
        headings = re.findall(r"(?m)^#{2,3} (.+)$", self.changelog())
        with self.subTest(headings=headings):
            repeated = sorted({h for h in headings if headings.count(h) > 1})
            self.assertEqual(
                [], repeated,
                f"the changelog repeats these sections, so a change lands in a "
                f"section the reader cannot find: {repeated}",
            )

    def test_no_bullet_list_is_split_by_a_blank_line(self):
        # A blank line between two bullets of the same list makes a renderer treat
        # them as two lists, which is how a list silently becomes two sections.
        lines = self.changelog().splitlines()
        offenders = []
        previous = None
        for index, line in enumerate(lines, 1):
            if line.startswith("- ") or line.startswith("  ") and line.strip():
                if previous == "" and lines[index - 3].strip().startswith(("- ", "  ")):
                    offenders.append(index)
                previous = "bullet"
            elif line.strip():
                previous = "text"
            else:
                previous = ""
        self.assertEqual(
            [], offenders,
            "these lines are bullets that follow a blank line, splitting one list "
            f"into two: {offenders}",
        )

    def test_a_section_heading_is_followed_by_its_own_bullets(self):
        # The complement of the check above: a `###` section is immediately
        # followed by a bullet, not by prose or by a nested heading. `## Unreleased`
        # is a release heading and is legitimately followed by a `###`, so only
        # third-level headings are checked.
        body = self.changelog()
        for heading in re.finditer(r"(?m)^(### .+)$", body):
            after = body[heading.end():].lstrip("\n")
            first = after.splitlines()[0] if after.strip() else ""
            with self.subTest(heading=heading.group(1)):
                self.assertTrue(
                    first.startswith("- "),
                    f"{heading.group(1)} is followed by {first[:40]!r} rather than a "
                    "bullet, so its first item is separated from the rest",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
