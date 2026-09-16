#!/usr/bin/env python3
"""Rewrite DT_RUNPATH/DT_RPATH of bundled ELF libraries to $ORIGIN.

Flutter linux plugins are copied with install(FILES), so they keep the
build-tree RUNPATH (container paths like /work/client/linux/flutter/...).
Sibling libraries such as libduckdb.so then fail to load on a real host
unless LD_LIBRARY_PATH is set. $ORIGIN makes the bundle relocatable.
"""

from __future__ import annotations

import pathlib
import struct
import sys

ORIGIN = b"$ORIGIN\x00"
PT_LOAD = 1
PT_DYNAMIC = 2
DT_NULL = 0
DT_STRTAB = 5
DT_RPATH = 15
DT_RUNPATH = 29


def _patch(path: pathlib.Path) -> str:
    data = bytearray(path.read_bytes())
    if data[:4] != b"\x7fELF":
        return "skip-not-elf"
    if data[4] != 2 or data[5] != 1:
        return "skip-not-elf64le"
    e_phoff = struct.unpack_from("<Q", data, 32)[0]
    e_phentsize = struct.unpack_from("<H", data, 54)[0]
    e_phnum = struct.unpack_from("<H", data, 56)[0]
    loads: list[tuple[int, int, int]] = []
    dyn: tuple[int, int] | None = None
    for i in range(e_phnum):
        offset = e_phoff + i * e_phentsize
        p_type = struct.unpack_from("<I", data, offset)[0]
        p_offset, p_vaddr, _p_paddr, p_filesz = struct.unpack_from(
            "<QQQQ",
            data,
            offset + 8,
        )
        if p_type == PT_LOAD:
            loads.append((p_offset, p_vaddr, p_filesz))
        elif p_type == PT_DYNAMIC:
            dyn = (p_offset, p_filesz)
    if dyn is None:
        return "skip-no-dynamic"

    def vaddr_to_off(addr: int) -> int | None:
        for file_off, vaddr, filesz in loads:
            if vaddr <= addr < vaddr + filesz:
                return file_off + (addr - vaddr)
        return None

    dyn_off, dyn_sz = dyn
    strtab_addr = None
    entries: list[tuple[int, int, int]] = []
    cursor = 0
    while cursor + 16 <= dyn_sz:
        loc = dyn_off + cursor
        tag, val = struct.unpack_from("<QQ", data, loc)
        entries.append((loc, tag, val))
        if tag == DT_NULL:
            break
        if tag == DT_STRTAB:
            strtab_addr = val
        cursor += 16
    if strtab_addr is None:
        return "skip-no-strtab"
    str_off = vaddr_to_off(strtab_addr)
    if str_off is None:
        return "skip-strtab"

    changed = False
    for loc, tag, val in entries:
        if tag not in (DT_RPATH, DT_RUNPATH):
            continue
        struct.pack_into("<Q", data, loc, DT_RUNPATH)
        start = str_off + val
        try:
            end = data.index(0, start)
        except ValueError:
            return "fail-unterminated"
        old = bytes(data[start:end])
        if old == ORIGIN[:-1]:
            continue
        if len(ORIGIN) - 1 > end - start:
            return f"fail-too-small:{old!r}"
        data[start : start + len(ORIGIN)] = ORIGIN
        for pad in range(start + len(ORIGIN), end + 1):
            data[pad] = 0
        changed = True
    if not changed:
        return "skip-no-rpath"
    path.write_bytes(data)
    return "patched"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: set_bundle_runpath.py <bundle-lib-dir>", file=sys.stderr)
        return 2
    lib_dir = pathlib.Path(argv[1])
    if not lib_dir.is_dir():
        print(f"missing lib dir: {lib_dir}", file=sys.stderr)
        return 1
    failed = False
    for path in sorted(lib_dir.glob("*.so*")):
        if path.is_symlink() or not path.is_file():
            continue
        status = _patch(path)
        print(f"{path.name}: {status}")
        if status.startswith("fail-"):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
