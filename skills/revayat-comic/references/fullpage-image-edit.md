# Full-Page Image-Edit Workflow (Bubbles-Emptied + Full-Page Context)

Tiny isolated crop inpainting destroys manga speedlines, screentones, hair strands, and color gradients, producing blocky black-and-white noise patches and dirty halos. **Never send an isolated small crop to an image-editing model.**

## Core Two-Phase Rule

1. **Empty ONLY clean speech bubbles first.**
   - Run `revayat-comic clean --bubbles-only` so uniform white/solid speech bubbles become clean blank spaces (with interior speckle sweep removing every stray ink dot/punctuation speck).
   - Leave ALL on-art lettering, speedline shouts, map labels, cover logos, chapter titles, and stylized sound effects **100% untouched** on the original artwork.
2. **Submit the FULL bubbles-emptied page to the image-editing model.**
   - Pass the entire page image as the single reference to `Numera-Gen-mcp` `edit_image`. Comparative benchmark on `p0009` (2026-11-25):
     - `openai/gpt-image-2.6-sunburst`: **primary choice for full-page comic editing** — 9/9 exact surgical placement, 0 empty-bubble spills, lossless `1024×1536` PNG output.
     - `antigravity/gemini-3.1-flash-image`: **fast secondary / text-to-image choice** — fast, first-try accurate Persian spelling and strong manga ink/SFX generation, 7/9 exact placement on dense pages (2 items drifted into adjacent blank bubbles; returns `848×1264` JPEG).
     - `deepinfra/google/nano-banana-pro`: returned HTTP 404 (`model_unavailable`) on the configured gateway.
   - Supply a numbered list of EVERY remaining English/source on-art text item with:
     1. Exact panel & spatial location (e.g., `"Bottom panel, top-center over speedlines above the angry chibi head"`).
     2. Exact OCR-verified source text (e.g., `"DAMN YOU!"`).
     3. Exact target Persian text, including explicit line breaks (e.g., `"لعنتی!"`).
     4. Explicit spelling & diacritic notes for tricky Persian strings (e.g., `"آااااه!"` — madda `آ` ONLY on the first alef, plain `ا` on the rest; `"اِه!"` — plain alef with kasra, NO madda; prefer concise high-legibility Persian words where extra dots might blur).
     5. Visual lettering style (white fill + black outline, white on dark map, tilt angle, comic sans/Vazir look).
   - Explicitly instruct the model to keep EVERY empty speech bubble pure blank white and keep ALL characters, faces, panel borders, speedlines, screentones, and Japanese brush SFX 100% untouched.

## Verified Tuned Prompt Template

```text
Edit this manga/comic page ONLY to replace the N specific remaining source lettering items below with exact, properly connected right-to-left Persian (Farsi) text in the exact same positions, sizes, and comic lettering styles.

STRICT PRESERVATION RULES:
- Keep EVERY empty white speech bubble 100% pure blank white (add ZERO text inside empty speech bubbles).
- Keep ALL characters, faces, eyes, hair, clothing, panel borders, screentones, speedlines, map shapes, arrows, numbered pins, and untranslated Japanese brush SFX 100% unchanged.
- Do NOT draw boxes, patches, smudges, or gray halos behind any replaced text; restore crisp background lines/art seamlessly behind every letter.

EXACT PERSIAN REPLACEMENTS (follow exact spelling and diacritics character-for-character):
1. <panel & position> — replace "<OCR_SOURCE>" with: "<EXACT_PERSIAN>" (<style, color, outline, tilt, line spacing>).
2. ...

Typography: clean modern Persian comic sans-serif (Vazir-style), exact right-to-left connected script, Persian digits (۰–۹). Verify every dot on Persian letters (ن، ت، پ، چ، ژ، ق، ف، ی) carefully.
```

## Post-Edit Compositing & Visual Verification

1. Inspect the returned full page visually with the `Read` tool (Stage 5). Check every single Persian dot, madda, letter join, badge clearance, and background line. If any glyph or dot slips, refine the prompt for that item and rerun that page.
2. Resample the approved full-page output back to the exact original pixel dimensions (`W × H`) using Lanczos resampling.
3. Composite ONLY the padded on-art replacement masks from the full-page edit onto the bubbles-emptied original page — preserving 100% exact original pixels across all untouched artwork, characters, and panel borders.
4. Run deterministic pure-Rust `revayat-comic typeset` (`cosmic-text` + bundled Vazir TTF) into the empty speech bubbles with generous line spacing (`>= 1.38x`) and RTL punctuation handling.
5. Verify with `revayat-comic qa check --strict` and final visual sign-off.
