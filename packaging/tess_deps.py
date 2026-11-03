"""List the DLLs tesseract.exe needs, by walking PE import tables.

Usage:  python packaging/tess_deps.py "C:\\Program Files\\Tesseract-OCR"
Prints one file name per line (tesseract.exe plus every DLL from that folder
it imports, directly or transitively, including delay-loaded ones).

Pure standard library, so it runs on any CI runner. Only DLLs that exist in
the Tesseract folder are followed; system DLLs (kernel32, msvcrt...) are not.
"""
from __future__ import annotations

import os
import struct
import sys


def _rva_to_offset(rva: int, sections: list[tuple[int, int, int]]) -> int | None:
    for va, size, raw in sections:
        if va <= rva < va + size:
            return raw + (rva - va)
    return None


def _cstring(data: bytes, off: int) -> str:
    end = data.index(b"\0", off)
    return data[off:end].decode("ascii", "replace")


def pe_imports(path: str) -> set[str]:
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] != b"MZ":
        return set()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return set()
    coff = pe + 4
    n_sections, opt_size = struct.unpack_from("<H", data, coff + 2)[0], struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    dd_off = opt + (112 if magic == 0x20B else 96)
    n_dd = struct.unpack_from("<I", data, dd_off - 4)[0]
    sec = opt + opt_size
    sections = []
    for i in range(n_sections):
        s = sec + i * 40
        vsize, va, rawsize, raw = struct.unpack_from("<IIII", data, s + 8)
        sections.append((va, max(vsize, rawsize), raw))

    names: set[str] = set()

    def directory(index: int) -> tuple[int, int]:
        if index >= n_dd:
            return 0, 0
        return struct.unpack_from("<II", data, dd_off + index * 8)

    # normal imports
    rva, _ = directory(1)
    off = _rva_to_offset(rva, sections) if rva else None
    while off is not None:
        _, _, _, name_rva, _ = struct.unpack_from("<IIIII", data, off)
        if name_rva == 0:
            break
        noff = _rva_to_offset(name_rva, sections)
        if noff is not None:
            names.add(_cstring(data, noff))
        off += 20

    # delay-load imports
    rva, _ = directory(13)
    off = _rva_to_offset(rva, sections) if rva else None
    while off is not None:
        attrs, name_rva = struct.unpack_from("<II", data, off)
        if name_rva == 0:
            break
        if not (attrs & 1):  # attribute 0 => RVAs are actually VAs (old style); skip the imagebase
            base = struct.unpack_from("<Q" if magic == 0x20B else "<I", data, opt + (24 if magic == 0x20B else 28))[0]
            name_rva -= base
        noff = _rva_to_offset(name_rva, sections)
        if noff is not None:
            names.add(_cstring(data, noff))
        off += 32
    return names


def runtime_files(tess_dir: str, root: str = "tesseract.exe") -> list[str]:
    available = {f.lower(): f for f in os.listdir(tess_dir)}
    needed: list[str] = []
    todo = [root]
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        key = name.lower()
        if key in seen or key not in available:
            continue
        seen.add(key)
        needed.append(available[key])
        for imp in pe_imports(os.path.join(tess_dir, available[key])):
            if imp.lower() in available and imp.lower() not in seen:
                todo.append(imp)
    return sorted(needed, key=str.lower)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for f in runtime_files(sys.argv[1]):
        print(f)
