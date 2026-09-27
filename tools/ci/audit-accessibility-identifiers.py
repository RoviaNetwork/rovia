#!/usr/bin/env python3
"""Audit the iOS accessibility identifier contract in the app target.

The rules this script enforces, and why:

1. Every identifier constant is declared exactly once, is namespaced under
   "rovia.", contains no whitespace, and is not duplicated.
2. Every declared constant is classified as either a container identifier or an
   element identifier, and the two sets are disjoint. Views use this
   classification to decide how an identifier may be attached.
3. A container identifier is never attached to a container view by a bare
   .accessibilityIdentifier call. SwiftUI propagates an identifier set on a
   container to its children and overrides their own identifiers, so container
   identifiers must go through the container treatment
   (ConditionalAccessibilityIdentifier) that applies
   .accessibilityElement(children: .contain) first.
4. Every declared constant actually reaches a view, either directly, through the
   container modifier, or as a component argument.
5. Every container-level component applies the container treatment. "Container
   level" means a component that wraps caller-supplied content, because that
   content's identifiers are the ones at risk. A component that builds its own
   children and merges them with `.accessibilityElement(children: .combine)` is
   meant to collapse to a single element and is not a container in this sense.

   The scope, stated exactly, because the first version of this rule was narrower
   than this text claimed. A component is checked when all of these hold, and the
   tests hold both directions of each:

   - It is a type declaration this scan reaches: `struct`, `class`, `actor` or
     `enum`, preceded by one or more attributes — on the same line as the keyword or
     on the lines before it (`@MainActor`, `@Observable`, `@ViewBuilder(a: 1)`,
     `@Foo(Bar(baz: 2))`) — by
     any of `public`, `internal`, `private`, `fileprivate`, `package`, `final` or
     `open`, and by `indirect` for an enum or class. Indentation does not exclude
     it, so a type nested inside another is reached and examined as a component of
     its own. No other qualifier is accepted, and none is needed: `case struct` is
     not valid Swift.
   - The scan reads every `.swift` file under the app directory, at any depth,
     because Xcode compiles a source listed with a relative path under a group. It
     prints how many files and declarations it found and how many rule 5 examined,
     so a narrowing to a subset shows up in the output of every run.
   - Its body is read by pairing braces with string literals skipped, so a `{` or
     `}` inside a string does not change where the type ends.

   - It wraps caller-supplied content, spelled `@ViewBuilder var content: Content`,
     `@ViewBuilder var content: () -> Content`, `let content: Content` or
     `var content: some View` — a property named exactly `content`.
   - It takes an identifier, spelled `identifier`, `accessibilityIdentifier`,
     `containerIdentifier` or any other name ending in `identifier`, with type
     `String`, `String?`, `LocalizedStringKey` or `String Resource`.
   - It declares `content` as a *property*. This is what excludes the treatment
     itself: `ConditionalAccessibilityIdentifier` takes `content` as a function
     parameter, so the shape predicate does not match it. There is no name check.

   Two limits are listed here. A test walks this list and requires every entry to
   name, in backticks, something a test in `test_audit_accessibility_identifiers.py`
   is named after — so a limit added here without a test fails rather than joining a
   list nobody checks:

   - A declaration whose opening brace is on a `line after` its name.
   - A `typealias`, which names a type whose declaration this scan never reads.

   One thing this scan cannot cover is stated separately, after the list, because it
   has no test and cannot have one here: **a declaration produced by a macro
   expansion**. The scan reads source text, and a macro's output is not in the source
   text — there is nothing to write in a fixture that the scan would fail to see, so
   a test for this would pass without proving anything. It remains a real gap, and it
   is a gap in this text rather than in the list above.

   Two conditions are then reported independently, because a component can fail
   both: it does not route its identifier through the treatment, and it applies a
   container role of its own.

   The second condition is the bare word `accessibilityElement`, so it accepts
   `.contain` as well as `.combine`. That is deliberate and asymmetric with rule 3:
   `has_container_treatment` requires `.contain` *by name*, because there the
   question is whether a container's children keep their identifiers, and `.combine`
   answers no. Here the question is whether the component claims a container role of
   its own over caller-supplied content, and both roles claim one, so either is a
   finding. Both readings are tested.

Exit status is 0 when the contract holds and 1 when any rule is violated, so the
command can be used as a local check or a CI step.

Usage:
    python3 tools/ci/audit-accessibility-identifiers.py
    python3 tools/ci/audit-accessibility-identifiers.py --app client/app/ios/RoviaApp
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CONTAINER_VIEWS = (
    "List",
    "ScrollView",
    "NavigationSplitView",
    "VStack",
    "HStack",
    "Group",
    "Form",
    "Section",
    "ContentUnavailableView",
    "RoviaScreen",
)

# A type declaration, with any access modifier and `final`/`open` in front. Named
# once and used both to find declarations and to count them, so the coverage the
# audit prints cannot be computed by a different rule than the one that scans.
# An attribute, `@MainActor` or `@Observable`, and `indirect`, may sit on the lines
# before a declaration, so the anchor accepts them there too: the previous version
# started at the declaration keyword and any of those hid the type. An attribute's
# argument list may itself contain parentheses, so it is matched with a one-level
# allowance rather than up to the first `)`.
#
# `case` was accepted here once and removed: `case struct` is not valid Swift, so
# nothing needed it, and deleting the alternative left every test green — which is
# what "dead" means. Two tests hold the set: one that `indirect enum` and
# `indirect class` are reached, and one that the four bare declaration forms are
# reached with no qualifier at all.
TYPE_DECLARATION = re.compile(
    r"(?m)^[ \t]*(?:(?:@[\w:.]+(?:\([^()]*(?:\([^()]*\)[^()]*)*\))?)\s*)*"
    r"(?:(?:public|internal|private|fileprivate|package|final|open)\s+)*"
    r"(?:indirect\s+)*"
    r"(?:struct|class|actor|enum)\s+(\w+)[^{\n]*\{"
)

# "Wraps caller-supplied content" and "takes an identifier", in the spellings
# SwiftUI code actually uses. Both were single patterns matching one spelling, so a
# component written `@ViewBuilder var content: () -> Content` or
# `let content: Content` or `var content: some View`, or holding
# `accessibilityIdentifier` / `containerIdentifier` / `LocalizedStringKey`, was
# skipped and the audit reported OK.
WRAPS_CALLER_CONTENT = re.compile(
    r"\b(?:var|let)\s+content\s*"
    r"(?::\s*(?:Content\b|some\s+View\b)|:\s*\(\s*\)\s*->\s*\w+)"
)
TAKES_AN_IDENTIFIER = re.compile(
    r"\b\w*[Ii]dentifier\??\s*:\s*"
    r"(?:String\??|LocalizedStringKey\b|String\s+Resource\b)"
)

APPLIED_PATTERNS = (
    r"\.accessibilityIdentifier\(AppAccessibilityIdentifier\.(\w+)\b",
    r"ConditionalAccessibilityIdentifier\(\s*identifier: AppAccessibilityIdentifier\.(\w+)\b",
    r"\bidentifier: AppAccessibilityIdentifier\.(\w+)\b",
    r"\bmessageIdentifier: AppAccessibilityIdentifier\.(\w+)\b",
    r"\bdismissIdentifier: AppAccessibilityIdentifier\.(\w+)\b",
)


def bracket_pairs(text: str) -> dict[int, tuple[int, str | None]]:
    """Map every closing bracket offset to its opening offset and the owning type.

    A single forward scan builds this. Scanning forward avoids the off-by-one
    bracket accounting that a backwards scan gets wrong, and string literals are
    skipped so brackets inside text and SF Symbol names are ignored.
    """
    pairs: dict[int, tuple[int, str | None]] = {}
    stack: list[tuple[str, int, str | None]] = []
    i = 0
    length = len(text)
    while i < length:
        character = text[i]
        if character == '"':
            i += 1
            while i < length:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            i += 1
            continue
        if character in "([{":
            owner = identifier_before(text, i)
            stack.append((character, i, owner))
        elif character in ")]}":
            if stack:
                opener, open_index, owner = stack.pop()
                pairs[i] = (open_index, owner)
        i += 1
    return pairs


def resolve_base_view(text: str, index: int, pairs: dict[int, tuple[int, str | None]]) -> str | None:
    """Return the view type that an identifier at ``index`` is a modifier on."""
    position = index - 1
    while position >= 0 and text[position] in " \t\n\r":
        position -= 1
    if position < 0:
        return None

    character = text[position]
    if character in ")]}":
        pair = pairs.get(position)
        if pair is None:
            return None
        open_index, owner = pair
        if owner and owner[0].isupper():
            return owner
        return resolve_base_view(text, open_index, pairs)

    start, end = identifier_bounds(text, position)
    if end < start:
        return None
    name = text[start : end + 1]
    return name if name and name[0].isupper() else None


def identifier_before(text: str, bracket_index: int) -> str | None:
    end = bracket_index - 1
    while end >= 0 and text[end] in " \t\n\r":
        end -= 1
    if end < 0:
        return None
    start, end = identifier_bounds(text, end)
    if end < start:
        return None
    return text[start : end + 1]


def identifier_bounds(text: str, position: int) -> tuple[int, int]:
    """Return the start and end offsets of the identifier covering ``position``."""
    start = position
    while start >= 0 and (text[start].isalnum() or text[start] == "_"):
        start -= 1
    start += 1
    end = position
    while end >= 0 and (text[end].isalnum() or text[end] == "_"):
        end += 1
    end -= 1
    return start, end




def has_container_treatment(text: str, index: int) -> bool:
    """True when the element already has the *container* treatment.

    The check used to be for the bare word `accessibilityElement` anywhere in the
    preceding 600 characters, which is satisfied by
    `.accessibilityElement(children: .combine)`. That is the opposite of what rule 3
    asks for: `.combine` merges the container's children into the container's own
    element and discards their individual identifiers, while `.contain` keeps them,
    so a container identifier guarded by `.combine` is guarded by the thing rule 3
    exists to prevent.

    The treatment is therefore required by name — either the container modifier,
    which applies `.contain` itself, or the `.contain` call it applies.
    """
    window = text[max(0, index - 600) : index]
    return (
        "accessibilityElement(children: .contain)" in window
        or "ConditionalAccessibilityIdentifier" in window
    )


def component_bodies(root_source: str) -> list[tuple[str, str]]:
    """Every type declaration the pattern reaches, as (name, body text).

    Not "top-level", and not only structs. The anchor is `TYPE_DECLARATION`, which
    matches `struct`, `class`, `actor` and `enum` with any access modifier or
    `final`/`open` in front, at any indentation — so a type nested inside another is
    reached and examined as a component in its own right. Two tests hold that: one
    for a nested declaration being found, one for the brace-on-the-next-line form
    being *not* found, which is the known limit.

    The body is read by brace balance from the declaration's own opening brace,
    rather than by a regex for the whole type, because a body can contain the
    sequence that ends a non-greedy match and a component check that silently saw
    the first nine lines of a forty-line struct would be worse than no check.
    """
    found: list[tuple[str, str]] = []
    # One forward scan gives the offset of every closing brace and the offset of
    # the one that opened it, already skipping string literals. Reused rather than
    # reimplemented, because the previous hand-rolled brace count was not: a `}`
    # inside a string literal closed the type early, so the properties below it fell
    # outside the body and the component passed the shape predicate on a body that
    # no longer contained its own properties. A `{` inside a string literal was
    # worse — the walk never closed, so the component disappeared from the scan and
    # only the coverage count moved.
    pairs = bracket_pairs(root_source)
    # Invert the map once, so finding a declaration's own closing brace is a lookup
    # rather than a scan that has to pick the right one.
    closing_for = {open_index: close for close, (open_index, _) in pairs.items()}
    for match in TYPE_DECLARATION.finditer(root_source):
        # The declaration's own opening brace is the last character of its head, and
        # the closing brace wanted is the one that pairs with *that* offset. Taking
        # the first closing brace at or after it instead truncates the body at the
        # first nested block, which is the same defect this function was just fixed
        # for.
        head_end = match.end() - 1
        close = closing_for.get(head_end)
        if close is None:
            continue
        found.append((match.group(1), root_source[match.end(): close]))
    return found



def audit(app_dir: Path) -> list[str]:
    # Recursive, because Xcode lists a source with a relative path under a group
    # and compiles it: a file in a subdirectory is part of the target. `glob` is not
    # recursive, so such a source was compiled and unchecked while this audit
    # claimed to read every file in the target. Keyed by the path relative to the
    # app directory, so a finding names where the component is and two files of the
    # same name in different directories do not collide.
    sources = {
        str(path.relative_to(app_dir)): path.read_text(encoding="utf-8")
        for path in sorted(app_dir.rglob("*.swift"))
    }
    if "AppSnapshot.swift" not in sources:
        return [f"{app_dir} does not contain AppSnapshot.swift"]
    snapshot = sources["AppSnapshot.swift"]
    all_text = "\n".join(sources.values())

    match = re.search(r"enum AppAccessibilityIdentifier \{(.*?)\n\}", snapshot, re.S)
    if match is None:
        return ["AppAccessibilityIdentifier was not found in AppSnapshot.swift"]
    enum = match.group(1)

    # Every declaration, not a dict. `dict(re.findall(...))` keeps the last value
    # for a repeated name and drops the earlier one, so a constant declared twice
    # — with the same value or a different one — was reported as declared once and
    # the rule that every identifier is declared exactly once was enforced by
    # nothing. The pairs are kept, grouped by name, so a repeat can be reported
    # with both values.
    # Each declaration's line in the *file*, found by walking the declarations in
    # order with a cursor over the whole source. Two things this replaces were
    # wrong: counting newlines inside the enum body gave a line number relative to
    # that slice rather than the file, and `str.index` returns the first match for
    # the text, so two declarations of the same constant spelled the same way were
    # both reported at the first one's line. A cursor is also the only way to tell
    # those two apart at all.
    declarations: list[tuple[str, str, int]] = []
    cursor = match.start(1)
    declaration_pattern = re.compile(r'static let (\w+) = "([^"]+)"')
    while True:
        found = declaration_pattern.search(snapshot, cursor)
        if found is None or found.start() >= match.end(1):
            break
        declarations.append(
            (found.group(1), found.group(2), snapshot[: found.start()].count("\n") + 1)
        )
        cursor = found.end()
    if not declarations:
        return ["AppAccessibilityIdentifier declares no string constants"]

    by_name: dict[str, list[tuple[str, int]]] = {}
    for name, value, line in declarations:
        by_name.setdefault(name, []).append((value, line))
    declared = {name: values[0][0] for name, values in by_name.items()}

    def list_names(list_name: str) -> list[str]:
        found = re.search(r"static let " + list_name + r"[^=]*= \[(.*?)\n    \]", enum, re.S)
        if found is None:
            return []
        return [name for name in re.findall(r"\b(\w+)\b", found.group(1)) if name in declared]

    containers = {declared[name] for name in list_names("containerIdentifiers")}
    elements = {declared[name] for name in list_names("elementIdentifiers")}
    values = set(declared.values())

    problems: list[str] = []

    for name, occurrences in by_name.items():
        if len(occurrences) > 1:
            where = ", ".join(
                f"{value!r} at the declaration on line {line}"
                for value, line in occurrences
            )
            problems.append(
                f"{name} is declared {len(occurrences)} times: {where}. A constant "
                "declared twice has one value at runtime and the other in review, "
                "and which one wins depends on declaration order"
            )

    for name, value in declared.items():
        if not value.startswith("rovia."):
            problems.append(f"{name} = {value!r} is outside the rovia. namespace")
        if " " in value or not value:
            problems.append(f"{name} = {value!r} is empty or contains whitespace")

    if len(values) != len(declared):
        seen: dict[str, list[str]] = {}
        for name, value in declared.items():
            seen.setdefault(value, []).append(name)
        for value, names in seen.items():
            if len(names) > 1:
                problems.append(f"duplicate identifier {value!r} declared by {names}")

    unclassified = values - containers - elements
    if unclassified:
        problems.append(f"declared but not classified: {sorted(unclassified)}")
    unknown = (containers | elements) - values
    if unknown:
        problems.append(f"classified but not declared: {sorted(unknown)}")

    overlap = containers & elements
    if overlap:
        problems.append(f"classified as both container and element: {sorted(overlap)}")

    applied = set()
    for pattern in APPLIED_PATTERNS:
        for found in re.finditer(pattern, all_text):
            applied.add(next(group for group in found.groups() if group))

    unused = sorted(set(declared) - applied)
    if unused:
        problems.append(f"constants that never reach a view: {unused}")

    unguarded = []
    for name, text in sources.items():
        pairs = bracket_pairs(text)
        for found in re.finditer(r"\.accessibilityIdentifier\(", text):
            base = resolve_base_view(text, found.start(), pairs)
            if base in CONTAINER_VIEWS and not has_container_treatment(text, found.start()):
                unguarded.append(f"{name}: bare identifier on {base}")
    problems.extend(f"container identifier is not guarded: {entry}" for entry in sorted(set(unguarded)))

    root = sources.get("RootView.swift", "")
    modifier = re.search(
        r"struct ConditionalAccessibilityIdentifier: ViewModifier \{(.*?)\n\}\n", root, re.S
    )
    if modifier is None:
        problems.append("ConditionalAccessibilityIdentifier is missing from RootView.swift")
    elif not (
        "accessibilityElement(children: .contain)" in modifier.group(1)
        and "accessibilityIdentifier(identifier)" in modifier.group(1)
    ):
        problems.append("ConditionalAccessibilityIdentifier does not apply .contain and the identifier")

    # Rule 5 is about components that wrap content somebody else wrote.
    # "Container-level" is read as that, not as "mentions a container view": a
    # generic component taking `@ViewBuilder var content: Content` has children
    # whose identifiers must survive, so its own identifier has to go through the
    # treatment. A component that builds its own `Text` children and merges them
    # with `.accessibilityElement(children: .combine)` — a header, a row — is
    # *supposed* to collapse to one element, and routing its identifier through
    # the treatment would stop that. Requiring the treatment of those would flag
    # correct code, which is the same mistake as checking one hard-coded name.
    # Over *every* source, not RootView.swift alone. Rules 1-4 already read the
    # whole target; rule 5 reading one file meant a component with exactly the
    # defect it exists to catch was found in that file and missed everywhere else,
    # and the audit reported OK. The treatment is still located in RootView.swift,
    # because that is where it is defined; the components are not.
    rule_5_examined = 0
    for file_name, text in sorted(sources.items()):
      for name, body in component_bodies(text):
        rule_5_examined += 1
        if not WRAPS_CALLER_CONTENT.search(body):
            continue
        if not TAKES_AN_IDENTIFIER.search(body):
            continue
        # Two independent conditions, not an if/elif. A component can fail both —
        # it can skip the treatment *and* apply a role of its own — and a reader
        # fixing it has to fix both, so reporting only the first would send them
        # back a second time.
        if "ConditionalAccessibilityIdentifier" not in body:
            problems.append(
                f"{file_name}: {name} wraps caller-supplied content and takes an "
                "identifier but does not route it through the container treatment, "
                "so its identifier would override the identifiers of that content"
            )
        if "accessibilityElement" in body:
            problems.append(
                f"{file_name}: {name} wraps caller-supplied content and applies a "
                "container role of its own instead of through the treatment"
            )

    # Coverage, on every run. A rule that quietly reads one file out of many cannot
    # be seen to have narrowed, and these numbers are what make it visible without a
    # fixture: they are the size of what was examined.
    type_declarations = sum(
        len(TYPE_DECLARATION.findall(text)) for text in sources.values()
    )
    print(f"source files: {len(sources)}")
    print(f"type declarations: {type_declarations}")
    print(f"rule 5 examined: {rule_5_examined} of {type_declarations}")
    print(f"declared constants: {len(declared)}")
    print(f"container identifiers: {len(containers)}")
    print(f"element identifiers: {len(elements)}")
    print(f"constants reaching a view: {len(applied & set(declared))}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app",
        # Resolved from this script's own location, not from the process working
        # directory. The relative default made the audit exit 1 — reporting a
        # missing file that is not missing — whenever it was run from anywhere
        # other than the repository root, including from `tools/ci`, which is
        # where the suite runs it. An absolute default also means the audit and
        # the test that derives its counts agree on which directory they mean.
        default=str(Path(__file__).resolve().parents[2] / "client/app/ios/RoviaApp"),
        help="directory containing the app target Swift sources",
    )
    arguments = parser.parse_args()

    problems = audit(Path(arguments.app))
    if problems:
        print("accessibility identifier audit FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("accessibility identifier audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
