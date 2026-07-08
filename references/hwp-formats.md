# HWP format internals

Working notes for extending the parser. Sources: Hancom's public HWP 5.0 spec
(한글문서파일형식 5.0 공개 문서) and the OWPML standard (KS X 6101) for HWPX.

## HWP 5.0 (.hwp) — OLE compound file

### Streams

| Stream | Content |
|---|---|
| `FileHeader` | 256 bytes: signature `HWP Document File`, version (offset 32, 4B), flags (offset 36, 4B) |
| `DocInfo` | Document-wide records (fonts, styles, ID mappings) — compressed like sections |
| `BodyText/Section0..N` | Body records per section |
| `ViewText/Section0..N` | Distribution-document body (encrypted) — replaces BodyText |
| `PrvText` | Preview text, UTF-16LE, truncated (~2000 chars) |
| `PrvImage` | Preview image (BMP/GIF) |
| `BinData/*` | Embedded binaries (images, OLE objects) |
| `Scripts/*` | JavaScript macros |

### FileHeader flags (offset 36, little-endian DWORD)

| Bit | Meaning |
|---|---|
| 0 | Sections are zlib-compressed (raw deflate, `wbits=-15`) |
| 1 | Password-protected |
| 2 | Distribution document (배포용) — body in encrypted `ViewText` |
| 3.. | Script, DRM, XML template, history, e-signature, certificate encryption ... |

### Record structure

Each record: 4-byte header `DWORD = tag(10) | level(10) | size(12)`.
If `size == 0xFFF`, the real size follows as an extra DWORD.
`level` expresses tree nesting (a table's cell paragraphs sit deeper than body paragraphs).

Key tags (`HWPTAG_BEGIN = 0x10`):

| Tag | ID | Content |
|---|---|---|
| `HWPTAG_PARA_HEADER` | 66 | Paragraph header (char count, control mask) |
| `HWPTAG_PARA_TEXT` | 67 | Paragraph text, UTF-16LE + control codes |
| `HWPTAG_PARA_CHAR_SHAPE` | 68 | Character shape runs |
| `HWPTAG_CTRL_HEADER` | 71 | Control object header (table `tbl `, section def, etc.) |
| `HWPTAG_LIST_HEADER` | 72 | List header (e.g. table cell paragraph list) |
| `HWPTAG_PAGE_DEF` | 73 | Page geometry |
| `HWPTAG_TABLE` | 77 | Table object (row/col counts, cell spans) |

### PARA_TEXT control codes (UTF-16 code units < 32)

| Codes | Kind | Width |
|---|---|---|
| 0, 10 (LF), 13 (para end), 24–31 | char control | 1 wchar |
| 4–9, 19, 20 | inline control (tab=9, ...) | 8 wchars |
| 1–3, 11, 12, 14–18, 21–23 | extended control (section/table/object anchors carry a pointer) | 8 wchars |

Extraction rule: emit `\n` for 10, drop 13 (each PARA_TEXT record is already one
paragraph — emitting the terminator doubles line spacing), `\t` for 9 (then skip
7 more wchars), `-` for 24 (hyphen), a space for 30/31 (non-breaking/fixed-width),
skip 1 wchar for other char controls, skip 8 wchars for everything else < 32.
Decode contiguous text runs as UTF-16LE byte slices, not per-code-unit `chr()`,
so surrogate pairs (emoji, CJK Ext-B) survive.

### Distribution documents (배포용)

`ViewText` records are wrapped with an obfuscation layer (record-seeded PRNG XOR +
AES-128-ECB on a derived key). Not implemented here — re-save the file as a normal
document in Hancom Office instead.

## HWPX (.hwpx) — OWPML zip package

### Entries

| Entry | Content |
|---|---|
| `mimetype` | `application/hwp+zip` |
| `version.xml` | Format/application version |
| `META-INF/container.xml` | Package manifest pointer |
| `Contents/content.hpf` | OPF-style manifest & spine |
| `Contents/header.xml` | Styles, fonts, document properties |
| `Contents/section0..N.xml` | Body sections (OWPML) |
| `Preview/PrvText.txt` | Plain-text preview |
| `BinData/*` | Embedded binaries |

### Body XML (namespace `hp` = `.../hwpml/2011/paragraph`)

```
<hs:sec>
  <hp:p>                      paragraph
    <hp:run>
      <hp:t>text</hp:t>       text (may contain hp:lineBreak with tails)
      <hp:tbl>                table (inline object inside a run)
        <hp:tr><hp:tc>
          <hp:subList><hp:p>…</hp:p></hp:subList>
        </hp:tc></hp:tr>
      </hp:tbl>
      <hp:rect|container|…>   drawing objects — text lives in nested hp:subList
    </hp:run>
  </hp:p>
</hs:sec>
```

Parse by local name (`tag.rsplit('}', 1)[-1]`) — Hancom has revised namespace URIs
between releases, and DRM-packaged HWPX may omit `Contents/section*.xml` entirely
(detect and refuse rather than returning empty text).

## Writing HWPX (package rules learned from real files)

Dissected from Hancom-authored HWPX packages; these are the invariants a writer
must respect.

### Minimal valid package (9–10 entries)

`mimetype`, `version.xml`, `META-INF/{container.xml, manifest.xml, container.rdf}`,
`Contents/{content.hpf, header.xml, section0.xml}`, `Preview/PrvText.txt`,
`settings.xml`. `BinData/*` and `Preview/PrvImage.*` only when embedding binaries.

- **`mimetype` must be the FIRST zip entry, STORED (uncompressed)**, containing
  exactly `application/hwp+zip` (19 bytes, no newline) — same convention as ODF.
- `content.hpf` (OPF) must list every part in `opf:manifest` and order
  `header (linear="no") → section0` in `opf:spine`. Images need `isEmbeded="1"`
  (Hancom's spelling — keep it, along with `tagetApplication` in version.xml).
- `container.xml` points at `content.hpf`, `Preview/PrvText.txt`, `container.rdf`.
- `PrvText.txt` is UTF-8 **without BOM**.

### ID reference system (header.xml `hh:refList`)

Resources are 0-based-id pools referenced from the body:

```
hp:p @paraPrIDRef / @styleIDRef   →  hh:paraPr @id / hh:style @id
hp:run @charPrIDRef               →  hh:charPr @id
hp:tbl, hp:tc @borderFillIDRef    →  hh:borderFill @id
hh:charPr/hh:fontRef @hangul...   →  hh:fontface/hh:font @id
```

Each list's `itemCnt` must equal its child count; dangling IDRefs are fatal in the
editor. The python-hwpx blank template ships style id 0 = 바탕글, ids 2–11 =
개요 1–10 (usable for headings), and `add_run(bold=/size=/color=)` creates matching
charPr entries on demand.

### Units

Page/table geometry is HWPUNIT (1/7200 inch — A4 portrait = 59528 × 84188).
Character height is 1/100 pt (`height="1000"` = 10 pt).

### Run splitting (why template fill needs cross-run matching)

Hancom's editor splits paragraph text into multiple `hp:run`/`hp:t` nodes following
the author's edit history, so a placeholder like `{{성명}}` is often stored as
`{{성` + `명}}` in separate runs. `fill_hwpx.py` therefore concatenates the
paragraph text with per-node offset maps, matches on the joined string, and writes
back per node; the replacement inherits the charPr of the run where `{{` starts.
Paragraph terminators are per-record in .hwp but real `<hp:lineBreak/>` elements
inside `hp:t` in HWPX.
