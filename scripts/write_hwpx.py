#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a new HWPX document from a markdown-subset or JSON spec.

Usage:
    python write_hwpx.py SPEC.md  [--out OUT.hwpx] [--format md|json]
    python write_hwpx.py SPEC.json --out OUT.hwpx

Markdown subset:
    #..######   headings (mapped to 개요 1..6 styles, bold, sized)
    **bold**  *italic*  __underline__   inline runs
    | a | b |   tables (separator rows |---| are skipped)
    - item      bullet paragraphs (literal "• " prefix)
    blank line  paragraph separator

JSON spec:
    {"blocks": [
      {"type": "heading", "level": 1, "text": "제목"},
      {"type": "para", "runs": [{"text": "굵게", "bold": true}, {"text": " 보통"}]},
      {"type": "para", "text": "단순 문단"},
      {"type": "table", "rows": [["구분", "내용"], ["1", "값"]],
       "merges": [[0, 0, 0, 1]], "widths": [1, 3], "header_fill": "#E7EAF0"},
      {"type": "bullet", "items": ["항목1", "항목2"]}
    ]}

Dependencies: pip install python-hwpx  (pure Python; needs lxml)
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
import zipfile

HEADING_STYLE_ID = {n: str(n + 1) for n in range(1, 7)}   # 개요 1..6 = style id 2..7
HEADING_SIZE_PT = {1: 16, 2: 14, 3: 13, 4: 12, 5: 11, 6: 10.5}

INLINE_RE = re.compile(r"\*\*(?P<b>.+?)\*\*|__(?P<u>.+?)__|\*(?P<i>.+?)\*")


def parse_inline(text):
    """Split markdown inline formatting into run segments."""
    runs, pos = [], 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            runs.append({"text": text[pos:m.start()]})
        if m.group("b") is not None:
            runs.append({"text": m.group("b"), "bold": True})
        elif m.group("u") is not None:
            runs.append({"text": m.group("u"), "underline": True})
        else:
            runs.append({"text": m.group("i"), "italic": True})
        pos = m.end()
    if pos < len(text):
        runs.append({"text": text[pos:]})
    return runs or [{"text": ""}]


def parse_markdown(src):
    """Markdown subset -> block list (same shape as the JSON spec)."""
    blocks, para_buf, table_buf = [], [], []

    def flush_para():
        if para_buf:
            blocks.append({"type": "para", "runs": parse_inline(" ".join(para_buf))})
            para_buf.clear()

    def flush_table():
        if table_buf:
            blocks.append({"type": "table", "rows": [list(r) for r in table_buf]})
            table_buf.clear()

    for raw in src.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            flush_para()
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue  # separator row
            table_buf.append(cells)
            continue
        flush_table()
        if not stripped:
            flush_para()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            blocks.append({"type": "heading", "level": len(m.group(1)), "text": m.group(2)})
            continue
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            flush_para()
            blocks.append({"type": "para", "runs":
                           [{"text": "• "}] + parse_inline(m.group(1))})
            continue
        para_buf.append(stripped)
    flush_table()
    flush_para()
    return blocks


def render(blocks, out_path):
    from hwpx.document import HwpxDocument

    doc = HwpxDocument.new()
    for i, blk in enumerate(blocks):
        kind = blk.get("type")
        if kind == "heading":
            level = max(1, min(6, int(blk.get("level", 1))))
            p = doc.add_paragraph("", style_id_ref=HEADING_STYLE_ID[level],
                                  include_run=False)
            p.add_run(blk.get("text", ""), bold=True, size=HEADING_SIZE_PT[level])
        elif kind == "para":
            runs = blk.get("runs")
            if not runs:
                doc.add_paragraph(blk.get("text", ""))
                continue
            p = doc.add_paragraph("", include_run=False)
            for r in runs:
                p.add_run(r.get("text", ""),
                          bold=bool(r.get("bold")), italic=bool(r.get("italic")),
                          underline=bool(r.get("underline")),
                          color=r.get("color"), size=r.get("size"))
        elif kind == "bullet":
            for item in blk.get("items", []):
                p = doc.add_paragraph("", include_run=False)
                p.add_run("• ")
                for r in parse_inline(item) if isinstance(item, str) else item:
                    p.add_run(r.get("text", ""), bold=bool(r.get("bold")),
                              italic=bool(r.get("italic")),
                              underline=bool(r.get("underline")))
        elif kind == "table":
            rows = blk.get("rows") or []
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            t = doc.add_table(len(rows), ncols)
            for ri, row in enumerate(rows):
                for ci in range(ncols):
                    t.set_cell_text(ri, ci, row[ci] if ci < len(row) else "")
            if blk.get("widths"):
                t.set_column_widths(blk["widths"])
            if blk.get("header_fill"):
                for ci in range(ncols):
                    t.set_cell_shading(0, ci, blk["header_fill"])
            for mg in blk.get("merges", []):
                t.merge_cells(*mg)
        else:
            raise ValueError(f"unknown block type at index {i}: {kind!r}")
    doc.save_to_path(out_path)


def check_package(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
            raise ValueError("package check failed: mimetype must be first entry, stored")
        if z.read("mimetype") != b"application/hwp+zip":
            raise ValueError("package check failed: wrong mimetype")
        required = {"version.xml", "META-INF/container.xml", "Contents/content.hpf",
                    "Contents/header.xml", "Contents/section0.xml"}
        missing = required - set(z.namelist())
        if missing:
            raise ValueError(f"package check failed: missing {sorted(missing)}")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", help="input spec file (.md or .json)")
    ap.add_argument("--out", help="output .hwpx path (default: spec name + .hwpx)")
    ap.add_argument("--format", choices=["md", "json"],
                    help="force input format (default: by extension, json if content starts with '{')")
    ap.add_argument("--verbose", action="store_true", help="show python-hwpx internal messages")
    args = ap.parse_args()

    try:
        with io.open(args.spec, encoding="utf-8-sig") as f:
            src = f.read()
    except OSError as e:
        sys.exit(f"cannot read spec: {e}")

    fmt = args.format
    if not fmt:
        ext = os.path.splitext(args.spec)[1].lower()
        fmt = "json" if ext == ".json" or src.lstrip().startswith("{") else "md"
    try:
        if fmt == "json":
            data = json.loads(src)
            blocks = data["blocks"] if isinstance(data, dict) else data
        else:
            blocks = parse_markdown(src)
    except (json.JSONDecodeError, KeyError) as e:
        sys.exit(f"cannot parse spec ({fmt}): {e}")
    if not blocks:
        sys.exit("empty spec: nothing to write")

    out = args.out or os.path.splitext(args.spec)[0] + ".hwpx"
    chatter = io.StringIO()
    try:
        if args.verbose:
            render(blocks, out)
        else:
            with contextlib.redirect_stdout(chatter), contextlib.redirect_stderr(chatter):
                render(blocks, out)
        check_package(out)
    except ImportError:
        sys.exit("missing dependency: python -m pip install --no-deps python-hwpx  (needs lxml)")
    except Exception as e:
        noise = chatter.getvalue().strip()
        if noise:
            print(noise, file=sys.stderr)
        sys.exit(f"cannot write: {type(e).__name__}: {e}")

    print(f"written: {out} ({os.path.getsize(out)} bytes, {len(blocks)} blocks)")
    print("verify:  python hwp_text.py \"%s\"  (round-trip read)" % out)


if __name__ == "__main__":
    main()
