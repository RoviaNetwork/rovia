#!/usr/bin/env python3
"""Write the verification record's derived suite figures, or check them.

The record in `docs/development/foundation-verification.md` states how many tests each
tool suite holds and what they total. Those numbers were being re-derived by hand after
every pass, and hand-derivation is where this repository has repeatedly gone wrong: a
careful regular expression once rewrote a *historical* before/after table, replacing a
figure that pass had measured with today's, which is exactly the mistake the record
itself warns about three paragraphs earlier.

So the numbers are written here, from the same loaders the suite uses, and the
historical tables are explicitly left alone. Two modes:

    update-record-counts.py            rewrite the derived figures
    update-record-counts.py --check    exit 1 if the committed text disagrees

What is written:

  * one row per `tools/**/test_*.py` file, in the per-suite table
  * the "N files, M tests, 0 failures" summary line
  * the `After` column of the *last* before/after table, which is the live one

What is not written, and why:

  * every earlier before/after table. Its "before" describes a tree that has since
    moved, and its "after" is what that pass measured then. Rewriting them would turn a
    record into a copy of the present.
  * the per-suite seconds column. That is one observation from one run, and the record
    says so; a figure that is neither derived nor a measurement should not exist.
"""

import argparse
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD = REPO_ROOT / "docs/development/foundation-verification.md"

# A per-suite row, read by splitting into cells rather than by one pattern.
#
# The first version used a single regex that required three columns, so once a bad
# write stripped the runtime cell the row stopped matching: the updater then reported
# "already current" on every run while the count it printed was two tests stale, and
# the runtime the prose refers to had silently stopped existing. Splitting the cells
# makes a short row a thing it repairs rather than a thing it cannot see.
SUITE_CELL = re.compile(r"^`(tools/[^`]+\.py)`$")
BEFORE_AFTER = re.compile(r"^\| Tool tests \| (\d+) \| (\d+) \|$")


def suite_counts():
    """test file path -> test count, loaded the way the runner runs them."""
    totals = {}
    for path in sorted((REPO_ROOT / "tools").rglob("test_*.py")):
        suite = unittest.defaultTestLoader.discover(
            str(path.parent), pattern=path.name, top_level_dir=str(path.parent)
        )
        totals[str(path.relative_to(REPO_ROOT))] = suite.countTestCases()
    return totals


def suite_runtimes():
    """Observed runtimes from the record's own table, so they survive a rewrite."""
    text = RECORD.read_text(encoding="utf-8")
    runtimes = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or not SUITE_CELL.match(cells[0]):
            continue
        if len(cells) >= 3 and cells[2]:
            runtimes[SUITE_CELL.match(cells[0]).group(1)] = cells[2]
    return runtimes


def last_before_after_index(lines):
    """Index of the last before/after `Tool tests` row: the one that is live."""
    indices = [
        index for index, line in enumerate(lines) if BEFORE_AFTER.match(line.strip())
    ]
    if not indices:
        raise SystemExit("update-record-counts: the record has no before/after table")
    return indices[-1]


def apply(counts, runtimes=None):
    """Return the updated text and the list of changed lines.

    `runtimes` is read back out of the record itself so a rewrite preserves the
    observed figures; the updater never invents one, and marks a row as not measured
    when the column is missing.
    """
    text = RECORD.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    total = sum(counts.values())
    files = len(counts)
    live = last_before_after_index(lines)

    changed = []
    missing_runtime = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        # The terminator is read from the line itself, not from a stripped copy.
        # `bare.endswith("\n")` where `bare` is the result of `rstrip("\n")` is
        # always False, so the first version of this script wrote rows back without
        # their newline and glued the next row onto them - which is how the record
        # briefly carried "| Tool tests | 364 | 614 || Security-sensitive paths …".
        terminator = "\n" if line.endswith("\n") else ""

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        suite = SUITE_CELL.match(cells[0]) if cells else None
        if suite and suite.group(1) in counts and len(cells) >= 2:
            name = suite.group(1)
            # Keep the observed runtime when the row still has one, and say so plainly
            # when it does not rather than inventing a figure that was never measured.
            runtime = cells[2] if len(cells) >= 3 and cells[2] else None
            if runtime is None:
                missing_runtime.append(name)
                updated = f"| `{name}` | {counts[name]} | not measured |"
            else:
                updated = f"| `{name}` | {counts[name]} | {runtime} |"
            if updated != stripped:
                changed.append((index, stripped, updated))
                lines[index] = updated + terminator
            continue

        if index == live:
            updated = f"| Tool tests | 364 | {total} |"
            if updated != stripped:
                changed.append((index, stripped, updated))
                lines[index] = updated + terminator

    updated_text = "".join(lines)
    updated_text = re.sub(
        r"\*\*\d+ files, \d+ tests, 0 failures\*\*",
        f"**{files} files, {total} tests, 0 failures**",
        updated_text,
    )
    if missing_runtime:
        print(
            "update-record-counts: these suites have no recorded runtime and are "
            "marked as not measured: " + ", ".join(sorted(missing_runtime)),
            file=sys.stderr,
        )
    return updated_text, changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the record disagrees with the loaders",
    )
    parser.add_argument(
        "--show", action="store_true", help="print each change instead of writing it"
    )
    arguments = parser.parse_args(argv)

    if not RECORD.is_file():
        sys.stderr.write(f"update-record-counts: {RECORD} does not exist\n")
        return 1

    counts = suite_counts()
    updated, changed = apply(counts, runtimes=suite_runtimes())

    if arguments.show:
        for index, before, after in changed:
            print(f"line {index + 1}:\n  - {before}\n  + {after}")
        return 0

    if arguments.check:
        if updated != RECORD.read_text(encoding="utf-8"):
            sys.stderr.write(
                "update-record-counts: the record's suite figures are not what the "
                "loaders report. Run update-record-counts.py and commit the result.\n"
            )
            for index, before, after in changed:
                sys.stderr.write(f"  line {index + 1}: {after}\n")
            return 1
        sys.stdout.write("update-record-counts: the record is current\n")
        return 0

    if updated == RECORD.read_text(encoding="utf-8"):
        sys.stdout.write("update-record-counts: the record is already current\n")
        return 0

    RECORD.write_text(updated, encoding="utf-8")
    sys.stdout.write(
        f"update-record-counts: updated {RECORD.relative_to(REPO_ROOT)} "
        f"({len(counts)} files, {sum(counts.values())} tests, {len(changed)} lines)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
