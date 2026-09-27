#!/usr/bin/env python3
"""Write the README's derived figures between its markers, or check them.

The README states how many tests exist. A number in prose is a number somebody has to
remember to bump, and this repository has a long record of exactly that failure: a
count in a document quietly going stale while every test stayed green. So the README's
counts are generated here from the same loaders the test suite uses, and
`tools/ci/test_ci_checks.py` holds the committed text against them.

Two modes:

    update-readme-counts.py            rewrite the block between the markers
    update-readme-counts.py --check    exit 1 if it is not what the loaders say

The Swift figures are read by counting the tests in the sources rather than by running
`swift test`, for the same reason `test_ci_checks.py` counts them: a count that comes
from a run is only as good as the run, and a count that comes from the source is
checkable without a toolchain. The hosted CI run is the evidence that those tests
actually execute and pass, and the badge says so.
"""

import argparse
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

START = "<!-- counts:start -->"
END = "<!-- counts:end -->"

# The app test target's sources, as the Xcode project lists them. A name is read from
# the project's own sources phase rather than hardcoded, so a file added to the target
# is counted by the same rule that compiles it.
APP_TEST_DIR = REPO_ROOT / "client" / "app" / "ios" / "RoviaAppTests"


def swift_test_methods(directory):
    """Count `func test…` declarations under a directory."""
    if not directory.is_dir():
        return 0
    pattern = re.compile(r"^\s*func\s+(test\w*)\s*\(", re.M)
    return sum(
        len(pattern.findall(path.read_text(encoding="utf-8")))
        for path in sorted(directory.rglob("*.swift"))
    )


def package_totals():
    """package path -> test count, for every entry in the shared package list."""
    listing = REPO_ROOT / "tools" / "ci" / "local-packages.txt"
    totals = {}
    for line in listing.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        totals[line] = swift_test_methods(REPO_ROOT / line / "Tests")
    return totals


def tool_test_totals():
    """test file -> test count, loaded the way the runner runs them."""
    totals = {}
    for path in sorted((REPO_ROOT / "tools").rglob("test_*.py")):
        loader = unittest.defaultTestLoader
        suite = loader.discover(
            str(path.parent), pattern=path.name, top_level_dir=str(path.parent)
        )
        totals[str(path.relative_to(REPO_ROOT))] = suite.countTestCases()
    return totals


def figures():
    packages = package_totals()
    tools = tool_test_totals()
    return {
        "swift_packages": len(packages),
        "swift_tests": sum(packages.values()),
        "app_tests": swift_test_methods(APP_TEST_DIR),
        "tool_files": len(tools),
        "tool_tests": sum(tools.values()),
    }


def block(values):
    total = values["swift_tests"] + values["app_tests"] + values["tool_tests"]
    rows = [
        f"| Swift packages (`tools/ci/local-packages.txt`) | {values['swift_packages']} | {values['swift_tests']} |",
        f"| iOS app model (`RoviaAppTests`) | 1 | {values['app_tests']} |",
        f"| Tooling gates (`tools/**/test_*.py`) | {values['tool_files']} | {values['tool_tests']} |",
        f"| **Total** | | **{total}** |",
    ]
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the README is not what the loaders say",
    )
    arguments = parser.parse_args(argv)

    if not README.is_file():
        sys.stderr.write(f"update-readme-counts: {README} does not exist\n")
        return 1

    values = figures()
    replacement = f"{START}\n{block(values)}\n{END}"

    text = README.read_text(encoding="utf-8")
    begin = text.find(START)
    finish = text.find(END)
    if begin == -1 or finish == -1 or finish < begin:
        sys.stderr.write(
            f"update-readme-counts: {README} has no {START} … {END} block\n"
        )
        return 1

    current = text[begin:finish + len(END)]
    if arguments.check:
        if current != replacement:
            sys.stderr.write(
                "update-readme-counts: the README's figures are not what the "
                "loaders report. Run update-readme-counts.py and commit the result.\n"
            )
            return 1
        sys.stdout.write("update-readme-counts: the README is current\n")
        return 0

    if current == replacement:
        sys.stdout.write("update-readme-counts: the README is already current\n")
        return 0

    README.write_text(
        text[:begin] + replacement + text[finish + len(END):], encoding="utf-8"
    )
    sys.stdout.write(f"update-readme-counts: updated {README.relative_to(REPO_ROOT)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
