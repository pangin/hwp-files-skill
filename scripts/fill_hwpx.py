#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill {{placeholder}} fields in an existing HWPX template, preserving all formatting.

Usage:
    python fill_hwpx.py FORM.hwpx --mode scan                       # list placeholders
    python fill_hwpx.py FORM.hwpx --data VALUES.json --out OUT.hwpx
    python fill_hwpx.py FORM.hwpx --data VALUES.json --out OUT.hwpx --missing warn|blank

Behavior:
    - {{key}} syntax ({{ key }} with spaces also accepted); keys match [A-Za-z0-9_.\\-가-힣]+
    - Matches placeholders even when Hancom's editor split them across multiple runs
    - Replacement text inherits the character style of the run where "{{" starts
    - Newlines in values become <hp:lineBreak/> (when the match sits inside one text node)
    - Only Contents/section*.xml (and Preview/PrvText.txt) are rewritten;
      every other zip entry is copied byte-for-byte — formatting cannot drift
    - --missing: error (default, fail fast) | warn (leave placeholder) | blank (empty string)

Dependencies: lxml only (pip install lxml)
"""
import argparse
import io
import json
import re
import sys
import zipfile

from lxml import etree

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-가-힣]+)\s*\}\}")
SECTION_RE = re.compile(r"Contents/section\d+\.xml")


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def hp_ns(elem):
    return elem.tag.split("}")[0][1:] if elem.tag.startswith("{") else ""


def sniff_zip(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("this is an OLE file (HWP 5.x binary, possibly with a fake "
                         ".hwpx extension) — fill supports HWPX only")
    if not magic.startswith(b"PK"):
        raise ValueError("not a zip container — not an HWPX file")


class Segment:
    """One editable text slot: hp:t element text, or the tail of a child of hp:t."""
    __slots__ = ("node", "kind", "text", "in_table")

    def __init__(self, node, kind, text, in_table):
        self.node, self.kind, self.in_table = node, kind, in_table
        self.text = text or ""

    def get(self):
        return self.text

    def set(self, value):
        self.text = value
        if self.kind == "text":
            self.node.text = value
        else:
            self.node.tail = value


def paragraph_segments(p_elem, in_table):
    """Text segments of a paragraph's direct runs (nested-table paragraphs excluded —
    they are visited separately as their own hp:p elements)."""
    segs = []
    for run in p_elem:
        if local(run.tag) != "run":
            continue
        for child in run:
            if local(child.tag) != "t":
                continue
            segs.append(Segment(child, "text", child.text, in_table))
            for sub in child:
                segs.append(Segment(sub, "tail", sub.tail, in_table))
    return segs


def iter_paragraphs(root):
    """All hp:p elements with an is-inside-table flag."""
    for p in root.iter():
        if local(p.tag) != "p":
            continue
        in_table = False
        anc = p.getparent()
        while anc is not None:
            if local(anc.tag) == "tbl":
                in_table = True
                break
            anc = anc.getparent()
        yield p, in_table


def find_matches(segs):
    """Match placeholders on the concatenated paragraph text.
    Returns [(key, seg_index_start, offset_start, seg_index_end, offset_end)]."""
    full, bounds = [], []
    pos = 0
    for i, s in enumerate(segs):
        t = s.get()
        bounds.append((pos, pos + len(t)))
        full.append(t)
        pos += len(t)
    text = "".join(full)
    out = []
    for m in PLACEHOLDER_RE.finditer(text):
        si = ei = None
        for i, (a, b) in enumerate(bounds):
            if si is None and a <= m.start() < b:
                si = (i, m.start() - a)
            if a < m.end() <= b:
                ei = (i, m.end() - a)
        if si is not None and ei is None and bounds and m.end() == bounds[-1][1]:
            ei = (len(bounds) - 1, m.end() - bounds[-1][0])
        if si is not None and ei is not None:
            out.append((m.group(1), si[0], si[1], ei[0], ei[1]))
    return out


def insert_linebreaks(seg, prefix, value, suffix):
    """Write value with newlines into a 'text' segment as <hp:lineBreak/> elements."""
    t_elem = seg.node
    ns = hp_ns(t_elem)
    parts = value.split("\n")
    t_elem.text = prefix + parts[0]
    anchor = None
    for part in parts[1:]:
        br = etree.SubElement(t_elem, f"{{{ns}}}lineBreak" if ns else "lineBreak")
        br.tail = part
        anchor = br
    if anchor is not None:
        anchor.tail = (anchor.tail or "") + suffix
    else:
        t_elem.text += suffix


def apply_to_paragraph(segs, data, missing, stats):
    """Replace matched placeholders right-to-left so earlier offsets stay valid."""
    matches = find_matches(segs)
    for key, si, so, ei, eo in reversed(matches):
        stats["found"].setdefault(key, 0)
        stats["found"][key] += 1
        if key in data:
            value = str(data[key])
        elif missing == "blank":
            value = ""
        else:
            stats["unresolved"].add(key)
            continue
        head = segs[si].get()[:so]
        tail = segs[ei].get()[eo:]
        if "\n" in value and si == ei and segs[si].kind == "text" and len(segs[si].node) == 0:
            insert_linebreaks(segs[si], head, value, tail)
            segs[si].text = segs[si].node.text or ""
        else:
            if "\n" in value:
                value = value.replace("\n", " ")
                stats["warnings"].append(
                    f"'{key}': newline replaced with space (placeholder spans styled/split nodes)")
            if si == ei:
                segs[si].set(head + value + tail)
            else:
                segs[si].set(head + value)
                for j in range(si + 1, ei):
                    segs[j].set("")
                segs[ei].set(tail)
            stats["replaced"].setdefault(key, 0)
            stats["replaced"][key] += 1
            continue
        stats["replaced"].setdefault(key, 0)
        stats["replaced"][key] += 1


def scan_report(zf):
    found = {}
    for name in sorted(n for n in zf.namelist() if SECTION_RE.fullmatch(n)):
        root = etree.fromstring(zf.read(name))
        for p, in_table in iter_paragraphs(root):
            segs = paragraph_segments(p, in_table)
            for key, *_ in find_matches(segs):
                slot = found.setdefault(key, {"count": 0, "in_table": 0, "files": set()})
                slot["count"] += 1
                slot["in_table"] += 1 if in_table else 0
                slot["files"].add(name)
    return found


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template", help="input .hwpx form")
    ap.add_argument("--mode", choices=["scan", "fill"], default=None,
                    help="scan: list placeholders; fill: replace (default when --data given)")
    ap.add_argument("--data", help="JSON file of {key: value}")
    ap.add_argument("--out", help="output .hwpx (required for fill)")
    ap.add_argument("--missing", choices=["error", "warn", "blank"], default="error")
    args = ap.parse_args()

    mode = args.mode or ("fill" if args.data else "scan")
    try:
        sniff_zip(args.template)
    except (OSError, ValueError) as e:
        sys.exit(f"cannot fill: {e}")

    if mode == "scan":
        with zipfile.ZipFile(args.template) as zf:
            found = scan_report(zf)
        if not found:
            print("no {{placeholders}} found")
            return
        print(f"{len(found)} placeholder key(s):")
        for key in sorted(found):
            s = found[key]
            loc = ", ".join(sorted(s["files"]))
            table_note = f", {s['in_table']} in tables" if s["in_table"] else ""
            print(f"  {{{{{key}}}}}  x{s['count']} ({loc}{table_note})")
        return

    if not args.data or not args.out:
        sys.exit("fill mode needs --data VALUES.json and --out OUT.hwpx")
    try:
        with io.open(args.data, encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("data JSON must be an object of {key: value}")
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read data: {e}")

    stats = {"found": {}, "replaced": {}, "unresolved": set(), "warnings": []}
    new_sections = {}
    with zipfile.ZipFile(args.template) as zf:
        names = zf.namelist()
        for name in sorted(n for n in names if SECTION_RE.fullmatch(n)):
            raw = zf.read(name)
            root = etree.fromstring(raw)
            before = sum(stats["replaced"].values())
            for p, in_table in iter_paragraphs(root):
                segs = paragraph_segments(p, in_table)
                if segs:
                    apply_to_paragraph(segs, data, args.missing, stats)
            if sum(stats["replaced"].values()) == before:
                continue  # untouched section: keep original bytes
            decl_end = raw.find(b"?>")
            decl = raw[:decl_end + 2] if raw.startswith(b"<?xml") and decl_end != -1 else \
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            new_sections[name] = decl + etree.tostring(root, xml_declaration=False,
                                                       encoding="utf-8")

        unresolved = stats["unresolved"] if args.missing != "blank" else set()
        if unresolved and args.missing == "error":
            sys.exit("cannot fill: no value for placeholder(s): "
                     + ", ".join(sorted(unresolved))
                     + "  (use --missing warn|blank to override)")
        unused = sorted(set(data) - set(stats["found"]))

        with zipfile.ZipFile(args.out, "w") as zout:
            for info in zf.infolist():
                raw = zf.read(info.filename)
                if info.filename in new_sections:
                    raw = new_sections[info.filename]
                elif info.filename == "Preview/PrvText.txt" and new_sections:
                    try:
                        prv = raw.decode("utf-8")
                        new_prv = PLACEHOLDER_RE.sub(
                            lambda m: str(data.get(m.group(1), m.group(0))), prv)
                        if new_prv != prv:
                            raw = new_prv.encode("utf-8")
                    except UnicodeDecodeError:
                        pass  # keep original preview as-is
                ctype = zipfile.ZIP_STORED if info.filename == "mimetype" \
                    else info.compress_type
                zout.writestr(zipfile.ZipInfo(info.filename, info.date_time), raw,
                              compress_type=ctype)

    total = sum(stats["replaced"].values())
    print(f"filled: {args.out} — {total} replacement(s), "
          f"{len(stats['replaced'])}/{len(stats['found'])} key(s)")
    for key in sorted(stats["replaced"]):
        print(f"  {{{{{key}}}}} x{stats['replaced'][key]}")
    if unresolved:
        print("warning: unresolved placeholder(s) left in document: "
              + ", ".join(sorted(unresolved)), file=sys.stderr)
    if unused:
        print("warning: data key(s) not found in template: " + ", ".join(unused),
              file=sys.stderr)
    for w in stats["warnings"]:
        print("warning:", w, file=sys.stderr)


if __name__ == "__main__":
    main()
