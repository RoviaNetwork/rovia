#!/usr/bin/env python3
"""Tests for `tools/ci/check-repository-hygiene.sh`.

The gate itself is a shell script, so this file holds the tests that make it a gate
rather than a script: a shell script that finds nothing is indistinguishable from a
shell script that checks nothing until something is planted in a tree and the script
has to refuse it.

Each test builds a throwaway tree, plants exactly one defect, and requires a
non-zero exit with a diagnostic that names the defect. A test that passes because the
gate refused for a different reason is worse than no test, so the refusal message is
asserted, not just the exit status.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The planted credentials are assembled from fragments rather than written out.
#
# A literal `ghp_…` in a public repository is what GitHub's own secret scanning looks
# for, so committing one — even a dummy, even in a test — earns the owner an alert
# about a token that does not exist. The shapes still have to reach the gate intact,
# so they are built here instead. The fragments are the point: a reader can see there
# is no real token in this file, and the gate still sees the shape it searches for.
GITHUB_TOKEN = "ghp_" + "0" * 8 + "a" * 8 + "b" * 8 + "C" * 8
AWS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"
SLACK_TOKEN = "xoxb-" + "1234567890-abcdefghijklmnop"
PEM_HEADER = "-----BEGIN " + "RSA " + "PRIVATE KEY" + "-----"

GATE = REPO_ROOT / "tools" / "ci" / "check-repository-hygiene.sh"

# The classes .gitignore has to carry. Duplicated here on purpose: if the list lived
# only in the gate, a change to it would change both sides of the assertion and the
# check would prove nothing.
REQUIRED_IGNORES = (
    ".DS_Store",
    "DerivedData/",
    "build/",
    ".build/",
    ".swiftpm/",
    "xcuserdata/",
    "*.xcuserstate",
    "__pycache__/",
    "*.pyc",
    "*.p12",
    "*.mobileprovision",
    "*.cer",
    "*.key",
    "*.pem",
    ".env",
    "/LibXray.xcframework/",
    "/Libbox.xcframework/",
    "/.superpowers/",
    "/docs/superpowers/",
)


class HygieneGateTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.root = Path(self.directory)
        (self.root / "tools" / "ci").mkdir(parents=True)
        (self.root / "LICENSE").write_text("MIT\n", encoding="utf-8")
        (self.root / ".editorconfig").write_text("root = true\n", encoding="utf-8")
        (self.root / "CODEOWNERS").write_text("* @princeofscale\n", encoding="utf-8")
        (self.root / "tools" / "ci" / "gate.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.write_gitignore()

    def write_gitignore(self, entries=REQUIRED_IGNORES):
        (self.root / ".gitignore").write_text(
            "\n".join(entries) + "\n", encoding="utf-8"
        )

    def run_gate(self):
        return subprocess.run(
            [str(GATE), "--root", str(self.root)],
            capture_output=True,
            text=True,
        )

    def assertRefused(self, result, needle):
        self.assertEqual(
            1, result.returncode,
            f"the gate accepted a tree with a defect: {result.stdout}{result.stderr}",
        )
        self.assertIn(
            needle, result.stdout + result.stderr,
            f"the refusal did not name the defect: {result.stdout}{result.stderr}",
        )

    def assertAccepted(self, result):
        self.assertEqual(
            0, result.returncode,
            f"the gate refused a clean tree: {result.stdout}{result.stderr}",
        )


class TheGateRefusesPlantedDefects(HygieneGateTestCase):
    def test_a_clean_tree_is_accepted(self):
        # The control for every test below. Without it, a gate that refused
        # everything would pass all of them.
        self.assertAccepted(self.run_gate())

    def test_a_private_key_block_is_refused(self):
        (self.root / "tools" / "ci" / "creds.py").write_text(
            f'KEY = """{PEM_HEADER}\nMIIEow...\n"""\n',
            encoding="utf-8",
        )
        self.assertRefused(self.run_gate(), "possible secret")

    def test_a_github_token_is_refused(self):
        (self.root / "tools" / "ci" / "token.py").write_text(
            f'TOKEN = "{GITHUB_TOKEN}"\n',
            encoding="utf-8",
        )
        self.assertRefused(self.run_gate(), "possible secret")

    def test_an_aws_access_key_id_is_refused(self):
        (self.root / "tools" / "ci" / "aws.py").write_text(
            f'KEY_ID = "{AWS_KEY_ID}"\n', encoding="utf-8"
        )
        self.assertRefused(self.run_gate(), "possible secret")

    def test_a_slack_token_is_refused(self):
        (self.root / "tools" / "ci" / "slack.py").write_text(
            f'SLACK = "{SLACK_TOKEN}"\n', encoding="utf-8"
        )
        self.assertRefused(self.run_gate(), "possible secret")

    def test_a_mobileprovision_profile_is_refused(self):
        (self.root / "Rovia.mobileprovision").write_bytes(b"\x30\x82binary")
        self.assertRefused(self.run_gate(), "build artifact")

    def test_a_p12_certificate_is_refused(self):
        (self.root / "dist.p12").write_bytes(b"\x30\x82binary")
        self.assertRefused(self.run_gate(), "build artifact")

    def test_a_pem_private_key_file_is_refused(self):
        (self.root / "key.pem").write_text(
            PEM_HEADER.replace("RSA ", "") + chr(10), encoding="utf-8"
        )
        self.assertRefused(self.run_gate(), "build artifact")

    def test_a_dot_ds_store_is_refused(self):
        # A tree with no .git, so the gate falls back to a filesystem walk and the
        # .DS_Store is in the file set.
        (self.root / ".DS_Store").write_bytes(b"\x00\x01")
        self.assertRefused(self.run_gate(), "artifact")

    def test_a_compiled_python_file_is_refused(self):
        (self.root / "tools" / "ci" / "module.pyc").write_bytes(b"\x00\x01")
        self.assertRefused(self.run_gate(), "build artifact")

    def test_a_machine_path_is_refused(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "notes.md").write_text(
            "Derived data lives at /Users/alice/Library/Developer/Xcode/DerivedData.\n",
            encoding="utf-8",
        )
        self.assertRefused(self.run_gate(), "machine-specific path")

    def test_a_home_path_is_refused(self):
        (self.root / "notes.md").write_text(
            "the checkout was /home/bob/vclient\n", encoding="utf-8"
        )
        self.assertRefused(self.run_gate(), "machine-specific path")

    def test_a_placeholder_path_is_accepted(self):
        # The other direction. A negative test needs the shape of a machine path, and
        # a gate that refused "someone" would make that test impossible to write.
        (self.root / "notes.md").write_text(
            "a rejected source is /Users/someone/profile.yaml\n"
            "another is /home/example/config\n",
            encoding="utf-8",
        )
        self.assertAccepted(self.run_gate())

    def test_a_missing_gitignore_entry_is_refused(self):
        missing = [e for e in REQUIRED_IGNORES if e != "*.mobileprovision"]
        self.write_gitignore(missing)
        self.assertRefused(self.run_gate(), "does not cover '*.mobileprovision'")

    def test_a_gitignore_covered_only_by_a_substring_is_refused(self):
        # `build/` as a bare substring of some longer line is not coverage. The gate
        # requires the line to be exactly the entry.
        (self.root / ".gitignore").write_text(
            "\n".join(f"# note about {e}" for e in REQUIRED_IGNORES) + "\n",
            encoding="utf-8",
        )
        self.assertRefused(self.run_gate(), "does not cover")

    def test_a_file_over_four_mebibytes_is_refused(self):
        (self.root / "blob.bin").write_bytes(b"x" * (4 * 1024 * 1024 + 1))
        self.assertRefused(self.run_gate(), "larger than 4 MiB")

    def test_the_gate_refuses_when_there_is_nothing_to_scan(self):
        # An empty tree must not look like a clean tree. This is the same refusal the
        # lint and warnings gates make, and it has to survive the bash 3.2 unbound
        # array failure, which exits 0 rather than 1.
        with tempfile.TemporaryDirectory() as empty_directory:
            empty = Path(empty_directory)
            result = subprocess.run(
                [str(GATE), "--root", str(empty)], capture_output=True, text=True
            )
            self.assertEqual(
                1, result.returncode,
                f"the gate accepted an empty tree: {result.stdout}{result.stderr}",
            )
            self.assertIn("no publishable files", result.stdout + result.stderr)


class TheGateChecksWhatWouldBePublished(HygieneGateTestCase):
    """The property the design exists for, in a tree that is a git repository.

    Every other test plants a defect in a plain directory, which exercises the
    filesystem fallback. These plant one in a real repository, where the file set comes
    from `git ls-files --cached --others --exclude-standard`.

    The distinction is the whole reason the gate is not a walk of the working tree: a
    Mac writes a .DS_Store into a directory as soon as anyone opens it in Finder, and
    .DS_Store is correctly ignored. A gate that flagged it would fail on every
    developer's machine, which is how a gate gets deleted.
    """

    def make_repository(self):
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "gate@example.invalid"],
            ["git", "config", "user.name", "Gate Test"],
            ["git", "add", "-A"],
        ):
            result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
            self.assertEqual(
                0, result.returncode,
                f"could not prepare the test repository: {result.stderr}",
            )

    def test_a_dot_ds_store_the_ignore_rules_exclude_is_not_a_failure(self):
        (self.root / ".DS_Store").write_bytes(b"\x00\x01")
        (self.root / "docs").mkdir()
        (self.root / "docs" / ".DS_Store").write_bytes(b"\x00\x01")
        self.make_repository()
        result = self.run_gate()
        self.assertEqual(
            0, result.returncode,
            "the gate flagged an artifact .gitignore already excludes: "
            f"{result.stdout}{result.stderr}",
        )
        self.assertIn("git ls-files", result.stdout)

    def test_an_artifact_that_is_not_ignored_is_still_a_failure(self):
        # The other direction, and the reason the one above is not simply "ignore
        # everything": removing the ignore rule brings the same file back as a failure.
        self.write_gitignore([e for e in REQUIRED_IGNORES if e != ".DS_Store"])
        (self.root / ".DS_Store").write_bytes(b"\x00\x01")
        self.make_repository()
        self.assertRefused(self.run_gate(), "would be published")

    def test_a_secret_in_an_untracked_file_that_git_would_publish_is_refused(self):
        (self.root / "tools" / "ci" / "fresh.py").write_text(
            f'''TOKEN = "{GITHUB_TOKEN}"\n''',
            encoding="utf-8",
        )
        self.make_repository()
        self.assertRefused(self.run_gate(), "possible secret")

    def test_a_file_git_ignores_is_not_published_and_not_refused(self):
        # The secret is real to the pattern; the ignore rule is what keeps it out. This
        # is the shape of an accident — somebody writes a token into a scratch file
        # under a directory .gitignore covers.
        entries = list(REQUIRED_IGNORES) + ["scratch/"]
        self.write_gitignore(entries)
        (self.root / "scratch").mkdir()
        (self.root / "scratch" / "token.py").write_text(
            f'''TOKEN = "{GITHUB_TOKEN}"\n''',
            encoding="utf-8",
        )
        self.make_repository()
        result = self.run_gate()
        self.assertEqual(
            0, result.returncode,
            f"a file git ignores was treated as publishable: "
            f"{result.stdout}{result.stderr}",
        )


class TheGateExcludesItselfOnPurpose(HygieneGateTestCase):
    def test_the_exclusions_are_exactly_two_named_paths(self):
        # A scanner written as source contains the shapes it searches for, so it has
        # to exclude itself. The exclusion is a list, and a list that can grow without
        # anybody noticing stops being a disclosure and becomes a hole.
        source = GATE.read_text(encoding="utf-8")
        begin = source.index("skip_secrets=(")
        finish = source.index(")", begin)
        entries = [
            line.strip().strip('"')
            for line in source[begin + len("skip_secrets=("):finish].splitlines()
            if line.strip()
        ]
        self.assertEqual(2, len(entries), f"the exclusion list holds {entries}")
        self.assertTrue(
            all("check-repository-hygiene" in entry or "test_check_repository_hygiene" in entry
                for entry in entries),
            f"the exclusion list names something else: {entries}",
        )

    def test_the_gate_does_not_flag_its_own_patterns(self):
        # Run against this repository, where the gate and its test are present. If the
        # exclusion failed, the gate would find its own regex literals.
        result = subprocess.run(
            [str(GATE), "--root", str(REPO_ROOT)], capture_output=True, text=True
        )
        self.assertEqual(
            0, result.returncode,
            f"the gate flags this repository: {result.stdout}{result.stderr}",
        )


class TheGateRunsInTheSuite(unittest.TestCase):
    def test_the_runner_invokes_the_gate(self):
        # Deleting this line removes the gate from every run, local and hosted, with
        # no test failing. The lint and warnings gates each hold their own invocation
        # for the same reason.
        runner = (REPO_ROOT / "tools" / "ci" / "run-tool-tests.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("tools/ci/check-repository-hygiene.sh", runner)
        self.assertIn("the repository hygiene gate reported findings", runner)

    def test_the_gate_is_executable(self):
        self.assertTrue(GATE.is_file(), "the gate does not exist")
        self.assertTrue(os.access(GATE, os.X_OK), "the gate is not executable")

    def test_the_documentation_names_the_gate(self):
        for document in ("docs/development/ci.md", "SECURITY.md"):
            with self.subTest(document=document):
                self.assertIn(
                    "check-repository-hygiene.sh",
                    (REPO_ROOT / document).read_text(encoding="utf-8"),
                    f"{document} does not name the hygiene gate",
                )


if __name__ == "__main__":
    unittest.main()
