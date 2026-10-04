#!/usr/bin/env python3
"""Make a gomobile-built .xcframework byte-for-byte reproducible.

gomobile and xcodebuild leave three sources of nondeterminism in an otherwise
pinned build, and each one breaks the engine lock's promise that a digest
pins a build rather than a machine:

1. The ``LibXray`` binary is a BSD ``ar`` archive whose member headers carry
   the build-time mtime, uid, and gid. They are rewritten to zero, the same
   normalisation ``ar -D`` performs, applied here in place so no tool beyond
   the standard library is needed.
2. Each framework ``Info.plist`` is stamped with ``0.0.<epoch>`` as
   ``CFBundleVersion``. The version fields are rewritten to the engine
   version recorded in the lock, which is deterministic and more honest than
   a timestamp.
3. The xcframework ``Info.plist`` lists ``AvailableLibraries`` in whatever
   order the slice map happened to iterate. The list is sorted by
   ``LibraryIdentifier``.

Everything else — the compiled code itself — is left untouched. If two builds
still disagree after this pass, the difference is in the code and this script
must not hide it: the caller (``verify-xray.sh``) compares the results.

Usage:
    determinize-xcframework.py FRAMEWORK_PATH --version VERSION

Exit status: 0 the framework was normalised, 1 an input was missing or
malformed, 2 usage error.
"""

from __future__ import annotations

import plistlib
import struct
import sys
from pathlib import Path

AR_HEADER_SIZE = 60
AR_GLOBAL_MAGIC = b"!<arch>\n"
AR_MEMBER_MAGIC = b"`\n"
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
# mtime(12) uid(6) gid(6): zeroed, space-padded, exactly as ar -D writes them.
DETERMINISTIC_MTIME = b"0           "
DETERMINISTIC_UID = b"0     "
DETERMINISTIC_GID = b"0     "


def fail(message: str) -> None:
    print(f"determinize-xcframework: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_ar_region(data: bytearray, start: int, end: int, path: Path) -> None:
    """Zero the volatile fields of every ar member header in data[start:end]."""
    if data[start : start + 8] != AR_GLOBAL_MAGIC:
        fail(f"not an ar archive at {start:#x} in {path}")
    offset = start + 8
    while offset < end:
        header_end = offset + AR_HEADER_SIZE
        if header_end > end:
            fail(f"truncated ar member header at {offset:#x} in {path}")
        if data[header_end - 2 : header_end] != AR_MEMBER_MAGIC:
            fail(f"bad ar member magic at {offset:#x} in {path}")
        try:
            member_size = int(bytes(data[offset + 48 : offset + 58]).decode("ascii").strip())
        except ValueError:
            fail(f"unparsable ar member size at {offset:#x} in {path}")
        data[offset + 16 : offset + 28] = DETERMINISTIC_MTIME
        data[offset + 28 : offset + 34] = DETERMINISTIC_UID
        data[offset + 34 : offset + 40] = DETERMINISTIC_GID
        # A BSD long name (#1/<n>) is stored inside the member data, so the
        # size field already includes it; the next header follows the data.
        offset = header_end + member_size
        if member_size % 2 == 1:
            offset += 1  # members are 2-byte aligned, padded with \n
    if offset != end:
        fail(f"ar archive does not end on a member boundary in {path}")


def normalize_binary(path: Path) -> None:
    """Normalise a gomobile framework binary.

    gomobile wraps the Go static archive in a Mach-O fat container, even for
    a single architecture, so the walk is: fat header, per-slice offsets,
    then the ar member headers inside each slice. A plain ar archive (no fat
    wrapper) is accepted too, for the day gomobile stops wrapping.
    """
    data = bytearray(path.read_bytes())
    if data[:8] == AR_GLOBAL_MAGIC:
        normalize_ar_region(data, 0, len(data), path)
    else:
        magic = struct.unpack(">I", data[0:4])[0] if len(data) >= 4 else 0
        if magic == FAT_MAGIC:
            count = struct.unpack(">I", data[4:8])[0]
            entry_size, header_size = 20, 8
        elif magic == FAT_MAGIC_64:
            count = struct.unpack(">I", data[4:8])[0]
            entry_size, header_size = 32, 8
        else:
            fail(f"not an ar archive or a fat binary: {path}")
        if count == 0 or count > 16:
            fail(f"implausible fat slice count {count} in {path}")
        normalized = 0
        for index in range(count):
            base = header_size + index * entry_size
            if magic == FAT_MAGIC:
                slice_offset, slice_size = struct.unpack(">II", data[base + 8 : base + 16])
            else:
                slice_offset, slice_size = struct.unpack(">QQ", data[base + 8 : base + 24])
            region = data[slice_offset : slice_offset + 8]
            if region == AR_GLOBAL_MAGIC:
                normalize_ar_region(data, slice_offset, slice_offset + slice_size, path)
                normalized += 1
        if normalized == 0:
            fail(f"no ar slice found in fat binary: {path}")
    path.write_bytes(bytes(data))


def normalize_framework_plist(path: Path, version: str) -> None:
    with path.open("rb") as stream:
        plist = plistlib.load(stream)
    plist["CFBundleShortVersionString"] = version
    plist["CFBundleVersion"] = version
    with path.open("wb") as stream:
        plistlib.dump(plist, stream, sort_keys=True)


def normalize_xcframework_plist(path: Path) -> None:
    with path.open("rb") as stream:
        plist = plistlib.load(stream)
    libraries = plist.get("AvailableLibraries")
    if isinstance(libraries, list):
        libraries.sort(key=lambda entry: str(entry.get("LibraryIdentifier", "")))
    with path.open("wb") as stream:
        plistlib.dump(plist, stream, sort_keys=True)


def determinize(framework_path: Path, version: str) -> None:
    if not framework_path.is_dir():
        fail(f"xcframework does not exist: {framework_path}")
    root_plist = framework_path / "Info.plist"
    if not root_plist.is_file():
        fail(f"xcframework has no Info.plist: {framework_path}")
    normalize_xcframework_plist(root_plist)
    binaries = 0
    # Slice layouts differ: iOS keeps Info.plist at the framework root, macOS
    # keeps it under Versions/A/Resources. Walk the whole framework tree.
    for plist in sorted(framework_path.rglob("LibXray.framework/**/Info.plist")):
        normalize_framework_plist(plist, version)
    for binary in sorted(framework_path.rglob("LibXray.framework/**/LibXray")):
        if binary.is_file():
            normalize_binary(binary)
            binaries += 1
    if binaries == 0:
        fail(f"no LibXray binaries found under {framework_path}")


def main(argv: list[str]) -> int:
    args = list(argv)
    version = ""
    rest: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--version":
            if index + 1 >= len(args):
                print("determinize-xcframework: --version requires a value", file=sys.stderr)
                return 2
            version = args[index + 1]
            index += 2
        elif arg.startswith("--version="):
            version = arg.split("=", 1)[1]
            index += 1
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        elif arg.startswith("-"):
            print(f"determinize-xcframework: unknown option: {arg}", file=sys.stderr)
            return 2
        else:
            rest.append(arg)
            index += 1
    if len(rest) != 1:
        print(__doc__)
        return 2
    if not version.strip():
        print("determinize-xcframework: --version is required", file=sys.stderr)
        return 2
    determinize(Path(rest[0]), version.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
