# Native Word companions and comic PDF workflows

Use the helpers shipped with this Revayat installation. A separate Docx or PDF
Processing Pro plugin is not required. The Word companion is an editable
translation/review snapshot; the primary book remains CBZ, PDF or page images.

## Export an editable Word companion

After importing and recording the translations or review notes you want to
share, select `REVIEW_OUTPUT` as a new `.docx` file path. For a CBZ/PDF primary
edition, place it beside the actual `OUTPUT` file. For a delivered page folder,
it may be a new file inside that folder. `OUTPUT` keeps its meaning from the
main skill; do not append filenames to a primary edition's file path. Run:

```bash
$PY "$SKILL_DIR/scripts/revayat-comic.py" review-docx \
  --doc "$WORK/comic.json" --out "$REVIEW_OUTPUT"
```

Choose a **new** filename. Existing files, folders and symlinks are refused;
there is no overwrite option. A review companion may contain unresolved content,
so it does not require the primary publication gate to pass first.

The companion contains the chapter identity and source/target languages,
the exact input-document hash, every source page ID and its pixel dimensions,
known PDF point dimensions, and every region in recorded reading order. Each
region retains its stable ID, kind, speaker, state, source text, displayed
Persian, full Persian variant, and available review/processing notes and
recorded review decisions. Empty pages and absent Persian are explicit.
Recorded review codes are history, not fresh semantic approval.

Text is editable Word text, not a screenshot. Persian remains in logical
Unicode order with its ZWNJ, ezafe and deliberate blank lines. Paragraph and
run direction are separate so Latin identifiers are not blindly forced RTL.
The document requests Vazirmatn for complex-script text and Arial for Latin;
fonts are not embedded. A viewer may substitute an installed font.

The JSON result includes `path`, `sha256`, `snapshot_sha256`, `pages`, `regions`
and `review_only: true`. These counts describe the source snapshot, not Word's
rendered pagination. Word can repaginate editable text; this companion makes
no claim to preserve the comic's physical layout or to certify its artwork.

## Make corrections without losing identity

1. Review the source/Persian pair and notes under the unchanged region ID.
2. Apply accepted changes to that ID in the existing worksheet. Preserve its
   mapping headers; use the [recovery workflow](recovery.md) for stale mappings.
3. Merge and repeat the affected processing and QA stages from the main skill.
4. Export another companion to a new filename when a fresh snapshot is needed.

Editing Word does not automatically change `comic.json`, worksheets or the
primary edition. Full variants must survive any reviewed shortening. A Word
file edited after export also no longer has the hash printed by that export.

## Safe publication and practical limits

The helper holds the workspace claim while reading the snapshot, then uses a
separate destination claim and publishes a complete staged file without
replacing an existing destination. It rechecks the input generation before
publication. It never writes the document or its primary-export metadata.
Original inputs, page assets and worksheet directories are protected destinations.

| Limit | Reason |
| --- | --- |
| 16 MiB input `comic.json` | Bound the JSON read before parsing. |
| 2,000 pages and 20,000 regions | Bound chapter traversal and document structure. |
| 2,000,000 emitted text characters | Bound transcript content, including headings and repeated review material. |
| 100,000 paragraphs and 100,000 text runs | Bound blank-line and mixed-direction markup expansion. |
| 32 MiB main document XML | Bound the uncompressed document before ZIP publication. |

Exceeding a limit fails rather than truncating. Review exceptionally large work
as separate chapter workspaces. No images or font binaries are embedded.
On POSIX, atomic publication uses a same-directory hard link; a filesystem
without that operation fails safely. Windows uses a non-replacing rename.

The CLI emits JSON with `ok: false` and a nonzero status for a refused export.
Invalid XML control characters are errors, never silently deleted or substituted.
Resolve the reported issue and use a new output path when an existing artifact
must be kept. Preserve evidence from an interrupted write for inspection.

CLI diagnostic logs use the shared run logger. They do **not** replace the
[translation activity log](translation-log.md). The using agent must record the
actual companion result, snapshot/artifact hashes and remaining review items in
the output-side activity record. Keep that record beside the delivered Word
file when its folder differs from the primary edition's folder.

## Use the existing PDF preservation path

For a comic PDF, follow the main import workflow:

```bash
$PY "$SKILL_DIR/scripts/revayat-comic.py" import "$INPUT" --out "$WORK"
```

Specify the source reading direction/language as described in the main skill.
The importer uses the embedded image when the PDF structure proves it is the
whole visible page; other pages use the bounded render path. Known visible PDF
paper dimensions are recorded separately from immutable raster dimensions.
An arbitrary fixed-DPI OCR conversion must not replace that baseline.
Composite-page rendering retains the native density of embedded scans within
the allocation bound; an oversized page is refused rather than downsampled.
An undersampled visible-pixel reference cannot certify the delivered page.

Use the existing mask, cleaning, typesetting and QA stages. For the PDF example
below, `OUTPUT` is the actual new primary PDF path, such as
`out/chapter-fa.pdf`; its parent is the delivery directory:

```bash
$PY "$SKILL_DIR/scripts/revayat-comic.py" qa check --doc "$WORK/comic.json"
$PY "$SKILL_DIR/scripts/revayat-comic.py" export \
  --doc "$WORK/comic.json" --out "$OUTPUT"
$PY "$SKILL_DIR/scripts/revayat-comic.py" qa package \
  --doc "$WORK/comic.json" --file "$OUTPUT"
```

Check the real exit statuses and report contents. The PDF writer uses recorded
paper dimensions when available; a raw image's pixels alone do not establish a
physical paper size. Package checking concerns the committed visible page and
artifact bytes. Extracted text, OCR confidence or approximate page similarity
cannot substitute for integrity verification.

When source detail is poor, inspect separately identified reading/enhancement
copies under the [artwork rules](artwork-preservation.md). Optional OCR is
evidence for reading, not permission to replace originals or approve meaning;
see [OCR guidance](ocr.md). This installation does not claim to ship general
PDF form filling, table extraction, arbitrary PDF editing or Word import.

## Verify the companion's presentation

Check that the file opens in a compatible Word viewer and that source text,
Persian, Latin/numeric spans, punctuation and blank paragraphs remain readable.
Inspect early, middle and final source-page sections and an empty/unresolved
page. Make a correction in a separate copy to confirm the text is editable.

Word or LibreOffice can provide an optional PDF preview for visual inspection.
Keep that preview separately named; it is a rendering of the review companion,
not the primary comic PDF. A renderer is not bundled or automatically installed.
If none is available, report structural checks and the missing visual check
separately. XML/ZIP validity alone does not prove readable Persian.
