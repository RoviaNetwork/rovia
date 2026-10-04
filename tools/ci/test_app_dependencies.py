#!/usr/bin/env python3
"""The app's dependency on the canonical domain packages, as a source-level gate.

This gate reads declarations and bodies and compares them against rules. It is
not a parser, and a determined rewrite can get past it; the limits are listed
under "What this gate does not claim" below, and
`tools/ci/test_ci_checks.py` fails if that section is deleted or if a claim of
unconditional coverage is added back to this file or to the documents that
describe it.

The iOS app used to carry its own route matcher evaluation, host normalization,
and IPv4 CIDR containment. That was a second implementation of
`RoviaRouting.RouteEvaluator`: it could disagree with the canonical one, and
nothing in the build said so. The Xcode project now links the local packages.

A gate that lists the identifiers someone happened to use is a snapshot. This file
replaces that with rules that read declarations and bodies, and it proves each
rule with a mutation rather than asserting it:

* the dependency checks parse the Xcode project structurally — the targets, the
  local package references, the product dependencies, and the build files that
  link them — so a name in a comment or in a stale field does not satisfy them,
  and the mutations that break the project do their surgery by product name and
  package path rather than by object identifier;
* the duplicate-evaluator check reads every *body* in the app sources: function
  declarations, computed properties, closures bound to a name, and closures passed
  to a higher-order function. It decides from the declaration, from the return
  type, and from what the body computes, so `cidrContains`, `normaliseHost`,
  `isInSubnet`, `satisfiesRouteMatcher`, `decide(for:)`, a `var hostMatches: Bool
  { … }`, and a `contains { $0.matches(…) }` are all reached;
* the raw-trace checks cover `core`, `client`, `platform`, and `engines`, and
  they find `Codable` on the declaration, added by a retroactive extension, or
  reached through a `Codable` wrapper, a stored property, a collection, a
  `typealias`, or a body that accepts a trace and reaches for a leak channel.
  There are nine channels, all of them a place a hostname can travel to: a store
  (`UserDefaults`, `NSUbiquitousKeyValueStore`, `FileManager`, `write(to:`,
  `createFile(atPath:`, `NSKeyedArchiver`, `archiveRootObject`, `NSKeyedUnarchiver`)
  or a serialiser (`JSONEncoder`, `JSONSerialization.data`, `PropertyListEncoder`,
  `PropertyListSerialization`, `encode(`, `archive(`, `persist`, `store(`, `save(`),
  and four logging or message channels (`os_log(`, `OSLog(`, `Logger(`, `logger.`,
  `print(`, `debugPrint(`, `dump(`, `NSLog(`, `sendProviderMessage(`). A log is not
  a store, but it moves the value somewhere a log archive, a reader, or the host
  app can see it, which is the same problem in another shape. Each of those
  checks is bounded to the body it is about, so an unrelated call elsewhere in the
  file cannot be blamed on it.

## What this gate does not claim

It is a source-level check, and a determined rewrite can get past any such check.
These are the known limits, stated so nobody relies on more than it provides:

- **An operator overload is not detected.** `func ~=(lhs: String, rhs: String)`
  is not a declaration this file reads, because the name is not an identifier. A
  matcher written as an operator is a contrived shape; it was tried as a mutation
  and dropped rather than contorting the parser for it.
- **A matcher that avoids every signal passes.** A body that normalizes nothing,
  names nothing about ranges, hosts, or matchers, and calls nothing that looks
  like a match is not visible here. Renaming defeats a name list, not a rule set;
  removing the *idea* of a range or a host from the code is what defeats it.
- **A stored `RuleEvaluation` is not flagged.** `RouteEvaluator.evaluate` builds
  a local `[RuleEvaluation]` while it works, and a local is indistinguishable from
  a property without scope analysis. `RuleEvaluation` holds a rule identifier and
  a matched matcher rather than the input, so its `Codable` conformance is the
  whole risk and that is what is checked.
- **Swift is not parsed.** Comments and string literals are blanked, and every
  other construct is read by pattern. A syntax trick — an operator, a macro, a
  code-generated body — is outside it.
- **It reads the repository, not the build.** A target that links a product
  through a mechanism this file does not model would be reported as not linking
  it, which fails closed.

Every rule has a mutation that must fail, and several have the mirror test that a
legitimate shape is *not* flagged. A rule with no mutation is an assertion about
the source, not a gate.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from ci_check_support import core_root, pinned_core_tag

REPO_ROOT = Path(__file__).resolve().parents[2]

# The two local packages the app target and the test target must both link, and
# the path each one has, relative to the directory holding the Xcode project.
CANONICAL_PACKAGES = ("RoviaConfig", "RoviaRouting", "RoviaSubscription", "RoviaApplePlatform")
LOCAL_PACKAGE_PATHS = {
    "RoviaApplePlatform": "../../../platform/apple",
}
# Remote packages enter the project only pinned: exact repository URL and an
# exact version, read from the project, never a sibling checkout. The tag must
# agree with tools/ci/core-pin.txt, which is what the text gates fetch.
REMOTE_PACKAGES = {
    "rovia-core": {
        "url": "https://github.com/RoviaNetwork/rovia-core",
        "version": "0.2.3",
        "products": ("RoviaConfig", "RoviaRouting", "RoviaSubscription"),
    },
    "rovia-engine": {
        "url": "https://github.com/RoviaNetwork/rovia-engine",
        "version": "0.3.0",
        "products": ("RoviaXray", "RoviaXrayLive"),
    },
}
# Local references that must never come back: core and engines moved to
# RoviaNetwork/rovia-core and RoviaNetwork/rovia-engine. A sibling checkout
# would silently shadow the pinned revision the release ships.
FORBIDDEN_LOCAL_PATH_PREFIXES = ("../../../core", "../../../engines")
LINKED_TARGETS = ("RoviaApp", "RoviaAppTests")
APP_SOURCE_DIRECTORIES = ("client/app/ios",)
RAW_TRACE_TYPES = ("RoutingDecisionTrace", "RuleEvaluation")
# The one of the two that holds the raw hostname, address, and port. A stored
# copy of it is a leak; a stored `RuleEvaluation` is a rule value.
RAW_INPUT_TYPE = "RoutingDecisionTrace"
# A function that returns one of these is forwarding to the canonical model, not
# deciding anything of its own.
CANONICAL_RETURN_TYPES = (
    "routingdiagnostic",
    "routeset",
    "routeinput",
    "routingdecisiontrace",
)
REDACTED_TYPE = "RoutingDiagnostic"

# Where a raw trace would leave the process. Every one of these is a channel a
# hostname can travel down, so a body that accepts a trace and reaches for one of
# them is a leak whatever the store is called.
DURABLE_STORE_CALLS = (
    "UserDefaults",
    "NSUbiquitousKeyValueStore",
    "FileManager",
    "write(to:",
    "createFile(atPath:",
    "NSKeyedArchiver",
    "archiveRootObject",
    "NSKeyedUnarchiver",
)
SERIALIZE_CALLS = (
    "JSONEncoder",
    "JSONSerialization.data",
    "PropertyListEncoder",
    "PropertyListSerialization",
    "encode(",
    "archive(",
    "persist",
    "store(",
    "save(",
)
# Log and message channels. `os_log`, `Logger`, `print`, and a provider message
# are not stores: they move the value to somewhere a reader, a log archive, or
# the host app can see it, which is the same problem in a different shape.
LEAK_CHANNELS = (
    "os_log(",
    "OSLog(",
    "Logger(",
    "logger.",
    "print(",
    "debugPrint(",
    "dump(",
    "sendProviderMessage(",
    "NSLog(",
)

# -- the Xcode project, parsed ---------------------------------------------

OBJECT_START = re.compile(r"^\t\t([0-9A-F]{24})(?: /\*.*?\*/)? = \{", re.M)
TARGET_ISA = re.compile(r"\bisa = PBXNativeTarget;")
NAME_PATTERN = re.compile(r"\bname = (\w+);")
def list_pattern(key: str) -> re.Pattern:
    """A parenthesised object list, anchored on the key that introduces it.

    A generic `key = (` pattern matches `buildPhases` before it reaches
    `packageProductDependencies`, which is the kind of near-miss that makes a
    structural check silently structural-looking.
    """
    return re.compile(rf"\b{key} = \((?P<body>.*?)\n\t\t*\);", re.S)
LOCAL_REFERENCE_ISA = "XCLocalSwiftPackageReference"
REMOTE_REFERENCE_ISA = "XCRemoteSwiftPackageReference"
PRODUCT_DEPENDENCY_ISA = "XCSwiftPackageProductDependency"
FILE_REFERENCE_ISA = "PBXFileReference"
BUILD_FILE_ISA = "PBXBuildFile"
PHASE_FILES = re.compile(r"\bfiles = \((?P<body>.*?)\n\t\t*\);", re.S)
BUILD_PHASES_PATTERN = re.compile(r"\bbuildPhases = \((?P<body>.*?)\n\t\t*\);", re.S)
ISA_PATTERN = re.compile(r"\bisa = (?P<isa>\w+);")
RELATIVE_PATH_PATTERN = re.compile(r"\brelativePath = (?P<path>[^;]+);")
REPOSITORY_URL_PATTERN = re.compile(r'\brepositoryURL = "(?P<url>[^"]+)";')
REQUIREMENT_KIND_PATTERN = re.compile(r"\bkind = (?P<kind>\w+);")
REQUIREMENT_VERSION_PATTERN = re.compile(r"\bversion = (?P<version>[^;]+);")
PRODUCT_NAME_PATTERN = re.compile(r"\bproductName = (?P<product>\w+);")
PACKAGE_FIELD_PATTERN = re.compile(r"\bpackage = (?P<package>[0-9A-F]{24})")
BUILD_FILE_REF = re.compile(r"\b(?P<what>fileRef|productRef) = (?P<ref>[0-9A-F]{24})")
FILE_PATH_PATTERN = re.compile(r"\bpath = (?P<path>[^;]+);")
OBJECT_ID = re.compile(r"([0-9A-F]{24})")


def project_objects(text: str) -> dict[str, str]:
    """Split a project file into its objects.

    Every read below is per object. A pattern that runs across object boundaries
    can attribute one object's fields to another — which is how a phase without a
    linked product can look like one with it.
    """
    starts = [(match.start(), match.group(1)) for match in OBJECT_START.finditer(text)]
    objects: dict[str, str] = {}
    for index, (start, identifier) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        objects[identifier] = text[start:end]
    return objects


class Project:
    """The parts of an Xcode project this gate reads, as data."""

    def __init__(self, text: str):
        self.text = text
        self.objects = project_objects(text)
        self.targets = {
            name.group(1): body
            for body in self.objects.values()
            if TARGET_ISA.search(body)
            for name in [NAME_PATTERN.search(body)]
            if name
        }
        self.local_references = {
            identifier: {
                "path": RELATIVE_PATH_PATTERN.search(body).group("path").strip()
            }
            for identifier, body in self.objects.items()
            if LOCAL_REFERENCE_ISA in body and RELATIVE_PATH_PATTERN.search(body)
        }
        self.remote_references = {}
        for identifier, body in self.objects.items():
            # Match the declaration, not the use-site comment: product
            # dependencies name their package in a comment carrying the same
            # words but no fields of their own.
            if f"isa = {REMOTE_REFERENCE_ISA};" not in body:
                continue
            url = REPOSITORY_URL_PATTERN.search(body)
            kind = REQUIREMENT_KIND_PATTERN.search(body)
            version = REQUIREMENT_VERSION_PATTERN.search(body)
            self.remote_references[identifier] = {
                "url": url.group("url") if url else None,
                "kind": kind.group("kind") if kind else None,
                "version": version.group("version").strip() if version else None,
            }
        self.product_dependencies = {}
        for identifier, body in self.objects.items():
            product = PRODUCT_NAME_PATTERN.search(body)
            if PRODUCT_DEPENDENCY_ISA not in body or product is None:
                continue
            package = PACKAGE_FIELD_PATTERN.search(body)
            self.product_dependencies[identifier] = {
                "product": product.group("product"),
                "package": package.group("package") if package else None,
            }
        self.build_files = {}
        for identifier, body in self.objects.items():
            if BUILD_FILE_ISA not in body:
                continue
            reference = BUILD_FILE_REF.search(body)
            if reference is not None:
                self.build_files[identifier] = {
                    "what": reference.group("what"),
                    "ref": reference.group("ref"),
                }
        self.file_paths = {
            identifier: FILE_PATH_PATTERN.search(body).group("path").strip().strip('"')
            for identifier, body in self.objects.items()
            if FILE_REFERENCE_ISA in body and FILE_PATH_PATTERN.search(body)
        }
        project_section = text.split("/* Begin PBXProject section */", 1)[-1].split(
            "/* End PBXProject section */", 1
        )[0]
        references = list_pattern("packageReferences").search(project_section)
        self.package_references = (
            {match.group(0) for match in OBJECT_ID.finditer(references.group("body"))}
            if references
            else set()
        )

    def phase(self, target: str, isa: str) -> str | None:
        body = self.targets.get(target)
        if body is None:
            return None
        phases = BUILD_PHASES_PATTERN.search(body)
        if phases is None:
            return None
        phase_ids = {match.group(0) for match in OBJECT_ID.finditer(phases.group("body"))}
        for identifier in phase_ids:
            candidate = self.objects.get(identifier, "")
            declaration = ISA_PATTERN.search(candidate)
            if declaration is None or declaration.group("isa") != isa:
                continue
            files = PHASE_FILES.search(candidate)
            if files is not None:
                return files.group("body")
        return None

    def _entries(self, body: str | None) -> list[str]:
        if body is None:
            return []
        return [match.group(0) for match in OBJECT_ID.finditer(body)]

    def declared_products(self, target: str) -> set[str]:
        """Products a target declares in `packageProductDependencies`, resolved to names."""
        body = self.targets.get(target)
        if body is None:
            return set()
        listed = list_pattern("packageProductDependencies").search(body)
        if listed is None:
            return set()
        products = set()
        for entry in self._entries(listed.group("body")):
            dependency = self.product_dependencies.get(entry)
            if dependency is not None:
                products.add(dependency["product"])
        return products

    def linked_products(self, target: str) -> set[str]:
        """Products a target's Frameworks build phase actually links."""
        products = set()
        for entry in self._entries(self.phase(target, "PBXFrameworksBuildPhase")):
            build_file = self.build_files.get(entry)
            if build_file is None or build_file["what"] != "productRef":
                continue
            dependency = self.product_dependencies.get(build_file["ref"])
            if dependency is not None:
                products.add(dependency["product"])
        return products

    def compiled_sources(self, target: str) -> set[str]:
        """The file names a target's Sources build phase compiles."""
        paths = set()
        for entry in self._entries(self.phase(target, "PBXSourcesBuildPhase")):
            build_file = self.build_files.get(entry)
            if build_file is None or build_file["what"] != "fileRef":
                continue
            path = self.file_paths.get(build_file["ref"])
            if path:
                paths.add(path)
        return paths


# -- source analysis -------------------------------------------------------

DECLARATION = re.compile(
    r"^[ \t]*(?P<modifiers>(?:public |internal |private |fileprivate |package |static |final |lazy "
    r"|mutating |nonmutating |override |required |convenience |indirect )*)"
    r"(?P<what>struct|class|enum|actor|protocol|typealias|extension|func)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.M,
)
TYPE_DECLARATION = re.compile(
    r"^[ \t]*(?P<modifiers>(?:public |internal |private |fileprivate |package |final )*)"
    r"(?P<what>struct|class|enum|actor)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:<[^>]*>)?\s*(?::\s*(?P<conformances>[A-Za-z0-9_, ]*?)\s*)?\{",
    re.M,
)


def strip_comments_and_strings(text: str) -> str:
    """Blank comments and string literals, preserving offsets and newlines."""
    result: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character == '"':
            result.append('"')
            index += 1
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    result.append("  ")
                    index += 2
                    continue
                if text[index] == '"':
                    result.append('"')
                    index += 1
                    break
                result.append("\n" if text[index] == "\n" else " ")
                index += 1
            continue
        if text.startswith("//", index):
            while index < length and text[index] != "\n":
                result.append(" ")
                index += 1
            continue
        if text.startswith("/*", index):
            depth = 0
            while index < length:
                if text.startswith("/*", index):
                    depth += 1
                    result.append("  ")
                    index += 2
                    continue
                if text.startswith("*/", index):
                    depth -= 1
                    result.append("  ")
                    index += 2
                    if depth == 0:
                        break
                    continue
                result.append("\n" if text[index] == "\n" else " ")
                index += 1
            continue
        result.append(character)
        index += 1
    return "".join(result)


COMPUTED_PROPERTY = re.compile(
    r"^[ \t]*(?P<modifiers>(?:public |internal |private |fileprivate |package |static |final |lazy "
    r"|override |nonisolated |weak |unowned )*)var\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<type>[^{\n]+?)\s*\{\s*(?:get\b)?",
    re.M,
)
CLOSURE_BINDING = re.compile(
    r"^[ \t]*(?:public |internal |private |fileprivate |package |static |final |lazy )*"
    r"(?:let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=\n]+)?=\s*\{",
    re.M,
)
CLOSURE_PARAMETERS = re.compile(r"\bin\s*\((?P<params>[^)]*)\)")


def matching_brace(text: str, start: int) -> int:
    """The index of the brace closing the one at `start`, or -1."""
    depth = 0
    for index in range(start, len(text)):
        character = text[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def regions(text: str) -> list[dict]:
    """Every place a body can be written, with the span of that body.

    A function is not the only body in Swift. A computed property, a closure bound
    to a name, and an anonymous closure are all bodies, and a detector that only
    reads `func` declarations misses a matcher written in any of them. Each region
    carries its own span so a check about what a body *reaches for* is bounded by
    that body instead of by the rest of the file.
    """
    stripped = strip_comments_and_strings(text)
    found: list[dict] = []

    def add(kind: str, name: str, params: str, returns: str, start: int) -> None:
        end = matching_brace(stripped, start)
        if end == -1:
            return
        found.append(
            {
                "kind": kind,
                "name": name,
                "params": params,
                "returns": returns,
                "line": stripped.count("\n", 0, start) + 1,
                "body": stripped[start : end + 1],
            }
        )

    for match in DECLARATION.finditer(stripped):
        if match.group("what") != "func":
            continue
        tail = stripped[match.end() : match.end() + 500]
        parameters = re.match(r"[ \t]*\((?P<params>[^)]*)\)", tail)
        returns = re.search(r"\)\s*(?:async\s*)?(?:throws\s*)?->\s*(?P<returns>[^{\n]+)", tail)
        opening = stripped.find("{", match.end())
        if opening == -1 or opening - match.end() > 500:
            continue
        add(
            "function",
            match.group("name"),
            parameters.group("params") if parameters else "",
            returns.group("returns").strip() if returns else "",
            opening,
        )

    for match in COMPUTED_PROPERTY.finditer(stripped):
        add("computed property", match.group("name"), "", match.group("type"), match.end() - 1)

    for match in CLOSURE_BINDING.finditer(stripped):
        parameters = CLOSURE_PARAMETERS.search(stripped[match.end() : match.end() + 200])
        add(
            "closure",
            match.group("name"),
            parameters.group("params") if parameters else "",
            "",
            match.end() - 1,
        )

    for match in re.finditer(
        r"\b(map|filter|reduce|contains|allSatisfy|sorted|compactMap|first|dropFirst)\s*(\{|\()",
        stripped,
    ):
        add("closure", match.group(1), "", "", match.end() - 1)

    return sorted(found, key=lambda entry: entry["line"])


def folded(*parts) -> str:
    """Lower-case and drop underscores, so snake_case and camelCase compare alike."""
    return "".join(part for part in parts if part).replace("_", "").lower()


def duplicate_evaluator_findings(
    text: str, *, strict: bool = False, is_test_source: bool = False
) -> list[str]:
    """Declarations that reimplement route evaluation, whatever they are called.

    Six rules, so no single naming habit gets past all of them:

    1. a type whose name is about IP ranges, CIDR, or subnets;
    2. a function that normalises or canonicalises a host, address, or network
       label, in either spelling;
    3. a function whose name says it answers containment or membership of a range
       or an address;
    4. a function that compares matchers, or a matcher against an input;
    5. a function that returns a decision, a route, or a verdict for an input;
    6. with `strict`, a string compared by suffix or prefix, which is the
       domain-suffix matcher the canonical package already provides.
    """
    findings: list[str] = []
    stripped = strip_comments_and_strings(text)
    for match in TYPE_DECLARATION.finditer(stripped):
        name = folded(match.group("name"))
        if (
            name.startswith("ipv4")
            or name.startswith("ipv6")
            or name in ("iprange", "cidr", "cidrrange", "subnet", "subnetrange", "ipranges", "cidrranges")
        ):
            findings.append(f"{match.group('name')} declares a range type of its own")
        elif "routeevaluator" in name and "canonical" not in name and "bridge" not in name:
            findings.append(f"{match.group('name')} declares a route evaluator of its own")

    for entry in regions(text):
        name = folded(entry["name"])
        params = folded(entry["params"])
        returns = folded(entry["returns"])
        where = f"line {entry['line']}: {entry['kind']} {entry['name']}"
        if is_test_source and name.startswith("test"):
            # A test named after the behaviour it asserts is not an
            # implementation of that behaviour.
            continue
        if entry["kind"] == "computed property" and not returns.startswith("bool"):
            # A computed property that answers a question is worth looking at; one
            # that formats a value is not deciding anything.
            continues = True
        else:
            continues = False

        for verb in ("normalize", "normalise", "canonicalize", "canonicalise"):
            if name.startswith(verb) and any(
                word in name for word in ("host", "domain", "address", "ip", "network", "label", "subnet")
            ):
                findings.append(f"{where} normalizes a host, address, or network label")

        if any(verb in name for verb in ("contains", "isin", "within", "inside", "belongs")) and any(
            word in name for word in ("range", "cidr", "subnet", "network", "prefix", "block", "address", "ip")
        ):
            findings.append(f"{where} answers containment for a range or an address")
        if name.startswith("matches") and any(
            word in name for word in ("range", "cidr", "subnet", "address", "ip", "prefix", "suffix")
        ):
            findings.append(f"{where} matches an address against a range or a label")
        # A matcher predicate answers a question and returns a verdict; a
        # converter turns a display matcher into a canonical one and returns a
        # value. Only the first is a reimplementation.
        decides = returns.startswith("bool")
        if "matcher" in name and any(
            verb in name for verb in ("match", "compare", "satisf", "applie", "evaluate", "test")
        ) and decides:
            findings.append(f"{where} decides whether a matcher matches")
        if "matcher" in params and any(
            verb in name for verb in ("match", "compare", "satisf", "applie", "evaluate", "first")
        ) and (decides or any(word in params for word in ("input", "host", "address", "destination"))):
            findings.append(f"{where} decides whether a matcher matches")

        if continues:
            continue
        if re.search(r"\bmatch(es|ing)?[A-Za-z]*\s*\(", entry["body"]) and "RouteEvaluator" not in entry["body"]:
            findings.append(
                f"{where} computes a match in its own body rather than asking the canonical evaluator"
            )
        if any(verb in name for verb in ("evaluate", "decide", "explain", "resolve", "routefor")) and any(
            word in params for word in ("input", "destination", "host", "address", "request", "sample")
        ) and not any(canonical in returns for canonical in CANONICAL_RETURN_TYPES):
            # Returning a canonical type is forwarding, not deciding: a function
            # whose result is `RoutingDiagnostic` has no answer of its own to
            # disagree with.
            findings.append(f"{where} returns a decision for an input")
        if name.startswith(("firstmatch", "firstmatching", "firstsatisfied", "indexofmatch")):
            findings.append(f"{where} finds the first matching rule of its own")
        if "first" in name and "match" in name:
            findings.append(f"{where} finds the first match of its own")

    if strict:
        # Bounded to the region that contains the call, so the finding names the
        # body that does the comparison and a later unrelated `hasPrefix` in the
        # same file cannot be blamed on it.
        for entry in regions(text):
            for match in re.finditer(r"\b(\w+)\.(hasSuffix|hasPrefix)\(", entry["body"]):
                subject = folded(match.group(1))
                if not any(
                    word in subject
                    for word in ("host", "domain", "suffix", "prefix", "label", "address", "network")
                ):
                    continue
                findings.append(
                    f"line {entry['line']}: {match.group(1)}.{match.group(2)} compares a "
                    f"string by suffix or prefix inside {entry['kind']} {entry['name']}, "
                    "which is the domain-suffix matcher"
                )
    return sorted(set(findings))


def raw_trace_findings(text: str) -> list[str]:
    """Ways a raw trace could acquire `Codable` or be written somewhere durable."""
    findings: list[str] = []
    stripped = strip_comments_and_strings(text)
    trace_alternatives = "|".join(RAW_TRACE_TYPES)

    for match in TYPE_DECLARATION.finditer(stripped):
        conformances = folded(match.group("conformances"))
        name = match.group("name")
        if name in RAW_TRACE_TYPES and "codable" in conformances:
            findings.append(f"{name} declares Codable")
        if "codable" in conformances or "encodable" in conformances or "decodable" in conformances:
            body = stripped[match.end() : match.end() + 2000]
            if re.search(
                rf"\b(let|var)\s+\w+\s*:\s*(\[\s*[^\]\n]*\])?\s*{RAW_INPUT_TYPE}\b", body
            ):
                findings.append(f"{name} is Codable and stores a {RAW_INPUT_TYPE}")

    for match in re.finditer(
        rf"^[ \t]*(?:public |internal |package )*extension\s+({trace_alternatives})\s*:\s*"
        r"(?P<conformances>[A-Za-z0-9_, ]*?)\s*\{",
        stripped,
        re.M,
    ):
        if "codable" in folded(match.group("conformances")):
            findings.append(f"an extension makes {match.group(1)} Codable")

    for match in re.finditer(
        rf"^[ \t]*(?:public |internal |package )*typealias\s+([A-Za-z0-9_]+)\s*=\s*({trace_alternatives})\b",
        stripped,
        re.M,
    ):
        findings.append(f"{match.group(1)} is an alias of {match.group(2)}")

    # Only the raw-input type is a storage risk. `RouteEvaluator.evaluate` builds a
    # local `[RuleEvaluation]` while it works, and demanding that it not would be
    # demanding that the canonical evaluator stop working.
    for match in re.finditer(
        rf"^[ \t]*(?:public |internal |package )*(?:let|var)\s+([A-Za-z0-9_]+)\s*:\s*"
        rf"([^=\n]*\b{RAW_INPUT_TYPE}\b[^=\n]*?)\s*(?:=[^=\n]*)?$",
        stripped,
        re.M,
    ):
        findings.append(
            f"{match.group(1)} stores a {RAW_INPUT_TYPE} in a property, so any "
            "container holding it keeps the raw input"
        )

    for entry in regions(text):
        lowered = folded(entry["params"])
        if not any(folded(trace) in lowered for trace in RAW_TRACE_TYPES):
            continue
        # Bounded to this body. A window of characters around the name was both
        # too wide — an unrelated encoder call elsewhere in the file made an
        # innocent function look guilty — and positioned by a search over the
        # unstripped text, so a mention of the name in a comment moved it.
        body = entry["body"]
        channel = next(
            (
                call
                for call in DURABLE_STORE_CALLS + SERIALIZE_CALLS + LEAK_CHANNELS
                if call in body
            ),
            None,
        )
        if channel is not None:
            findings.append(
                f"line {entry['line']}: {entry['kind']} {entry['name']} accepts a raw trace "
                f"and reaches for {channel!r}"
            )

    for match in re.finditer(
        rf"\b({RAW_INPUT_TYPE})\b[^\n]*?\b(UserDefaults|NSUbiquitousKeyValueStore|NSKeyedArchiver|FileManager)\b"
        rf"|\b(UserDefaults|NSUbiquitousKeyValueStore|NSKeyedArchiver|FileManager)\b[^\n]*?"
        rf"\b({RAW_INPUT_TYPE})\b",
        stripped,
    ):
        findings.append("a durable store is handed a raw trace")

    return sorted(set(findings))


# -- the checks ------------------------------------------------------------


def swift_sources(root: Path, directories: tuple[str, ...]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for directory in directories:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.swift")):
            if ".build" in path.parts or "DerivedData" in path.parts or "xcuserdata" in str(path):
                continue
            sources[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    return sources


def project_text(root: Path) -> str:
    return (root / "client/app/ios/RoviaApp.xcodeproj/project.pbxproj").read_text(encoding="utf-8")


def package_dependency_problems(root: Path) -> list[str]:
    """The app target and the test target must link every canonical package.

    Local packages by path, remote packages by exact URL and version. A core
    product that stops pointing at the pinned remote — or a sibling checkout
    of core or engines reintroduced as a local reference — is a release
    integrity failure, not a build convenience.
    """
    problems: list[str] = []
    project = Project(project_text(root))
    project_directory = root / "client/app/ios"

    paths = {reference["path"] for reference in project.local_references.values()}
    for package, relative in LOCAL_PACKAGE_PATHS.items():
        if relative not in paths:
            problems.append(f"the project does not reference the local package {package} at {relative}")
        if not (project_directory / relative / "Package.swift").is_file():
            problems.append(f"the package path {relative} does not resolve to a Package.swift")
    for path in sorted(paths):
        if path.startswith(FORBIDDEN_LOCAL_PATH_PREFIXES):
            problems.append(
                f"the project references {path}, but core and engines live in their own "
                "repositories and enter here only as pinned SPM dependencies"
            )

    remote_ids = set(project.remote_references)
    for name, expected in REMOTE_PACKAGES.items():
        # The Xcode pin is a bare version, the git tag carries its `v`:
        # v0.2.3 the tag, 0.2.3 the pin. Compared after that prefix, so a
        # real drift still fails and the naming convention cannot hide it.
        # Only rovia-core has a core-pin.txt binding; rovia-engine is pinned
        # by the exactVersion above.
        if name != "rovia-core":
            continue
        if expected["version"] != pinned_core_tag().removeprefix("v"):
            problems.append(
                f"the {name} pin {expected['version']} disagrees with tools/ci/core-pin.txt"
            )
    for name, expected in REMOTE_PACKAGES.items():
        matches = [
            identifier
            for identifier, reference in project.remote_references.items()
            if reference["url"] == expected["url"]
        ]
        if not matches:
            problems.append(f"the project has no remote reference to {expected['url']}")
            continue
        for identifier in matches:
            reference = project.remote_references[identifier]
            if reference["kind"] != "exactVersion" or reference["version"] != expected["version"]:
                problems.append(
                    f"the {name} reference is not pinned to exactly {expected['version']}"
                )
            if identifier not in project.package_references:
                problems.append(f"the {name} remote reference is declared but not attached to the project")

    for identifier, reference in project.local_references.items():
        if identifier not in project.package_references:
            problems.append(
                f"the local package {reference['path']} is declared but not attached to the project"
            )
    if not project.package_references:
        problems.append("the project attaches no package reference at all")

    remote_products: dict[str, set[str]] = {}
    for name, expected in REMOTE_PACKAGES.items():
        remote_products[name] = set(expected["products"])
    for identifier, dependency in project.product_dependencies.items():
        if dependency["product"] not in CANONICAL_PACKAGES:
            continue
        if dependency["package"] is None:
            problems.append(f"the {dependency['product']} product dependency points at no package")
            continue
        if dependency["package"] in project.local_references:
            if dependency["product"] != "RoviaApplePlatform":
                problems.append(
                    f"the {dependency['product']} product dependency points at a local package; "
                    "only RoviaApplePlatform may"
                )
            continue
        if dependency["package"] not in remote_ids:
            problems.append(
                f"the {dependency['product']} product dependency points at no known package"
            )

    for target in LINKED_TARGETS:
        if target not in project.targets:
            problems.append(f"the project has no target named {target}")
            continue
        for package in CANONICAL_PACKAGES:
            if package not in project.declared_products(target):
                problems.append(f"{target} does not declare the {package} product dependency")
            if package not in project.linked_products(target):
                problems.append(f"{target} does not link the {package} product")
    return problems


def canonical_import_problems(root: Path) -> list[str]:
    """A file the app target compiles must import each canonical package.

    The app target only, not the test target: a test file that imports the
    package while the shipped app does not is exactly the state this gate exists
    to prevent.
    """
    project = Project(project_text(root))
    problems: list[str] = []
    sources = swift_sources(root, APP_SOURCE_DIRECTORIES)
    compiled = project.compiled_sources("RoviaApp")
    for package in CANONICAL_PACKAGES:
        importers = sorted(
            relative
            for relative, text in sources.items()
            if Path(relative).name in compiled
            and re.search(rf"^import {package}$", text, re.M)
        )
        if not importers:
            problems.append(
                f"no source the app target compiles imports {package}, so the "
                "canonical model cannot be reached from the app"
            )
    return problems


def duplicate_evaluator_problems(root: Path) -> list[str]:
    problems: list[str] = []
    project = Project(project_text(root))
    app_sources = project.compiled_sources("RoviaApp")
    for relative, text in swift_sources(root, APP_SOURCE_DIRECTORIES).items():
        strict = Path(relative).name in app_sources
        is_test_source = "Tests" in relative
        for finding in duplicate_evaluator_findings(
            text, strict=strict, is_test_source=is_test_source
        ):
            problems.append(f"{relative}: {finding}")
    return problems


def core_sources_root(root: Path) -> Path:
    """Where the checks read core sources from.

    The workspace carries a mutated copy under core/; anywhere else the
    pinned checkout is read. Mutation tests depend on the first, clean runs
    on the second, and neither may silently read the other.
    """
    if (root / "core" / "config" / "Package.swift").is_file():
        return root
    return core_root()


def raw_trace_problems(root: Path) -> list[str]:
    problems: list[str] = []
    # Local trees, then core: a trace must not be stored on either side of
    # the boundary, and the report keeps checkout-relative paths so a finding
    # names the file it is in.
    core = core_sources_root(root)
    scan_roots = [(root, ("client", "platform")), (core, ("core",))]
    for base_root, directories in scan_roots:
        for directory in directories:
            base = base_root / directory
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.swift")):
                if ".build" in path.parts or "DerivedData" in path.parts:
                    continue
                for finding in raw_trace_findings(path.read_text(encoding="utf-8")):
                    problems.append(f"{path.relative_to(base_root)}: {finding}")
    return problems


def redacted_contract_problems(root: Path) -> list[str]:
    core = core_sources_root(root)
    problems: list[str] = []
    models = (core / "core/config/Sources/RoviaConfig/CanonicalModels.swift").read_text(
        encoding="utf-8"
    )
    for phrase in ("In memory only", "never written to disk", REDACTED_TYPE):
        if phrase not in models:
            problems.append(f"the raw trace no longer states '{phrase}' in its contract")
    diagnostic = (core / "core/routing/Sources/RoviaRouting/RoutingDiagnostic.swift").read_text(
        encoding="utf-8"
    )
    declaration = re.search(
        rf"^[ \t]*(?:public |internal |package )*struct {REDACTED_TYPE}\s*:\s*([A-Za-z0-9_, ]+?)\s*\{{",
        diagnostic,
        re.M,
    )
    if declaration is None or "codable" not in folded(declaration.group(1)):
        problems.append(f"{REDACTED_TYPE} is the serializable form and must stay Codable")
    return problems


PROJECT_FILE = "client/app/ios/RoviaApp.xcodeproj/project.pbxproj"
MODELS_FILE = "core/config/Sources/RoviaConfig/CanonicalModels.swift"
DIAGNOSTIC_FILE = "core/routing/Sources/RoviaRouting/RoutingDiagnostic.swift"
EVALUATOR_FILE = "core/routing/Sources/RoviaRouting/RouteEvaluator.swift"
APPLE_PLATFORM_FILE = "platform/apple/Sources/RoviaApplePlatform/ApplePlatform.swift"
BRIDGE_FILE = "client/app/ios/RoviaApp/CanonicalRouteBridge.swift"
APP_SNAPSHOT_FILE = "client/app/ios/RoviaApp/AppSnapshot.swift"

ALL_CHECKS = (
    package_dependency_problems,
    canonical_import_problems,
    duplicate_evaluator_problems,
    raw_trace_problems,
    redacted_contract_problems,
)


class Workspace:
    """A temporary copy of the repository, for mutation tests.

    Core sources ride along from the pinned checkout: mutations address them
    by the same relative paths the checks read, so the workspace mirrors the
    checkout under core/.
    """

    def __init__(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.root = self.directory / "repository"
        shutil.copytree(
            REPO_ROOT,
            self.root,
            ignore=shutil.ignore_patterns(
                ".git", ".build", "DerivedData", "__pycache__", ".DS_Store", "*.xcuserstate"
            ),
        )
        shutil.copytree(
            core_root() / "core",
            self.root / "core",
            ignore=shutil.ignore_patterns(".build", "DerivedData", "__pycache__", ".DS_Store"),
        )

    def close(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def write(self, relative: str, text: str) -> None:
        (self.root / relative).write_text(text, encoding="utf-8")

    def append(self, relative: str, text: str) -> None:
        with (self.root / relative).open("a", encoding="utf-8") as stream:
            stream.write(text)

    def replace(self, relative: str, old: str, new: str, count: int = 1) -> None:
        text = self.read(relative)
        assert old in text, f"{relative} does not contain {old!r}"
        self.write(relative, text.replace(old, new, count))

    def transform(self, relative: str, operation) -> None:
        """Rewrite a file with a function of its current text."""
        self.write(relative, operation(self.read(relative)))


class WorkspaceTestCase(unittest.TestCase):
    """Each test states a mutation and requires the check to notice it."""

    def setUp(self) -> None:
        self.workspace = Workspace()
        self.addCleanup(self.workspace.close)
        self.root = self.workspace.root

    def assertClean(self) -> None:
        for check in ALL_CHECKS:
            with self.subTest(check=check.__name__):
                self.assertEqual(check(self.root), [])

    def assertCaught(self, *checks) -> list[str]:
        found: list[str] = []
        for check in checks:
            found.extend(check(self.root))
        self.assertTrue(found, "the mutation was not caught")
        return found


# The project mutations below are surgery keyed on the product name and the
# package path, not on the project's object identifiers. A gate whose own tests
# depend on `E10000000000000000000005` breaks the moment Xcode renumbers the
# objects, and a broken mutation proves nothing.
def renumber_identifiers(text: str, prefix: str = "DEAD") -> str:
    """Rewrite every object identifier to a fresh, equally shaped one.

    A gate that finds objects by an identifier prefix or by a literal in a test
    looks fine until Xcode renumbers, and then it fails silently. This keeps the
    shape — 24 hex digits, tab-indented, same order — and changes nothing else.
    """
    mapping: dict[str, str] = {}

    def replace(match):
        original = match.group(0)
        if original not in mapping:
            mapping[original] = f"{prefix}{len(mapping):020X}"
        return mapping[original]

    return re.sub(r"\b[0-9A-F]{24}\b", replace, text)


def _drop_product_from_target(text: str, target: str, product: str) -> str:
    project = Project(text)
    listed = list_pattern("packageProductDependencies").search(project.targets[target])
    for entry in project._entries(listed.group("body")):
        dependency = project.product_dependencies.get(entry)
        if dependency is None or dependency["product"] != product:
            continue
        line = next(line for line in text.splitlines() if line.strip().startswith(entry))
        return text.replace(line + "\n", "", 1)
    raise AssertionError(f"{target} does not declare {product}")


def _drop_product_from_frameworks(text: str, target: str, product: str) -> str:
    project = Project(text)
    for entry in project._entries(project.phase(target, "PBXFrameworksBuildPhase")):
        build_file = project.build_files.get(entry)
        if build_file is None or build_file["what"] != "productRef":
            continue
        dependency = project.product_dependencies.get(build_file["ref"])
        if dependency is None or dependency["product"] != product:
            continue
        line = next(line for line in text.splitlines() if line.strip().startswith(entry))
        return text.replace(line + "\n", "", 1)
    raise AssertionError(f"{target} does not link {product}")


def _repoint_local_reference(text: str, expected_path: str, new_path: str) -> str:
    project = Project(text)
    if expected_path not in {reference["path"] for reference in project.local_references.values()}:
        raise AssertionError(f"no local package reference at {expected_path}")
    return text.replace(f"relativePath = {expected_path};", f"relativePath = {new_path};", 1)


def _detach_local_reference(text: str, expected_path: str) -> str:
    project = Project(text)
    identifier = next(
        key for key, reference in project.local_references.items() if reference["path"] == expected_path
    )
    line = next(line for line in text.splitlines() if line.strip().startswith(identifier))
    return text.replace(line + "\n", "", 1)


def _point_product_at_nothing(text: str, product: str) -> str:
    for body in Project(text).objects.values():
        if "XCSwiftPackageProductDependency" in body and f"productName = {product};" in body:
            return text.replace(
                body, re.sub(r"\n\t\t\tpackage = [0-9A-F]{24}[^\n]*", "", body, count=1), 1
            )
    raise AssertionError(f"no product dependency for {product}")


def _rename_product(text: str, product: str) -> str:
    assert f"productName = {product};" in text
    return text.replace(f"productName = {product};", f"productName = {product}Renamed;", 1)


def _comment_out_product(text: str, target: str, product: str) -> str:
    """Replace one target's product-dependency entry with a comment.

    Keyed on the product the entry declares, not on the first entry that looks
    like it: commenting out the wrong one would still be a mutation, and would
    still pass, for the wrong reason.
    """
    project = Project(text)
    listed = list_pattern("packageProductDependencies").search(project.targets[target])
    for entry in project._entries(listed.group("body")):
        dependency = project.product_dependencies.get(entry)
        if dependency is None or dependency["product"] != product:
            continue
        line = next(line for line in text.splitlines() if line.strip().startswith(entry))
        label = re.search(r"/\* (\w+) \*/", line)
        return text.replace(
            line + "\n", f"\t\t\t\t/* {label.group(1)} is declared here */\n", 1
        )
    raise AssertionError(f"{target} does not declare {product}")


def _local_reference_id(text: str, expected_path: str) -> str:
    project = Project(text)
    return next(
        key for key, reference in project.local_references.items() if reference["path"] == expected_path
    )


def _remote_reference_id(text: str, url: str) -> str:
    project = Project(text)
    return next(
        key for key, reference in project.remote_references.items() if reference["url"] == url
    )


def _float_remote_requirement(text: str, url: str) -> str:
    identifier = _remote_reference_id(text, url)
    body = Project(text).objects[identifier]
    assert "kind = exactVersion;" in body, "the remote reference is not version-pinned"
    floated = body.replace("kind = exactVersion;", "kind = branch;", 1)
    return text.replace(body, floated, 1)


def _change_remote_url(text: str, url: str, new_url: str) -> str:
    _remote_reference_id(text, url)
    old = f'repositoryURL = "{url}";'
    assert old in text
    return text.replace(old, f'repositoryURL = "{new_url}";', 1)


def _point_product_at_package(text: str, product: str, package_id: str) -> str:
    for body in Project(text).objects.values():
        if "XCSwiftPackageProductDependency" in body and f"productName = {product};" in body:
            assert re.search(r"\bpackage = [0-9A-F]{24}", body), f"{product} has no package field to repoint"
            return text.replace(
                body,
                re.sub(r"\bpackage = [0-9A-F]{24}[^\n]*", f"package = {package_id}", body, count=1),
                1,
            )
    raise AssertionError(f"no product dependency for {product}")


def _add_local_core_reference(text: str) -> str:
    anchor = "/* End XCLocalSwiftPackageReference section */"
    assert anchor in text
    block = (
        "\t\tDEAD00000000000000000001 /* XCLocalSwiftPackageReference \"core/config\" */ = {\n"
        "\t\t\tisa = XCLocalSwiftPackageReference;\n"
        "\t\t\trelativePath = ../../../core/config;\n"
        "\t\t};\n"
    )
    return text.replace(anchor, block + anchor, 1)


def _mutate_project(operation):
    return lambda workspace: workspace.transform(PROJECT_FILE, operation)


PACKAGE_MUTATIONS = {
    "the local platform package path is repointed": _mutate_project(
        lambda text: _repoint_local_reference(text, LOCAL_PACKAGE_PATHS["RoviaApplePlatform"], "../../../platform/elsewhere")
    ),
    "the remote pin is floated to a branch": _mutate_project(
        lambda text: _float_remote_requirement(text, REMOTE_PACKAGES["rovia-core"]["url"])
    ),
    "the remote URL is changed": _mutate_project(
        lambda text: _change_remote_url(
            text,
            REMOTE_PACKAGES["rovia-core"]["url"],
            "https://example.invalid/rovia-core",
        )
    ),
    "a core product is repointed at the local platform package": _mutate_project(
        lambda text: _point_product_at_package(
            text, "RoviaConfig", _local_reference_id(text, LOCAL_PACKAGE_PATHS["RoviaApplePlatform"])
        )
    ),
    "a local core reference is reintroduced": _mutate_project(_add_local_core_reference),
    "the product dependency is removed from the app target": _mutate_project(
        lambda text: _drop_product_from_target(text, "RoviaApp", "RoviaConfig")
    ),
    "the product dependency is removed from the test target": _mutate_project(
        lambda text: _drop_product_from_target(text, "RoviaAppTests", "RoviaRouting")
    ),
    "a product is declared but no longer linked": _mutate_project(
        lambda text: _drop_product_from_frameworks(text, "RoviaApp", "RoviaConfig")
    ),
    "a product dependency points at no package": _mutate_project(
        lambda text: _point_product_at_nothing(text, "RoviaRouting")
    ),
    "a local package is declared but not attached to the project": _mutate_project(
        lambda text: _detach_local_reference(text, LOCAL_PACKAGE_PATHS["RoviaApplePlatform"])
    ),
    "a product is renamed so it is not the canonical one": _mutate_project(
        lambda text: _rename_product(text, "RoviaConfig")
    ),
    "the import is removed": lambda workspace: workspace.replace(
        BRIDGE_FILE, "import RoviaRouting\n", ""
    ),
}

# A second evaluator, written twelve ways. None of them uses a name from the
# original code, and one of them uses no identifying name at all.
EVALUATOR_MUTATIONS: dict[str, str] = {
    "a range type under a new name": """
enum ipv4MaskTable {
    static func contains(_ address: String, in cidr: String) -> Bool { true }
}
""",
    "a CIDR helper under a new name": """
func cidrContains(_ address: String) -> Bool { true }
""",
    "a subnet membership helper": """
func isInSubnet(_ address: String, _ prefix: Int) -> Bool { true }
""",
    "a host normalizer with the other spelling": """
func normaliseHost(_ value: String) -> String { value.lowercased() }
""",
    "a canonicalizer for addresses": """
func canonicalizeIPAddress(_ value: String) -> String { value }
""",
    "a suffix matcher": """
func matchesDomainSuffix(_ host: String, _ suffix: String) -> Bool {
    host == suffix || host.hasSuffix("." + suffix)
}
""",
    "a matcher predicate": """
func satisfiesRouteMatcher(_ matcher: RouteMatcherSummary, _ input: DebugInput) -> Bool { true }
""",
    "a decision function": """
func decide(for input: DebugInput, using rules: [RouteRuleSummary]) -> RouteOutcome { .direct }
""",
    "a first-match search": """
func indexOfFirstMatch(in rules: [RouteRuleSummary], for input: DebugInput) -> Int? { nil }
""",
    "a second evaluator type": """
enum RouteEngine: Sendable {
    func evaluate(_ input: DebugInput) -> RouteOutcome { .direct }
}
""",
    "the original code, restored verbatim": """
enum IPv4Range {
    static func contains(_ address: String, in cidr: String) -> Bool { false }
}
struct MatcherProbe {
    func matches(_ input: DebugInput) -> Bool { false }
    func firstMatchingMatcher(in input: DebugInput) -> Int? { nil }
    static func normalizeHost(_ value: String) -> String { value }
}
func evaluateRoute(_ input: DebugInput) -> RouteOutcome { .direct }
""",
    "a file of its own": """
import Foundation

func withinAddressRange(_ address: String, _ range: String) -> Bool { false }
""",
    "a closure bound to a name": """
let matchesDomainSuffix = { (host: String, suffix: String) -> Bool in
    host == suffix || host.hasSuffix("." + suffix)
}
""",
    "a computed property that decides a match": """
struct SuffixProbe {
    var hostMatches: Bool { host.hasSuffix(".example.invalid") }
}
""",
    "a closure passed to contains": """
let verdict = rules.contains { $0.matches(input) }
""",
    "a method on an enum instead of a free function": """
enum Matcher {
    static func isWithinSubnet(_ address: String, _ cidr: String) -> Bool { false }
}
""",
}

# Shapes that look like a reimplementation or a trace leak and are not. A gate
# that flags these is a gate people disable.
LEGITIMATE_SHAPES = {
    "an evaluator-shaped name on a comment": """
// func normalizeHost(_ value: String) -> String { value }
/* enum IPv4Range { } */
""",
    "an evaluator-shaped name in a string": """
let example = "func evaluateRoute(for input: String)"
""",
    "a shared JSON encoder in the config package": """
let encoder = JSONEncoder()
""",
    "an accessibility prefix assertion": """
func checkPrefix(_ identifier: String) -> Bool {
    identifier.hasPrefix("rovia.")
}
""",
    "an unrelated print after a trace parameter": """
public func describe(_ trace: RoutingDecisionTrace) -> String {
    "a trace with \\(trace.evaluations.count) evaluations"
}

public func unrelated() {
    print("hello")
}
""",
    "a canonical-model mention in a comment": """
// RoutingDecisionTrace holds the raw input and is not Codable.
""",
    "a display model named after a matcher": """
struct RouteMatcherSummary: Equatable, Identifiable {
    let id: String
    var valueLabel: String { "\\(id) value" }
}
""",
}

TRACE_MUTATIONS = {
    "Codable on the declaration": lambda workspace: workspace.replace(
        MODELS_FILE,
        "public struct RoutingDecisionTrace: Sendable, Equatable {",
        "public struct RoutingDecisionTrace: Codable, Sendable, Equatable {",
    ),
    "Codable on RuleEvaluation": lambda workspace: workspace.replace(
        MODELS_FILE,
        "public struct RuleEvaluation: Sendable, Equatable {",
        "public struct RuleEvaluation: Codable, Sendable, Equatable {",
    ),
    "Codable added by a retroactive extension": lambda workspace: workspace.append(
        MODELS_FILE, "\nextension RoutingDecisionTrace: Codable {}\n"
    ),
    "a Codable wrapper that stores a trace": lambda workspace: workspace.append(
        BRIDGE_FILE,
        "\nstruct PersistedTrace: Codable {\n    let trace: RoutingDecisionTrace\n}\n",
    ),
    "a trace stored in a dictionary": lambda workspace: workspace.append(
        EVALUATOR_FILE,
        "\npublic let lastTraces: [String: RoutingDecisionTrace] = [:]\n",
    ),
    "a trace stored as an optional property": lambda workspace: workspace.append(
        MODELS_FILE, "\npublic var lastTrace: RoutingDecisionTrace?\n"
    ),
    "a trace handed to an encoder": lambda workspace: workspace.append(
        MODELS_FILE,
        "\npublic func persist(_ trace: RoutingDecisionTrace) throws {\n"
        "    _ = try JSONEncoder().encode(trace)\n}\n",
    ),
    "a trace written to a durable store": lambda workspace: workspace.append(
        APPLE_PLATFORM_FILE,
        "\npublic func stash(_ trace: RoutingDecisionTrace) {\n"
        '    UserDefaults.standard.set(1, forKey: "trace")\n}\n',
    ),
    "a trace aliased under a storable name": lambda workspace: workspace.append(
        MODELS_FILE, "\npublic typealias StoredTrace = RoutingDecisionTrace\n"
    ),
    "a trace printed in a package": lambda workspace: workspace.append(
        MODELS_FILE,
        "\npublic func report(_ trace: RoutingDecisionTrace) {\n    print(trace)\n}\n",
    ),
    "a trace written to the unified log in the app": lambda workspace: workspace.append(
        BRIDGE_FILE,
        "\nfunc note(_ trace: RoutingDecisionTrace) {\n"
        '    os_log("trace: %{public}@", trace.description)\n}\n',
    ),
    "a trace sent to a Logger in the platform package": lambda workspace: workspace.append(
        APPLE_PLATFORM_FILE,
        "\npublic func note(_ trace: RoutingDecisionTrace) {\n"
        '    let logger = Logger(subsystem: "io.rovia", category: "route")\n'
        '    logger.info("\\(trace)")\n}\n',
    ),
    # The next two carry no `Logger(` token on purpose. `OSLog(` and a
    # lower-case `logger.` are separate channels in the list, and a mutation that
    # happens to contain all three would go on proving them together, so removing
    # `OSLog(` from the detector would not fail a single test.
    "a trace sent to an OSLog in the platform package": lambda workspace: workspace.append(
        APPLE_PLATFORM_FILE,
        "\npublic func note(_ trace: RoutingDecisionTrace) {\n"
        '    let log = OSLog(subsystem: "io.rovia", category: "route")\n'
        '    log.debug("\\(trace)")\n}\n',
    ),
    "a trace sent to a stored logger in the app": lambda workspace: workspace.append(
        BRIDGE_FILE,
        "\nfunc note(_ trace: RoutingDecisionTrace) {\n"
        '    self.logger.debug("\\(trace)")\n}\n',
    ),
    "a trace sent to the host as a provider message": lambda workspace: workspace.append(
        BRIDGE_FILE,
        "\nfunc forward(_ trace: RoutingDecisionTrace, to session: Any) {\n"
        '    _ = session.sendProviderMessage("\\(trace)")\n}\n',
    ),
    "a trace written with debugPrint in the app": lambda workspace: workspace.append(
        BRIDGE_FILE,
        "\nfunc trace(_ trace: RoutingDecisionTrace) {\n    debugPrint(trace)\n}\n",
    ),
    "a trace written with NSLog in the platform package": lambda workspace: workspace.append(
        APPLE_PLATFORM_FILE,
        "\npublic func note(_ trace: RoutingDecisionTrace) {\n"
        '    NSLog("route: %@", "\\(trace)")\n}\n',
    ),
    "a rule evaluation dumped in a package": lambda workspace: workspace.append(
        EVALUATOR_FILE,
        "\npublic func debug(_ evaluation: RuleEvaluation) {\n    dump(evaluation)\n}\n",
    ),
    "a trace held in a Codable envelope in the app": lambda workspace: workspace.append(
        BRIDGE_FILE,
        "\nstruct TraceArchive: Encodable {\n    let trace: RoutingDecisionTrace\n}\n",
    ),
    "a rule evaluation handed to an encoder": lambda workspace: workspace.append(
        EVALUATOR_FILE,
        "\npublic func record(_ evaluation: RuleEvaluation) throws {\n"
        "    _ = try JSONEncoder().encode(evaluation)\n}\n",
    ),
}

CONTRACT_MUTATIONS = {
    "a deleted contract sentence": lambda workspace: workspace.replace(
        MODELS_FILE, "In memory only", "In the evaluator"
    ),
    "the redacted diagnostic no longer Codable": lambda workspace: workspace.replace(
        DIAGNOSTIC_FILE,
        "public struct RoutingDiagnostic: Codable, Sendable, Equatable {",
        "public struct RoutingDiagnostic: Sendable, Equatable {",
    ),
}


class MutationGateTests(WorkspaceTestCase):
    """The gate, stated as the mutations it has to catch.

    A test that only asserts a property of the current tree proves the property
    today. Each test here breaks the property in a temporary copy and requires a
    check to notice, so the check has to be doing the work.
    """

    def test_the_unmodified_workspace_passes_every_check(self):
        self.assertClean()

    def test_every_package_dependency_mutation_is_caught(self):
        for label, mutate in PACKAGE_MUTATIONS.items():
            with self.subTest(mutation=label):
                self.setUp()
                mutate(self.workspace)
                self.assertCaught(package_dependency_problems, canonical_import_problems)

    def test_every_duplicate_evaluator_mutation_is_caught(self):
        for label, source in EVALUATOR_MUTATIONS.items():
            with self.subTest(mutation=label):
                self.setUp()
                if label == "a file of its own":
                    self.workspace.write("client/app/ios/RoviaApp/RouteMatcher.swift", source)
                else:
                    self.workspace.append(APP_SNAPSHOT_FILE, source)
                self.assertCaught(duplicate_evaluator_problems)

    def test_every_legitimate_shape_is_not_flagged(self):
        for label, source in LEGITIMATE_SHAPES.items():
            with self.subTest(shape=label):
                self.setUp()
                self.workspace.append(APP_SNAPSHOT_FILE, source)
                self.assertEqual(
                    duplicate_evaluator_problems(self.root),
                    [],
                    f"{label} was wrongly flagged as a reimplementation",
                )
                self.assertEqual(raw_trace_problems(self.root), [], f"{label} was wrongly flagged")

    def test_a_prefix_assertion_in_a_test_target_file_is_legal(self):
        # The rule is scoped by what the app target compiles, so an identifier
        # prefix assertion in the test target is not a domain-suffix matcher.
        self.workspace.append(
            "client/app/ios/RoviaAppTests/AppModelTests.swift",
            "\nfunc checkPrefix(_ identifier: String) -> Bool { identifier.hasPrefix(\"rovia.\") }\n",
        )
        self.assertEqual(duplicate_evaluator_problems(self.root), [])

    def test_every_raw_trace_mutation_is_caught(self):
        for label, mutate in TRACE_MUTATIONS.items():
            with self.subTest(mutation=label):
                self.setUp()
                mutate(self.workspace)
                self.assertCaught(raw_trace_problems)

    def test_every_redacted_contract_mutation_is_caught(self):
        for label, mutate in CONTRACT_MUTATIONS.items():
            with self.subTest(mutation=label):
                self.setUp()
                mutate(self.workspace)
                self.assertCaught(redacted_contract_problems)


class PackageDependencyStructureTests(WorkspaceTestCase):
    """What the gate reads, checked against the real project rather than a copy."""

    def test_the_project_is_parsed_into_targets_references_and_products(self):
        project = Project(self.workspace.read(PROJECT_FILE))
        self.assertEqual(
            sorted(project.targets), ["RoviaApp", "RoviaAppTests", "RoviaTunnel"]
        )
        self.assertEqual(
            {reference["path"] for reference in project.local_references.values()},
            set(LOCAL_PACKAGE_PATHS.values()),
        )
        self.assertEqual(
            {
                (reference["url"], reference["kind"], reference["version"])
                for reference in project.remote_references.values()
            },
            {
                (expected["url"], "exactVersion", expected["version"])
                for expected in REMOTE_PACKAGES.values()
            },
        )
        for target in LINKED_TARGETS:
            with self.subTest(target=target):
                self.assertEqual(project.declared_products(target), set(CANONICAL_PACKAGES))
                self.assertEqual(project.linked_products(target), set(CANONICAL_PACKAGES))

    def test_a_name_in_a_comment_does_not_declare_a_product(self):
        # Commented out by product name, not by object identifier: the same
        # surgery the mutations use, so this test cannot break when Xcode
        # renumbers either.
        self.workspace.transform(
            PROJECT_FILE, lambda text: _comment_out_product(text, "RoviaApp", "RoviaConfig")
        )
        project = Project(self.workspace.read(PROJECT_FILE))
        self.assertNotIn("RoviaConfig", project.declared_products("RoviaApp"))
        self.assertIn("is declared here", self.workspace.read(PROJECT_FILE))
        # And the gate notices the app no longer declares it.
        self.assertCaught(package_dependency_problems)

    def test_the_gate_reports_a_product_that_was_renamed(self):
        self.workspace.transform(PROJECT_FILE, lambda text: _rename_product(text, "RoviaConfig"))
        found = self.assertCaught(package_dependency_problems)
        self.assertTrue(any("RoviaConfig" in problem for problem in found), found)

    def test_the_project_mutations_do_not_name_object_identifiers(self):
        # A gate whose own fixtures name `E1000…0005` stops working the moment
        # Xcode renumbers the objects, and the failure looks like a passing gate:
        # the mutation would raise, not fail. So the surgery is done by product
        # name and package path, and this test renumbers every identifier in the
        # project and requires the same result.
        renumbered = renumber_identifiers(self.workspace.read(PROJECT_FILE))
        for label, operation in (
            (
                "a repointed package path",
                lambda text: _repoint_local_reference(
                    text, LOCAL_PACKAGE_PATHS["RoviaApplePlatform"], "../../elsewhere"
                ),
            ),
            ("a dropped target product", lambda text: _drop_product_from_target(text, "RoviaApp", "RoviaConfig")),
            (
                "a dropped frameworks entry",
                lambda text: _drop_product_from_frameworks(text, "RoviaApp", "RoviaConfig"),
            ),
            (
                "a detached local reference",
                lambda text: _detach_local_reference(text, LOCAL_PACKAGE_PATHS["RoviaApplePlatform"]),
            ),
            ("a product pointed at no package", lambda text: _point_product_at_nothing(text, "RoviaRouting")),
            ("a renamed product", lambda text: _rename_product(text, "RoviaConfig")),
            (
                "a floated remote pin",
                lambda text: _float_remote_requirement(text, REMOTE_PACKAGES["rovia-core"]["url"]),
            ),
            (
                "a commented-out product entry",
                lambda text: _comment_out_product(text, "RoviaApp", "RoviaConfig"),
            ),
        ):
            with self.subTest(operation=label):
                # Both results are normalised back to placeholder identifiers, so
                # the comparison is about which line the surgery touched and not
                # about the identifiers Xcode happened to assign.
                self.assertEqual(
                    renumber_identifiers(operation(renumbered)),
                    renumber_identifiers(operation(self.workspace.read(PROJECT_FILE))),
                )

    def test_the_project_objects_are_parsed_by_shape_not_by_prefix(self):
        # The parse must not depend on an identifier starting with a particular
        # letter, only on the 24 hex digits Xcode assigns.
        text = self.workspace.read(PROJECT_FILE)
        renumbered = renumber_identifiers(text)
        self.assertNotEqual(text, renumbered)
        project = Project(renumbered)
        self.assertEqual(
            {reference["path"] for reference in project.local_references.values()},
            set(LOCAL_PACKAGE_PATHS.values()),
        )

    def test_the_app_target_compiles_the_bridge(self):
        project = Project(self.workspace.read(PROJECT_FILE))
        self.assertIn("CanonicalRouteBridge.swift", project.compiled_sources("RoviaApp"))
        self.assertIn("AppSnapshot.swift", project.compiled_sources("RoviaApp"))


class DuplicateEvaluatorDetectorTests(unittest.TestCase):
    """The detector, against declarations written out here rather than in the app."""

    def detector(self, source: str, strict: bool = False) -> list[str]:
        return duplicate_evaluator_findings(source, strict=strict)

    def test_the_bridge_and_the_display_models_are_clean(self):
        for relative in (
            "client/app/ios/RoviaApp/CanonicalRouteBridge.swift",
            "client/app/ios/RoviaApp/AppSnapshot.swift",
            "client/app/ios/RoviaApp/RoutingDebuggerView.swift",
        ):
            with self.subTest(source=relative):
                self.assertEqual(
                    self.detector((REPO_ROOT / relative).read_text(encoding="utf-8"), strict=True),
                    [],
                )

    def test_each_rule_fires_on_its_own_shape(self):
        cases = {
            "range type": "enum ipv6Range { case all }",
            "cidr type": "struct CIDR { let prefix: Int }",
            "subnet type": "final class Subnet { let mask: UInt32 }",
            "normalizeHost": "func normalizeHost(_ value: String) -> String { value }",
            "normaliseHost": "func normaliseHost(_ value: String) -> String { value }",
            "canonicalizeIPAddress": "func canonicalizeIPAddress(_ value: String) -> String { value }",
            "cidrContains": "func cidrContains(_ address: String) -> Bool { true }",
            "isInSubnet": "func isInSubnet(_ address: String) -> Bool { true }",
            "withinPrefix": "func withinPrefix(_ address: String) -> Bool { true }",
            "belongsToBlock": "func belongsToBlock(_ address: String) -> Bool { true }",
            "matchesSubnet": "func matchesSubnet(_ address: String) -> Bool { true }",
            "comparesMatcher": "func comparesMatcher(_ a: Int, _ b: Int) -> Bool { true }",
            "satisfiesRouteMatcher": "func satisfiesRouteMatcher(_ a: Int) -> Bool { true }",
            "evaluateRoute": "func evaluateRoute(for input: String) -> Int { 0 }",
            "decide": "func decide(for destination: String) -> Int { 0 }",
            "explain": "func explain(for request: String) -> Int { 0 }",
            "resolve": "func resolve(for host: String) -> Int { 0 }",
            "firstMatchingRule": "func firstMatchingRule(in rules: [Int]) -> Int? { nil }",
            "indexOfFirstMatch": "func indexOfFirstMatch(in rules: [Int]) -> Int? { nil }",
            "a second evaluator type": "enum RouteEvaluator2 { func evaluate(_ input: String) {} }",
        }
        for label, source in cases.items():
            with self.subTest(case=label):
                self.assertTrue(
                    self.detector(source, strict=True),
                    f"{label} was not detected as a reimplementation",
                )

    def test_comments_and_strings_are_not_declarations(self):
        source = """
        // func normalizeHost(_ value: String) -> String { value }
        /* enum IPv4Range { } */
        let sample = "func evaluateRoute(for input: String)"
        """
        self.assertEqual(self.detector(source, strict=True), [])

    def test_a_call_into_the_canonical_evaluator_is_not_a_declaration(self):
        source = """
        enum CanonicalRouteBridge {
            static func evaluation(sample: DebugSampleSummary) throws -> DebugEvaluation {
                let diagnostic = try RouteEvaluator().explain(input, using: routeSet)
                return DebugEvaluation(decision: displayOutcome(diagnostic.finalDecision))
            }
        }
        """
        self.assertEqual(self.detector(source, strict=True), [])

    def test_the_prefix_rule_needs_a_host_shaped_subject(self):
        host = """
        func domainMatches(_ host: String, _ suffix: String) -> Bool {
            host == suffix || host.hasSuffix("." + suffix)
        }
        """
        self.assertTrue(self.detector(host, strict=True))

    def test_the_prefix_rule_ignores_an_accessibility_identifier(self):
        # The test target checks `identifier.hasPrefix("rovia.")`, and that is
        # not a domain-suffix matcher. The subject decides, not the method.
        source = """
        func checkPrefix(_ identifier: String) -> Bool {
            identifier.hasPrefix("rovia.")
        }
        """
        self.assertEqual(self.detector(source, strict=False), [])
        self.assertEqual(self.detector(source, strict=True), [])




class RawTraceDetectorTests(unittest.TestCase):
    """The trace detector, against the shapes that would reintroduce the risk."""

    def detector(self, source: str) -> list[str]:
        return raw_trace_findings(source)

    def test_the_current_sources_are_clean(self):
        roots = {
            "core/": core_root(),
            "client/": REPO_ROOT,
            "platform/": REPO_ROOT,
        }
        for relative in (
            "core/config/Sources/RoviaConfig/CanonicalModels.swift",
            "core/config/Sources/RoviaConfig/ConfigValidation.swift",
            "core/routing/Sources/RoviaRouting/RouteEvaluator.swift",
            "core/routing/Sources/RoviaRouting/RoutingDiagnostic.swift",
            "client/app/ios/RoviaApp/CanonicalRouteBridge.swift",
            "client/app/ios/RoviaApp/AppModel.swift",
            "platform/apple/Sources/RoviaApplePlatform/ApplePlatform.swift",
        ):
            with self.subTest(source=relative):
                base = next(root for prefix, root in roots.items() if relative.startswith(prefix))
                self.assertEqual(
                    self.detector((base / relative).read_text(encoding="utf-8")), []
                )

    def test_each_shape_is_detected(self):
        cases = {
            "declaration": "public struct RoutingDecisionTrace: Codable, Sendable {}",
            "rule evaluation declaration": "public struct RuleEvaluation: Codable, Sendable {}",
            "retroactive extension": "extension RoutingDecisionTrace: Codable {}",
            "retroactive extension on a rule evaluation": "extension RuleEvaluation: Codable {}",
            "wrapper": "struct Archive: Codable { let trace: RoutingDecisionTrace }",
            "encodable wrapper": "struct Archive: Encodable { let trace: RoutingDecisionTrace }",
            "stored property": "public var lastTrace: RoutingDecisionTrace",
            "optional property": "public var lastTrace: RoutingDecisionTrace?",
            "dictionary": "public var cache: [String: RoutingDecisionTrace] = [:]",
            "array": "public var traces: [RoutingDecisionTrace] = []",
            "encoder call": (
                "public func persist(_ trace: RoutingDecisionTrace) throws {\n"
                "    _ = try JSONEncoder().encode(trace)\n}"
            ),
            "rule evaluation through an encoder": (
                "public func persist(_ evaluation: RuleEvaluation) throws {\n"
                "    _ = try JSONEncoder().encode(evaluation)\n}"
            ),
            "durable store": (
                "public func stash(_ trace: RoutingDecisionTrace) {\n"
                '    UserDefaults.standard.set(1, forKey: "t")\n}'
            ),
            "typealias": "public typealias Stored = RoutingDecisionTrace",
            "durable store with the type inline": (
                "let value = UserDefaults.standard.object(forKey: RoutingDecisionTrace.self)"
            ),
        }
        for label, source in cases.items():
            with self.subTest(shape=label):
                self.assertTrue(
                    self.detector(source), f"{label} was not detected as a trace risk"
                )

    def test_a_mention_in_a_comment_is_not_a_risk(self):
        source = """
        // A RoutingDecisionTrace holds the raw input and is not Codable.
        /* UserDefaults.standard.set(trace, forKey: "x") is what we must avoid */
        let message = "encode(trace)"
        """
        self.assertEqual(self.detector(source), [])

    def test_a_stored_rule_evaluation_is_not_a_risk(self):
        # `RouteEvaluator.evaluate` builds a local `[RuleEvaluation]` while it
        # works, and a local and a stored property are indistinguishable without
        # scope analysis. `RuleEvaluation` holds a rule identifier and a matched
        # matcher, not the input, so its Codable conformance is the whole risk and
        # the gate checks exactly that. Demanding more would mean demanding that
        # the canonical evaluator stop evaluating.
        for source in (
            "public var lastEvaluation: RuleEvaluation",
            "let evaluations: [RuleEvaluation] = []",
            "struct Archive: Codable { let evaluation: RuleEvaluation }",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.detector(source), [])

    def test_a_plain_json_encoder_is_not_a_risk(self):
        # The detector is about traces, not about JSON. RoviaConfig.JSONCoding is a
        # legitimate shared encoder, and flagging it would make the gate noise.
        source = "let encoder = JSONEncoder()\nlet decoder = JSONDecoder()\n"
        self.assertEqual(self.detector(source), [])

    def test_a_persistence_function_without_a_trace_parameter_is_not_a_risk(self):
        source = (
            "public func save<T: Encodable>(_ value: T, to path: String) throws {\n"
            "    let data = try JSONEncoder().encode(value)\n"
            "    try data.write(to: URL(fileURLWithPath: path))\n"
            "}\n"
        )
        self.assertEqual(self.detector(source), [])


class RedactedContractDetectorTests(WorkspaceTestCase):
    def test_the_contract_sentences_are_required(self):
        self.assertEqual(redacted_contract_problems(self.root), [])

    def test_deleting_a_sentence_is_caught(self):
        self.workspace.replace(
            MODELS_FILE, "never written to disk", "sometimes written to disk"
        )
        self.assertCaught(redacted_contract_problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
