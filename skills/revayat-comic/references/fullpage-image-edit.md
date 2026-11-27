# Crop edits for lettering on artwork

Use this workflow for translated text over artwork, such as map labels, speedline shouts, and titles. Read the overview, crop sheets, and `work/story.md` before writing replacements. Use ASCII digits (`0-9`) in the replacement. Standalone numeric artwork, including a volume badge `15`, map pins `1-8`, and a watch reading `00:00`, stays pixel-for-pixel unchanged. Mark it `keep` and exclude it from both the edit and paste masks.

## Prepare the crop

Merge and review the worksheets, then clean the speech balloons. Take the page's actual ID from `comic.json`:

```bash
revayat-comic clean --doc "$WORK/comic.json" --bubbles-only
revayat-comic fullpage-prompt --doc "$WORK/comic.json" --page p0009 > "$WORK/p0009-edit.json"
```

`fullpage-prompt` writes the page paths, dimensions, and text map to stdout. It defaults to `antigravity/gemini-3.1-flash-image`; use `--model <MODEL>` to choose another model. The cleaned page is the crop source. Skip the image edit if the page has no approved on-art replacement.

Crop one lettering zone at a time. Find the full visible footprint of the letters, including the farthest drop shadow, glow, and outline, and leave 120-240 px of artwork beyond it at the original page scale where the page permits. At a page edge, keep all visible effects and pad if the model needs more room without stretching. Record the source rectangle (`x`, `y`, width, height) and any padding. Keep adjacent balloons out of the crop where possible. Stage input crops inside the connection's allowed input root.

On Numera's `default` connection using an `openai-images` gateway, use a `1:1` crop and request `size: "1024x1024"` (`1K`). In prior trials, rectangular and `512x512` requests returned `partial` and a 1024×1024 square anyway. Do not shrink the context to fit a small square. On routes that preserve framing at other [supported Gemini aspect ratios](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-image), use a supported ratio and the smallest tier that keeps the glyphs legible (`0.5K` or `1K`). These tiers are output sizes for a given ratio, not arbitrary pixel dimensions.

For multiple small SFX or labels, a `2×2` grid can save requests. Use equal square crops with the same shadow-inclusive margins, separated by a 4 px magenta (`#FF00FF`) cross. Specify the exact text per quadrant (`TOP-LEFT`, `TOP-RIGHT`, `BOTTOM-LEFT`, `BOTTOM-RIGHT`). Use solo crops if a grid would clip effects, lose lettering detail, or put a nearby numeric badge at risk. Split the returned cells at the divider and realign each one separately.

## Submit and inspect the edit

Send the crop as the only reference to `Numera-Gen-mcp` `edit_image` with the selected model and `target_language` set to `Persian`. Submit at most 2–3 `edit_image` requests concurrently on the `default` gateway to avoid transient upstream HTTP 502 timeouts. Use the documented pixel size for the ratio and tier if the connection supports it. Check the returned image's actual dimensions and keep the source crop and candidates separate.

Use the empirically verified 4-part Variant C prompt blueprint (or Variant D clean-only restoration paired with Rust Vazir) from `references/gemini-flash-prompting.md`:

1. **Context and framing lock**: state the medium (`full-color` or `monochrome` manga crop), lock exact `1:1` framing, and name how many English elements are replaced.
2. **Named protected freeze zones**: list every nearby landmark that must stay pixel-identical, especially adjacent Japanese hiragana/katakana/kanji (`うわあああ`, `ゴゴゴ`), standalone volume badges (`15`), map pins (`1-8`), character faces/hands, and panel or balloon borders.
3. **Step 1, erase and restore texture**: remove the exact English text plus its full drop shadow, outline, and glow, and name the exact surface texture to reconstruct (uniform black-dot halftone grid, sharp radial ink speedlines, flat `#000000` ink, or painted fabric/skin) with zero gray blur.
4. **Step 2, positive Persian lettering and glyph anatomy**: give verbatim Persian with line breaks, exact ink color and outer outline/halo color + pixel width, angle, scale, and positive Persian glyph descriptions (final/standalone `ی` has a smooth open tail with empty space and zero dots underneath; medial `ـیـ` keeps two small dots; `ک` keeps a clean diagonal top stroke; keep ASCII digits `0-9`; never write forbidden Arabic glyphs inside the prompt).

Flat solid-color pages and multi-line lists (such as a table of contents) skip the image model and use deterministic Rust cleaning and Vazir typesetting. Ordinary speech balloons always use deterministic Rust Vazir (`Vazir-Medium` / `Vazir-Bold`) and never fall back to external image pixels.

Open the returned crop with `Read`. Check the Persian lettering and compare against the original at full 1024x1024 resolution. Follow the outer edge of each old effect and check for ghost ink, missing outlines, dotted final `ی`, altered Japanese kana, or framing drift. Reject any defect immediately; revise the prompt once or switch horizontal titles/credits to clean-only restoration plus Rust Vazir.

## Paste back and review

1. Resize the return to the crop's original padded dimensions with Lanczos, then remove any recorded padding. Check nearby line intersections; reject the edit if the framing shifted.
2. Start from the bubbles-emptied page. Paste at the recorded `x`, `y` using a mask that includes the entire erased source footprint and all new lettering effects. Use a 4 to 6 px feather in clean surrounding artwork beyond both footprints so the blend cannot bring the old shadow back. Preserve every pixel outside the approved mask, including standalone numbers and hand-drawn frames.
3. Have an independent reviewer inspect the composite at full resolution. For a seam or edge halo, send only a small `1:1` crop centered on that seam. Ask the editor to repair the affected strip, paste only the approved strip at its coordinates, and recheck it.
4. Save each approved composite as `<page_id>.png` in a separate directory at the original page dimensions. Leave the original and cleaned images unchanged. Remove only the temporary crops you staged.

```bash
revayat-comic typeset --doc "$WORK/comic.json" --external-dir "$EDITED"
revayat-comic qa check --doc "$WORK/comic.json" --strict
```

Set `$EDITED` to the approved PNG directory. Never copy rendered output pages back into `$EDITED`. The CLI composites approved on-art regions using a solid padded mask clipped against kept regions, standalone numeric art, protected Japanese kana, and closed balloons, reserves that external footprint so speech bubbles cannot collide with it, and sets every speech balloon deterministically with the bundled Vazir fonts. Open the `qa review-pack` zoomed side-by-side crops before exporting.
