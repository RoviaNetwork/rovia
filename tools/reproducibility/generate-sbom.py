#!/usr/bin/env python3
"""Generate an SPDX 2.3 SBOM for the Rovia iOS product slice.

The document is written for a reviewer who cannot see the build, so it names
the shipped components rather than only the source packages:

* the host application and the Packet Tunnel extension, with the versions and
  bundle identifiers taken from the Xcode project inputs;
* every local Swift package listed in tools/ci/local-packages.txt;
* every engine candidate the lock has approved and enabled, with its source
  commit and artifact digest. That is an inventory, not a decision:
  ``tools/ci/verify-engine-checksums.sh`` is where "may this ship" is enforced,
  and it refuses a lock whose approved engines are not declared as production
  engines. Listing an engine the lock has not reconciled yet is deliberate, so a
  reviewer sees the discrepancy instead of reading a document that omits a
  binary the build inputs contain.

SPDX 2.3 details that are easy to get wrong and are therefore asserted by
tools/reproducibility/test_generate_sbom.py:

* ``creationInfo.created`` is a UTC instant that ends in ``Z``. Python's
  ``datetime.isoformat`` emits ``+00:00`` and microseconds, which is not a
  valid SPDX timestamp.
* ``creationInfo.creators`` entries are actors: ``Person:``, ``Organization:``
  or ``Tool:`` followed by a name. A bare tool name is not a valid creator.
* ``documentNamespace`` must be unique per document. A fixed namespace makes
  two documents indistinguishable, so the namespace carries a run identifier:
  a caller-supplied one for reproducible builds, otherwise a random UUID.

Reproducibility: a document is byte-reproducible only when both of its
run-dependent fields are fixed. ``documentNamespace`` carries
``--namespace-id``, and ``creationInfo.created`` carries ``--created`` or
``SOURCE_DATE_EPOCH``. Fixing one and not the other produces documents that
differ in a single field, which is the case this previously documented as
reproducible.

Usage:
    generate-sbom.py <repository-root> <output> [--lock PATH] [--namespace-id ID]
                     [--created SECONDS|RFC3339]
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

SPDX_VERSION = "SPDX-2.3"
DATA_LICENSE = "CC0-1.0"
TOOL_NAME = "rovia-sbom"
TOOL_VERSION = "0.2.0"
DOCUMENT_NAME = "Rovia-iOS"
NAMESPACE_BASE = "https://rovia.invalid/spdx"
APP_EXECUTABLE = "Rovia"
EXTENSION_NAME = "RoviaTunnel"
PACKAGE_LIST = "tools/ci/local-packages.txt"
APP_INFO_PLIST = "client/app/ios/RoviaApp/Info.plist"
EXTENSION_INFO_PLIST = "client/app/ios/RoviaTunnel/Info.plist"
BUNDLE_IDENTIFIERS = "client/app/ios/Config/BundleIdentifiers.xcconfig"
COPYRIGHT = "Copyright (c) 2026 Rovia contributors"
NOASSERTION = "NOASSERTION"

# Rovia's own source is MIT, and the packages below are built from it.
PROJECT_LICENSE = "MIT"

# The license of the code an engine candidate builds, keyed by the upstream
# project its `source` names. This is the only place the mapping is written
# down, and it is checked against the `license` the lock declares, so the two
# cannot drift apart without the generator refusing.
#
# The candidate called `xray` in the shipped lock is built from libXray, so the
# license that applies is libXray's. Xray-core is a different project with a
# different license and would be a different candidate.
ENGINE_LICENSES = {
    "https://github.com/XTLS/libXray": "MIT",
    "https://github.com/XTLS/Xray-core": "MPL-2.0",
    "https://github.com/SagerNet/sing-box": "GPL-3.0-or-later",
}


def utc_timestamp(epoch: int | None = None) -> str:
    """The SPDX creation instant.

    ``creationInfo.created`` is a wall-clock reading, so two runs of the same tree
    produced documents that differed in one field and the document was not
    byte-reproducible however fixed the namespace was. The instant is therefore
    settable: ``--created`` wins, then ``SOURCE_DATE_EPOCH``, and only a run that
    supplies neither gets the current time. That ordering is the one the
    reproducible-builds convention uses, and it means a caller who has already
    exported SOURCE_DATE_EPOCH does not have to pass a second flag.
    """
    if epoch is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def spdx_identifier(*parts: str) -> str:
    safe = [re.sub(r"[^A-Za-z0-9.\-]+", "-", part).strip("-") or "unknown" for part in parts]
    return "SPDXRef-" + "-".join(safe)


def read_plist(path: Path) -> dict:
    with path.open("rb") as stream:
        document = plistlib.load(stream)
    if not isinstance(document, dict):
        raise SystemExit(f"{path} is not a property-list dictionary")
    return document


def read_bundle_identifiers(path: Path) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        identifiers[key.strip()] = value.strip()
    return identifiers


def package_name(manifest: Path) -> str | None:
    match = re.search(r'name:\s*"([^"]+)"', manifest.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def swift_package_component(name: str, version: str) -> dict:
    return {
        "SPDXID": spdx_identifier("Package", name),
        "name": name,
        "versionInfo": version,
        "supplier": "Organization: Rovia contributors",
        "primaryPackagePurpose": "LIBRARY",
        "downloadLocation": NOASSERTION,
        "filesAnalyzed": False,
        "licenseConcluded": "MIT",
        "licenseDeclared": "MIT",
        "copyrightText": COPYRIGHT,
        "comment": (
            "Local Swift package built from this repository. The MIT license covers the new "
            "Rovia source only; see THIRD_PARTY_NOTICES.md for bundled components."
        ),
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:swift/{quote(name)}@{version}",
            }
        ],
    }


def binary_component(
    identifier: str,
    name: str,
    version: str,
    comment: str,
    purl_name: str | None = None,
    license_id: str = PROJECT_LICENSE,
) -> dict:
    return {
        "SPDXID": spdx_identifier(identifier, name),
        "name": name,
        "versionInfo": version,
        "supplier": "Organization: Rovia contributors",
        "primaryPackagePurpose": "APPLICATION",
        "downloadLocation": NOASSERTION,
        "filesAnalyzed": False,
        "licenseConcluded": license_id,
        "licenseDeclared": license_id,
        "copyrightText": COPYRIGHT,
        "comment": comment,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:generic/{quote(purl_name or name)}@{version}",
            }
        ],
    }


def engine_license(name: str, entry: dict) -> str:
    """The SPDX identifier for an engine, or a refusal.

    Three ways this refuses, each because an SBOM that guesses is worse than one
    that stops:

    * the lock does not say what license the code is;
    * the lock names a source this generator has no license for, so the declared
      license cannot be checked against anything;
    * the lock's license disagrees with the license the source implies, which
      means one of the two is a copy-paste from the wrong project.
    """
    source = entry.get("source")
    declared = entry.get("license")
    if not isinstance(source, str) or not source.strip():
        raise SystemExit(
            f"generate-sbom.py: engine candidate {name!r} has no source, so its "
            "license cannot be derived"
        )
    if not isinstance(declared, str) or not declared.strip():
        raise SystemExit(
            f"generate-sbom.py: engine candidate {name!r} declares no license; "
            f"refusing to emit a component whose license is unknown (source {source})"
        )
    expected = ENGINE_LICENSES.get(source.rstrip("/"))
    if expected is None:
        raise SystemExit(
            f"generate-sbom.py: engine candidate {name!r} is built from {source}, "
            f"whose license this generator does not know; the lock declares "
            f"{declared} but nothing here can confirm it"
        )
    if declared != expected:
        raise SystemExit(
            f"generate-sbom.py: engine candidate {name!r} declares license {declared} "
            f"but {source} is {expected}; refusing to emit a component whose declared "
            "license contradicts its source"
        )
    return declared


def engine_component(name: str, entry: dict) -> dict:
    version = entry.get("version") or "unversioned"
    license_id = engine_license(name, entry)
    component = binary_component(
        "Engine",
        f"{name}-{version}",
        version,
        (
            f"Bundled {name} engine built from {entry.get('source')} at commit "
            f"{entry.get('commit')} with {entry.get('goVersion')} for architectures "
            f"{', '.join(entry.get('architectures') or [])}. Approval: {entry.get('approval')}."
        ),
        purl_name=name,
        license_id=license_id,
    )
    component["name"] = name
    component["SPDXID"] = spdx_identifier("Engine", name, str(version))
    component["comment"] += (
        f" Upstream license {license_id}, derived from {entry.get('source')} and "
        "required to match the engine lock."
    )
    digest = entry.get("sha256")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        component["checksums"] = [{"algorithm": "SHA256", "checksumValue": digest}]
    return component


RFC3339_UTC = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z$")


def resolve_created(value: str | None) -> int | None:
    """Seconds since the epoch for --created, or SOURCE_DATE_EPOCH, or None.

    Accepts either form a build system is likely to have: an integer count of
    seconds, or the RFC 3339 instant. Returns None when neither source supplies
    one, which is the caller's signal to use the wall clock and say so.
    """
    if value is not None:
        # The flag was given, so a blank value is a usage error rather than a
        # request for the wall clock. Silently defaulting here is how a
        # reproducibility claim becomes false without anything failing.
        if not value.strip():
            print(
                "generate-sbom.py: --created was given an empty value; pass "
                "seconds since the Unix epoch or an RFC 3339 UTC instant ending in Z",
                file=sys.stderr,
            )
            raise SystemExit(2)
        raw = value.strip()
    else:
        raw = (os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
        if not raw:
            return None
    instant = RFC3339_UTC.match(raw)
    if instant:
        parsed = datetime.strptime(instant.group(1), "%Y-%m-%dT%H:%M:%S")
        return int(parsed.replace(tzinfo=timezone.utc).timestamp())
    try:
        return int(raw)
    except ValueError:
        print(
            "generate-sbom.py: --created must be seconds since the Unix epoch or an "
            f"RFC 3339 UTC instant ending in Z, not {raw!r}",
            file=sys.stderr,
        )
        raise SystemExit(2)


def load_lock(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise SystemExit(f"{path} is not valid JSON: {error}")
    return lock if isinstance(lock, dict) else {}


def enabled_engines(lock: dict) -> dict[str, dict]:
    """Engines the lock has approved and enabled, keyed by candidate name.

    This is an inventory of what the build inputs would ship, not a policy
    decision: any approved, enabled candidate appears, even one the engine lock
    verifier has not yet accepted as a production engine, so a reviewer can see
    the discrepancy instead of reading an SBOM that quietly omits a binary.
    tools/ci/verify-engine-checksums.sh is where "may this ship" is decided.
    """
    candidates = lock.get("candidates")
    if not isinstance(candidates, dict):
        return {}
    engines: dict[str, dict] = {}
    for name, entry in candidates.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is True and entry.get("approval") == "approved":
            engines[str(name)] = entry
    return engines


def build_document(
    root: Path, lock: dict, namespace_id: str, created: int | None = None
) -> dict:
    identifiers = read_bundle_identifiers(root / BUNDLE_IDENTIFIERS)
    app_plist = read_plist(root / APP_INFO_PLIST)
    extension_plist = read_plist(root / EXTENSION_INFO_PLIST)
    version = str(app_plist.get("CFBundleShortVersionString") or "0.0.0")
    app_identifier = identifiers.get("ROVIA_BUNDLE_IDENTIFIER") or "io.rovia.client"
    tunnel_identifier = identifiers.get("ROVIA_TUNNEL_BUNDLE_IDENTIFIER") or f"{app_identifier}.tunnel"

    app = binary_component(
        "App",
        app_identifier,
        version,
        (
            f"Rovia host application ({APP_EXECUTABLE}). Marketing version {version}, "
            f"build {app_plist.get('CFBundleVersion')}, bundle identifier {app_identifier}, "
            f"minimum system {app_plist.get('MinimumOSVersion') or 'declared in the project'}."
        ),
        purl_name="rovia",
    )
    app["name"] = "Rovia"
    app["primaryPackagePurpose"] = "APPLICATION"
    extension = binary_component(
        "Extension",
        tunnel_identifier,
        str(extension_plist.get("CFBundleShortVersionString") or version),
        (
            f"Packet Tunnel extension ({EXTENSION_NAME}) with bundle identifier "
            f"{tunnel_identifier}, embedded in the host application. It performs no "
            "post-install code download; the engine is a reviewed build input."
        ),
        purl_name="rovia-tunnel",
    )
    extension["name"] = EXTENSION_NAME

    components = [app, extension]

    package_list = root / PACKAGE_LIST
    if not package_list.is_file():
        raise SystemExit(f"the local package list is missing: {package_list}")
    for line in package_list.read_text(encoding="utf-8").splitlines():
        relative = line.strip()
        if not relative or relative.startswith("#"):
            continue
        manifest = root / relative / "Package.swift"
        if not manifest.is_file():
            raise SystemExit(f"{relative}/Package.swift is missing but listed in {PACKAGE_LIST}")
        name = package_name(manifest)
        if not name:
            raise SystemExit(f"{relative}/Package.swift does not declare a package name")
        components.append(swift_package_component(name, version))

    engine_ids: list[str] = []
    for name, entry in sorted(enabled_engines(lock).items()):
        component = engine_component(name, entry)
        engine_ids.append(component["SPDXID"])
        components.append(component)

    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": app["SPDXID"],
        },
        {
            "spdxElementId": app["SPDXID"],
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": extension["SPDXID"],
        },
    ]
    for component in components:
        if component is app or component is extension:
            continue
        relationships.append(
            {
                "spdxElementId": app["SPDXID"],
                "relationshipType": "STATIC_LINK",
                "relatedSpdxElement": component["SPDXID"],
            }
        )
    for identifier in engine_ids:
        relationships.append(
            {
                "spdxElementId": extension["SPDXID"],
                "relationshipType": "DYNAMIC_LINK",
                "relatedSpdxElement": identifier,
            }
        )

    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": DATA_LICENSE,
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": DOCUMENT_NAME,
        "documentNamespace": f"{NAMESPACE_BASE}/{DOCUMENT_NAME}/{namespace_id}",
        "creationInfo": {
            "created": utc_timestamp(created),
            "creators": [
                f"Tool: {TOOL_NAME}-{TOOL_VERSION}",
                "Organization: Rovia contributors",
            ],
        },
        "documentDescribes": [app["SPDXID"]],
        "packages": components,
        "relationships": relationships,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="repository root")
    parser.add_argument("output", help="SBOM path to write")
    parser.add_argument("--lock", default=None, help="engine lock (default: <root>/engines.lock.json)")
    parser.add_argument(
        "--namespace-id",
        default=None,
        help="document namespace run identifier (default: a random UUID); pass a fixed value with --created for a byte-reproducible document",
    )
    parser.add_argument(
        "--created",
        default=None,
        help=(
            "creationInfo.created as seconds since the Unix epoch, or an RFC 3339 "
            "UTC instant ending in Z. Overrides SOURCE_DATE_EPOCH. Without either, "
            "the current time is used and the document is not byte-reproducible"
        ),
    )
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    if not root.is_dir():
        print(f"generate-sbom.py: repository root does not exist: {root}", file=sys.stderr)
        return 1
    output = Path(arguments.output).resolve()
    lock_path = Path(arguments.lock).resolve() if arguments.lock else root / "engines.lock.json"
    created = resolve_created(arguments.created)
    if created is None:
        print(
            "generate-sbom.py: note: no --created and no SOURCE_DATE_EPOCH, so "
            "creationInfo.created is the current time and this document is not "
            "byte-reproducible; pass --created SECONDS or set SOURCE_DATE_EPOCH "
            "for a document that is",
            file=sys.stderr,
        )
    namespace_id = arguments.namespace_id or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9._\-]+", namespace_id):
        print(
            "generate-sbom.py: the namespace identifier must be an ASCII token without slashes",
            file=sys.stderr,
        )
        return 2

    document = build_document(root, load_lock(lock_path), namespace_id, created)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"generate-sbom.py: could not write {output}: {error}", file=sys.stderr)
        return 1
    print(f"generate-sbom.py: wrote {output} with {len(document['packages'])} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
