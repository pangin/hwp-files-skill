# hwp-files

[Claude Code](https://claude.com/claude-code) skill for reading **and writing** Korean **HWP 5.0** (`.hwp`) and **HWPX** (`.hwpx`) documents — pure Python, no Hancom Office required.

한컴오피스 없이 HWP/HWPX 문서를 읽고, 새 HWPX를 생성하고, `{{자리표시자}}` 양식을 자동으로 채우는 Claude Code 스킬입니다.

## Features

### Read (`scripts/hwp_text.py`)
- **`.hwp` (HWP 5.0)** — OLE compound file parsing: zlib-compressed `BodyText` sections, record-level walk, `PARA_TEXT` extraction with control-code and surrogate-pair handling, table markers
- **`.hwpx` (OWPML)** — zip/XML parsing: paragraphs, tables rendered as `| cell | cell |` rows, text inside drawing objects
- **Format sniffing by magic bytes** — catches `.hwpx` files that are secretly HWP 5.0 OLE containers (common with government portal downloads) and vice versa
- **Safe failure modes** — password-protected and distribution (배포용) documents are detected and refused with a clear message instead of returning garbage (distribution docs still allow `--mode preview`, which reads their plaintext preview stream)
- Modes: `text` (default) / `preview` (fast, from embedded preview stream) / `inspect` (container structure, version, flags, record stats)

### Write (`scripts/write_hwpx.py`)
- Create new `.hwpx` from a **markdown subset** (headings → 개요 styles, `**bold**`/`*italic*`/`__underline__`, `| a | b |` tables, bullets) or a **JSON block spec** (adds run color/size, cell merges, column widths, header shading)
- Built on [python-hwpx](https://github.com/airmang/python-hwpx); output passes package-structure checks and round-trip reading

### Fill templates (`scripts/fill_hwpx.py`)
- Replace `{{key}}` placeholders in existing `.hwpx` forms — **including placeholders split across runs** by Hancom's editor, inside table cells, and in headers/footers
- Byte-preserving: only section XMLs (and the text preview) are rewritten; every other zip entry is copied verbatim, so layout/fonts/stamps cannot drift
- `--mode scan` lists all placeholders first; `--missing error|warn|blank` controls unfilled-key policy; newline values become real line breaks

## Install as a Claude Code skill

```bash
git clone https://github.com/pangin/hwp-files-skill ~/.claude/skills/hwp-files
python -m pip install olefile lxml
python -m pip install --no-deps python-hwpx    # write support (--no-deps: any lxml>=5 works)
```

Claude Code picks it up automatically; it triggers on phrases like "hwp 파일 읽어줘", "hwpx로 만들어줘", "이 양식 채워줘".

## Standalone CLI

```bash
# read
python scripts/hwp_text.py "문서.hwp"                  # body text to stdout (UTF-8)
python scripts/hwp_text.py "문서.hwp" --mode inspect   # streams, version, flags

# create
python scripts/write_hwpx.py 보고서.md --out 보고서.hwpx

# fill a form
python scripts/fill_hwpx.py 양식.hwpx --mode scan
python scripts/fill_hwpx.py 양식.hwpx --data 값.json --out 완성.hwpx
```

## Limitations

- Direct `.hwp` (binary) writing is not supported — create `.hwpx` and save as `.hwp` in Hancom Office.
- Distribution (배포용/DRM) and password-protected documents are refused (preview mode works for distribution docs).
- HWP 3.x and older are unsupported.
- Writing v1 scope: no images, page setup, real outline numbering, or footnotes.
- Generated files pass structural validation and round-trip reading, but open them once in Hancom Office before first real-world use.

See [`references/hwp-formats.md`](references/hwp-formats.md) for format internals.

## Credits

- HWPX document assembly: [python-hwpx](https://github.com/airmang/python-hwpx) (Apache-2.0)

## License

[MIT](LICENSE)
