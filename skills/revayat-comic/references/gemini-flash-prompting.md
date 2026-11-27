# Gemini 3.1 Flash Image prompting guide

Use this guide when calling `antigravity/gemini-3.1-flash-image` through `Numera-Gen-mcp` (`edit_image`, `connection="default"`) for comic lettering over artwork. Operational crop geometry, compositing rules, and CLI commands stay in `references/fullpage-image-edit.md`.

## Model behavior and gateway limits

Verified live on `connection="default"` (`antigravity/gemini-3.1-flash-image`):

- **Gateway contract**: single reference image (`max_references: 1`), `masks: unsupported`, single-shot calls without multi-turn memory, discrete output tiers (`1:1` at `1024x1024` for 1K, `512x512` for 0.5K). Prompt text is the only mask the model receives.
- **Persian language prior**: Google's official image-generation documentation lists Egyptian Arabic (`ar-EG`, where final and isolated `ي` always carries two dots) among top-tuned languages, while Persian (`fa-IR`) is absent. Short prompts that ask for "Persian" without describing the letter shapes fall back to dotted Arabic `ي`, drop outer halos, or drift away from the target box.
- **No forbidden glyphs in the prompt**: follow Google's semantic negative prompting rule. Describe the desired clean shape positively ("isolated final `ی` has a smooth open tail with empty space and zero dots underneath") and never print forbidden Arabic letters or negative tokens inside the prompt text.

## Routing table: pick the right tool before calling the model

| Region type | Example | Mandatory route | Reason |
| --- | --- | --- | --- |
| Flat solid-color pages and multi-line lists | Table of contents (`p0003`), stacked text on solid purple/white | Pure Rust flat clean + Vazir (0 model calls) | Exact centering, consistent scale, zero Persian glyph errors |
| Straight horizontal titles, credits, and crisp captions over art | Cover author credit (`p0001`), chapter title (`p0005`), straight dark-box captions | Variant D: Gemini clean-only artwork restoration + Rust Vazir (`bold`, `outline`) | Model restores artwork without generating text; Rust renders exact Vazir glyphs and halos |
| Ornate colored/beveled calligraphic logos | Cover title `Sekirei` -> `سکیری` (`p0001`, `p0002`) | Variant C: 4-part structured narrative prompt on Gemini 3.1 Flash | Preserves metallic/mauve calligraphy, bevel shadow, and diagonal sweep |
| Tilted, curved, or hand-brushed SFX over speedlines/screentones | `UWAAAAH!` -> `وااای!` (`p0009`), `COME ON, DUDE.` (`p0009`), `RUMBLE` -> `غرش` (`p0019`) | Variant C: 4-part structured narrative prompt on Gemini 3.1 Flash | Matches hand-drawn angle, ink polarity, outer outline, and speedline/halftone texture |
| Speech, thought, and standard dialogue balloons | Ordinary speech bubbles | Pure Rust `clean --bubbles-only` + deterministic Vazir (`Vazir-Medium` / `Vazir-Bold`) | Keeps font family, weight, and size uniform across the whole chapter |

## Live benchmark results (`antigravity/gemini-3.1-flash-image`)

Measured across 11 live `1024x1024` trials on five Sekirei Vol. 15 crops (`C1` cover logo + credit, `C2` chapter title over halftone/mist, `C3` tilted white-on-black shout over Japanese `あああ—`, `C4` two-line white aside beside `う`, `C5` small SFX on halftone under `ゴゴゴ`). Each output was scored 0-2 on seven axes (14 max): Persian glyph accuracy, stroke/halo/polarity, erasure completeness, background texture, freeze-zone integrity, scale/angle integration, and framing lock.

| Variant | Length | Results | Outcome |
| --- | --- | --- | --- |
| Variant A (terse baseline) | ~100 words | `C1`: **7/14 FAIL** (turned purple logo white, dropped white halo on author credit) | Retired |
| Variant B (medium bullet list) | ~140 words | `C1`/`C3`/`C5`: 13/14 (slight scale/join drift); `C4`: **8/14 FAIL** (drifted into upper-right white bubble) | Retired for end-to-end lettering |
| Variant C (4-part narrative + anatomy) | ~240-310 words | **14/14 on all 5 crops (70/70, 0 failures)**: exact purple bevel on `سکیری`, 3 px white halo on credit, dotless final `ی`, exact dark-wedge placement on `C4`, crisp halftone dots and untouched Japanese kana | **Adopted default for stylized on-art lettering** |
| Variant D (clean-only restoration) | ~90-120 words | **14/14 on `C1` credit & `C2` title (28/28)**: spotless ribbon/skin/halftone restoration with zero text artifacts | **Adopted default for horizontal titles/credits paired with Rust Vazir** |

## Four-part Variant C prompt blueprint

Build every end-to-end Gemini 3.1 Flash prompt with these four parts in order:

1. **Context and framing lock**: name the medium ("full-color Japanese manga cover crop" or "monochrome Japanese manga action panel crop"), lock exact `1:1` framing, color/monochrome profile, and state the exact count of English text elements being replaced.
2. **Named protected freeze zones**: list every nearby visual element that stays pixel-identical. Always name visible Japanese hiragana/katakana/kanji (such as `うわあああ` or `ゴゴゴ`), standalone volume badges (`15`), map pins (`1-8`), character faces/hands, and panel or balloon borders.
3. **Step 1, erase and restore print texture**: name the exact English text, its location, and its drop shadow/outline/glow to remove, then name the exact underlying surface texture to reconstruct (uniform black-dot halftone grid, sharp radial black-and-white ink speedlines, flat pitch-black `#000000` ink fill, or smooth painted skin/fabric).
4. **Step 2, positive Persian lettering and glyph anatomy**: give the verbatim Persian with line breaks, specify exact foreground ink hex/color, exact outer outline/halo color and pixel width (for example, `3 px pure-white #FFFFFF outer halo` or `4 px solid black #000000 outer outline`), angle, and scale, then describe any tricky Persian letters right-to-left.

### Persian glyph anatomy cheat sheet

Include the matching clause whenever the target Persian contains these letters:

- **Final or standalone `ی`** (`سکیری`, `آشیکابی`, `وااای!`, `ای`): smooth curved open bowl/tail with empty space and zero dots underneath.
- **Medial `ـیـ`** (`سکیری`, `هشتمین`, `آشیکابی`): connected tooth with two neat dots centered underneath (distinguish explicitly when the same word has both medial `ـیـ` and dotless final `ی`).
- **Persian `ک`** (`سکیری`, `ساکوراکو`, `گوکوراکوئین`): clean diagonal top stroke (`سرکش`).
- **Four Persian-only letters**: `پ` (three dots cleanly below), `چ` (three dots inside the belly), `ژ` (three dots above), `گ` (double parallel diagonal top strokes).
- **Medial hamza `ـئـ`** (`گوکوراکوئین`): small hamza cleanly above its connected tooth.
- **Digits**: keep ASCII digits (`0-9`) verbatim.

## Copy-paste templates

### Template 1: Clean-only artwork restoration (Variant D + Rust Vazir)

```text
Manga artwork restoration on this exact 1:1 [color / black-and-white] crop. Do not add any text, letters, numbers, symbols, or marks anywhere in the output.
Keep every other element pixel-identical, including [named freeze zones: volume badge, Japanese kana, character linework, panel borders].
Completely erase the English text "[SOURCE_TEXT]" at [exact position], including its entire drop shadow, outline, and glow.
Across the cleared footprint, reconstruct only the underlying manga artwork seamlessly: [exact surface texture: uniform black-dot halftone grid / crisp radial ink speedlines / flat pitch-black #000000 ink / painted ribbon and skin].
Return the exact same 1:1 framing and color/monochrome contrast with clean, text-free artwork.
```

### Template 2: Stylized cover logo and credit with outer halo (Variant C)

```text
This image is a full-color Japanese manga cover crop being localized into a professional Persian print edition. Return the exact same 1:1 composition, camera framing, character faces, clothing, ribbons, and color palette with only [N] English text elements replaced.

Protected freeze zones that remain completely untouched: [circular volume badge "15" on the right edge with a clean gap to its left; character hair, faces, skin, clothing, and ribbons outside the letter footprints].

Step 1, erase and restore artwork: completely clear [English title and credit with shadow/bevel/halo]. Beneath both cleared areas, smoothly restore [exact continuous illustration surfaces].

Step 2, paint the Persian cover title in place of "[SOURCE_TITLE]": render "[PERSIAN_TITLE]" in [exact calligraphy color, bevel/shadow, scale, and diagonal flow], stopping cleanly before the volume badge. Spell and form every letter accurately from right to left: [per-letter anatomy, explicitly separating dotted medial ـیـ and dotless final ی].

Step 3, set the Persian credit in place of "[SOURCE_CREDIT]" at [position] on [N] clean horizontal lines:
[LINE_1]
[LINE_2]
Render in crisp solid black (#000000) ink surrounded everywhere by a smooth 3 px pure-white (#FFFFFF) outer halo so every letter separates cleanly from the artwork behind it. [Per-letter anatomy for ک/گ/ئ/ی].
```

### Template 3: Dark-on-light title or SFX with white halo over halftone/speedlines (Variant C)

```text
This image is a monochrome Japanese manga panel crop being localized into a professional Persian print edition. Return the exact same 1:1 composition, framing, crisp monochrome ink linework, and regular halftone dot grid with only one English lettering element replaced.

Protected freeze zones that remain completely pixel-identical: [tall vertical Japanese katakana "ゴゴゴ" immediately above / character hair, eyes, hands / speech balloon border / panel gutters].

Step 1, erase and restore texture: completely clear only "[SOURCE_TEXT]" at [position] along with its outer border. Across the cleared area, reconstruct [exact halftone dot grid / sharp radial speedlines / flat #000000 ink boundary] cleanly with crisp dots and lines and zero gray blur or wash.

Step 2, letter the Persian text in the exact same position, compact scale, and [angle/alignment]:
[PERSIAN_TEXT]
Render in bold solid black (#000000) ink surrounded everywhere by a clean uniform [2-3] px pure solid white (#FFFFFF) outer halo so every letter pops cleanly off both dark ink and halftone dots. Form every character accurately from right to left: [per-letter anatomy].
```

### Template 4: Light-on-dark (white-on-black) shout or aside beside Japanese kana (Variant C)

```text
This image is a monochrome Japanese manga action panel crop being localized into a professional Persian print edition. Return the exact same 1:1 composition, framing, pure black-and-white ink contrast, and line weights with only one English lettering element replaced.

Protected freeze zones that remain completely pixel-identical: [giant hand-drawn Japanese hiragana "あああ—" / "う" / spiky hair / chibi face / panel borders].

Step 1, erase and restore ink artwork: completely clear only "[SOURCE_TEXT]" at [exact position in dark wedge / above hair] together with its thick black outer border. Across the cleared area, reconstruct crisp black-and-white radial speedlines and flat pitch-black #000000 manga ink with clean negative space and zero gray haze.

Step 2, hand-letter the Persian text in the exact same spot, [angle], and energetic scale:
[PERSIAN_TEXT]
Render every character in pure solid white (#FFFFFF) fill wrapped completely in a crisp uniform [3-4] px pure solid black (#000000) outer outline so every stroke reads sharply across both speedlines and pitch-black ink. Form every character accurately from right to left: [per-letter anatomy, dotless final ی, three-dot پ].
```

### Template 5: Targeted seam or edge strip repair

```text
Minimal manga seam repair on this exact crop. Keep all Persian letters, Japanese kana, character linework, and framing completely unchanged.
Repair only the thin [top / bottom / left / right] seam artifact at [exact edge] by continuing the adjacent [halftone dot grid / radial speedlines / solid ink / painted background] smoothly across that narrow strip with zero blur.
```

## Instant-reject QA triggers and retry rule

Reject a generated crop immediately before compositing if any of these appear when inspected at full 1024x1024 resolution:

1. Any final or standalone `ی` carrying two dots underneath, missing medial `ـیـ` dots, broken letter joins, or distorted `ک`/`گ`/`پ`.
2. Missing or uneven outer halo/outline, or inverted ink polarity relative to the source lettering.
3. Any pixel drift, warping, or erasure on adjacent Japanese kana/kanji or standalone numeric badges (`15`, `00:00`, map pins).
4. Flat blurry gray smudge replacing halftone dots or radial speedlines, or ghost English strokes left underneath.
5. Misplaced text (drifted out of the original footprint) or framing zoom/shift along the crop border.

**Retry rule**: tighten the texture, location anchor, or glyph anatomy description once. If a horizontal title or credit fails a second time, switch to Template 1 (clean-only restoration) and typeset it deterministically with bundled Vazir instead of repeating end-to-end model retries.
