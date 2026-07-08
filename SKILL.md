---
name: hwp-files
description: Read, inspect, create, and fill Korean HWP 5.0 (.hwp) and HWPX (.hwpx) documents without Hancom Office. Use when the user wants to parse or extract text from HWP/HWPX files, create new HWPX documents, or fill {{placeholder}} form templates. Triggers on phrases like "hwp 파일", "hwpx 읽기", "한글 문서 추출", "hwpx 생성", "한글 문서 만들기", "한글 양식 채우기", "양식 자동 기입", or when a task involves .hwp/.hwpx inputs or outputs.
---

# HWP Files

Read AND write Hancom HWP documents with pure Python — no Hancom Office, no COM automation.

## Quick decision

| Want to... | Use |
|---|---|
| Extract body text + tables from .hwp / .hwpx | `scripts/hwp_text.py FILE` (auto-detects format) |
| Fast preview (first ~4KB, no full parse) | `scripts/hwp_text.py FILE --mode preview` |
| Identify real format / streams / stats | `scripts/hwp_text.py FILE --mode inspect` |
| Create a new .hwpx from markdown/JSON | `scripts/write_hwpx.py SPEC.md --out OUT.hwpx` |
| List `{{placeholders}}` in a .hwpx form | `scripts/fill_hwpx.py FORM.hwpx --mode scan` |
| Fill a .hwpx form template with values | `scripts/fill_hwpx.py FORM.hwpx --data VALUES.json --out OUT.hwpx` |
| Produce a legacy .hwp file | Create .hwpx here, then open in Hancom Office and save as .hwp (direct .hwp writing is not supported) |

## Dependencies

| Feature | Requires |
|---|---|
| Read .hwp | `olefile` |
| Read .hwpx / fill templates | stdlib + `lxml` (fill only) |
| Create .hwpx | `python-hwpx` (pure Python, needs lxml) |

```bash
python -m pip install olefile lxml
python -m pip install --no-deps python-hwpx   # --no-deps: it may pin an older lxml;
                                              # any lxml >= 5 works (verified with 6.x)
```
On Windows with a locked-down pip.exe (Device Guard), always use `python -m pip`.

## Reading

```bash
python scripts/hwp_text.py "문서.hwp"                    # text to stdout (UTF-8)
python scripts/hwp_text.py "문서.hwpx" --out out.txt     # write to file
python scripts/hwp_text.py "문서.hwp" --mode inspect     # format, version, flags, streams
```

Output conventions:
- `[TABLE]` / `[/TABLE]` bracket tables in both formats. HWP cells appear as level-indented paragraphs between the markers; HWPX rows render as `| cell | cell |` lines.
- Indentation depth reflects record nesting (table cells are deeper than body text).

## Creating documents (`write_hwpx.py`)

```bash
python scripts/write_hwpx.py 보고서.md --out 보고서.hwpx     # md/json auto-detected
python scripts/write_hwpx.py spec.json --out 문서.hwpx
```

Markdown subset → HWPX mapping:

| Markdown | Result |
|---|---|
| `#` .. `######` | 개요 1–6 styles, bold, sized 16/14/13/12/11/10.5 pt |
| `**bold**` `*italic*` `__underline__` | formatted runs within a paragraph |
| `\| a \| b \|` lines | table (separator rows `\|---\|` skipped) |
| `- item` | bullet paragraph (literal `• ` prefix — not real numbering) |
| blank line | paragraph break |

JSON spec (`{"blocks": [...]}`) unlocks what markdown can't express: run `color`/`size`,
cell merges (`"merges": [[r1,c1,r2,c2]]`), column `widths`, `header_fill` shading.
See the docstring in `scripts/write_hwpx.py` for the full block schema.

Out of scope (v1): images, page setup, real outline numbering, footnotes, per-cell styling via markdown.

## Filling form templates (`fill_hwpx.py`)

Workflow — always scan first, then fill:

```bash
python scripts/fill_hwpx.py 양식.hwpx --mode scan
python scripts/fill_hwpx.py 양식.hwpx --data 값.json --out 완성.hwpx
```

Rules:
- `{{key}}` syntax (`{{ key }}` with spaces OK); keys: letters, digits, `_ . -`, 한글.
- Placeholders inside table cells and headers/footers are found and filled.
- **Split runs are handled**: if Hancom's editor stored `{{성명}}` as `{{성` + `명}}` across runs, the match still works. Replacement text inherits the character style of the run where `{{` starts.
- Newlines in values become real line breaks (`<hp:lineBreak/>`).
- `--missing error` (default) fails fast listing unfilled keys; `warn` leaves placeholders; `blank` inserts empty strings. Data keys absent from the template are warned either way.
- Only the section XMLs (and text preview) are rewritten — every other zip entry is copied byte-for-byte, so fonts, layout, images, and stamps cannot drift.

## Gotchas

- **Trust the magic bytes, not the extension.** Government portals hand out `.hwpx` files that are really HWP 5.0 OLE files (and vice versa). All scripts sniff the container (`D0 CF 11 E0` = OLE → HWP 5.x, `PK` = zip → HWPX) and dispatch or refuse accordingly — never route by extension.
- **Distribution documents (배포용 문서) are not extractable in text mode.** HWP flag bit 2 means the body lives in an encrypted `ViewText` stream; text mode exits with a clear message. **`--mode preview` still works** — distribution docs keep a plaintext `PrvText` — so use preview to peek, or re-save as a normal document in Hancom Office for full extraction.
- **Password-protected files** (flag bit 1) are refused in both text and preview modes.
- **HWP 3.x and older** (no OLE signature) are unsupported.
- **Windows console mojibake**: the scripts force UTF-8 on stdout/stderr. If piping through other tools, keep the chain UTF-8 (`--out file` is the safe path).
- **HWP table structure is flat**: cells arrive as separate paragraphs at a deeper record level, so column alignment must be reconstructed from context. HWPX preserves real row/cell structure.
- **PrvText preview is truncated by design** (~2000 chars) and has no table structure — use it for sniffing content, not for extraction.
- **Generated/filled files: verify before shipping.** Round-trip with `hwp_text.py`, re-scan filled forms for leftover `{{`, and open once in Hancom Office before first real-world use — automated checks can't fully guarantee editor compatibility.
- **Real form fields (누름틀)**: if a template uses actual HWPX form fields instead of `{{text}}`, use python-hwpx's `fill_by_path` API instead of `fill_hwpx.py`.

## How it works (for extending)

- **.hwp** = OLE compound file. `FileHeader` stream carries version + flags (bit 0: zlib-compressed sections, bit 1: password, bit 2: distribution). Body text lives in `BodyText/Section{N}` streams: raw-deflate streams of tagged records (4-byte header: tag 10 bits, level 10 bits, size 12 bits; size 0xFFF → extended 4-byte size). Text records are `HWPTAG_PARA_TEXT` (tag 67), UTF-16LE with embedded control codes (codes < 32: some occupy 1 wchar, inline/extended controls occupy 8 wchars).
- **.hwpx** = zip package of OWPML XML (KS X 6101). Sections are `Contents/section{N}.xml`; paragraphs are `hp:p > hp:run > hp:t`, tables are `hp:tbl > hp:tr > hp:tc > hp:subList > hp:p`. The parsers match on local names, so namespace revisions don't break them.
- **Writing** uses [python-hwpx](https://github.com/airmang/python-hwpx) (Apache-2.0) for document assembly; template filling manipulates section XML directly with lxml and repacks the zip (mimetype stays the first entry, stored uncompressed).

See `references/hwp-formats.md` for the full record/element map and package internals.
