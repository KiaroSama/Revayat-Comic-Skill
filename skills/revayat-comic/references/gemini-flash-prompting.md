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
| Straight titles and credits over art | Cover credit, chapter title | Rust Vazir with measured outline settings; use Variant D for clean-only restoration if Rust cannot clean the art | Keeps Persian glyphs and fine outlines under direct control |
| Ornate colored or beveled calligraphic logos | Cover title `Sekirei` -> `سکیری` (`p0001`, `p0002`) | Variant C | Matches the calligraphy, bevel shadow, and diagonal sweep |
| Slanted caption boxes and crisp tilted SFX | Tilted box header, `FLASH` or `STEP` over halftone | Rust cleanup and Vazir with `extra.angle` | Keeps the text at the source angle and preserves screentone dots |
| Curved or hand-brushed SFX Rust cannot match | Brush-lettered shout over speedlines | Variant C with measured outline, protected zones, and source angle | Lets the model match hand lettering inside the approved edit |
| Speech, thought, and standard dialogue balloons | Ordinary speech bubbles | Pure Rust `clean --bubbles-only` + deterministic Vazir (`Vazir-Medium` / `Vazir-Bold`) | Keeps font family, weight, and size uniform across the whole chapter |

## Live benchmark results (`antigravity/gemini-3.1-flash-image`)

Measured across 11 live `1024x1024` trials on five Sekirei Vol. 15 crops (`C1` cover logo + credit, `C2` chapter title over halftone/mist, `C3` tilted white-on-black shout over Japanese `あああ—`, `C4` two-line white aside beside `う`, `C5` small SFX on halftone under `ゴゴゴ`). Each output was scored 0-2 on seven axes (14 max): Persian glyph accuracy, stroke/halo/polarity, erasure completeness, background texture, freeze-zone integrity, scale/angle integration, and framing lock.

| Variant | Length | Results | Outcome |
| --- | --- | --- | --- |
| Variant A (terse baseline) | ~100 words | `C1`: **7/14 FAIL** (turned purple logo white, dropped white halo on author credit) | Retired |
| Variant B (medium bullet list) | ~140 words | `C1`/`C3`/`C5`: 13/14 (slight scale/join drift); `C4`: **8/14 FAIL** (drifted into upper-right white bubble) | Retired for end-to-end lettering |
| Variant C (4-part narrative + anatomy) | ~240-310 words | **14/14 on all 5 crops (70/70, 0 failures)**: exact purple bevel on `سکیری`, 3 px white halo on credit, dotless final `ی`, exact dark-wedge placement on `C4`, crisp halftone dots and untouched Japanese kana | **Adopted default for stylized on-art lettering** |
| Variant D (clean-only restoration) | ~90-120 words | **14/14 on `C1` credit & `C2` title (28/28)**: spotless ribbon/skin/halftone restoration with zero text artifacts | Use when Rust cannot clean a title or credit on its own |

## Outline, badge, and tilt rules

- **Outline fidelity.** Measure the original edge at native page scale. Every prompt must state the source outline color, width, and opacity or softness; write `no outline` when there is none. For a clean-only prompt, those measurements define the footprint to remove. Use the measured values, not a preset: `SAKURAKO GOKURAKUIN` might need a thin, faint 1 px halo with no thick white sticker outline; a chapter title might need a crisp 1.5 px white outline. For `FLASH` or `STEP`, ask for a crisp thin white outline matching the original over intact halftone dots, with no flat white wipe box. Scale the widths with the input crop if you resize it.
- **Graphic badge preservation.** Never erase or redraw a circled volume number such as `⑮` or adjacent Japanese katakana SFX. Mark these regions `keep: true` (`keep: yes` in the worksheet), name them in the prompt, and exclude their pixels from the edit and paste masks. The gateway receives no mask, so apply that exclusion locally and reject any composite that changes those pixels.
- **Tilt or slant.** Measure the source baseline or caption edge. Prefer deterministic Rust `extra.angle` for slanted caption boxes or crisp tilted SFX over halftone. Generative diffusion can smear the screentone. If a hand-drawn effect still needs a model edit, state the measured angle in the prompt and check it against the source before pasting.

## Four-part Variant C prompt blueprint

Build every end-to-end Gemini 3.1 Flash prompt with these four parts in order:

1. **Context and framing lock**: name the medium ("full-color Japanese manga cover crop" or "monochrome Japanese manga action panel crop"), lock exact `1:1` framing, color/monochrome profile, and state the exact count of English text elements being replaced.
2. **Named protected freeze zones**: list every nearby visual element that stays pixel-identical. Always name visible Japanese hiragana/katakana/kanji (such as `うわあああ` or `ゴゴゴ`), standalone volume badges (`15`), map pins (`1-8`), character faces/hands, and panel or balloon borders.
3. **Step 1, erase and restore print texture**: name the exact English text, its location, and its drop shadow/outline/glow to remove, then name the exact underlying surface texture to reconstruct (uniform black-dot halftone grid, sharp radial black-and-white ink speedlines, flat pitch-black `#000000` ink fill, or smooth painted skin/fabric).
4. **Step 2, Persian lettering and glyph anatomy**: give the verbatim Persian with line breaks. Specify the ink color, measured outline color, width and opacity, angle, and scale. Describe tricky Persian letters from right to left.

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
Erase the English text "[SOURCE_TEXT]" at [exact position], including its drop shadow and [measured outline/halo color, width, and opacity; or no outline].
Restore only the artwork inside that footprint: [uniform black-dot halftone grid / crisp radial ink speedlines / flat #000000 ink / painted ribbon and skin]. Continue halftone dots at the same spacing and size, with no flat white wipe box.
Return the exact same 1:1 framing and color/monochrome contrast with clean, text-free artwork.
```

### Template 2: Stylized cover logo and credit with outer halo (Variant C)

```text
This image is a full-color Japanese manga cover crop being localized into a professional Persian print edition. Return the exact same 1:1 composition, camera framing, character faces, clothing, ribbons, and color palette with only [N] English text elements replaced.

Leave [circled volume badge ⑮ with clearance to its left; adjacent Japanese katakana; character hair, faces, clothing, and ribbons outside the letters] pixel-identical.

Step 1, erase and restore artwork: erase [English title and credit, with the measured outline color, width, and opacity of each and any bevel or shadow]. Restore [exact illustration surfaces] inside those footprints.

Step 2, paint "[PERSIAN_TITLE]" in place of "[SOURCE_TITLE]". Match [calligraphy color, measured outline, bevel/shadow, scale, and diagonal flow]. Stop before the volume badge. Use [per-letter anatomy, including dotted medial ـیـ and dotless final ی].

Step 3, set the Persian credit in place of "[SOURCE_CREDIT]" at [position] on [N] horizontal lines:
[LINE_1]
[LINE_2]
Use [measured source ink and halo, for example black ink with a thin, faint 1 px halo only, no thick white sticker outline]. Use [per-letter anatomy for ک/گ/ئ/ی].
```

### Template 3: Dark-on-light title or SFX with white halo over halftone/speedlines (Variant C)

```text
This image is a monochrome Japanese manga panel crop being localized into a professional Persian print edition. Return the exact same 1:1 composition, framing, crisp monochrome ink linework, and regular halftone dot grid with only one English lettering element replaced.

Protected freeze zones that remain completely pixel-identical: [tall vertical Japanese katakana "ゴゴゴ" immediately above / character hair, eyes, hands / speech balloon border / panel gutters].

Step 1, erase only "[SOURCE_TEXT]" at [position], including [measured outline color, width, and opacity]. Continue the original halftone pattern or speedlines across the cleared area. Keep the dots crisp, with no flat white wipe box or blur.

Step 2, letter the Persian text at the same position and scale, following [measured source angle]:
[PERSIAN_TEXT]
Match the source ink and weight. Give the letters [measured outline color, width, and opacity, such as a crisp 1.5 px white outline on a thin chapter title, or a crisp thin white outline over intact dots for FLASH or STEP]. Form each character right to left: [per-letter anatomy].
```

### Template 4: Light-on-dark (white-on-black) shout or aside beside Japanese kana (Variant C)

```text
This image is a monochrome Japanese manga action panel crop being localized into a professional Persian print edition. Return the exact same 1:1 composition, framing, pure black-and-white ink contrast, and line weights with only one English lettering element replaced.

Protected freeze zones that remain completely pixel-identical: [giant hand-drawn Japanese hiragana "あああ—" / "う" / spiky hair / chibi face / panel borders].

Step 1, erase only "[SOURCE_TEXT]" at [position in dark wedge / above hair], including its [measured outline color, width, and opacity]. Reconstruct the original speedlines or flat #000000 ink with no gray haze.

Step 2, hand-letter the Persian text at the same position and scale, following [measured source angle]:
[PERSIAN_TEXT]
Use white (#FFFFFF) fill with the original [measured width and opacity] black (#000000) outline. Form each character right to left: [per-letter anatomy, dotless final ی, three-dot پ].
```

### Template 5: Targeted seam or edge strip repair

```text
Repair only the [top / bottom / left / right] seam at [exact edge]. Continue the adjacent [halftone dot grid / radial speedlines / solid ink / painted background] across the strip without blur.
Keep all Persian letters and their [measured outline color, width, and opacity; or no outline] unchanged. Preserve Japanese kana, circled badges, linework, and framing pixel for pixel.
```

## Instant-reject QA triggers and retry rule

Reject a generated crop immediately before compositing if any of these appear when inspected at full 1024x1024 resolution:

1. Any final or standalone `ی` carrying two dots underneath, missing medial `ـیـ` dots, broken letter joins, or distorted `ک`/`گ`/`پ`.
2. A thicker, fainter, missing, or uneven outline compared with the source, or reversed ink polarity.
3. Any change to adjacent Japanese kana/kanji or standalone numeric artwork (`⑮`, `00:00`, map pins).
4. A flat white wipe box, smeared halftone dots or speedlines, or English strokes left under the replacement.
5. Text outside the original footprint, lost tilt, or framing drift at the crop border.

**Retry rule**: tighten the texture, location anchor, or glyph anatomy description once. If a horizontal title or credit fails a second time, switch to Template 1 (clean-only restoration) and typeset it deterministically with bundled Vazir instead of repeating end-to-end model retries.
