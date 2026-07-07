#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract text and structure from Korean HWP 5.0 (.hwp) and HWPX (.hwpx) documents.

Usage:
    python hwp_text.py FILE [--mode text|preview|inspect] [--out OUT]

Modes:
    text     Full body text with [TABLE] markers and level indentation (default)
    preview  Fast preview from the embedded preview stream (truncated by design)
    inspect  Container structure: streams/entries, version, flags, record stats

Dependencies:
    olefile (only for .hwp): pip install olefile
    .hwpx needs stdlib only (zipfile + ElementTree).
"""
import argparse
import io
import re
import struct
import sys
import zipfile
import zlib
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- HWP 5.0
# Record tag IDs (HWPTAG_BEGIN = 0x10)
TAG_PARA_TEXT = 0x10 + 51
TAG_TABLE = 0x10 + 61

# Control characters inside PARA_TEXT payloads (UTF-16LE code units).
# "char" controls occupy 1 wchar; inline/extended controls occupy 8 wchars.
SINGLE_WCHAR_CTRLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def _hwp5_header(ole):
    if not ole.exists("FileHeader"):
        raise ValueError("OLE container without FileHeader stream — not an HWP "
                         "(legacy .doc/.xls also use OLE; check the real format)")
    header = ole.openstream("FileHeader").read()
    if not header.startswith(b"HWP Document File"):
        raise ValueError("FileHeader signature mismatch — not an HWP 5.x file")
    version = struct.unpack_from("<I", header, 32)[0]
    flags = struct.unpack_from("<I", header, 36)[0]
    return version, flags


def _iter_records(data):
    pos, end = 0, len(data)
    while pos + 4 <= end:
        (hdr,) = struct.unpack_from("<I", data, pos)
        tag = hdr & 0x3FF
        level = (hdr >> 10) & 0x3FF
        size = (hdr >> 20) & 0xFFF
        pos += 4
        if size == 0xFFF:  # extended size
            if pos + 4 > end:
                raise ValueError("truncated record header (extended size)")
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        if size > end - pos:
            raise ValueError(f"truncated record payload (tag {tag}: "
                             f"need {size} bytes, {end - pos} left)")
        yield tag, level, data[pos:pos + size]
        pos += size


def _para_text(payload):
    out = []
    i, n = 0, len(payload) - (len(payload) % 2)
    while i + 2 <= n:
        (ch,) = struct.unpack_from("<H", payload, i)
        if ch < 32:
            if ch == 10:  # line break within paragraph
                out.append("\n")
                i += 2
            elif ch == 13:  # paragraph terminator — one paragraph per record already
                i += 2
            elif ch == 9:
                out.append("\t")
                i += 16  # inline control: 8 wchars incl. the tab code
            elif ch in (30, 31):  # non-breaking / fixed-width space
                out.append(" ")
                i += 2
            elif ch == 24:  # hyphen
                out.append("-")
                i += 2
            elif ch in SINGLE_WCHAR_CTRLS:
                i += 2
            else:
                i += 16  # inline/extended control: 8 wchars
        else:
            # decode contiguous text runs as UTF-16LE bytes so surrogate
            # pairs (emoji, CJK Ext-B) recombine instead of crashing later
            start = i
            while i + 2 <= n and struct.unpack_from("<H", payload, i)[0] >= 32:
                i += 2
            out.append(payload[start:i].decode("utf-16-le", errors="replace"))
    return "".join(out)


def _hwp5_sections(ole, flags):
    compressed = bool(flags & 0x01)
    sections = sorted(
        (e for e in ole.listdir() if e[0] == "BodyText" and e[1].startswith("Section")),
        key=lambda e: int(re.sub(r"\D", "", e[1]) or 0),
    )
    for entry in sections:
        raw = ole.openstream(entry).read()
        yield entry[1], (zlib.decompress(raw, -15) if compressed else raw)


def extract_hwp_text(path):
    import olefile
    ole = olefile.OleFileIO(path)
    try:
        _, flags = _hwp5_header(ole)
        if flags & 0x02:
            raise ValueError("password-protected HWP — cannot extract")
        if flags & 0x04:
            raise ValueError("distribution (배포용) HWP — body is in encrypted ViewText; "
                             "open in Hancom Office and re-save as normal HWP/HWPX first")
        lines = []
        for _, data in _hwp5_sections(ole, flags):
            open_tables = []  # record levels of currently open tables
            for tag, level, payload in _iter_records(data):
                while open_tables and level < open_tables[-1]:
                    closed = open_tables.pop()
                    lines.append("  " * max(closed - 1, 0) + "[/TABLE]")
                indent = "  " * max(level - 1, 0)
                if tag == TAG_TABLE:
                    lines.append(indent + "[TABLE]")
                    open_tables.append(level)
                elif tag == TAG_PARA_TEXT:
                    for part in _para_text(payload).split("\n"):
                        lines.append(indent + part)
            while open_tables:
                closed = open_tables.pop()
                lines.append("  " * max(closed - 1, 0) + "[/TABLE]")
        return "\n".join(lines)
    finally:
        ole.close()


def preview_hwp(path):
    import olefile
    ole = olefile.OleFileIO(path)
    try:
        _, flags = _hwp5_header(ole)
        if flags & 0x02:
            raise ValueError("password-protected HWP — preview stream is not readable")
        # distribution docs (flag bit 2) keep a plaintext PrvText: preview still works
        if not ole.exists("PrvText"):
            raise ValueError("no PrvText stream in this HWP")
        return ole.openstream("PrvText").read().decode("utf-16-le", errors="replace")
    finally:
        ole.close()


def inspect_hwp(path):
    import olefile
    ole = olefile.OleFileIO(path)
    try:
        version, flags = _hwp5_header(ole)
        out = [
            f"format: HWP 5.x (OLE compound file)",
            f"version: {version >> 24}.{(version >> 16) & 0xFF}.{(version >> 8) & 0xFF}.{version & 0xFF}",
            f"flags: compressed={bool(flags & 1)} password={bool(flags & 2)} distribution={bool(flags & 4)}",
            "streams:",
        ]
        out += [f"  /{'/'.join(e)}" for e in ole.listdir()]
        if not (flags & 0x06):
            for name, data in _hwp5_sections(ole, flags):
                stats = {}
                for tag, _, _ in _iter_records(data):
                    stats[tag] = stats.get(tag, 0) + 1
                para = stats.get(TAG_PARA_TEXT, 0)
                tbl = stats.get(TAG_TABLE, 0)
                out.append(f"section {name}: {sum(stats.values())} records, "
                           f"{para} text paragraphs, {tbl} tables")
        return "\n".join(out)
    finally:
        ole.close()


# ---------------------------------------------------------------- HWPX
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _t_text(t_elem):
    parts = [t_elem.text or ""]
    for child in t_elem:
        if _local(child.tag) == "lineBreak":
            parts.append("\n")
        parts.append(child.tail or "")
    return "".join(parts)


def _render_para(p_elem, depth):
    lines, buf = [], []

    def flush():
        joined = "".join(buf)
        buf.clear()
        for part in joined.split("\n"):
            lines.append("  " * depth + part)

    for run in p_elem:
        if _local(run.tag) != "run":
            continue
        for child in run:
            kind = _local(child.tag)
            if kind == "t":
                buf.append(_t_text(child))
            elif kind == "secPr":
                continue
            else:
                # tables, drawing objects, text boxes, and ctrl-wrapped content
                # (headers/footers/footnotes live in ctrl > … > subList)
                if "".join(buf).strip():
                    flush()
                buf.clear()
                if kind == "tbl":
                    lines.extend(_render_table(child, depth))
                else:
                    lines.extend(_render_generic(child, depth))
    if "".join(buf).strip() or not lines:
        flush()
    return lines


def _render_generic(elem, depth):
    lines = []
    for child in elem:
        kind = _local(child.tag)
        if kind == "subList":
            for sp in child:
                if _local(sp.tag) == "p":
                    lines.extend(_render_para(sp, depth))
        elif kind == "tbl":
            lines.extend(_render_table(child, depth))
        else:
            lines.extend(_render_generic(child, depth))
    return lines


def _render_table(tbl_elem, depth):
    indent = "  " * depth
    lines = [indent + "[TABLE]"]
    for tr in (e for e in tbl_elem if _local(e.tag) == "tr"):
        cells = []
        for tc in (e for e in tr if _local(e.tag) == "tc"):
            cell_lines = _render_generic(tc, depth + 1)
            cells.append(" / ".join(s.strip() for s in cell_lines if s.strip()))
        lines.append(indent + "| " + " | ".join(cells) + " |")
    lines.append(indent + "[/TABLE]")
    return lines


def _hwpx_sections(zf):
    names = [n for n in zf.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)]
    return sorted(names, key=lambda n: int(re.search(r"\d+", n).group()))


def extract_hwpx_text(path):
    with zipfile.ZipFile(path) as zf:
        sections = _hwpx_sections(zf)
        if not sections:
            raise ValueError("no Contents/section*.xml — not a regular HWPX (DRM-packaged?)")
        lines = []
        for name in sections:
            root = ET.fromstring(zf.read(name))
            for child in root:
                if _local(child.tag) == "p":
                    lines.extend(_render_para(child, 0))
                else:
                    lines.extend(_render_generic(child, 0))
        return "\n".join(lines)


def preview_hwpx(path):
    with zipfile.ZipFile(path) as zf:
        for name in ("Preview/PrvText.txt", "Preview/PrvText.utf8"):
            if name not in zf.namelist():
                continue
            raw = zf.read(name)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is None or "\x00" in text:
                # BOM-less UTF-16 can "succeed" as UTF-8 with embedded NULs
                try:
                    text = raw.decode("utf-16")
                except UnicodeDecodeError:
                    text = text.replace("\x00", "") if text is not None else None
            if text is None:
                raise ValueError(f"preview entry {name} exists but could not be decoded")
            return text
        raise ValueError("no preview text entry in this HWPX")


def inspect_hwpx(path):
    with zipfile.ZipFile(path) as zf:
        out = ["format: HWPX (OWPML zip package)", "entries:"]
        out += [f"  {n}" for n in zf.namelist()]
        for name in _hwpx_sections(zf):
            root = ET.fromstring(zf.read(name))
            paras = sum(1 for e in root.iter() if _local(e.tag) == "p")
            tables = sum(1 for e in root.iter() if _local(e.tag) == "tbl")
            out.append(f"section {name}: {paras} paragraphs, {tables} tables")
        return "\n".join(out)


# ---------------------------------------------------------------- dispatch
def sniff(path):
    with open(path, "rb") as f:
        magic = f.read(8)
    if magic.startswith(b"\xd0\xcf\x11\xe0"):
        return "hwp"
    if magic.startswith(b"PK"):
        return "hwpx"
    raise ValueError(f"unrecognized container (magic={magic[:4].hex()}) — "
                     "HWP 3.x and other formats are not supported")


def main():
    # Windows console often defaults to cp949; force UTF-8 to avoid mojibake
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--mode", choices=["text", "preview", "inspect"], default="text")
    ap.add_argument("--out", help="write result to file (UTF-8) instead of stdout")
    args = ap.parse_args()

    try:
        kind = sniff(args.file)
        fn = {
            ("hwp", "text"): extract_hwp_text,
            ("hwp", "preview"): preview_hwp,
            ("hwp", "inspect"): inspect_hwp,
            ("hwpx", "text"): extract_hwpx_text,
            ("hwpx", "preview"): preview_hwpx,
            ("hwpx", "inspect"): inspect_hwpx,
        }[(kind, args.mode)]
        result = fn(args.file)
    except ImportError:
        sys.exit("missing dependency: pip install olefile")
    except (ValueError, OSError, zlib.error, struct.error,
            zipfile.BadZipFile, ET.ParseError) as e:
        sys.exit(f"cannot extract: {e}")

    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"written: {args.out} ({len(result)} chars)")
    else:
        print(result)


if __name__ == "__main__":
    main()
