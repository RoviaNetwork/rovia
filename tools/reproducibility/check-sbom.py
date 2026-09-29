#!/usr/bin/env python3
"""Check an SPDX 2.3 SBOM for the invariants this repository depends on.

The generator is not trusted to be the only writer of an SBOM: a release gate
needs an independent check that runs on the file that was actually produced.
This script re-reads a document and reports every invariant it can see without
network access:

* SPDX 2.3 identity fields, a CC0-1.0 data license, and a single SPDXRef-DOCUMENT;
* a ``created`` instant that is UTC and ends in ``Z``, matching the SPDX 2.3
  timestamp format rather than Python's ``+00:00`` offset;
* ``creators`` that are actors (``Person:``, ``Organization:``, ``Tool:``) and a
  versioned tool creator;
* a document namespace that is an absolute URI, carries no fragment, and does
  not end in one of the fixed placeholders (``spdx/foundation`` among them)
  that would make two documents indistinguishable;
* unique, well-formed SPDX identifiers, relationship types drawn from the SPDX
  2.3 enum, no duplicated relationship, and every relationship pointing at an
  element the document declares;
* the product components Rovia actually ships: the application, the Packet
  Tunnel extension, and every Swift package in tools/ci/local-packages.txt;
* valid relationship types.

It cannot check upstream SPDX tooling compatibility, purl resolution, or licence
conclusions; those remain reviewer responsibilities.

Usage:
    check-sbom.py <sbom> [--repository PATH]
    check-sbom.py <repository-root>     # checks every SBOM under the root

``--repository PATH`` additionally checks that the document covers every package
listed in ``PATH``'s ``tools/ci/local-packages.txt``, which is what the release
gate uses so a package cannot be dropped from the SBOM without failing.

Exit status: 0 valid, 1 problems found, 2 usage error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SUPPORTED_SPDX_VERSION = "SPDX-2.3"
REQUIRED_DATA_LICENSE = "CC0-1.0"
DOCUMENT_ID = "SPDXRef-DOCUMENT"
PACKAGE_LIST = "tools/ci/local-packages.txt"
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SPDX_ID = re.compile(r"^SPDXRef-[A-Za-z0-9.\-]+$")
CREATOR = re.compile(r"^(Person|Organization|Tool): \S.*$")
# A tool creator that names no version cannot say which tool wrote the document.
# The name and the version are separated by the last hyphen before a digit, so
# "rovia-sbom-0.2.0" is the tool "rovia-sbom" at "0.2.0", not the tool
# "rovia-sbom-0.2" at "0".
VERSIONED_TOOL = re.compile(r"^Tool: [A-Za-z][A-Za-z0-9._\-]*-[0-9][0-9A-Za-z.+-]*$")
RELATIONSHIP_TYPE = re.compile(r"^[A-Z_]+$")
SPDX_RELATIONSHIP_TYPES = frozenset(
    {
        "AMENDS",
        "ANCESTOR_OF",
        "BUILD_DEPENDENCY_OF",
        "BUILD_TOOL_OF",
        "CONTAINED_BY",
        "CONTAINS",
        "COPY_OF",
        "DATA_FILE_OF",
        "DEPENDENCY_MANIFEST_OF",
        "DEPENDENCY_OF",
        "DEPENDS_ON",
        "DESCENDANT_OF",
        "DESCRIBED_BY",
        "DESCRIBES",
        "DEV_DEPENDENCY_OF",
        "DISTRIBUTION_ARTIFACT",
        "DOCUMENTATION_OF",
        "DYNAMIC_LINK",
        "EXAMPLE_OF",
        "EXPANDED_FROM_ARCHIVE",
        "FILE_ADDED",
        "FILE_DELETED",
        "FILE_MODIFIED",
        "GENERATED_FROM",
        "GENERATES",
        "HAS_PREREQUISITE",
        "METAFILE_OF",
        "OPTIONAL_COMPONENT_OF",
        "OPTIONAL_DEPENDENCY_OF",
        "OTHER",
        "PACKAGE_OF",
        "PATCH_APPLIED",
        "PATCH_FOR",
        "PREREQUISITE_FOR",
        "PROVIDED_DEPENDENCY_OF",
        "REQUIREMENT_DESCRIPTION_FOR",
        "RUNTIME_DEPENDENCY_OF",
        "SPECIFICATION_FOR",
        "STATIC_LINK",
        "TEST_CASE_OF",
        "TEST_DEPENDENCY_OF",
        "VARIANT_OF",
    }
)
PACKAGE_NAME = re.compile(r'name:\s*"([^"]+)"')
REMOTE_PIN_PATTERN = re.compile(
    r"isa = XCRemoteSwiftPackageReference;"
    r".*?repositoryURL = \"(?P<url>[^\"]+)\";"
    r".*?kind = (?P<kind>\w+);"
    r".*?version = (?P<version>[^;]+);",
    re.S,
)


def remote_pins(project_text: str) -> list[dict]:
    """Pinned remote packages from the Xcode project. Mirrors the generator;
    both read the project rather than a second list, so they cannot drift."""
    pins = []
    for match in REMOTE_PIN_PATTERN.finditer(project_text):
        pins.append(
            {
                "url": match.group("url"),
                "kind": match.group("kind"),
                "version": match.group("version").strip(),
            }
        )
    return pins
# A namespace has to identify one document. These are the fixed placeholders the
# project used before namespaces carried a run identifier; reusing one makes two
# documents indistinguishable to anything that stores them.
PLACEHOLDER_NAMESPACES = {"spdx", "sbom", "rovia", "rovia-ios", "document", "foundation", "package", "packages"}


def problems(document) -> list[str]:
    """Return every invariant the document breaks."""
    found: list[str] = []
    if not isinstance(document, dict):
        return ["the document is not a JSON object"]

    if document.get("spdxVersion") != SUPPORTED_SPDX_VERSION:
        found.append(
            f"spdxVersion must be {SUPPORTED_SPDX_VERSION}, found {document.get('spdxVersion')!r}"
        )
    if document.get("dataLicense") != REQUIRED_DATA_LICENSE:
        found.append(
            f"dataLicense must be {REQUIRED_DATA_LICENSE}, found {document.get('dataLicense')!r}"
        )
    if document.get("SPDXID") != DOCUMENT_ID:
        found.append(f"SPDXID must be {DOCUMENT_ID}, found {document.get('SPDXID')!r}")
    if not document.get("name"):
        found.append("the document has no name")

    creation = document.get("creationInfo")
    if not isinstance(creation, dict):
        found.append("creationInfo is missing")
        creation = {}
    created = creation.get("created")
    if not isinstance(created, str) or not UTC_TIMESTAMP.fullmatch(created):
        found.append(
            f"creationInfo.created must be a UTC instant ending in Z, found {created!r}"
        )
    creators = creation.get("creators")
    if not isinstance(creators, list) or not creators:
        found.append("creationInfo.creators must be a non-empty list")
    else:
        for creator in creators:
            if not isinstance(creator, str) or not CREATOR.fullmatch(creator):
                found.append(f"creator {creator!r} must be 'Person:', 'Organization:' or 'Tool:' followed by a name")
        if not any(VERSIONED_TOOL.fullmatch(creator) for creator in creators if isinstance(creator, str)):
            found.append(
                "creators must include a versioned tool creator such as 'Tool: rovia-sbom-0.2.0'"
            )

    namespace = document.get("documentNamespace")
    if not isinstance(namespace, str) or not namespace:
        found.append("documentNamespace is missing")
    else:
        if not namespace.startswith(("https://", "http://", "urn:")):
            found.append(f"documentNamespace must be an absolute URI, found {namespace!r}")
        if "#" in namespace:
            found.append(f"documentNamespace must not contain a fragment, found {namespace!r}")
        if namespace.rstrip("/").rsplit("/", 1)[-1].lower() in PLACEHOLDER_NAMESPACES:
            found.append(
                "documentNamespace must end in a per-document identifier so two documents are "
                f"distinguishable, found {namespace!r}"
            )

    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        found.append("packages must be a non-empty list")
        return found

    identifiers: set[str] = {DOCUMENT_ID}
    for package in packages:
        if not isinstance(package, dict):
            found.append("a package entry is not a JSON object")
            continue
        identifier = package.get("SPDXID")
        if not isinstance(identifier, str) or not SPDX_ID.fullmatch(identifier):
            found.append(f"package SPDXID {identifier!r} is not a valid SPDXRef identifier")
            continue
        if identifier in identifiers:
            found.append(f"duplicate SPDX identifier {identifier}")
        identifiers.add(identifier)
        if not package.get("name"):
            found.append(f"{identifier} has no name")
        if not package.get("downloadLocation"):
            found.append(f"{identifier} has no downloadLocation")
        if not isinstance(package.get("filesAnalyzed"), bool):
            found.append(f"{identifier} must declare filesAnalyzed")
        if not package.get("copyrightText"):
            found.append(f"{identifier} has no copyrightText")
        if not package.get("licenseConcluded") or not package.get("licenseDeclared"):
            found.append(f"{identifier} must declare licenseConcluded and licenseDeclared")

    relationships = document.get("relationships")
    if not isinstance(relationships, list) or not relationships:
        found.append("relationships must be a non-empty list")
    else:
        seen: set[tuple] = set()
        for relationship in relationships:
            if not isinstance(relationship, dict):
                found.append("a relationship entry is not a JSON object")
                continue
            kind = relationship.get("relationshipType")
            if not isinstance(kind, str) or not RELATIONSHIP_TYPE.fullmatch(kind) or kind not in SPDX_RELATIONSHIP_TYPES:
                found.append(f"relationshipType {kind!r} is not an SPDX 2.3 relationship type")
            for field in ("spdxElementId", "relatedSpdxElement"):
                value = relationship.get(field)
                if value not in identifiers:
                    found.append(f"relationship {field} {value!r} refers to an unknown SPDX identifier")
            key = (
                relationship.get("spdxElementId"),
                kind,
                relationship.get("relatedSpdxElement"),
            )
            if all(part is not None for part in key):
                if key in seen:
                    found.append(
                        f"duplicate relationship {key[0]} {key[1]} {key[2]}"
                    )
                seen.add(key)

    described = document.get("documentDescribes")
    if described is not None:
        if not isinstance(described, list) or not described:
            found.append("documentDescribes must be a non-empty list when present")
        else:
            for value in described:
                if value not in identifiers:
                    found.append(f"documentDescribes {value!r} refers to an unknown SPDX identifier")

    related: set[str] = set()
    for relationship in relationships or []:
        if isinstance(relationship, dict):
            related.add(relationship.get("spdxElementId"))
            related.add(relationship.get("relatedSpdxElement"))
    for identifier in sorted(identifiers - {DOCUMENT_ID}):
        if identifier not in related:
            found.append(f"{identifier} is not connected to the document by any relationship")

    roles = {
        "application component": [p for p in packages if str(p.get("SPDXID", "")).startswith("SPDXRef-App-")],
        "extension component": [p for p in packages if str(p.get("SPDXID", "")).startswith("SPDXRef-Extension-")],
        "Swift package components": [p for p in packages if str(p.get("SPDXID", "")).startswith("SPDXRef-Package-")],
    }
    for label, found_packages in roles.items():
        if not found_packages:
            found.append(f"the document is missing {label}")
    return found


def check_package_coverage(document, root: Path) -> list[str]:
    """Confirm every local package and every pinned remote is present."""
    listing = root / PACKAGE_LIST
    if not listing.is_file():
        return [f"the local package list is missing: {PACKAGE_LIST}"]
    found: list[str] = []
    packages = [
        package for package in document.get("packages", []) if isinstance(package, dict)
    ]
    identifiers = {
        str(package.get("SPDXID", "")).removeprefix("SPDXRef-Package-") for package in packages
    }
    for line in listing.read_text(encoding="utf-8").splitlines():
        relative = line.strip()
        if not relative or relative.startswith("#"):
            continue
        manifest = root / relative / "Package.swift"
        if not manifest.is_file():
            found.append(f"{relative}/Package.swift is missing")
            continue
        match = PACKAGE_NAME.search(manifest.read_text(encoding="utf-8"))
        if match is None:
            found.append(f"{relative}/Package.swift does not declare a package name")
        elif match.group(1) not in identifiers:
            found.append(f"{relative} ({match.group(1)}) is missing from the SBOM")
    project = root / "client/app/ios/RoviaApp.xcodeproj/project.pbxproj"
    for pin in remote_pins(project.read_text(encoding="utf-8")):
        name = pin["url"].rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        matches = [
            package
            for package in packages
            if package.get("downloadLocation") == pin["url"]
            and str(package.get("versionInfo", "")) == pin["version"]
        ]
        if not matches:
            found.append(f"pinned remote {name}@{pin['version']} is missing from the SBOM")
    return found


def main(argv: list[str]) -> int:
    repository: Path | None = None
    positional: list[str] = []
    while argv:
        argument = argv.pop(0)
        if argument in ("-h", "--help"):
            print(__doc__)
            return 0
        if argument == "--repository" or argument.startswith("--repository="):
            if argument.startswith("--repository="):
                value = argument.split("=", 1)[1]
            else:
                if not argv:
                    print("check-sbom.py: --repository requires a value", file=sys.stderr)
                    return 2
                value = argv.pop(0)
            repository = Path(value).resolve()
            continue
        if argument.startswith("-"):
            print(f"check-sbom.py: unknown option: {argument}", file=sys.stderr)
            return 2
        positional.append(argument)

    if len(positional) != 1:
        print(
            "usage: check-sbom.py <sbom> [--repository PATH] | check-sbom.py <repository-root>",
            file=sys.stderr,
        )
        return 2

    target = Path(positional[0]).resolve()
    if target.is_dir():
        root = target
        candidates = sorted(root.glob("**/*.spdx.json")) + sorted(root.glob("**/SBOM*.json"))
        if not candidates:
            print(f"check-sbom.py: no SBOM was found under {root}", file=sys.stderr)
            return 1
        failures = 0
        for candidate in candidates:
            try:
                document = load(candidate)
            except (OSError, ValueError) as error:
                print(f"check-sbom.py: {candidate} could not be read: {error}", file=sys.stderr)
                failures += 1
                continue
            found = problems(document) + check_package_coverage(document, root)
            failures += report(candidate, found)
        return 1 if failures else 0

    try:
        document = load(target)
    except (OSError, ValueError) as error:
        print(f"check-sbom.py: {target} could not be read: {error}", file=sys.stderr)
        return 1
    found = problems(document)
    if repository is not None:
        found = found + check_package_coverage(document, repository)
    return report(target, found)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def report(path: Path, found: list[str]) -> int:
    if found:
        print(f"check-sbom.py: {path} is not a usable SPDX 2.3 document", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"check-sbom.py: {path} satisfies the SPDX 2.3 invariants Rovia depends on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
