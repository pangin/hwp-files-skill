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
