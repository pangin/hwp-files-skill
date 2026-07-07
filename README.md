# hwp-files

[Claude Code](https://claude.com/claude-code) skill for reading Korean **HWP 5.0** (`.hwp`) and **HWPX** (`.hwpx`) documents — pure Python, no Hancom Office required.

한컴오피스 없이 HWP/HWPX 문서의 본문과 표를 추출하는 Claude Code 스킬입니다.

## Features

- **`.hwp` (HWP 5.0)** — OLE compound file parsing: zlib-compressed `BodyText` sections, record-level walk, `PARA_TEXT` extraction with control-code handling, table markers
- **`.hwpx` (OWPML)** — zip/XML parsing: paragraphs, tables rendered as `| cell | cell |` rows, text inside drawing objects
- **Format sniffing by magic bytes** — catches `.hwpx` files that are secretly HWP 5.0 OLE containers (common with government portal downloads) and vice versa
- **Safe failure modes** — password-protected and distribution (배포용) documents are detected and refused with a clear message instead of returning garbage (distribution docs still allow `--mode preview`, which reads their plaintext preview stream)
- Modes: `text` (default) / `preview` (fast, from embedded preview stream) / `inspect` (container structure, version, flags, record stats)

## Install as a Claude Code skill

```bash
git clone https://github.com/pangin/hwp-files-skill ~/.claude/skills/hwp-files
pip install olefile
```

Claude Code picks it up automatically; it triggers on phrases like "hwp 파일 읽어줘".

## Standalone CLI

```bash
python scripts/hwp_text.py "문서.hwp"                  # body text to stdout (UTF-8)
python scripts/hwp_text.py "문서.hwpx" --out out.txt   # write to file
python scripts/hwp_text.py "문서.hwp" --mode inspect   # streams, version, flags
python scripts/hwp_text.py "문서.hwp" --mode preview   # fast truncated preview
```

## Limitations

- Read-only. To *produce* HWP files, generate `.docx` and re-save in Hancom Office.
- Distribution (배포용/DRM) and password-protected documents are refused.
- HWP 3.x and older are unsupported.
- `.hwp` table cells are emitted as indented paragraphs (flat), not reconstructed grids; `.hwpx` tables keep row structure.

See [`references/hwp-formats.md`](references/hwp-formats.md) for format internals.

## License

[MIT](LICENSE)
