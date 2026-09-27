#!/usr/bin/env python3
"""Tests for tools/ci/audit-accessibility-identifiers.py.

The audit exists to catch a real class of defect: a bare
.accessibilityIdentifier applied to a container view, which makes SwiftUI
override the identifiers of that container's children. Two earlier versions of
this audit reported "no violations" while such a call was present, so the audit's
own resolution logic is tested here against synthetic sources instead of being
trusted.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "tools" / "ci" / "audit-accessibility-identifiers.py"

spec = importlib.util.spec_from_file_location("audit_accessibility", AUDIT_PATH)
audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit)


ENUM_HEAD = """
import Foundation

enum AppAccessibilityIdentifier {
    static let elementOne = "rovia.thing.one"
    static let elementTwo = "rovia.thing.two"
    static let containerOne = "rovia.thing.container"

    static let containerIdentifiers: [String] = [
        containerOne
    ]

    static let elementIdentifiers: [String] = [
        elementOne,
        elementTwo
    ]
}
"""

ROOT_VIEW = """
import SwiftUI

struct ConditionalAccessibilityIdentifier: ViewModifier {
    let identifier: String?

    func body(content: Content) -> some View {
        if let identifier {
            content
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier(identifier)
        } else {
            content
        }
    }
}

struct SectionCard<Content: View>: View {
    let title: String
    var identifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            content
        }
        .modifier(ConditionalAccessibilityIdentifier(identifier: identifier))
    }
}
"""


def source_leaf_uses() -> str:
    return """
struct Thing: View {
    var body: some View {
        Text("hello (world) [test]")
            .accessibilityIdentifier(AppAccessibilityIdentifier.elementOne)
            .accessibilityIdentifier(AppAccessibilityIdentifier.elementTwo)
    }
}
"""


def source_bare_container_use() -> str:
    return """
struct Thing: View {
    var body: some View {
        ContentUnavailableView(
            "No data",
            systemImage: "tray",
            description: Text("nothing here")
        )
        .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
    }
}
"""


def source_guarded_container_use() -> str:
    return """
struct Thing: View {
    var body: some View {
        ContentUnavailableView(
            "No data",
            systemImage: "tray",
            description: Text("nothing here")
        )
        .modifier(ConditionalAccessibilityIdentifier(
            identifier: AppAccessibilityIdentifier.containerOne
        ))
    }
}
"""


def source_container_with_closure_body() -> str:
    return """
struct Thing: View {
    var body: some View {
        List {
            Text("row")
        }
        .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
    }
}
"""


def source_closure_returning_constructor() -> str:
    return """
struct Thing: View {
    var body: some View {
        Group {
            Text("row")
        }
        .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
    }
}
"""


def source_card_argument() -> str:
    return """
struct Thing: View {
    var body: some View {
        SectionCard(title: "Members", identifier: AppAccessibilityIdentifier.containerOne) {
            Text("row")
        }
    }
}
"""


def source_doubled_declaration_same_value() -> str:
    return """
enum AppAccessibilityIdentifier {
    static let elementOne = "rovia.thing.one"
    static let elementOne = "rovia.thing.one"
    static let containerOne = "rovia.thing.container"

    static let containerIdentifiers: [String] = [
        containerOne
    ]

    static let elementIdentifiers: [String] = [
        elementOne
    ]
}
"""


def source_doubled_declaration_different_value() -> str:
    return """
enum AppAccessibilityIdentifier {
    static let elementOne = "rovia.thing.one"
    static let elementOne = "rovia.thing.shadowed"
    static let containerOne = "rovia.thing.container"

    static let containerIdentifiers: [String] = [
        containerOne
    ]

    static let elementIdentifiers: [String] = [
        elementOne
    ]
}
"""


def source_combine_near_a_container() -> str:
    # The container treatment applied to a sibling, and a bare identifier on a
    # container view after it. The treatment has to be *near* the call rather than
    # in the same modifier chain: `resolve_base_view` stops at a modifier, so a
    # chained `.accessibilityElement(...).accessibilityIdentifier(...)` never
    # reaches the container check at all.
    return """
struct Thing: View {
    var body: some View {
        VStack {
            Text("header")
                .accessibilityElement(children: .combine)
            List {
                Text("row")
            }
            .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
        }
    }
}
"""


def source_contain_near_a_container() -> str:
    return """
struct Thing: View {
    var body: some View {
        VStack {
            Text("header")
                .accessibilityElement(children: .contain)
            List {
                Text("row")
            }
            .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
        }
    }
}
"""


def source_modifier_near_a_container() -> str:
    return """
struct Thing: View {
    var body: some View {
        VStack {
            Text("header")
                .modifier(ConditionalAccessibilityIdentifier(
                    identifier: AppAccessibilityIdentifier.elementOne
                ))
            List {
                Text("row")
            }
            .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
        }
    }
}
"""


def source_second_component_without_treatment() -> str:
    return """
struct OtherCard<Content: View>: View {
    let identifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack {
            content
        }
        .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
    }
}
"""


def source_doubled_declaration_known_lines() -> str:
    """Two declarations of one name on lines 4 and 7 of the file.

    The numbers are checked exactly, so a report that is off by an offset, or
    that reports the same line twice because it searched for the text rather than
    walking the declarations, fails. The blank lines are deliberate: a report that
    counted from the enum body rather than the file would not notice them.
    """
    return """
import Foundation

enum AppAccessibilityIdentifier {
    static let elementOne = "rovia.thing.one"

    static let containerOne = "rovia.thing.container"

    static let elementOne = "rovia.thing.shadowed"

    static let elementTwo = "rovia.thing.two"

    static let containerIdentifiers: [String] = [
        containerOne
    ]

    static let elementIdentifiers: [String] = [
        elementOne,
        elementTwo
    ]
}
"""


CONTAINER_COMPONENT_SPELLINGS = {
    "struct, @ViewBuilder var content: Content": """
struct Panel<Content: View>: View {
    var identifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "struct, @ViewBuilder var content: () -> Content": """
struct Panel<Content: View>: View {
    var identifier: String?
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack { content() }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "struct, let content: Content": """
struct Panel<Content: View>: View {
    var identifier: String?
    let content: Content

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "struct, var content: some View": """
struct Panel: View {
    var identifier: String?
    var content: some View

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "public struct, @ViewBuilder var content: Content": """
public struct Panel<Content: View>: View {
    var identifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "public struct, @ViewBuilder var content: () -> Content": """
public struct Panel<Content: View>: View {
    var identifier: String?
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack { content() }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "internal struct, var content: some View": """
internal struct Panel: View {
    var identifier: String?
    var content: some View

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "final class, @ViewBuilder var content: Content": """
final class PanelController {
    var identifier: String?
    @ViewBuilder var content: Content

    func body() -> some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "open class, var content: some View": """
open class PanelController {
    var identifier: String?
    var content: some View

    func body() -> some View {
        VStack { content }
            .accessibilityIdentifier(identifier ?? "")
    }
}
""",
    "struct, var accessibilityIdentifier: String?": """
struct Panel<Content: View>: View {
    var accessibilityIdentifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(accessibilityIdentifier ?? "")
    }
}
""",
    "struct, var containerIdentifier: String?": """
struct Panel<Content: View>: View {
    var containerIdentifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(containerIdentifier ?? "")
    }
}
""",
    "struct, let identifier: LocalizedStringKey": """
struct Panel<Content: View>: View {
    let identifier: LocalizedStringKey
    @ViewBuilder var content: Content

    var body: some View {
        VStack { content }
            .accessibilityIdentifier(Text(identifier))
    }
}
""",
}


# A component that wraps caller-supplied content, takes an identifier and omits the
# container treatment — and applies the identifier to a *leaf*, so rule 3 has nothing
# to say about it and rule 5 is the only rule that can find it.
LEAF_IDENTIFIED_PANEL = """
import SwiftUI

public struct SummaryPanel<Content: View>: View {
    var identifier: String?
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading) {
            Text("title")
                .accessibilityIdentifier(identifier ?? "")
            content()
        }
    }
}
"""


# A component whose properties come after a string literal holding a brace. The
# closing brace ends the naive brace balance early, so the body is cut short and
# the content and identifier properties fall outside it.
BRACE_IN_STRING_COMPONENT = """
public struct SummaryPanel<Content: View>: View {
    let closing = "}"
    let opening = "{"
    var identifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack {
            content
        }
        .accessibilityIdentifier(identifier ?? "")
    }
}
"""


ATTRIBUTE_DECLARATIONS = {
    "plain struct": "struct Panel: View {",
    "@MainActor struct": "@MainActor struct Panel: View {",
    "@MainActor public struct": "@MainActor public struct Panel: View {",
    "@Observable final class": "@Observable final class Panel {",
    "indirect enum": "indirect enum Panel {",
}


class BracketResolutionTests(unittest.TestCase):
    def resolve(self, source: str) -> str | None:
        pairs = audit.bracket_pairs(source)
        index = source.index(".accessibilityIdentifier(")
        return audit.resolve_base_view(source, index, pairs)

    def test_resolves_leaf_text_call(self):
        self.assertEqual(self.resolve(source_leaf_uses()), "Text")

    def test_resolves_multiline_container_call(self):
        self.assertEqual(self.resolve(source_bare_container_use()), "ContentUnavailableView")

    def test_resolves_container_with_closure_body(self):
        self.assertEqual(self.resolve(source_container_with_closure_body()), "List")

    def test_resolves_closure_returning_constructor(self):
        self.assertEqual(self.resolve(source_closure_returning_constructor()), "Group")

    def test_ignores_brackets_inside_string_literals(self):
        source = 'Text("a (b) [c] \\" d)")\n    .accessibilityIdentifier(AppAccessibilityIdentifier.elementOne)\n'
        self.assertEqual(self.resolve(source), "Text")

    def test_identifier_bounds_is_symmetric(self):
        source = "let value = ContentUnavailableView("
        start, end = audit.identifier_bounds(source, len("let value = ContentUnavailabl") - 1)
        self.assertEqual(source[start : end + 1], "ContentUnavailableView")


class AuditTests(unittest.TestCase):
    def run_audit(
        self,
        view_source: str,
        root_view: str = ROOT_VIEW,
        enum_source: str = ENUM_HEAD,
        extra_sources: dict[str, str] | None = None,
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "RoviaApp"
            app.mkdir()
            (app / "AppSnapshot.swift").write_text(enum_source)
            (app / "RootView.swift").write_text(root_view)
            (app / "Thing.swift").write_text(view_source)
            for name, body in (extra_sources or {}).items():
                target = app / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
            return audit.audit(app)

    def test_clean_source_passes(self):
        self.assertEqual(self.run_audit(source_leaf_uses() + source_card_argument()), [])

    def test_guarded_container_passes(self):
        self.assertEqual(
            self.run_audit(source_guarded_container_use() + source_leaf_uses()),
            [],
        )

    def test_bare_container_identifier_fails(self):
        problems = self.run_audit(source_bare_container_use())
        self.assertTrue(
            any("not guarded" in problem for problem in problems),
            f"expected an unguarded container failure, got {problems}",
        )

    def test_container_with_closure_body_fails(self):
        problems = self.run_audit(source_container_with_closure_body())
        self.assertTrue(
            any("not guarded" in problem for problem in problems),
            f"expected an unguarded container failure, got {problems}",
        )

    def test_closure_returning_constructor_fails(self):
        problems = self.run_audit(source_closure_returning_constructor())
        self.assertTrue(
            any("not guarded" in problem for problem in problems),
            f"expected an unguarded container failure, got {problems}",
        )

    def test_unused_constant_fails(self):
        problems = self.run_audit(source_leaf_uses())
        self.assertTrue(
            any("never reach a view" in problem for problem in problems),
            f"expected an unused constant failure, got {problems}",
        )

    def test_unclassified_constant_fails(self):
        enum = ENUM_HEAD.replace(
            "    static let containerIdentifiers: [String] = [",
            "    static let unclassified = \"rovia.thing.unclassified\"\n\n"
            "    static let containerIdentifiers: [String] = [",
        )
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "RoviaApp"
            app.mkdir()
            (app / "AppSnapshot.swift").write_text(enum)
            (app / "RootView.swift").write_text(ROOT_VIEW)
            (app / "Thing.swift").write_text(source_leaf_uses() + source_card_argument())
            problems = audit.audit(app)
        self.assertTrue(
            any("not classified" in problem for problem in problems),
            f"expected an unclassified constant failure, got {problems}",
        )

    def test_section_card_without_container_treatment_fails(self):
        root = ROOT_VIEW.replace(
            "        .modifier(ConditionalAccessibilityIdentifier(identifier: identifier))\n", ""
        )
        problems = self.run_audit(source_leaf_uses() + source_card_argument(), root_view=root)
        self.assertTrue(
            any("SectionCard" in problem for problem in problems),
            f"expected a SectionCard failure, got {problems}",
        )

    def test_a_constant_declared_twice_fails(self):
        # Rule 1 says every identifier constant is declared exactly once. Nothing
        # checked that: the declarations were collected with `dict(re.findall(...))`,
        # which keeps the last value for a repeated name and drops the earlier one,
        # so a constant declared twice was reported as declared once, and the
        # earlier value disappeared from every other rule's view of it.
        for label, enum_source in (
            ("same value", source_doubled_declaration_same_value()),
            ("different value", source_doubled_declaration_different_value()),
        ):
            with self.subTest(declaration=label):
                problems = self.run_audit(
                    source_leaf_uses() + source_card_argument(),
                    enum_source=enum_source,
                )
                self.assertTrue(
                    any("elementOne" in problem and "declared" in problem
                        for problem in problems),
                    f"declaring elementOne twice ({label}) was not reported: {problems}",
                )

    def test_the_duplicate_declaration_report_is_diagnosable(self):
        # Which values, and where. A report that only said "declared twice" would
        # send a reader to the whole enum.
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(),
            enum_source=source_doubled_declaration_different_value(),
        )
        reports = [problem for problem in problems if "elementOne" in problem]
        self.assertEqual(1, len(reports), f"expected one report, got {reports}")
        self.assertIn("rovia.thing.one", reports[0])
        self.assertIn("rovia.thing.shadowed", reports[0])
        self.assertRegex(reports[0], r"line \d+")

    def test_a_declaration_stated_once_is_not_reported_as_a_duplicate(self):
        # The fix must not turn a single declaration into a duplicate report.
        self.assertEqual(
            self.run_audit(source_leaf_uses() + source_card_argument()), []
        )

    def test_a_combine_guarded_container_fails_and_a_contain_guarded_one_passes(self):
        # Rule 3 asks for the treatment that applies `.contain`. The check was for
        # the bare word `accessibilityElement`, which `.combine` also contains, so
        # the one modifier that discards a container's children's identifiers was
        # accepted as the guard against exactly that.
        combined = self.run_audit(
            source_combine_near_a_container() + source_card_argument() + source_leaf_uses()
        )
        self.assertTrue(
            any("not guarded" in problem for problem in combined),
            f"a container identifier guarded only by a nearby .combine was "
            f"accepted: {combined}",
        )
        for label, source in (
            (".contain", source_contain_near_a_container()),
            ("the container modifier", source_modifier_near_a_container()),
        ):
            with self.subTest(treatment=label):
                self.assertEqual(
                    [], self.run_audit(source + source_card_argument() + source_leaf_uses()),
                    f"a container identifier guarded by {label} was refused",
                )

    def test_the_container_treatment_check_is_not_satisfied_by_the_word_alone(self):
        # The named failure: `has_container_treatment` returned True for any window
        # containing "accessibilityElement". Checked directly, because a test that
        # only went through the whole audit would also pass if the resolution logic
        # stopped ever reaching this function.
        combined = source_combine_near_a_container()
        index = combined.index(".accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)")
        self.assertFalse(
            audit.has_container_treatment(combined, index),
            "a nearby .combine still satisfies the container-treatment check",
        )
        contained = source_contain_near_a_container()
        self.assertTrue(
            audit.has_container_treatment(
                contained,
                contained.index(".accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)"),
            ),
            "a nearby .contain is not recognised as the container treatment",
        )
        modified = source_modifier_near_a_container()
        self.assertTrue(
            audit.has_container_treatment(
                modified,
                modified.index(".accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)"),
            ),
            "a nearby container modifier is not recognised",
        )
        # And the window is bounded, so a treatment far above is not a guard.
        distant = (
            "VStack {\n"
            "    Text(\"header\")\n"
            "        .accessibilityElement(children: .contain)\n"
            "}\n" + ("    // padding\n" * 60) +
            "struct Other: View {\n"
            "    var body: some View {\n"
            "        List { Text(\"row\") }\n"
            "            .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)\n"
            "    }\n"
            "}\n"
        )
        self.assertFalse(
            audit.has_container_treatment(
                distant, distant.index(".accessibilityIdentifier(")
            ),
            "a container treatment more than 600 characters away is still counted",
        )

    def test_a_second_container_component_without_the_treatment_fails(self):
        # Rule 5 was checked against one hard-coded name, so a second component
        # added later was checked by nothing. It is found by shape now.
        root = ROOT_VIEW + source_second_component_without_treatment()
        problems = self.run_audit(source_leaf_uses(), root_view=root)
        self.assertTrue(
            any("OtherCard" in problem and "container treatment" in problem
                for problem in problems),
            f"a second component wrapping content without the treatment was "
            f"accepted: {problems}",
        )

    def test_a_component_that_merges_its_own_children_is_not_a_container(self):
        # The other direction, and the reason rule 5 is scoped the way it is. A
        # header that builds its own `Text` children and merges them with
        # `.combine` is supposed to collapse to one element; requiring the
        # treatment of it would flag correct code.
        root = ROOT_VIEW + """
struct Banner: View {
    let identifier: String?

    var body: some View {
        VStack {
            Text("title")
            Text("body")
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(AppAccessibilityIdentifier.containerOne)
    }
}
"""
        problems = self.run_audit(source_leaf_uses(), root_view=root)
        self.assertEqual(
            [], [p for p in problems if "Banner" in p],
            f"a component that merges its own children was treated as a container: {problems}",
        )

    def test_the_treatment_is_excluded_by_the_shape_predicate_not_by_a_name(self):
        # There was a `if name == "ConditionalAccessibilityIdentifier": continue` in
        # rule 5 that could never run, because the shape predicate already excluded
        # the treatment — so the test named for it passed for a different reason and
        # could not fail. The branch is gone; this states the reason that actually
        # excludes it, and would fail if the predicate were widened to match a
        # function parameter.
        root = (REPO_ROOT / "client/app/ios/RoviaApp/RootView.swift").read_text(
            encoding="utf-8"
        )
        treatment = dict(audit.component_bodies(root))[
            "ConditionalAccessibilityIdentifier"
        ]
        self.assertIn(
            "content: Content", treatment,
            "the treatment no longer takes content, so this no longer describes it",
        )
        self.assertFalse(
            audit.WRAPS_CALLER_CONTENT.search(treatment),
            "the shape predicate now matches the treatment, so it would be checked "
            "against itself — the exclusion this test relies on is gone",
        )
        self.assertTrue(
            audit.TAKES_AN_IDENTIFIER.search(treatment),
            "the treatment no longer takes an identifier, so the other half of the "
            "shape has changed and this test needs re-reading",
        )
        problems = self.run_audit(source_leaf_uses())
        self.assertEqual([], [p for p in problems if "ConditionalAccessibility" in p])

    def test_the_duplicate_declaration_report_names_the_real_file_lines(self):
        # The line numbers were counted from the enum body slice and found with
        # `str.index`, which returns the first match for the text: a declaration on
        # file line 4 was reported as line 2, and two declarations of the same
        # constant with the same value were both reported as the first one's line.
        # Checked against a fixture whose lines are known and far apart.
        enum_source = source_doubled_declaration_known_lines()
        declared_lines = [
            number
            for number, line in enumerate(enum_source.splitlines(), 1)
            if line.strip().startswith("static let elementOne")
        ]
        self.assertEqual(
            2, len(declared_lines),
            f"the fixture is meant to declare elementOne twice, on {declared_lines}",
        )
        self.assertGreaterEqual(
            declared_lines[1] - declared_lines[0], 2,
            f"the fixture's declarations must not be adjacent: {declared_lines}",
        )
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(),
            enum_source=enum_source,
        )
        reports = [problem for problem in problems if "is declared 2 times" in problem]
        self.assertEqual(1, len(reports), f"expected one report, got {problems}")
        found = [int(number) for number in re.findall(r"line (\d+)", reports[0])]
        self.assertEqual(
            declared_lines, sorted(found),
            f"the report named {sorted(found)} for declarations that are on file "
            f"lines {declared_lines}",
        )

    def test_a_declaration_spelled_the_same_twice_gets_two_different_lines(self):
        # The same text twice: a report that searched for the text would give both
        # the first line. The numbers still have to be the two real ones.
        enum_source = source_doubled_declaration_same_value()
        declared_lines = [
            number
            for number, line in enumerate(enum_source.splitlines(), 1)
            if line.strip().startswith("static let elementOne")
        ]
        self.assertEqual(2, len(declared_lines), declared_lines)
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(), enum_source=enum_source
        )
        reports = [problem for problem in problems if "is declared 2 times" in problem]
        found = [int(number) for number in re.findall(r"line (\d+)", reports[0])]
        self.assertEqual(
            sorted(declared_lines), sorted(found),
            f"two identical declarations are on file lines {declared_lines} and the "
            f"report named {sorted(found)}",
        )

    def test_a_wrapping_component_is_caught_in_every_ordinary_spelling(self):
        # Rule 5's shape predicate matched one spelling of "wraps caller-supplied
        # content" and one spelling of "takes an identifier", so a component written
        # the ordinary SwiftUI ways was skipped and the audit reported OK.
        for label, component in sorted(CONTAINER_COMPONENT_SPELLINGS.items()):
            with self.subTest(spelling=label):
                problems = self.run_audit(
                    source_leaf_uses() + source_card_argument(),
                    root_view=ROOT_VIEW + component,
                )
                self.assertTrue(
                    any("Panel" in problem and "container treatment" in problem
                        for problem in problems),
                    f"a wrapping component written as {label!r} was accepted: {problems}",
                )

    def test_a_component_that_merges_its_own_children_is_still_not_a_container(self):
        # The other direction, in the same spellings. `.combine` on a component's
        # own children is correct, and the widened rule must not flag it — a rule
        # that fires on correct code gets disabled.
        for label, own_children in (
            ("children as Text", "Text(\"title\")\n            Text(\"body\")"),
            ("children as Label", "Label(\"title\", systemImage: \"star\")"),
        ):
            with self.subTest(children=label):
                # No `content` property: this component builds its own children,
                # which is the whole point. A component that declared caller-supplied
                # content and then ignored it in favour of its own children would be
                # a different defect — one rule 5 *should* report, for applying a
                # container role of its own.
                component = f"""
struct Panel: View {{
    var identifier: String?

    var body: some View {{
        VStack {{
            {own_children}
        }}
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(identifier ?? "")
    }}
}}
"""
                problems = self.run_audit(
                    source_leaf_uses() + source_card_argument(),
                    root_view=ROOT_VIEW + component,
                )
                self.assertEqual(
                    [], [problem for problem in problems if "Panel" in problem],
                    f"a component merging its own children ({label}) was reported as "
                    f"a container: {problems}",
                )

    def test_a_component_that_wraps_content_and_applies_its_own_role_is_reported(self):
        # The third condition of rule 5, in a shape the widened predicate now
        # matches: a component that declares caller-supplied content and then
        # collapses everything with its own `.combine`. It is still a container in
        # the sense of the rule — the content's identifiers are the ones at risk —
        # and a test that only covered the "no treatment" case would miss it.
        component = """
struct Panel<Content: View>: View {
    var identifier: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack {
            Text("header")
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(identifier ?? "")
    }
}
"""
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(), root_view=ROOT_VIEW + component
        )
        self.assertTrue(
            any("Panel" in problem and "container role of its own" in problem
                for problem in problems),
            f"a component applying its own role to caller-supplied content was "
            f"accepted: {problems}",
        )

    def test_the_cli_reports_a_public_component_end_to_end(self):
        # The shape predicate and the component scan are checked directly above, so
        # this runs the script the way a developer or CI would, to prove the two
        # reach the audit's own reporting path rather than only a helper.
        for label, component in sorted(CONTAINER_COMPONENT_SPELLINGS.items()):
            with self.subTest(spelling=label):
                with tempfile.TemporaryDirectory() as directory:
                    app = Path(directory) / "RoviaApp"
                    app.mkdir()
                    (app / "AppSnapshot.swift").write_text(ENUM_HEAD)
                    (app / "RootView.swift").write_text(ROOT_VIEW + component)
                    (app / "Thing.swift").write_text(
                        source_leaf_uses() + source_card_argument()
                    )
                    import subprocess

                    result = subprocess.run(
                        [sys.executable, str(AUDIT_PATH), "--app", str(app)],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        1, result.returncode,
                        f"the audit reported OK for a wrapping component written as "
                        f"{label!r}: {result.stdout}{result.stderr}",
                    )
                    self.assertIn("Panel", result.stdout + result.stderr)

    def test_a_defective_component_outside_root_view_is_found(self):
        # Rule 5 read only RootView.swift, while rules 1-4 read every source. A
        # component with exactly the defect rule 5 exists to catch was therefore
        # found in RootView.swift and missed in any other file — and because the
        # identifier here is applied to a leaf, rule 3 has nothing to say, so the
        # whole audit reported OK.
        for name in ("OverviewView.swift", "ServersView.swift", "Panel.swift"):
            with self.subTest(file=name):
                problems = self.run_audit(
                    source_leaf_uses() + source_card_argument(),
                    extra_sources={name: LEAF_IDENTIFIED_PANEL},
                )
                self.assertTrue(
                    any("SummaryPanel" in problem for problem in problems),
                    f"a defective component in {name} was not found at all: {problems}",
                )
                # And the finding has to say which file, because the same
                # component can exist in more than one of them.
                self.assertTrue(
                    any(name in problem and "SummaryPanel" in problem
                        for problem in problems),
                    f"the rule-5 finding does not name {name}: {problems}",
                )

    def test_the_same_component_in_root_view_is_found(self):
        # The other direction of the comparison above, so the two tests together
        # show the file is what changed rather than the shape.
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(),
            root_view=ROOT_VIEW + LEAF_IDENTIFIED_PANEL,
        )
        self.assertTrue(
            any("RootView.swift" in problem and "SummaryPanel" in problem
                for problem in problems),
            f"the defective component in RootView.swift was not reported: {problems}",
        )

    def test_the_audit_reports_how_much_of_the_target_it_examined(self):
        # A rule that silently reads one file out of many cannot be seen to have
        # narrowed. The audit prints how many type declarations it found and how
        # many files and declarations rule 5 covered, so a regression to a subset
        # is visible in the output of every run rather than only in a fixture.
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "RoviaApp"
            app.mkdir()
            (app / "AppSnapshot.swift").write_text(ENUM_HEAD)
            (app / "RootView.swift").write_text(ROOT_VIEW)
            (app / "Thing.swift").write_text(
                source_leaf_uses() + source_card_argument()
            )
            (app / "Panel.swift").write_text(LEAF_IDENTIFIED_PANEL)
            import subprocess

            result = subprocess.run(
                [sys.executable, str(AUDIT_PATH), "--app", str(app)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            lines = result.stdout.splitlines()

            def number(label: str) -> int:
                # The number *after* the colon. Reading the first number in the line
                # returned the 5 in "rule 5 examined" instead of the count, so the
                # assertion below was comparing 6 against 5 and would have failed
                # for a reason that had nothing to do with coverage.
                for line in lines:
                    if line.startswith(label):
                        _, _, value = line.partition(":")
                        self.assertNotEqual(
                            value.strip(), "", f"{label!r} line carries no value"
                        )
                        return int(value.strip().split()[0])
                self.fail(f"the audit printed no {label!r} line:\n{result.stdout}")

            # Every type declaration in the target, and every file it is in.
            # Counted here from the fixture on disk rather than read back from the
            # audit, so a file being dropped entirely fails the comparison.
            expected_declarations = sum(
                len(
                    re.findall(
                        r"(?m)^[ \t]*(?:(?:public|internal|private|fileprivate|package"
                        r"|final|open)\s+)*(?:struct|class|actor|enum)\s+\w+",
                        (app / path.name).read_text(),
                    )
                )
                for path in sorted(app.rglob("*.swift"))
            )
            self.assertEqual(
                expected_declarations, number("type declarations"),
                "the audit did not count every type declaration in the target",
            )
            self.assertEqual(
                4, number("source files"),
                "the audit did not count every file in the target",
            )
            # And rule 5's own coverage, which is the part that was narrowed. The
            # line reads "N of M", so both numbers are checked: the first against
            # the target, the second against what the scan found.
            examined_line = next(
                line for line in lines if line.startswith("rule 5 examined")
            )
            examined, _, of_total = examined_line.partition(":")[2].strip().partition(" of ")
            self.assertEqual(
                expected_declarations, int(of_total),
                "the audit's own declaration count does not match the target",
            )
            self.assertEqual(
                of_total.strip(), examined.strip(),
                f"rule 5 examined {examined.strip()} of {of_total.strip()}: a "
                "component outside RootView.swift is unchecked again",
            )

    def test_the_real_app_target_is_examined_in_full(self):
        # The same check against the app this repository ships, so the count in the
        # record is the count of the target rather than of a fixture.
        app = REPO_ROOT / "client" / "app" / "ios" / "RoviaApp"
        expected = sum(
            len(
                re.findall(
                    r"(?m)^[ \t]*(?:(?:public|internal|private|fileprivate|package"
                    r"|final|open)\s+)*(?:struct|class|actor|enum)\s+\w+",
                    path.read_text(),
                )
            )
            for path in sorted(app.glob("*.swift"))
        )
        self.assertGreater(expected, 0, "the pattern found no declarations at all")
        result = audit.audit(app)
        self.assertEqual(
            [], result, f"the real app target no longer passes: {result}",
        )
        # `rglob`, not `glob`: this companion walked the target the same way the
        # audit used to, so on the recursion axis it agreed with a narrower audit by
        # construction and could not see that narrowing. The keys are paths relative
        # to the app directory, which is also what the audit reports.
        components = [
            (str(path.relative_to(app)), name)
            for path in sorted(app.rglob("*.swift"))
            for name, _ in audit.component_bodies(
                path.read_text(encoding="utf-8")
            )
        ]
        self.assertEqual(
            expected, len(components),
            "the declaration scan finds a different number of declarations than "
            "the pattern the coverage count is compared against",
        )
        # And the scan reads a subdirectory, which is the axis `rglob` is here for.
        # The shipped target is flat, so the recursion axis is exercised against a
        # copy of it in the test beside this one rather than here.
        self.assertIn(
            ("RootView.swift", "SectionCard"), components,
            "the scan no longer finds a known component in a known file",
        )

    def test_the_scan_reaches_a_nested_declaration(self):
        # The scan's docstring used to say "every top-level struct", which stopped
        # being true when the anchor allowed indentation and classes. Held here so
        # the wording and the behaviour cannot drift apart again.
        source = """
struct Outer {
    struct Inner {
        var identifier: String?
    }
}
"""
        self.assertEqual(
            ["Outer", "Inner"],
            [name for name, _ in audit.component_bodies(source)],
        )

    def test_the_scan_does_not_reach_a_declaration_split_across_lines(self):
        # The other half of that docstring, stated as a limit rather than left
        # implied: the anchor requires the opening brace on the declaration line.
        source = """
struct Split
    : View
{
    var identifier: String?
}
"""
        self.assertEqual(
            [], [name for name, _ in audit.component_bodies(source)],
            "a declaration whose brace is on the next line is now reached, so the "
            "docstring's stated limit is stale",
        )

    def test_a_nested_defective_component_is_found(self):
        # A type nested inside another is a component of its own right, and a
        # defect in it is reported with the file it is in.
        component = """
struct Outer: View {
    struct SummaryPanel<Content: View>: View {
        var identifier: String?
        @ViewBuilder var content: Content

        var body: some View {
            VStack {
                Text("title")
                    .accessibilityIdentifier(identifier ?? "")
                content
            }
        }
    }
}
"""
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(),
            extra_sources={"Panel.swift": component},
        )
        self.assertTrue(
            any("Panel.swift" in problem and "SummaryPanel" in problem
                for problem in problems),
            f"a nested defective component was not reported: {problems}",
        )

    def test_a_brace_in_a_string_literal_does_not_close_the_body(self):
        # (a) The body was read by counting braces, so a `}` inside a string literal
        # closed the type early: the properties below it fell outside the body, the
        # shape predicate no longer matched, and the component was reported OK with
        # byte-identical coverage output. The same module's `bracket_pairs` already
        # skips string literals.
        for name, body in audit.component_bodies(BRACE_IN_STRING_COMPONENT):
            with self.subTest(component=name):
                self.assertTrue(
                    audit.WRAPS_CALLER_CONTENT.search(body),
                    "the body ended at the `}` inside a string literal, so the "
                    "content property is outside it",
                )
                self.assertTrue(
                    audit.TAKES_AN_IDENTIFIER.search(body),
                    "the body ended at the `}` inside a string literal, so the "
                    "identifier property is outside it",
                )
        # And through the audit, where it must be reported.
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(),
            extra_sources={"Panel.swift": BRACE_IN_STRING_COMPONENT},
        )
        self.assertTrue(
            any("SummaryPanel" in problem for problem in problems),
            f"a component with a brace in a string literal was reported OK: {problems}",
        )

    def test_an_opening_brace_in_a_string_literal_does_not_lose_the_component(self):
        # The other direction, which was the more silent one: the `}` case produced a
        # truncated body, while the `{` case made the brace walk never close and the
        # component vanished from the scan entirely — with the coverage count
        # dropping by one and nothing else changing.
        for name, body in audit.component_bodies(BRACE_IN_STRING_COMPONENT):
            with self.subTest(component=name):
                self.assertIn(
                    "var body: some View", body,
                    "the body ended before its own `body` property, so the `{` "
                    "inside a string literal was counted as a brace",
                )
        self.assertEqual(
            ["SummaryPanel"],
            [name for name, _ in audit.component_bodies(BRACE_IN_STRING_COMPONENT)],
        )

    def test_a_defective_component_in_a_subdirectory_is_found(self):
        # (b) `app_dir.glob("*.swift")` is not recursive. Xcode lists sources with a
        # relative path under a group, so a source in a subdirectory is compiled and
        # was therefore unchecked while the audit claimed to read every file in the
        # target.
        problems = self.run_audit(
            source_leaf_uses() + source_card_argument(),
            extra_sources={"Components/Panel.swift": LEAF_IDENTIFIED_PANEL},
        )
        self.assertTrue(
            any("SummaryPanel" in problem for problem in problems),
            f"a component in a subdirectory was reported OK: {problems}",
        )
        self.assertTrue(
            any("Components/Panel.swift" in problem for problem in problems),
            f"the finding does not name the subdirectory file: {problems}",
        )

    def test_the_reported_coverage_counts_subdirectory_sources(self):
        # The coverage test has to count the target independently of the audit's own
        # traversal, or a non-recursive walk makes both sides agree on a smaller
        # target and nothing fails. `rglob` here is the independent count.
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "RoviaApp"
            (app / "Components").mkdir(parents=True)
            (app / "AppSnapshot.swift").write_text(ENUM_HEAD)
            (app / "RootView.swift").write_text(ROOT_VIEW)
            (app / "Thing.swift").write_text(
                source_leaf_uses() + source_card_argument()
            )
            (app / "Components" / "Panel.swift").write_text(LEAF_IDENTIFIED_PANEL)
            import subprocess

            result = subprocess.run(
                [sys.executable, str(AUDIT_PATH), "--app", str(app)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            independent = sorted(
                str(path.relative_to(app)) for path in app.rglob("*.swift")
            )
            # Named, not counted by hand: the four files written above, and the
            # assertion below compares the audit's own count against this list, so a
            # narrower traversal has to disagree with it.
            self.assertEqual(
                ["AppSnapshot.swift", "Components/Panel.swift", "RootView.swift",
                 "Thing.swift"],
                independent,
            )
            reported = next(
                line for line in result.stdout.splitlines()
                if line.startswith("source files")
            )
            count = int(reported.partition(":")[2].strip())
            self.assertEqual(
                len(independent), count,
                f"the audit reports {count} source files while the target holds "
                f"{independent}, so its traversal is narrower than the target",
            )

    def test_a_declaration_behind_an_attribute_is_reached(self):
        # (c) The anchor sat on the declaration keyword, so anything on the line
        # before it — an attribute, `indirect` — hid the type.
        for label, declaration in sorted(ATTRIBUTE_DECLARATIONS.items()):
            with self.subTest(declaration=label):
                source = declaration + """
    var identifier: String?
    var content: some View
}
"""
                found = [
                    name for name, _ in audit.component_bodies(source)
                ]
                self.assertEqual(
                    ["Panel"], found,
                    f"a declaration written {label} is not reached: {found}",
                )

    def test_a_defective_component_behind_an_attribute_is_reported(self):
        for label, declaration in sorted(ATTRIBUTE_DECLARATIONS.items()):
            with self.subTest(declaration=label):
                component = declaration + """
    var identifier: String?
    var content: some View

    var body: some View {
        VStack {
            Text("title")
                .accessibilityIdentifier(identifier ?? "")
            content
        }
    }
}
"""
                problems = self.run_audit(
                    source_leaf_uses() + source_card_argument(),
                    extra_sources={"Panel.swift": component},
                )
                self.assertTrue(
                    any("Panel" in problem for problem in problems),
                    f"a defective component declared {label} was reported OK: {problems}",
                )

    def test_a_declaration_with_its_brace_on_a_line_after_its_name_is_not_reached(self):
        # The other half of that docstring, stated as a limit: the anchor needs the
        # declaration's opening brace on the same line as its name.
        source = """struct Panel
    : View
{
    var identifier: String?
    var content: some View
}
"""
        self.assertEqual(
            [], [name for name, _ in audit.component_bodies(source)],
            "a declaration split across lines is now reached, so the stated limit "
            "is stale",
        )

    def test_a_contain_treated_wrapping_component_is_reported(self):
        # (e) The second condition is the bare word `accessibilityElement`, so it
        # accepts `.contain` as well as `.combine`. That is deliberate — both are a
        # container role, and a component that wraps caller-supplied content should
        # not claim one itself either way — and `.combine` is the case already
        # covered. This is the other reading, held here so the asymmetry is tested
        # rather than assumed.
        for treatment in (".combine", ".contain"):
            with self.subTest(treatment=treatment):
                component = f"""
struct Panel<Content: View>: View {{
    var identifier: String?
    @ViewBuilder var content: Content

    var body: some View {{
        VStack {{
            content
        }}
        .accessibilityElement(children: {treatment})
        .accessibilityIdentifier(identifier ?? "")
    }}
}}
"""
                problems = self.run_audit(
                    source_leaf_uses() + source_card_argument(),
                    root_view=ROOT_VIEW + component,
                )
                self.assertTrue(
                    any("Panel" in problem and "container role of its own" in problem
                        for problem in problems),
                    f"a component applying {treatment} to caller-supplied content "
                    f"was accepted: {problems}",
                )

    def test_indirect_declarations_are_still_reached(self):
        # The anchor's `indirect` alternative is load-bearing and stays. An enum or
        # class declared `indirect` is a real type declaration, and a pattern without
        # it hides the type — which is the same class of miss as an attribute.
        for label, declaration in (
            ("indirect enum", "indirect enum Panel {"),
            ("indirect class", "indirect class Panel {"),
        ):
            with self.subTest(declaration=label):
                source = declaration + """
    var identifier: String?
    var content: some View
}
"""
                self.assertEqual(
                    ["Panel"], [name for name, _ in audit.component_bodies(source)],
                    f"a declaration written {label} is not reached",
                )

    def test_a_declaration_needing_no_qualifier_before_the_keyword_is_reached(self):
        # The other direction, and the reason the `case` alternative was removed. The
        # anchor accepts attributes and `indirect`; it does not accept `case`, because
        # `case struct` is not valid Swift, so no valid declaration needs it. If a
        # qualifier is ever added to the anchor, this holds the set of qualifiers that
        # have a real form.
        for label, source in (
            ("bare struct", "struct Panel: View {\n    var identifier: String?\n}\n"),
            ("bare class", "class Panel {\n    var identifier: String?\n}\n"),
            ("bare enum", "enum Panel {\n    var identifier: String?\n}\n"),
            ("bare actor", "actor Panel {\n    var identifier: String?\n}\n"),
        ):
            with self.subTest(declaration=label):
                self.assertEqual(
                    ["Panel"], [name for name, _ in audit.component_bodies(source)],
                    f"a plain {label} is not reached, so the anchor is too narrow",
                )

    def test_an_attribute_on_the_same_line_as_the_declaration_is_reached(self):
        # The form that carries the weight. An attribute on its own line leaves the
        # declaration line to match on its own, so a test written that way passes
        # even with attribute support removed — which is what the first version of
        # this test did. Same line, so the attribute has to be consumed for the
        # declaration to be found at all.
        for label, head in (
            ("no arguments", "@MainActor struct Panel: View {"),
            ("one argument", "@ViewBuilder(a: 1) struct Panel: View {"),
            ("a nested argument", "@Foo(Bar(baz: 2)) struct Panel: View {"),
            ("attribute then a modifier", "@MainActor public struct Panel: View {"),
            ("two attributes", "@MainActor @ViewBuilder(a: 1) struct Panel: View {"),
        ):
            with self.subTest(head=label):
                source = head + """
    var identifier: String?
    var content: some View
}
"""
                self.assertEqual(
                    ["Panel"], [name for name, _ in audit.component_bodies(source)],
                    f"a declaration written {label} is not reached",
                )

    def test_an_attribute_on_the_line_before_a_declaration_is_reached(self):
        # The other documented form: several attributes, each on its own line, before
        # one declaration. Also checked in the form that requires the attributes, by
        # joining them to the declaration line, so this cannot pass on the
        # declaration line alone.
        multiline = """@MainActor
@ViewBuilder(a: 1)
public struct Panel: View {
    var identifier: String?
    var content: some View
}
"""
        self.assertEqual(
            ["Panel"], [name for name, _ in audit.component_bodies(multiline)],
            "a declaration behind attributes on separate lines is not reached",
        )
        # The same attributes joined onto one line, so the declaration cannot be
        # found by its own line and the attributes have to be consumed. Joining with
        # a no-op left this passing with attribute support removed entirely.
        joined = " ".join(
            "@MainActor @ViewBuilder(a: 1) public struct Panel: View {".split()
        ) + "\n}\n"
        self.assertEqual(
            ["Panel"],
            [name for name, _ in audit.component_bodies(joined)],
            "the attributes were not needed for this declaration to be found, so "
            "this assertion checks nothing",
        )

    def test_a_typealias_is_not_a_declaration_this_scan_sees(self):
        # One of the stated limits, held — and the fixture is chosen so the limit is
        # what decides it. A bare `typealias Panel = Int` has no brace, so the stock
        # anchor rejects it for want of a `{` whether or not it accepts the keyword,
        # and the first version of this test therefore passed even with `typealias`
        # added to the anchor. The brace in the trailing comment is what makes the
        # two anchors differ, so this fails if the anchor ever widens to match one.
        for source in (
            "typealias Panel = Int  // {\n",
            "typealias Panel = SomeView { get }  //\n",
        ):
            with self.subTest(source=source.splitlines()[0]):
                self.assertEqual(
                    [], audit.component_bodies(source),
                    "a typealias was matched as a declaration; the anchor's keyword "
                    "set has widened",
                )

    @staticmethod
    def _ends_a_sentence(line: str) -> bool:
        return line.rstrip().endswith((".", "?", "!", ":"))

    @staticmethod
    def split_enumeration_blocks(passage: str) -> list[list[str]]:
        """A bulleted passage as blocks: a bullet and its continuations together.

        One definition, because there were two copies of this loop and only
        `_ends_a_sentence` was shared — so a rule could be weakened in one direction
        and the other kept testing the old behaviour, with nothing noticing.

        The rule a continuation obeys: an indented line that continues a sentence the
        previous line left open. A blank line always ends a block. An indented line
        whose predecessor finished its sentence is a new paragraph, and becomes a
        block of its own — that is what stops prose at the continuation column from
        being absorbed into the bullet above it.

        Against the audit's own docstring this is decidable rather than guessed: every
        continuation it has follows a line that had not ended a sentence, and every
        bullet follows one that had. `test_a_wrapped_continuation_is_still_read_as_a_continuation`
        states the other half, that a genuine wrapped continuation is one block.
        """
        blocks: list[list[str]] = []
        current: list[str] | None = None
        for line in passage.splitlines():
            if not line.strip():
                if current is not None:
                    blocks.append(current)
                current = None
                continue
            indented = line.startswith("     ")
            continues = (
                indented
                and current
                and not AuditTests._ends_a_sentence(current[-1])
            )
            if re.match(r"^   - ", line) or not continues:
                if current is not None:
                    blocks.append(current)
                current = [line]
            else:
                current.append(line)
        if current is not None:
            blocks.append(current)
        return blocks

    def test_no_prose_sits_between_the_bullets_of_the_enumeration(self):
        """The six conditions are six bullets and nothing else.

        Two earlier versions of this check did not do that, and both are worth
        naming. The first keyed the note-outside assertion on the literal phrase
        "cannot cover" and counted bullets, so prose between two conditions passed.
        The second walked the list but treated *any* line at five spaces, and any
        blank line, as a continuation — so a prose paragraph at the continuation
        column was absorbed into the bullet above it and passed, and a
        blank-line-separated paragraph at that column passed too.

        A continuation is defined here so it can be checked: an indented line that
        continues the sentence the previous line left open. A line at the
        continuation column that follows a line which *finished* its sentence is not
        a continuation, it is a new paragraph, and it becomes a block of its own. A
        blank line always ends a block. Both rules hold for every continuation the
        audit's docstring actually has, and both fail on the paragraphs they are
        meant to reject.
        """
        docstring = (REPO_ROOT / "tools/ci/audit-accessibility-identifiers.py").read_text(
            encoding="utf-8"
        )
        enumeration = docstring[
            docstring.index("A component is checked when all of these hold"):
            docstring.index("Two limits are listed here.")
        ]
        # From the first bullet: the two lines introducing the list are its
        # preamble, not a condition, and counting them made the total eight.
        enumeration = enumeration[enumeration.index("   - "):]
        blocks = self.split_enumeration_blocks(enumeration)

        self.assertEqual(
            6, len(blocks),
            f"the enumeration holds {len(blocks)} blocks, not the six conditions "
            "the docstring says a component is checked against: "
            + " | ".join(block[0].strip()[:40] for block in blocks),
        )
        for index, block in enumerate(blocks, 1):
            with self.subTest(condition=index):
                self.assertRegex(
                    block[0], r"^   - ",
                    f"block {index} is not a bullet, so prose sits between the "
                    f"conditions: {block[0].strip()[:70]!r}",
                )
        # The note the first version keyed on is prose, so it cannot be inside.
        self.assertNotIn(
            "cannot cover", enumeration,
            "the note about the untested gap is inside the enumeration again",
        )
        # And the limits follow the enumeration, in their own block.
        limits = docstring[
            docstring.index("Two limits are listed here."): docstring.index(
                "One thing this scan cannot cover is stated separately"
            )
        ]
        self.assertNotIn(
            "A component is checked", limits,
            "the enumeration is stated inside the limits block",
        )

    def test_a_wrapped_continuation_is_still_read_as_a_continuation(self):
        """The other direction: the rule must not reject a real continuation.

        A check that closes the gap by treating every indented line as prose would
        fail on the audit's own docstring, and would then be weakened. This states
        the positive case: a bullet whose sentence is left open across an indented
        line is one block, not two.
        """
        for label, passage, expected in (
            (
                "a sentence left open",
                "   - It is reached: `struct`, or\n     `class`, at any depth.\n",
                1,
            ),
            (
                "a closed sentence then prose",
                "   - It is reached.\n     Note: out of reach.\n",
                2,
            ),
            (
                "a blank line then an indented paragraph",
                "   - It is reached.\n\n     Note: out of reach.\n",
                2,
            ),
        ):
            with self.subTest(shape=label):
                blocks = self.split_enumeration_blocks(passage)
                self.assertEqual(
                    expected, len(blocks),
                    f"{label}: got {len(blocks)} blocks, expected {expected}",
                )

    def test_both_directions_go_through_the_one_block_splitter(self):
        """Two directions, one rule.

        There were two copies of the block-splitting loop — the negative direction
        over the audit's own docstring and the positive direction over synthetic
        passages — and only `_ends_a_sentence` was shared. So the rule could be
        weakened in one copy and the other kept testing the old behaviour, and the
        positive direction could not detect a weakening of the negative one at all.

        This asserts that the splitter is defined once under this name and that both
        tests call it, by reading the test file's own source. Reading it rather than
        calling the tests is the point: a test cannot observe which definition
        another test used.

        What it does not check: a copy of the rule under a *different* name, which
        neither direction calls and which this cannot see. That would be dead code
        rather than a second copy of a live rule, and the two are different problems.
        """
        source = (REPO_ROOT / "tools/ci/test_audit_accessibility_identifiers.py").read_text(
            encoding="utf-8"
        )
        # Counted with the parser, not with `source.count`: this test contains the
        # definition's name as a string literal, so a text count matches itself and
        # reported three definitions for one.
        import ast

        definitions = [
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef)
            and node.name == "split_enumeration_blocks"
        ]
        self.assertEqual(
            1, len(definitions),
            "the block splitter is defined more than once under this name, so the "
            f"two directions can disagree: {definitions}",
        )
        # And the sentence-end test it calls is defined once, also by the parser:
        # this test names both in string literals, so a text count matches itself.
        for shared in ("_ends_a_sentence", "split_enumeration_blocks"):
            with self.subTest(shared=shared):
                self.assertEqual(
                    1,
                    len([
                        node for node in ast.walk(ast.parse(source))
                        if isinstance(node, ast.FunctionDef) and node.name == shared
                    ]),
                    f"{shared} is defined more than once under this name, so the "
                    "rule can diverge",
                )
        for name in (
            "test_no_prose_sits_between_the_bullets_of_the_enumeration",
            "test_a_wrapped_continuation_is_still_read_as_a_continuation",
        ):
            with self.subTest(direction=name):
                self.assertIn(f"def {name}(", source)
        # And both call the helper rather than walking the list themselves.
        for name in (
            "test_no_prose_sits_between_the_bullets_of_the_enumeration",
            "test_a_wrapped_continuation_is_still_read_as_a_continuation",
        ):
            body = source[
                source.index(f"def {name}("): source.index("def ", source.index(f"def {name}(") + 1)
            ]
            with self.subTest(direction=name):
                self.assertIn(
                    "self.split_enumeration_blocks(", body,
                    f"{name} does not use the shared splitter",
                )
                self.assertNotIn(
                    "for line in", body,
                    f"{name} walks the lines itself, so it is not going through "
                    "the shared rule",
                )

    def test_weakening_the_shared_splitter_fails_both_directions(self):
        """Check the checker: one mutation, both directions must fail.

        The shared splitter is replaced with a weaker one — it returns the whole
        passage as a single block, which is how the negative direction was defeated
        before, when any indented line was absorbed as a continuation — and both
        tests are required to fail. If only the negative direction noticed, the
        positive one would still be asserting against a rule the suite no longer
        applies, which is the drift this collapse exists to prevent.

        The cases are built with a method name that is not under test and the
        direction's method is called unbound. Constructing a case *named* for the
        method under test is what the first version did, and `TestCase.__init__`
        validates that name before the assertion ever runs.
        """
        negative = "test_no_prose_sits_between_the_bullets_of_the_enumeration"
        positive = "test_a_wrapped_continuation_is_still_read_as_a_continuation"
        original = AuditTests.__dict__["split_enumeration_blocks"]
        self.assertIsInstance(
            original, staticmethod,
            "the shared splitter is no longer a staticmethod, so swapping it out "
            "for a weaker one is not the same operation",
        )

        def weakened(passage: str) -> list[list[str]]:
            return [passage.splitlines()]

        try:
            AuditTests.split_enumeration_blocks = staticmethod(weakened)
            case = AuditTests("test_clean_source_passes")
            for direction in (negative, positive):
                method = getattr(AuditTests, direction)
                with self.subTest(direction=direction):
                    with self.assertRaises(AssertionError):
                        method(case)
        finally:
            # The staticmethod wrapper has to go back on: assigning the plain
            # function would turn the attribute into an instance method, and every
            # later call would then pass `self` as the passage.
            AuditTests.split_enumeration_blocks = original
        # And with the real splitter both pass, so the failures above were the
        # mutation and not two tests that always fail.
        case = AuditTests("test_clean_source_passes")
        for direction in (negative, positive):
            with self.subTest(direction=direction):
                getattr(AuditTests, direction)(case)

    def test_every_stated_limit_is_held_by_a_test(self):
        """A property over the list, not a pair of names.

        The previous version checked two hard-coded limits against two hard-coded
        test names and asserted the word "macro" was absent. Adding a brand-new
        limit to the list left every test green, because nothing compared the list's
        size to anything.

        This walks the list instead. Every entry must be a bullet, must name a term
        in backticks, and that term must occur in the name of some test in this
        class. So a limit added without a test has no test to be named after and
        fails, whether it was spelled with a backticked term or not — and the
        bullets it does have to be are the list's only entries, so the note that
        follows it cannot be mistaken for one.
        """
        docstring = (REPO_ROOT / "tools/ci/audit-accessibility-identifiers.py").read_text(
            encoding="utf-8"
        )
        listed = docstring[
            docstring.index("Two limits are listed here."): docstring.index(
                "One thing this scan cannot cover is stated separately"
            )
        ]
        note = docstring[docstring.index("One thing this scan cannot cover"):]
        # The untested gap is not in the list, and says so.
        self.assertIn("macro", note.lower())
        self.assertIn("not in the source", note)
        self.assertNotIn("macro", listed.lower())

        # A test name cannot contain a space, so both sides are compared with spaces
        # and underscores unified. Without that, a limit stated as "line after" could
        # never be matched by a test named `..._line_after_...` and the check would
        # only ever pass by having no limits.
        test_names = " ".join(
            name
            for name, _ in inspect.getmembers(type(self), predicate=inspect.isfunction)
            if name.startswith("test_")
        ).replace(" ", "_")
        entries = re.findall(r"(?m)^   - (.+)$", listed)
        self.assertTrue(
            entries, f"no limits are listed at all, so this check is vacuous:\n{listed}"
        )
        for entry in entries:
            terms = re.findall(r"`([^`]+)`", entry)
            with self.subTest(limit=entry[:52]):
                self.assertTrue(
                    terms,
                    "this limit names no term in backticks, so no test can be named "
                    "after it",
                )
                self.assertTrue(
                    any(term.replace(" ", "_") in test_names for term in terms),
                    f"no test in this class is named after any of {terms}, so this "
                    "limit is stated without one",
                )

    def test_the_anchor_accepts_no_qualifier_but_indirect(self):
        """The `case` claim, held in both directions.

        `case` sat in the anchor's qualifier list and in the docstring and the code
        comment, and nothing held any of that: deleting the alternative left every
        test green, and re-adding it would too.

        What is inspected is stated here because the previous version claimed more.
        It said the check covered "the anchor or the comment above it" — and the
        slice it read began at `TYPE_DECLARATION = re.compile(`, which is *below*
        that comment. So the comment was never inspected, and it is where the removal
        of `case` is discussed and where the word `case` legitimately appears. The
        slice is widened to include it, and the assertion about `case` is
        restricted to the pattern itself, because the comment is *supposed* to
        mention the alternative it removed.
        """
        source = (REPO_ROOT / "tools/ci/audit-accessibility-identifiers.py").read_text(
            encoding="utf-8"
        )
        # The comment above the anchor is included, and the pattern is taken from it
        # separately: the comment is required to explain the removal, so it mentions
        # `case` on purpose and asserting its absence there would forbid the
        # explanation.
        block = source[source.index("# A type declaration"): source.index(
            "# \"Wraps caller-supplied content\""
        )]
        pattern = block[block.index("TYPE_DECLARATION = re.compile("):]
        pattern = pattern[: pattern.index(")\n") + 2]
        self.assertNotIn(
            "case", pattern,
            "`case` is in the anchor's pattern again; it is not valid Swift before a "
            "declaration and nothing needs it",
        )
        # `indirect` is load-bearing and stays.
        self.assertIn("indirect", pattern)
        # The comment above the anchor is part of what is inspected, and it has to
        # carry the *explanation*, not the word. `assertIn("case", ...)` passed for a
        # one-line `# `case`.` — a comment that says nothing — and the previous
        # version's comment claimed this held the explanation while the assertion
        # only held a token. So both the subject and the reason are required, and the
        # reason is the same sentence the module docstring gives.
        explanation = block[: block.index("TYPE_DECLARATION = re.compile(")]
        for required in (
            "`case`",
            "not valid Swift",
            "nothing needed it",
        ):
            with self.subTest(required=required):
                self.assertIn(
                    required, explanation,
                    f"the comment above the anchor no longer says {required!r}, so "
                    "the docstring's pointer to it is stale — the word alone is not "
                    "the explanation",
                )
        # And the keyword set is the four real ones.
        self.assertIsNotNone(
            re.search(r"\(\?:struct\|class\|actor\|enum\)", pattern),
            "the anchor no longer names the four declaration keywords",
        )
        # The docstring must not re-claim it either.
        docstring = re.sub(
            r"\s+", " ", source[: source.index('"""', source.index('"""') + 3) + 3]
        )
        self.assertNotIn(
            "`case`", docstring,
            "the docstring names `case` as a qualifier again",
        )
        self.assertIn(
            "`case struct` is not valid Swift", docstring,
            "the docstring no longer says why no qualifier is needed",
        )

    def test_the_scope_bullet_states_both_attribute_placements(self):
        """The scope statement has to match the anchor, in both directions.

        It said attributes are "on their own lines" while the anchor also accepts
        them on the declaration line, and there is now a test for that form. A
        statement narrower than the implementation is the defect this audit has been
        fixing in itself, so the wording is held here.
        """
        docstring = (REPO_ROOT / "tools/ci/audit-accessibility-identifiers.py").read_text(
            encoding="utf-8"
        )
        flat = re.sub(r"\s+", " ", docstring)
        scope = flat[flat.index("It is a type declaration this scan reaches"):
                     flat.index("No other qualifier is accepted")]
        self.assertIn(
            "on the same line as the keyword", scope,
            "the scope no longer says attributes may share the declaration line",
        )
        self.assertIn(
            "on the lines before it", scope,
            "the scope no longer says attributes may precede the declaration",
        )
        self.assertNotIn(
            "on their own lines", scope,
            "the scope still says attributes are only on their own lines, which is "
            "narrower than the anchor",
        )
        # And both placements are reached, so the wording is not vacuous.
        for label, source in (
            ("same line", "@MainActor struct Panel: View {\n}\n"),
            ("line before", "@MainActor\nstruct Panel: View {\n}\n"),
        ):
            with self.subTest(placement=label):
                self.assertEqual(
                    ["Panel"],
                    [name for name, _ in audit.component_bodies(source)],
                    f"an attribute {label} the declaration is not reached, so the "
                    "wording above is wrong",
                )

    def test_the_real_app_coverage_is_derived_from_a_recursive_walk(self):
        # (4) The companion test walked the target with the same non-recursive
        # `glob` the audit used to have, so on the recursion axis it agreed with a
        # narrower audit by construction. `rglob` here, and the file list is named.
        app = REPO_ROOT / "client" / "app" / "ios" / "RoviaApp"
        found = sorted(
            str(path.relative_to(app)) for path in app.rglob("*.swift")
        )
        self.assertTrue(found, "the app target holds no Swift sources at all")
        self.assertEqual(
            sorted(set(found)), found, "the walk produced a path twice"
        )
        for name in ("RootView.swift", "AppSnapshot.swift"):
            self.assertIn(name, found)
        # The flat layout is stated, because it is why the recursion axis cannot be
        # exercised against the shipped target and needs the isolated copy below.
        self.assertEqual(
            [], [name for name in found if "/" in name],
            "the app target now has subdirectory sources, so the isolated-copy test "
            "should be run against it directly",
        )

    def test_a_subdirectory_source_in_a_copy_of_the_real_target_is_reported(self):
        # (4) The recursion axis, exercised against the real target's own sources
        # rather than a four-file fixture: the real app is copied, a defective
        # component is added in a subdirectory, and the audit has to find it. A
        # non-recursive walk would report OK on the real target too.
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "RoviaApp"
            shutil.copytree(
                REPO_ROOT / "client" / "app" / "ios" / "RoviaApp", app
            )
            # A subdirectory the copied target does not have.
            (app / "Components").mkdir()
            (app / "Components" / "Panel.swift").write_text(
                LEAF_IDENTIFIED_PANEL
            )
            import subprocess

            result = subprocess.run(
                [sys.executable, str(AUDIT_PATH), "--app", str(app)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                1, result.returncode,
                f"the audit reported OK for a component in a subdirectory of the "
                f"real target: {result.stdout}{result.stderr}",
            )
            self.assertIn(
                "SummaryPanel", result.stdout + result.stderr,
                "the finding does not name the component",
            )
            self.assertIn(
                "Components/Panel.swift", result.stdout + result.stderr,
                f"the finding does not name the subdirectory file: "
                f"{result.stdout}{result.stderr}",
            )
            # The real sources were read too, not replaced by the copy: the
            # declaration count has to be far above the fixture's.
            self.assertRegex(
                result.stdout, r"type declarations: (?!1\b)\d+",
                "the audit saw too few declarations in the copied real target",
            )

    def test_real_app_target_passes(self):
        problems = audit.audit(REPO_ROOT / "client" / "app" / "ios" / "RoviaApp")
        self.assertEqual(problems, [], f"the shipped app target must satisfy the audit: {problems}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
