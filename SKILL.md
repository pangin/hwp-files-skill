---
name: hwp-files
description: Read, inspect, and extract text/tables from Korean HWP 5.0 (.hwp) and HWPX (.hwpx) documents without Hancom Office. Use when the user wants to parse, read, or convert HWP/HWPX files to text. Triggers on phrases like "hwp 파일", "hwpx 읽기", "한글 문서 추출", "한글 파일 텍스트", or when a task involves .hwp/.hwpx inputs.
---

# HWP Files

Parse Hancom HWP documents with pure Python — no Hancom Office, no COM automation.

## Quick decision

| Want to... | Use |
|---|---|
| Extract body text + tables from .hwp / .hwpx | `scripts/hwp_text.py FILE` (auto-detects format) |
| Fast preview (first ~4KB, no full parse) | `scripts/hwp_text.py FILE --mode preview` |
| Identify real format / streams / stats | `scripts/hwp_text.py FILE --mode inspect` |
| Write or edit HWP files | Not supported — generate .docx instead (docx-files skill); Hancom Office opens .docx and saves as .hwp/.hwpx |

## Dependencies

```bash
pip install olefile   # .hwp only; .hwpx needs stdlib only
```

## Usage

```bash
python scripts/hwp_text.py "문서.hwp"                    # text to stdout (UTF-8)
python scripts/hwp_text.py "문서.hwpx" --out out.txt     # write to file
python scripts/hwp_text.py "문서.hwp" --mode inspect     # format, version, flags, streams
```

Output conventions:
- `[TABLE]` / `[/TABLE]` bracket tables in both formats. HWP cells appear as level-indented paragraphs between the markers; HWPX rows render as `| cell | cell |` lines.
- Indentation depth reflects record nesting (table cells are deeper than body text).

## Gotchas

- **Trust the magic bytes, not the extension.** Government portals hand out `.hwpx` files that are really HWP 5.0 OLE files (and vice versa). `hwp_text.py` sniffs the container (`D0 CF 11 E0` = OLE → HWP 5.x, `PK` = zip → HWPX) and dispatches accordingly — never route by extension.
- **Distribution documents (배포용 문서) are not extractable in text mode.** HWP flag bit 2 means the body lives in an encrypted `ViewText` stream; text mode exits with a clear message. **`--mode preview` still works** — distribution docs keep a plaintext `PrvText` — so use preview to peek, or re-save as a normal document in Hancom Office for full extraction.
- **Password-protected files** (flag bit 1) are refused in both text and preview modes.
- **HWP 3.x and older** (no OLE signature) are unsupported.
- **Windows console mojibake**: the script forces UTF-8 on stdout/stderr. If piping through other tools, keep the chain UTF-8 (`--out file.txt` is the safe path).
- **HWP table structure is flat**: cells arrive as separate paragraphs at a deeper record level, so column alignment must be reconstructed from context. HWPX preserves real row/cell structure.
- **PrvText preview is truncated by design** (~2000 chars) and has no table structure — use it for sniffing content, not for extraction.

## How it works (for extending)

- **.hwp** = OLE compound file. `FileHeader` stream carries version + flags (bit 0: zlib-compressed sections, bit 1: password, bit 2: distribution). Body text lives in `BodyText/Section{N}` streams: raw-deflate streams of tagged records (4-byte header: tag 10 bits, level 10 bits, size 12 bits; size 0xFFF → extended 4-byte size). Text records are `HWPTAG_PARA_TEXT` (tag 67), UTF-16LE with embedded control codes (codes < 32: some occupy 1 wchar, inline/extended controls occupy 8 wchars).
- **.hwpx** = zip package of OWPML XML (KS X 6101). Sections are `Contents/section{N}.xml`; paragraphs are `hp:p > hp:run > hp:t`, tables are `hp:tbl > hp:tr > hp:tc > hp:subList > hp:p`. The parser matches on local names, so namespace revisions don't break it.

See `references/hwp-formats.md` for the full record/element map.
