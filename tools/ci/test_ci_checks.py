#!/usr/bin/env python3
"""Tests for the CI plumbing scripts added with the hardening work.

Both scripts exist so CI and a developer laptop run the same command:

* check-shell-syntax.sh refuses a repository whose shell scripts do not parse,
  because a syntax error in a gate is a gate that never runs.
* verify-bundle-metadata.sh refuses a processed bundle whose Info.plist still
  contains build variables, whose extension is missing, or whose versions are
  not usable, because "the build succeeded" is not evidence of a valid bundle.

The bundle checks run against synthetic bundles built here, so the refusals are
permanent rather than a one-time manual observation.
"""

from __future__ import annotations

import ast
import contextlib
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

REPO_ROOT = Path(__file__).resolve().parents[2]
# The version `check-python-lint.sh` pins, read from the gate rather than
# repeated, so this test cannot drift from the gate it is describing.
PYFLAKES_VERSION = re.search(
    r'PYFLAKES_VERSION="([0-9.]+)"',
    (REPO_ROOT / "tools/ci/check-python-lint.sh").read_text(encoding="utf-8"),
).group(1)
sys.path.insert(0, str(REPO_ROOT / "tools/ci"))

import script_test_support as gate  # noqa: E402

def pyflakes_argv():
    """The argv that runs the pinned pyflakes, the same way the lint gate does.

    `tools/ci/check-python-lint.sh` resolves the linter through the interpreter when
    `pyflakes` is importable and falls back to `uvx pyflakes==<pin>` otherwise, because
    a GitHub-hosted macOS runner has no `uvx`: the first hosted CI run failed with
    `FileNotFoundError: [Errno 2] No such file or directory: 'uvx'`, which is a linter
    that could not run looking exactly like a clean tree.

    Anything else in this module that shells out to the linter has to come through
    here. A test called `uvx` directly and failed on the runner for the same reason the
    gate did, one call site after the gate had been fixed - the lesson being that a
    dependency fixed in one place is only fixed in one place.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import pyflakes"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "pyflakes"]
    return ["uvx", f"pyflakes=={PYFLAKES_VERSION}"]


def flat(text: str) -> str:
    """Collapse whitespace, so a phrase survives being wrapped by a formatter."""
    return re.sub(r"\s+", " ", text)


# The five limits the app-dependency gate states in its own docstring, quoted
# from there so a test failure points at the gate rather than at a copy of the
# sentence that has drifted away from it.
GATE_LIMITS = (
    "An operator overload is not detected",
    "A matcher that avoids every signal passes",
    "A stored `RuleEvaluation` is not flagged",
    "Swift is not parsed",
    "It reads the repository, not the build",
)

# What each document that repeats those limits has to say, in its own words.
# `ci.md` states three of them and points at the docstring for the rest;
# `ios.md` and the changelog state all five in prose.
DOCUMENT_LIMITS = {
    "docs/development/ci.md": (
        "it reads declarations and bodies rather than Swift",
        "an operator overload is invisible to it",
        "a determined rewrite that avoids every signal is invisible too",
    ),
    "docs/development/ios.md": (
        "an operator overload is not a declaration it finds",
        "is not visible to it",
        "A stored `RuleEvaluation` is deliberately allowed",
        "reads the repository, not the build",
    ),
    "CHANGELOG.md": (
        "it reads declarations and bodies, not Swift",
        "a stored `RuleEvaluation` is deliberately allowed",
        "it reads the repository rather than the build",
    ),
}
from script_test_support import (  # noqa: E402
    policy_forbidden_tokens,
    publishing_steps,
    workflow_steps,
)

SHELL_SCRIPT = REPO_ROOT / "tools/ci/check-shell-syntax.sh"
BUNDLE_SCRIPT = REPO_ROOT / "tools/ci/verify-bundle-metadata.sh"
TAG_SCRIPT = REPO_ROOT / "tools/release/verify-tag.sh"
WORKFLOWS = REPO_ROOT / ".github/workflows"
APP_IDENTIFIER = "io.rovia.client"
TUNNEL_IDENTIFIER = "io.rovia.client.tunnel"
ACTION_PIN = re.compile(r"uses:\s*(\S+)@(\S+)")
SECRET_ENVIRONMENT_NAMES = (
    "ROVIA_KEYCHAIN_PASSWORD",
    "ROVIA_IOS_DIST_CERT_BASE64",
    "ROVIA_IOS_DIST_CERT_PASSWORD",
    "ROVIA_IOS_APP_PROFILE_BASE64",
    "ROVIA_IOS_TUNNEL_PROFILE_BASE64",
)
MARKETING_VERSION = re.compile(r"ROVIA_MARKETING_VERSION:\s*(\S+)")


# ---------------------------------------------------------------------------
# The ten live counts the record states and no test derived.
#
# Each of these was accurate when written and was still accurate when this
# class was added, which is exactly the problem: accuracy is not binding. A
# number nobody reads from its source cannot fail when the source moves, so
# these read each count from the thing it describes and require the documents to
# state what they read. Where a source is not reachable from a unit test the
# count is named as an exempt group in the record instead of being quietly
# dropped.
# ---------------------------------------------------------------------------


# The record, read through one function so a test can be executed against a
# deliberately wrong copy of it. The mutation test below needs to run the ten
# real tests against a record that says something else; without a seam there, the
# only way to mutate one is to edit the file, which is what the test is trying to
# avoid.
_RECORD_OVERRIDE: dict = {}


def read_record(
    name: str = "docs/development/foundation-verification.md", flatten: bool = True
):
    """The record, or an override of it.

    `flatten=False` serves the raw text, for the section readers: they match `^###`,
    which needs a real line start, and flattening removes every newline. Both shapes
    come from the same override, so a mutation test substitutes once and either can be
    run against it.
    """
    if name in _RECORD_OVERRIDE:
        text = _RECORD_OVERRIDE[name]
    else:
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
    return flat(text) if flatten else text


@contextlib.contextmanager
def record_replaced(name: str, text: str):
    """Serve `text` for the record, restoring the real one afterwards."""
    previous = _RECORD_OVERRIDE.get(name)
    _RECORD_OVERRIDE[name] = text
    try:
        yield
    finally:
        if previous is None:
            _RECORD_OVERRIDE.pop(name, None)
        else:
            _RECORD_OVERRIDE[name] = previous


def require_the_count_check_fails(test_name: str, record_text: str) -> None:
    """Run the named real test against a wrong record and require it to fail.

    Raises AssertionError if the test passes, which is the whole point: a count
    check that cannot fail when the document is wrong is not a count check. The
    test is the one that holds the count, named rather than re-implemented here,
    so this cannot drift into checking something the suite does not actually run.
    """
    method = getattr(LiveCountDerivationTests, test_name, None)
    if method is None:
        raise AssertionError(
            f"{test_name} does not exist, so the count it holds is not held at all"
        )
    case = LiveCountDerivationTests(test_name)
    with record_replaced("docs/development/foundation-verification.md", record_text):
        try:
            method(case)
        except AssertionError:
            return
    raise AssertionError(
        f"{test_name} passed against a record that states the wrong count, so the "
        "count it holds is not bound to the document"
    )



def _bound_names(node):
    """The names a statement binds, for the binding shapes that are definitions.

    A `def`, a `class`, an `import`, and an assignment to a name, a tuple, a list
    or a starred target. A loop target, a `with ... as`, and an `except ... as`
    are deliberately absent: binding the same name in two of those is ordinary
    code — two loops over `row`, two handles called `f` — and reporting them would
    make the check fail on correct files until someone widened an exclusion to
    silence it. A second *definition* at the same scope, by contrast, is a name
    that silently changes meaning, which is the bug worth refusing.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(node.name, node.lineno)]
    if isinstance(node, ast.AnnAssign):
        return [
            (child.id, node.lineno)
            for child in ast.walk(node.target)
            if isinstance(child, ast.Name)
        ]
    if isinstance(node, (ast.Assign, ast.AugAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        return [
            (child.id, node.lineno)
            for child in ast.walk(target)
            if isinstance(child, ast.Name)
        ]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [
            (alias.asname or alias.name.split(".")[0], node.lineno)
            for alias in node.names
        ]
    return []


# The documents a suite count may appear in. Every one is swept, not just the
# verification record: a count stated in a second place is a second claim, and the
# count check used to hold only the first form it happened to match.
# How a section of the verification record is found, in one place.
#
# There were three ways to do this and two of them disagreed. One matched `###`
# headings and filtered them by name — "remediation pass" or "remediation — dated
# summary" — so a dated pass section whose title does not say "remediation" was not
# found at all, and the invariant about the last pass section was decided by a
# section that was not last. The other two were structural: one compared every
# heading with a pinned list, the other matched ` — dated summary`.
#
# So: one reader, and every check that needs a section goes through it. A section is
# a `###` heading; a dated pass section is one whose title ends with the marker,
# whatever it is called.
RECORD = "docs/development/foundation-verification.md"
DATED_SUMMARY_MARKER = " — dated summary"


def run_one(case_class, test_name: str) -> bool:
    """Run one named test and report whether it passed.

    Through `TestSuite`, so the case is constructed the way unittest constructs it.
    Calling `CaseClass(name)()` directly does not work for a name that is not on that
    class, which is how two earlier versions of this tried to run a test against a
    method name belonging to a different class and got a `ValueError` from
    `TestCase.__init__` instead of a result.
    """
    result = unittest.TestResult()
    unittest.TestSuite([case_class(test_name)]).run(result)
    if result.errors or result.failures:
        return False
    return not result.skipped


def owner_of(test_name: str):
    """The class that defines a named test, so a mutation test need not hard-code it.

    Hard-coding the owner is how the first version of this test passed a name to the
    wrong class and got `ValueError: no such test method` from `TestCase.__init__`.
    """
    for candidate in vars(sys.modules[__name__]).values():
        if (
            isinstance(candidate, type)
            and issubclass(candidate, unittest.TestCase)
            and test_name in vars(candidate)
        ):
            return candidate
    raise AssertionError(f"no test class defines {test_name}")


def record_sections(document: str | None = None) -> list[str]:
    """Every `###` section title in the verification record, in document order.

    Read through `read_record`, not from the file, so a mutation test can run the
    section checks against a mutated record. Reading the file here bypassed the seam
    and the first version of the mutation test passed because of it.
    """
    if document is None:
        document = read_record(RECORD, flatten=False)
    return re.findall(r"(?m)^### (.+)$", document)


def record_section_subjects(document: str | None = None) -> list[str]:
    """Every section title with the dated-summary marker removed.

    What a pinned list holds: a section's subject, without the marker that says it
    is dated. Two titles differing only by the marker are one subject, and a pinned
    entry is satisfied by either spelling.
    """
    return [
        heading[: -len(DATED_SUMMARY_MARKER)]
        if heading.endswith(DATED_SUMMARY_MARKER)
        else heading
        for heading in record_sections(document)
    ]


def dated_summary_sections(document: str | None = None) -> list[str]:
    """The sections of the record that are dated pass summaries, whatever their title."""
    return [
        heading
        for heading in record_sections(document)
        if heading.endswith(DATED_SUMMARY_MARKER)
    ]


# A narrative pass section is titled "Nth remediation pass" — an ordinal, however it is
# spelled. Read as a shape, like the marker above, and not as a list of words that
# happen to co-occur: the old filter was this shape plus one hard-coded string
# containing the marker, so a dated summary whose title did not say "remediation" was
# not found at all.
#
# The ordinal is matched as an ordinal rather than as `\w+`, because `\w` excludes
# the hyphen: "Twenty-second remediation pass" was not a pass section to this pattern,
# so appending one mid-document was detected by nothing — not this list, not the
# pinned list, and not the last-`###` invariant, which only looks at the end. Widening
# it to `[\w-]+` would fix that and admit any hyphenated word in front, so the
# ordinals are spelled out instead, hyphenated compounds included, and the negative
# cases are tested.
_ORDINAL = (
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth"
    r"|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth"
    r"|seventeenth|eighteenth|nineteenth"
    r"|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:-first|-second|-third|-fourth|-fifth|-sixth|-seventh|-eighth|-ninth)?"
    r"|hundredth|thousandth|millionth)"
)
# Case-insensitive because the record capitalises the ordinal — "Second
# remediation pass" — and a lowercase alternation alone matched none of them.
PASS_SECTION_NARRATIVE = re.compile(
    rf"^(?:{_ORDINAL}|\d+(?:st|nd|rd|th)) remediation pass\b", re.IGNORECASE
)


def pass_sections(document: str | None = None) -> list[str]:
    """The record's pass sections, found by marker rather than by title wording."""
    return [
        heading
        for heading in record_sections(document)
        if heading.endswith(DATED_SUMMARY_MARKER) or PASS_SECTION_NARRATIVE.match(heading)
    ]



SUITE_COUNT_DOCUMENTS = (
    "docs/development/ci.md",
    "docs/development/ios.md",
    "docs/development/foundation-verification.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "PRIVACY.md",
    "docs/security/threat-model.md",
    "docs/legal/app-store-distribution.md",
)

# Claims about a count the record used to state, rather than about the tree now.
# Each is a sentence that reports a past state, and each is required to still be
# present, so this list cannot quietly grow into a place real claims are excused.
HISTORICAL_COUNT_CLAIMS = (
    (
        "docs/development/foundation-verification.md",
        "the record carried `Executed 60 tests, with 0 failures` as a transcript",
    ),
    (
        "docs/development/foundation-verification.md",
        "`Executed 60 tests, with 0 failures` and a test required that literal",
    ),
)


def suite_count_subjects(suite_counts):
    """{subject as a document names it: the counts that are true of it}.

    Takes the suite counts from the caller: they come from a method on the class
    that holds the loader, and a module-level function cannot reach it.

    Nine suite files counted by the loader, the XCTest target counted from its own
    methods, and the two test classes whose counts appear in the record. A subject
    may have more than one true count — `ExportOptionsTests` has its own tests and
    the total the loader discovers for it, the difference being tests inherited from
    a base class — so the acceptable set has one entry per true reading.
    """
    import importlib.util

    subjects = {}
    for suite, count in suite_counts.items():
        subjects[Path(suite).name] = {count}
    subjects["RoviaAppTests"] = {app_test_count()}

    def class_count(module: str, classname: str) -> int:
        spec = importlib.util.spec_from_file_location(
            "subject_" + classname, REPO_ROOT / module
        )
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return unittest.defaultTestLoader.loadTestsFromTestCase(
            getattr(loaded, classname)
        ).countTestCases()

    licences = class_count(
        "tools/reproducibility/test_generate_sbom.py", "EngineLicenseTests"
    )
    subjects["EngineLicenseTests"] = {licences}
    export = class_count(
        "tools/ci/test_verify_release_inputs.py", "ExportOptionsTests"
    )
    inherited = class_count(
        "tools/ci/test_verify_release_inputs.py", "ReleaseInputsTests"
    )
    # Its own tests, and everything the loader discovers for it.
    subjects["ExportOptionsTests"] = {export, max(export - inherited, 0)}
    return subjects



def duplicate_definitions(source: str, filename: str = "<test>"):
    """Names defined more than once at the same scope in one module.

    What counts as "defined" is `_bound_names`: `def`, `class`, `import`, and
    assignments to a name, tuple, list or starred target. Loop targets,
    `with ... as` and `except ... as` are not definitions and are not reported;
    the docstring there says why.

    The gap this exists for is that pyflakes reports a redefined `def`, `class` or
    `import`, but is silent about every rebound assignment. Verified against
    pyflakes 3.2.0, all of these pass it with no output: `X = 1; X = 2` with the
    first value used, `X: int = 1; X: int = 2`, `A, B = 1, 2; A, B = 3, 4`,
    `A = [1]; A = [2]`, a `for A in ...` followed by `A = 3`, and a
    `with ... as A` followed by `A = 3`. The first of those was the shape of the
    three unreferenced `LINT_GATE`/`LINT_VERSION` pairs removed alongside this.

    Reported as (scope, name, first line, second line) so a failure names the
    collision.
    """
    tree = ast.parse(source, filename)

    def walk(body, scope):
        seen, found = {}, []
        for node in body:
            for name, line in _bound_names(node):
                if name in seen:
                    found.append((scope, name, seen[name], line))
                else:
                    seen[name] = line
            if isinstance(node, ast.ClassDef):
                found.extend(walk(node.body, f"{scope}.{node.name}"))
        return found

    return walk(tree.body, filename)


def published_files():
    """Every file git would publish, relative to the repository root.

    `git ls-files --cached --others --exclude-standard` — the same call
    `tools/ci/check-repository-hygiene.sh` makes. A count derived from a walk of the
    working tree is a count about the machine, and this repository has been bitten by
    that twice in one afternoon.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--cached", "--others",
         "--exclude-standard"],
        capture_output=True, text=True, check=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line]


def json_inputs():
    """The JSON files the record's `python3 -m json.tool` line covers.

    Read from the publishable set rather than from a filesystem walk with a
    hand-maintained exclusion list. Two reasons, and the second is the one that
    broke:

      * a walk needs an exclusion list, and an exclusion list is a second, silent copy
        of `.gitignore` that nothing keeps in step with it;
      * a GitHub-hosted runner creates `.ci-schema-validator/` inside the checkout —
        a virtualenv full of JSON files — and the walk counted all of them. The
        third hosted CI run failed with "the record no longer states 'over 38 files'",
        because the count was 38 here and something larger there. The number was never
        wrong about the repository; it was wrong about the machine.

    Adding a JSON file to the repository still moves this, which is the point: the
    record has to absorb it or stop describing it.
    """
    return sorted(path for path in published_files() if path.suffix == ".json")


def json_input_groups():
    """(total, schema count, fixture count) for the record's 38/5/32 line."""
    files = json_inputs()
    schemas = [p for p in files if p.parts[0] == "schemas"]
    fixtures = [p for p in files if p.parts[0] == "fixtures"]
    return len(files), len(schemas), len(fixtures)


def accessibility_identifier_counts():
    """(containers, elements, reaching a view) read from the audit itself.

    The audit prints three counts and exits non-zero on a problem. Parsing its
    own output is the derivation: the numbers it reports are the numbers the
    record must state, so a constant added to the app moves both together.

    `cwd=REPO_ROOT` is kept, though it is no longer what makes this work: the
    audit's `--app` default used to be the relative `client/app/ios/RoviaApp`, and
    resolving it needed a working directory. That default is now resolved from the
    script's own location, so the audit reads the same directory from anywhere. The
    argument stays because the derivation is about *this* repository's app, and
    naming the working directory means the subprocess cannot be pointed at a
    different tree by whatever the caller happens to be doing — the failure being
    guarded against is a count derived from the wrong directory, not a missing
    one. `test_the_accessibility_audit_runs_from_outside_the_repository` covers
    the script itself, which is where the original defect was.
    """
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/ci/audit-accessibility-identifiers.py")],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    counts = {}
    for line in result.stdout.splitlines():
        match = re.match(
            r"(container identifiers|element identifiers|constants reaching a view): (\d+)",
            line.strip(),
        )
        if match:
            counts[match.group(1)] = int(match.group(2))
    if len(counts) != 3:
        raise AssertionError(
            f"the accessibility audit printed {sorted(counts)}, not three counts"
        )
    return (
        counts["container identifiers"],
        counts["element identifiers"],
        counts["constants reaching a view"],
    )


def sbom_component_counts():
    """(components, relationships) from a generated SBOM.

    Generated into a temporary file with both the namespace and the timestamp
    pinned, because the count is a property of the document the generator
    writes and not of the invocation.
    """
    import json as _json

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "sbom.json"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools/reproducibility/generate-sbom.py"),
                str(REPO_ROOT),
                str(output),
                "--namespace-id",
                "rovia-count-derivation",
                "--created",
                "1700000000",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        document = _json.loads(output.read_text(encoding="utf-8"))
    return len(document["packages"]), len(document["relationships"])


def workflow_job_count(text: str) -> int:
    """The number of direct children of the top-level `jobs:` mapping.

    Counted from the mapping's own indentation rather than by matching job-name
    shapes, because a regex over two-space keys also matches a workflow's nested
    mappings — which reported three jobs for `ci.yml`, a workflow with one.
    """
    jobs, inside, base = 0, False, None
    for line in text.splitlines():
        if re.match(r"^[a-z_]+:", line):
            inside = line.rstrip() == "jobs:"
            continue
        if not inside:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if base is None:
            base = indent
        if indent == base and line.rstrip().endswith(":"):
            jobs += 1
        elif indent < base:
            inside = False
    return jobs


def workflow_step_counts():
    """{workflow filename: (jobs, steps)} over every workflow in the tree."""
    counts = {}
    for path in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        counts[path.name] = (workflow_job_count(text), len(workflow_steps(text)))
    return counts


def shell_script_count():
    return len(list((REPO_ROOT / "tools").rglob("*.sh")))


def local_package_manifest_count():
    return sum(
        1
        for relative in local_packages()
        if (REPO_ROOT / relative / "Package.swift").is_file()
    )


def tracked_top_level_count():
    """Top-level entries git tracks, from `git ls-files`.

    This was `untracked_top_level_count`, reading `git status --porcelain` and
    counting `??` lines. That was correct only while the repository had no commits:
    staging the first commit made the number zero and the record's sentence false, and
    after that commit it is zero forever, which makes it a fact about nothing.

    The tracked count is the same kind of claim and survives publication: it is what a
    clone contains, it is the same in a pull-request checkout, and it changes only when
    a file is added or removed, which is the moment a reader would want to know.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return len({line.split("/", 1)[0] for line in result.stdout.splitlines() if line})


def signing_identity_position():
    """(1-based position, total steps) of the signing-identity gate."""
    names = [
        step.name
        for step in workflow_steps(
            (REPO_ROOT / ".github/workflows/release-ios.yml").read_text(encoding="utf-8")
        )
    ]
    return names.index("Require a resolved signing identity") + 1, len(names)


def unexecuted_gate_count():
    """The readiness document's own gate count, read from its rows."""
    document = (REPO_ROOT / "docs/development/release-readiness.md").read_text(encoding="utf-8")
    return len([line for line in document.splitlines() if re.match(r"^\| \d+ \|", line)])


def semantic_probe_negative_count():
    """The validator's negative probe count, from the probe functions."""
    import importlib.util
    import json as _json

    path = REPO_ROOT / "tools/ci/validate-schemas.py"
    spec = importlib.util.spec_from_file_location("count_derivation_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    minimal = _json.loads(
        (REPO_ROOT / "fixtures/config/minimal.json").read_text(encoding="utf-8")
    )
    request = list(module.control_api_negative_probes(REPO_ROOT))
    response = list(module.control_response_negative_probes(REPO_ROOT))
    engine = list(module.engine_lock_probes())
    secret = list(module.secret_reference_key_probes(minimal))
    # The request group holds one positive case at exactly 128, so it is not
    # counted here; `SemanticProbeCountTests` states the arithmetic in full.
    return (len(request) - 1) + len(response) + len(engine) + len(secret)


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
            globals()["PASS_SECTION_NARRATIVE"] = re.compile(
                pattern.pattern, pattern.flags & ~re.IGNORECASE
            )
            without_flag = {
                heading
                for heading in pass_sections(original)
                if heading[0].isupper() and heading.lower().endswith("remediation pass")
            }
        finally:
            globals()["PASS_SECTION_NARRATIVE"] = pattern
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

    def test_the_whole_file_passes_when_it_is_run_from_outside_the_repository(self):
        """Every test in this file, run from a directory outside the repository.

        The chdir test above covers the derivations. This runs the whole module
        the way a developer or a CI job might, so a dependency nothing else owns —
        a relative path in a test that reads a script, a `git` call that resolves
        the repository from the process directory — fails here rather than for the
        next person who runs the file from elsewhere.

        It used to run only this class, while four places in the repository
        described it as running "the whole file". That was a claim about more
        than the test did, and the git call above is exactly the kind of
        dependency it would not have caught. It runs the module now, and the
        nested run's own count is checked so "the whole file" stays true.

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
                [sys.executable, "-m", "unittest", "test_ci_checks"],
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
            # "The whole file" has to mean the whole file. The nested run
            # discovered its own count; this requires it to be every test in the
            # module apart from this one, which is the only one that cannot run
            # there. A nested run quietly narrowed to a class would keep passing
            # while the claim in the repository stayed wider than the check.
            reported = re.search(r"(?m)^Ran (\d+) tests?", result.stderr)
            self.assertIsNotNone(
                reported, f"the nested run reported no count:\n{result.stderr[-1500:]}"
            )
            discovered = unittest.defaultTestLoader.loadTestsFromModule(
                sys.modules[__name__]
            )
            # Every test in the module, including this one: unittest counts a
            # skipped test in the total, so the nested run reports the whole file
            # and skips only the copy of this test that would recurse.
            self.assertEqual(
                discovered.countTestCases(), int(reported.group(1)),
                f"the nested run executed {reported.group(1)} tests but this module "
                f"holds {discovered.countTestCases()}; 'the whole file' is no longer "
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
        since moved, and the copy count costs a 25-90 second instrumented run
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


def word_for(number: int) -> str:
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
        8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    }
    if number not in words:
        raise AssertionError(f"no word for {number}; the record would have to state the digits")
    return words[number]


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
        "tools/ci/test_ci_checks.py",
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
        # identified by its title rather than by the prose in its last column.
        title = "**Archive and export**"
        row = next(
            line
            for line in readiness.splitlines()
            if line.startswith("| 3 |") and title in line
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


PACKAGE_LIST = "tools/ci/local-packages.txt"


def local_packages():
    """Every entry in the package list, comments and blanks removed."""
    path = REPO_ROOT / PACKAGE_LIST
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


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


def app_test_count():
    """The app's XCTest count, counted the way `swiftpm_counts` counts SwiftPM's.

    The record carried the literal `Executed 60 tests, with 0 failures` from an
    `xcodebuild test` run, and a test required that literal — so the number was a
    transcript of one run that could only be updated by running the suite and
    editing the document by hand. Counting `func test…` in the test target gives
    the same 60 from the sources, and a test that a test is added to the target
    has to appear here, which a transcript cannot do.
    """
    target = REPO_ROOT / "client/app/ios/RoviaAppTests"
    return sum(
        len(re.findall(r"\bfunc (test\w*)\s*\(", source.read_text(encoding="utf-8")))
        for source in sorted(target.rglob("*.swift"))
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
        # This test is self-referential: the count for `test_ci_checks.py` is its
        # own. Adding a test here means updating the number below and the record
        # together, and the test fails if only one of them moved.
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

    UNEXECUTED_CONTROLS = {
        "Golden routing fixtures shared with Android": ("10",),
        "Fuzz targets for share-link and subscription parsing": None,
        "CI secret scanning and workflow review": ("1", "7"),
        "Dependency review and advisory monitoring": ("8",),
        "Physical-device tunnel tests for lifecycle": ("5",),
        "Independent reproducibility check for the engine artifact": ("6",),
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
        # Workspace instantiations through a suite that runs in the 25-90 second
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
            "gate": "The gate takes 25-90 seconds across the runs recorded here.",
            "other": "The fuzzer takes 3-4 seconds across the runs of the fuzz suite.",
        },
        "the suite already spends": {
            "gate": "That is 25-90 seconds the suite already spends.",
            "other": "The linter takes 3-4 seconds the suite already spends.",
        },
        "gate runtime range reads": {
            "gate": "The gate runtime range reads 25-90 seconds in every document.",
            "other": "The retry range reads 3-4 seconds on a slow link.",
        },
        "gate runs in the": {
            "gate": "The gate runs in the 25-90 seconds measured here.",
            "other": "The retry runs in the 3-4 seconds expected on a slow link.",
        },
    }
    RUNTIME_AGREED_RANGE = (25, 90)

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
            "The gate runs in the 25-90 second range measured here.\n"
        )
        matched = self.RUNTIME_SPAN.findall(unrelated)
        self.assertEqual(
            1, len(matched),
            f"expected only the sentence naming the gate to match, but "
            f"{len(matched)} spans matched: {matched}",
        )
        self.assertIsNotNone(
            self.RUNTIME_SPAN.search("The gate runs in the 25-90 second range measured here."),
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
        low, high = 25, 90
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

    def test_both_documents_say_no_review_is_enforced_yet(self):
        # The honest consequence of one owner: `CODEOWNERS` is inert until branch
        # protection requires a review, and requiring a review from the only possible
        # reviewer would be a self-review. Both documents have to say so, because a
        # reader of either one alone would otherwise believe a review is required.
        for document, name in ((self.codeowners, "CODEOWNERS"), (self.security, "SECURITY.md")):
            with self.subTest(document=name):
                flattened = flat(document)
                self.assertRegex(
                    flattened,
                    r"branch protection|external gate",
                    f"{name} does not say that required review is an open gate",
                )
        self.assertRegex(
            flat(self.codeowners), r"inert until branch protection",
            "CODEOWNERS does not say that it enforces nothing on its own",
        )
        self.assertRegex(
            flat(self.security), r"enforces nothing|nothing currently enforces",
            "SECURITY.md does not say that 'requires maintainer review' is not enforced",
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

    def test_the_runner_temporary_path_uses_the_environment_variable(self):
        # `$RUNNER_TEMP` rather than `${{ runner.temp }}`, and the reason written next
        # to it, so the next person to "tidy" it back into an expression finds out
        # from a comment rather than from a failed run.
        workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        ci = workflow.read_text(encoding="utf-8")
        # The declared *values*, not the file: the comment above them names
        # `${{ runner.temp }}` precisely to explain why it is not used, and a
        # whole-file substring check would fail on its own explanation. This is the
        # same shape as the hygiene gate excluding its own source from its own scan.
        values = {
            key: value
            for scope, key, value in self.env_blocks(workflow)
            if scope == "workflow"
        }
        self.assertEqual(
            "$RUNNER_TEMP/RoviaDerivedData", values.get("DERIVED_DATA"),
            "DERIVED_DATA must come from the RUNNER_TEMP environment variable, not "
            "from the runner context",
        )
        for scope, key, value in self.env_blocks(workflow):
            with self.subTest(scope=scope, key=key):
                self.assertNotIn("runner.", value)
        # The reason is written next to the variable, so the next person to move it
        # back reads a comment rather than rediscovering it from a failed run.
        self.assertIn("Unrecognized named-value", ci)
        self.assertIn("only in a", flat(ci))

    def test_ci_installs_the_linter_rather_than_hoping_uvx_exists(self):
        # A GitHub-hosted macOS runner has no `uvx`, and the first hosted CI run failed
        # on exactly that. The gate's fallback is right for a developer machine, so the
        # check is that CI does not *depend* on the fallback: it installs the pinned
        # linter into the virtualenv it already creates, so CI runs one interpreter with
        # one pin rather than depending on a resolution route that is not there.
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("pyflakes==", ci)
        self.assertIn("GITHUB_PATH", ci)
        gate = (REPO_ROOT / "tools" / "ci" / "check-python-lint.sh").read_text(
            encoding="utf-8"
        )
        pinned = re.search(r'PYFLAKES_VERSION="([^"]+)"', gate)
        self.assertIsNotNone(pinned, "the lint gate does not pin a version")
        self.assertIn(
            f"pyflakes=={pinned.group(1)}", ci,
            f"CI installs a different pyflakes than the gate asks for: the gate pins "
            f"{pinned.group(1)}",
        )

    def test_ci_validates_exactly_the_json_the_record_describes(self):
        """One definition of "the JSON files", used by the gate, the record, and CI.

        The workflow used to walk `schemas` and `fixtures` — a narrower set than the
        record's derivation counted — while the derivation itself walked the whole tree
        with a hand-maintained exclusion list that did not include the virtualenv the
        workflow creates inside the checkout. So the three disagreed: CI checked fewer
        files than the record claimed, and the record's number was perturbed by a
        directory nobody publishes. All three now read `git ls-files
        --exclude-standard`.
        """
        # Comments stripped, because the comment that explains this change quotes the
        # command it replaces — a whole-file substring check would fail on the
        # explanation of the fix. Reading the commands rather than the file is also
        # what the claim is about.
        ci = "\n".join(
            line for line in
            (REPO_ROOT / ".github" / "workflows" / "ci.yml")
            .read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertIn("git ls-files --cached --others --exclude-standard '*.json'", ci)
        self.assertNotIn("find schemas fixtures", ci)
        source = (REPO_ROOT / "tools" / "ci" / "test_ci_checks.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--exclude-standard", source)
        # And the derivation, run here, is the number the record states.
        self.assertIn(f"over {json_input_groups()[0]} files",
                      (REPO_ROOT / "docs/development/foundation-verification.md")
                      .read_text(encoding="utf-8"))

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
                self.assertIn(
                    match.group(1),
                    {str(len(holding)),
                     {5: "Five", 6: "Six", 7: "Seven"}[len(holding)]},
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
        source = (REPO_ROOT / "tools/ci/test_ci_checks.py").read_text(encoding="utf-8")
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
        self.assertGreaterEqual(len(gates), 10)
        body = self.readiness_document()
        for number, title in gates:
            with self.subTest(gate=number, title=title):
                # Every gate must name at least one path in the tree that would
                # have to change for it to be executed, so a row cannot drift
                # into describing something that is not here.
                row = next(
                    line
                    for line in body.splitlines()
                    if line.startswith(f"| {number} |")
                )
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
        required = {
            "GitHub Actions execution": ".github/workflows/ci.yml",
            "Signing, provisioning, and the Apple team identity":
                "tools/release/ExportOptions.plist",
            "Archive and export": ".github/workflows/release-ios.yml",
            "Upload, TestFlight, and App Store submission": "CODEOWNERS",
            "Physical-device VPN behaviour": "tools/ci/verify-simulator-install.sh",
            "A production engine": "engines.lock.json",
            "Environment approvals and branch protection": "CODEOWNERS",
            "Third-party advisories, dependency review, and secret scanning":
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
        for phrase in (
            "It is not evidence about a tunnel",
            "no review is currently required on any path",
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
            "GitHub Actions execution",
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
