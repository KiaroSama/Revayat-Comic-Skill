# Full-page image edits for lettering on artwork

Use this branch for text drawn over artwork, such as map labels, speedline shouts, title lettering, and sound effects selected for translation. Read the overview and crop sheets before you write the replacements. Preserve the original artwork and keep a separate copy of every candidate image.

## Prepare the edit

Merge and review the worksheets, then clean the speech balloons. For the page you want to edit, take its actual ID from `comic.json`:

```bash
revayat-comic clean --doc "$WORK/comic.json" --bubbles-only
revayat-comic fullpage-prompt --doc "$WORK/comic.json" --page p0009 > "$WORK/p0009-edit.json"
```

`fullpage-prompt` writes JSON to stdout. It defaults to `openai/gpt-image-2.6-sunburst`; use `--model <MODEL>` to choose another model. Check the generated replacements against the worksheet and the artwork. Give each replacement a precise location, the verified source text, the exact Persian spelling and line breaks, and the original lettering style. Do not send the page for editing if there is no on-art text to replace.

## Edit and inspect the whole page

Send the full bubbles-emptied page from the manifest to `Numera-Gen-mcp` `edit_image` as the reference. Small isolated patches lose the surrounding linework and screentones. Tell the editor to leave the speech balloons empty and keep the panel borders, artwork, and untranslated lettering as they are.

Open the returned page with `Read`. Compare it with the original and check the new text letter by letter, including dots and joins. Save approved images as `pNNNN.png` in a separate directory, where `pNNNN` is the page ID. The image must match the original page's exact pixel dimensions. Reject an edit if you cannot bring it to those dimensions without stretching or clipping the artwork.

## Composite and finish

```bash
revayat-comic typeset --doc "$WORK/comic.json" --external-dir "$EDITED"
revayat-comic qa check --doc "$WORK/comic.json" --strict
```

Set `$EDITED` to the approved PNG directory. Include only the pages you edited, named `<page_id>.png`. On those pages, the CLI composites the approved on-art edit areas and then sets speech balloon text with the bundled Vazir fonts. Pages without a matching PNG use the normal deterministic typesetting path. Open every rendered page again to check the mask edges, lettering, and nearby artwork. Fix problems before exporting.
