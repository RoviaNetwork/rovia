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
import os
import re
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
from script_test_support import workflow_steps  # noqa: E402

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

    The owner is resolved through `owner_of`, not a module global: the count
    checks live in the counts module while this helper lives in support.
    """
    owner = owner_of(test_name)
    method = getattr(owner, test_name, None)
    if method is None:
        raise AssertionError(
            f"{test_name} does not exist, so the count it holds is not held at all"
        )
    case = owner(test_name)
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

    Searches the split check modules, not just this one: the mutation tests in
    one module routinely own checks that live in another (the changelog
    mutations run the record checks owned by the docs module).

    `__main__` comes first on purpose: when a check file runs directly, its
    classes live under `__main__`, and a mutation test patches that copy — a
    second copy imported under its file name would still hold the original
    method, and the mutation would silently test nothing.
    """
    import importlib

    module_names = [
        "__main__",
        "test_ci_changelog",
        "test_ci_toolchain",
        "test_ci_workflows",
        "test_ci_counts",
        "test_ci_docs",
        __name__,
    ]
    for module_name in module_names:
        try:
            module = sys.modules.get(module_name) or importlib.import_module(module_name)
        except ImportError:
            continue
        for candidate in vars(module).values():
            if (
                isinstance(candidate, type)
                and issubclass(candidate, unittest.TestCase)
                and test_name in vars(candidate)
            ):
                return candidate
    raise AssertionError(f"no test class defines {test_name}: it does not exist, so nothing holds it")


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


def word_for(number: int) -> str:
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
        8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    }
    if number not in words:
        raise AssertionError(f"no word for {number}; the record would have to state the digits")
    return words[number]


def core_root() -> Path:
    """The pinned rovia-core sources the text gates read.

    A versioned tarball resolved by tools/ci/fetch-core.sh, never a sibling
    checkout: the build takes core as an SPM pin, and the gates take the same
    revision as files. CI exports ROVIA_CORE_ROOT; local runs without it fail
    with the command that fixes them rather than with a missing directory.
    """
    raw = os.environ.get("ROVIA_CORE_ROOT")
    if raw:
        candidate = Path(raw)
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        candidate = cache / "rovia-core" / pinned_core_tag()
    if (candidate / "core" / "config" / "Package.swift").is_file():
        return candidate
    raise AssertionError(
        "no pinned rovia-core checkout: run tools/ci/fetch-core.sh "
        "(or export ROVIA_CORE_ROOT) so the text gates read the pinned revision"
    )


def pinned_core_tag() -> str:
    for line in (REPO_ROOT / "tools/ci/core-pin.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("ROVIA_CORE_TAG="):
            return line.split("=", 1)[1].strip()
    raise AssertionError("tools/ci/core-pin.txt names no ROVIA_CORE_TAG")


def core_sources_root(root: Path) -> Path:
    """Where the checks read core sources from.

    The workspace carries a mutated copy under core/; anywhere else the
    pinned checkout is read. Mutation tests depend on the first, clean runs
    on the second, and neither may silently read the other.
    """
    if (root / "core" / "config" / "Package.swift").is_file():
        return root
    return core_root()
