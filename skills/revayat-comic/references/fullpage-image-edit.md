# Crop edits for lettering on artwork

Use this workflow for text drawn over artwork, such as map labels, speedline shouts and titles. Read the overview and crop sheets before writing replacements. A tight crop gives Persian glyphs more of the output frame and can lower image input token cost per request. Unrelated balloons stay unchanged because their pixels never enter the composite.

## Prepare the crop

Merge and review the worksheets, then clean the speech balloons. Take the page's actual ID from `comic.json`:

```bash
revayat-comic clean --doc "$WORK/comic.json" --bubbles-only
revayat-comic fullpage-prompt --doc "$WORK/comic.json" --page p0009 > "$WORK/p0009-edit.json"
```

`fullpage-prompt` writes the page paths, dimensions, and text map to stdout. It defaults to `antigravity/gemini-3.1-flash-image`; use `--model <MODEL>` to choose another model. The cleaned page is the crop source, not the image to send. Skip the image edit if the page has no approved on-art replacement.

Crop one lettering zone at a time. Leave about 40 to 80 pixels of surrounding linework or screentone at the original page scale where the page permits it. Record the exact top-left `x`, `y`, width, and height before making any sizing changes. Keep adjacent balloons out of the crop where possible. Extend context or pad without stretching, and record any temporary padding so you can remove it before pasting back. Stage input crops inside the connection's allowed input root.

On Numera's `default` connection using an `openai-images` gateway, use an exact `1:1` context crop and request `size: "1024x1024"` (`1K`). Square crops from 110×110 to 384×384 worked in live trials; rectangular `16:9`/`21:9` requests and `512x512` requests returned `partial` and output a 1024×1024 square anyway (outpainting rectangular inputs). Exact `1:1` requests at `1024x1024` returned `completed` with mean per-channel drift under 3/255 on untouched hair and speedlines before compositing (2.02 and 2.91, respectively).

### Lower cost with minimal crops and 2×2 batching

Because the `openai-images` gateway returns one 1024×1024 frame per request even for tiny inputs, you can minimize cost without losing sharpness in two ways:

1. **Tight single crop (`110×110` to `240×240`):** For a solo title, badge, or complex sign, send the smallest `1:1` square that still keeps ~20–40 px of context around the lettering (for example, `110×110` on a small SFX or `230×230` on a title badge). Even `110×110` produced clean Persian strokes on speedlines.
2. **2×2 magenta-divided contact grid (up to 4 small SFX/signs in one call — 75% fewer calls):** When a page or chapter has multiple small on-art sound effects or short labels, crop up to 4 equal `1:1` squares (for example `160×160` each), assemble them into one `2×2` square separated by a bright `#FF00FF` (magenta) 4 px cross divider, and submit ONE `1024x1024` edit listing the exact Persian replacement per quadrant (`TOP-LEFT`, `TOP-RIGHT`, `BOTTOM-LEFT`, `BOTTOM-RIGHT`). Each cell gets ~504×504 effective output pixels with zero cross-cell bleed; slice the 4 quadrants along the magenta cross, resize each back to its original square with Lanczos, and feather-paste only the lettering zone into its page. Use a solo `1:1` crop instead for intricate covers, maps, or multi-line titles.

On a route that preserves framing at other [supported Gemini aspect ratios](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-image), match the crop to a supported ratio. Use `0.5K` if the glyphs stay clear at that tier; use `1K` for fine lettering or dense linework. These tiers specify output sizes for a given ratio, not arbitrary pixel dimensions.

## Submit one crop and read the result

Send the crop as the only reference to `Numera-Gen-mcp` `edit_image` with the selected model and `target_language` set to `Persian`. Use the documented pixel size for the ratio and tier if the connection supports it. Check the returned image's actual dimensions; a requested size is not proof of what the route returned. Keep the source crop and every candidate separate.

Use this prompt structure for each crop. Give crop-local coordinates or a clear position cue, and put the exact Persian on its own lines:

```text
Edit only the English lettering at <crop-local position>.
Source text: <verified source text>
Exact Persian, with the line breaks shown:
<approved Persian>

Use the source lettering's weight, scale, angle, outline and alignment.
Copy the Persian spelling, joins, dots, punctuation and spaces exactly.
For سِکیری ۱۵, place the circled ۱۵ immediately to the left of سِکیری,
following right-to-left reading order. Keep a narrow gap so they do not touch.
Preserve the badge shape and both digits.
Do not alter surrounding lines, screentones, borders, balloons, or hand-drawn Japanese kana/SFX.
Return this crop with the same framing. Add no text or marks beyond the replacement.
```

Open the returned crop with `Read`. Check every letter, dot, join and line break, and verify that the volume badge is on the left of the title. Reject missing or unlisted text and any damage within the area you will paste. A crop that needs stretching, clipping, or redrawing to align is not ready to paste.

## Paste back and review

1. Resize the 1024×1024 return to the source square with Lanczos. If you padded the crop, remove the padding after resizing. Check nearby line intersections before pasting; reject the edit if the framing shifted.
2. Start from the bubbles-emptied page. Paste at the recorded `x`, `y` using a tight elliptical or rectangular mask over the approved lettering inside that rectangle. Feather the edge by 4 to 6 pixels inside the mask. Keep all pixels outside the mask identical to the base, including hair, kana, speedlines, borders, and empty balloons.
3. Have an independent reviewer inspect the composite at full resolution. If they flag a seam or edge halo, send only a tiny `1:1` crop centered on that seam. Ask the editor to repair only the affected strip. Align and paste just the approved strip at its coordinates, keeping the lettering and adjacent art unchanged. Recheck it before continuing.
4. Save each approved composite as `<page_id>.png` in a separate directory at the original page's exact dimensions. Do not overwrite the original or cleaned image. After compositing, remove only the temporary input crops you staged.

```bash
revayat-comic typeset --doc "$WORK/comic.json" --external-dir "$EDITED"
revayat-comic qa check --doc "$WORK/comic.json" --strict
```

Set `$EDITED` to the approved PNG directory. The CLI composites only authorized on-art areas and sets speech balloon text with the bundled Vazir fonts. Pages without a matching PNG use deterministic typesetting. Open every rendered page again to check the mask edges, lettering, and nearby artwork before exporting.
