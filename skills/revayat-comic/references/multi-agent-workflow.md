# Six-Stage Multi-Agent Comic Translation Workflow

Every chapter translation runs through **six distinct, specialized agent roles** in order. Separating translation, layout, bilingual review, execution, visual recheck, and final sign-off prevents one busy pass from rushing Persian tone, missing on-art sound effects, or overlooking visual defects.

## Story Continuity Memory

Every chapter or book has a running `work/story.md` (or `<workdir>/story.md`).
Each translation worker and shard reads it before drafting, then records their
page beats, current scene, speakers and listeners, relationships, honorifics,
emotional register, and any open cross-bubble or cross-page sentences. Follow
[the translation policy](translation-policy.md#story-continuity-memory) for the
handoff fields. Workers can record their updates privately while drafting; the
coordinator schedules shared writes one worker at a time in page order. A shard
that needs an unresolved handoff waits for the prior shard's update.

## Stage Overview

| Stage | Persian Title | Role | Primary Input | Required Output |
| --- | --- | --- | --- | --- |
| **1** | ترجمه اولیه | Initial Translation Agent | Full page images, crop sheets, OCR/worksheet stubs, chapter glossary, `story.md` | Draft worksheets (`pNNNN.done.txt`), `story.md` updates, glossary proposals |
| **2** | صفحه آرایی | Layout & Typesetting Planner Agent | Draft worksheets + full page images + bubble/region geometry | Line-broken, spaced worksheets + routing tag (`typeset` vs `fullpage_edit`) per region |
| **3** | بازبینی | Bilingual & Tone Review Agent | Original full pages + draft/planned worksheets + Persian voice guide | Reviewed, natural spoken-Persian worksheets with zero AI tells and verified meaning |
| **4** | اعمال ترجمه | Apply Translation Agent | Approved worksheets + `comic.json` | Emptied clean speech bubbles + approved crop edits pasted back in place + Vazir RTL typeset pages |
| **5a** | بازبینی خصمانهٔ تصویر | Adversarial Visual Recheck Agent (read-only) | Strict QA, every full-page comparison, and every 2x review crop | `work/review/ledger.tsv` with each page and crop verdict and exact defect codes |
| **5b** | اصلاح هدفمند مشکلات | Defect Repair Agent | `work/review/ledger.tsv` `FAIL` rows only | Targeted code/worksheet/crop fixes + regenerated `review-pack` handed back to Stage 5a until 0 `FAIL` rows remain |
| **6** | بازبینی نهایی و تحویل | Final Review & Delivery Agent | Verified final pages + `qa check --strict` + `qa review-pack --verify-ledger` | `qa package`, lossless CBZ + lossless PDF export, translation & QA log |

---

## Stage 1 — Initial Translation (`ترجمه اولیه`)

**Objective:** Read the actual page images and crop sheets with your own eyes, verify character names/terms against official sources, and draft natural, expressive Persian dialogue that sounds like real spoken Persian — never stiff machine translation or bookish officialese.

### Prompt Template (Stage 1)

```text
Role: Stage 1 — Initial Translation Agent (ترجمه اولیه) for Revayat Comic.
Input files:
- Full original pages: <workdir>/pages/pNNNN.*
- Crop sheets and overview: <workdir>/crops/overview.png, <workdir>/crops/sheet*.png
- Pending worksheets: <workdir>/worksheets/pNNNN.txt
- Story Continuity Memory: <workdir>/story.md (read before drafting)
- Glossary: the `glossary` field in <workdir>/comic.json
- Persian voice rules: skills/revayat-comic/references/voice/persian/SKILL.md

Instructions:
1. Inspect EVERY full page image and crop sheet visually before translating a single line. Never guess dialogue from OCR alone.
2. Check character names, honorifics, titles, and recurring terms in comic.json's glossary (and confirm canonical spellings once per series). Keep names and pronouns consistent across the entire chapter.
3. Translate into living, spoken Persian matched to each speaker's personality, age, emotion, and relationship:
   - Use natural colloquial spoken Persian for casual/emotional speech (e.g., «می‌رم»، «بگو ببینم»، «ای بابا»، «داره دیر می‌شه») and appropriate formal register only for formal characters, narrators, or official announcements.
   - Avoid literal English calques, passive «... شد» when active impersonal plural fits, stiff «می‌باشد / دارای / توسط / یک ... خوب», and AI-sounding phrasing.
   - Translate sound effects (SFX) and exclamations idiomatically (e.g., "MM-HMM" -> «آره، آره.» or «اوهوم، اوهوم.»; "TCH!" -> «اِه!» or «چِق!»; "UWAAAAH!" -> «آااااه!» with madda ONLY on the first alef).
   - Never soften, omit, or censor meaning.
4. Preserve every stable region ID (`@@ pNNNNrNNN`) and assign an explicit terminal action (`fa:`, `keep`, `drop`, `erase`).
5. Write ASCII digits (0-9) in dialogue, titles, captions, and translated on-art text. Mark standalone numeric art (volume 15, map pins 1-8, watch 00:00) keep and exclude it from edit masks. Record the source angle and weight of handwritten or tilted sketch lettering and preserve hand-drawn frames.
6. Update story.md with the page or shard beats and open continuations in the assigned write slot. Keep Japanese honorifics in Persian script and read connected balloons aloud together.

Output: Draft worksheets (pNNNN.done.txt), story.md updates, and glossary proposals for the coordinator.
```

---

## Stage 2 — Layout & Typesetting Planning (`صفحه آرایی`)

**Objective:** Shape every translated string to physically fit its bubble or artwork zone, enforce clean line breaks, generous line spacing, proper RTL punctuation, and decide which regions use deterministic Vazir typesetting or cropped on-art editing.

### Prompt Template (Stage 2)

```text
Role: Stage 2 — Layout & Typesetting Planner Agent (صفحه آرایی) for Revayat Comic.
Input files:
- Original full pages: <workdir>/pages/pNNNN.*
- Stage 1 draft worksheets: <workdir>/worksheets/pNNNN.done.txt
- Region geometry: <workdir>/comic.json

Instructions:
1. Inspect every region's shape and width on the full page:
   - Narrow/vertical speech bubbles: break lines explicitly so words never squeeze into cramped 1-word overhangs and trailing punctuation («.», «،», «؟!», «…») never clips or detaches.
   - Map labels, diagram callouts, and stacked captions: balance line lengths evenly and specify generous vertical line spacing (line-height >= 1.38x font size) so Persian dots/ascenders never collide between lines.
   - Cover titles, volume number circles, and spine badges: leave the original volume badge (e.g., `15`) in place and check clearance so the Persian title never overlaps it (e.g., «سِکیری»).
2. Classify EVERY active region into exactly one rendering route:
   - `typeset`: speech balloons, flat titles and lists, slanted caption boxes, and crisp SFX Rust can match. Keep the speech-balloon size cap separate from the size of captions and SFX.
   - `fullpage_edit`: on-art lettering whose background or hand-drawn shape needs a cropped edit. Use Stage 4's `revayat-comic fullpage-prompt` manifest.
3. Verify ASCII digits (`0-9`) and Persian mechanics: proper ZWNJ (`می‌`, `نمی‌`, `‌ها`, `‌ترین`), Persian punctuation (`،`, `؛`, `؟`), and `RLI`/`PDI` isolation for mixed Latin/Persian lines (e.g., `MBI`).

Output: Layout-planned worksheets and per-page `fullpage_edit` region manifests.
```

---

## Stage 3 — Bilingual & Tone Review (`بازبینی`)

**Objective:** Independently audit meaning fidelity, natural Persian comic tone, terminology consistency, and mechanics before a single pixel is rendered.

### Prompt Template (Stage 3)

```text
Role: Stage 3 — Bilingual & Tone Review Agent (بازبینی) for Revayat Comic.
Input files:
- Original full pages: <workdir>/pages/pNNNN.*
- Stage 2 worksheets: <workdir>/worksheets/pNNNN.done.txt
- Glossary: the `glossary` field in <workdir>/comic.json

Instructions:
1. Perform a line-by-line bilingual read against the original pages:
   - Catch any mistranslation, dropped nuance, swapped speaker, wrong number, or awkward punctuation (e.g., English `...` flipped to the wrong side, `?!` turned into `?`, or wrong madda like `آآآآه!` instead of `آااااه!`).
2. Read every Persian line aloud mentally:
   - Rewrite any stiff, robotic, overly formal, or translationese line into natural spoken Persian that fits the character's voice and emotional beat.
   - Check comedic timing, shouts, whispers, and hesitation markers so dialogue feels like a real Persian manga edition.
3. Run `revayat-comic voice lint <draft.md> --check --style` on each Persian draft; after merging accepted worksheets, run `revayat-comic falint check --doc <workdir>/comic.json`. Resolve mechanical and style findings against the source.
4. On English-source editions (`source_language: en`), confirm every Japanese kana/kanji-only SFX (`ゴゴゴ`, `うわあああ`) is marked `keep` and never translated or erased.
5. Confirm every region has an explicit terminal decision, natural spoken Persian tone, and zero unresolved glossary conflicts.

Output: Approved, review-signed worksheets ready for Stage 4 execution.
```

---

## Stage 4 — Apply Translation (`اعمال ترجمه`)

Clean and typeset speech balloons in bundled Vazir. Use the halftone-preserving cleanup and Rust lettering when they match the source. Where artwork needs a model edit, work on one wide-context crop at a time and keep approved composites in a separate PNG folder.

### Prompt Template (Stage 4)

```text
Role: Stage 4 — Apply Translation Agent (اعمال ترجمه) for Revayat Comic.
Input files:
- Approved Stage 3 worksheets and `comic.json`
- Page-level edit manifests (`revayat-comic fullpage-prompt`)
- Gemini 3.1 Flash prompting guide (`references/gemini-flash-prompting.md`)

Instructions:
1. Merge approved worksheets (`revayat-comic worksheet merge`), run `revayat-comic falint fix`, and rebuild masks (`revayat-comic mask`) for the current source, language, geometry, and keep/erase decisions. Retain approved free-lettering mask options.
2. Use `revayat-comic clean` for deterministic lettering, including masked halftone cleanup where needed. Use `clean --bubbles-only` when preparing a page for cropped on-art edits; it leaves the on-art lettering in place for the crop.
3. For each `fullpage_edit` region, follow `references/fullpage-image-edit.md` and `references/gemini-flash-prompting.md`. Measure the original outline. Keep circled badges and adjacent Japanese kana outside the edit and paste masks. For Variant D, route the approved clean-only PNG through `revayat-comic clean --external-dir <approved-clean-png-directory>` without `--bubbles-only`; keep those PNGs separate from Variant C composites and `work/rendered/`.
4. Run `revayat-comic typeset` without `--external-dir` for clean-only Variant D pages. Use `typeset --external-dir <approved-lettered-png-directory>` only for Variant C pages whose composites already have the approved Persian lettering. Rust sets the ordinary speech balloons in Vazir in both cases.

Output: Rendered full pages at the paths recorded in each page's `rendered` field in `<workdir>/comic.json`, ready for adversarial visual inspection.
```

---

## Stage 5a — Adversarial Visual Recheck (`بازبینی خصمانهٔ تصویر`, read-only)

Stage 5a checks the current evidence and writes `work/review/ledger.tsv`. The reviewer does not edit pages, masks, or worksheets.

### Prompt Template (Stage 5a)

```text
Role: Stage 5a, read-only adversarial visual reviewer.
Run `revayat-comic qa check --strict --doc <workdir>/comic.json`, then `revayat-comic qa review-pack --doc <workdir>/comic.json`. Read `<workdir>/review/flags.json` and resolve each crop_path relative to that file.

Open both sets of images with Read:
1. Every full-page [SOURCE | RENDERED] comparison: use the manifest row with `region_id=*` for each page. The CLI currently writes `crops/<page_id>-page-*.png`; if the manifest lists `pages/<page_id>-compare-*.png`, open that path. Scan top left, top right, bottom left, bottom right, then the margins, gutters, and SFX layers. Look for `UNTRANSLATED_TEXT`, `ERASED_GRAPHIC`, `FONT_MISMATCH`, and `UNDERSIZED_BALLOON`. Compare consecutive pages for weight and family drift. The full-page scan must include text with no region ID and text from dropped regions.
2. Every flagged region crop at 2x (`crops/*.png`). Compare the source and rendered halves using all seven checks below. Cover every high-risk area, on-art edit, title, and SFX. If the manifest omits a crop you need for that coverage, inspect matching 2x crops from the source and rendered pages. Record any finding on the page's `region_id=*` row without adding unofficial ledger rows.

Defect codes:
1. `UNTRANSLATED_TEXT`: English or other source text meant for translation still visible anywhere. Check for tiny `RUMBLE`, `FLASH`, or `STEP` beside Japanese kana or panel borders, including regions mistakenly marked `drop`. Intentionally kept artwork is not a translation omission.
2. `OUTLINE_MISMATCH`: The replacement has a thick white sticker halo where the source credit or chapter title had a faint edge, or it lacks the source's crisp white or black outline over textured SFX. Compare thickness, opacity, and polarity.
3. `FONT_MISMATCH`: A font family or weight jumps between comparable regions or pages, such as heavy bold on a light title or table of contents.
4. `ERASED_GRAPHIC`: A circled volume number (`⑮`), panel border, speedline, or adjacent Japanese SFX stroke was erased, smudged, or redrawn.
5. `UNDERSIZED_BALLOON`: Text floats in a roomy speech balloon with far more empty space than in the original. Compare the lettering to the usable balloon interior.
6. `HALFTONE_SMEAR`: A flat white rectangle or blurry patch wipes out halftone or screentone dots behind an SFX.
7. `MISSING_TILT`: Text sits at 0° in a deliberately slanted caption box or over slanted source SFX where the matching `extra.angle` is needed.

Also reject malformed Persian (`PERSIAN_GLYPH`), misplaced RTL punctuation (`BIDI_PUNCT`), crowding or poorly broken lines (`TINY_OR_CRAMPED`), clipping or collisions (`OVERLAP_OR_CLIP`), and stray or residual ink (`SPECKLE_OR_NOISE` or `ERASED_RESIDUAL`).

Start from the current `ledger.template.tsv`. Preserve the exact header (`page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes\treview_id`), IDs, `stage=5a`, and `review_id`. Write an explicit `PASS` or `FAIL` on every row. A visible defect defaults to `FAIL`; record every applicable code in `defect_codes` and name the location and evidence in `notes`. Leave unreadable or missing evidence unresolved until it is replaced. A clean strict QA result or a previous approval is not a reason to mark `PASS`. Open every current image yourself; never carry approvals across a changed `review_id`.
```

---

## Stage 5b — Targeted Defect Repair (`اصلاح هدفمند مشکلات`)

Fix only the defects Stage 5a recorded. Rebuild from the first affected stage so the reviewer sees the repair on the current rendered page.

### Prompt Template (Stage 5b)

```text
Role: Stage 5b, targeted defect repairer.
Read the FAIL rows in `<workdir>/review/ledger.tsv` and the corresponding regions in `<workdir>/comic.json`. Fix the cause without changing passing regions. Correct the worksheet, route a fitting or tilt change to Rust, or repair one approved on-art crop using `references/gemini-flash-prompting.md`.

Run these stages in order, each against `--doc <workdir>/comic.json`:
- If a repair changes masking, `keep`/`drop`/`translate` or `erase` decisions, geometry, `source_text`, or source language: `mask` -> `clean` -> `typeset` -> `qa check --strict`. Retain approved mask options, and rebuild approved external crops from the fresh cleaned page where needed.
- If the repair changes a clean-only Variant D PNG within the same mask: `clean --external-dir <approved-clean-png-directory>` -> `typeset` without `--external-dir` -> `qa check --strict`.
- If the repair changes only target text, style, outline, angle, or a lettered Variant C composite within the same mask: `typeset` -> `qa check --strict`. Pass `--external-dir` to `typeset` only for approved composites that already contain the lettering.

When strict QA passes, run `revayat-comic qa review-pack --doc <workdir>/comic.json`. Return the new template and every current page comparison and crop to Stage 5a. Changed evidence creates a new `review_id`; the old ledger is reference only. Only Stage 5a can approve the new evidence. Replace any legacy six-column ledger with the current template and review all its rows.
```

---

## Stage 6 — Final Review & Delivery (`بازبینی نهایی و تحویل`)

**Objective:** Enforce both automated strict QA and the fail-closed Stage 5a review ledger, verify consecutive-page visual consistency, and deliver lossless CBZ, lossless PDF, and the translation/QA report.

### Prompt Template (Stage 6)

```text
Role: Stage 6 — Final Review & Delivery Agent (بازبینی نهایی و تحویل) for Revayat Comic.
Input files:
- Stage 5 verified pages at the `rendered` paths recorded in `<workdir>/comic.json`
- `<workdir>/comic.json` and `<workdir>/review/ledger.tsv`

Instructions:
1. Run `revayat-comic qa check --strict --doc <workdir>/comic.json` and `revayat-comic qa review-pack --doc <workdir>/comic.json --verify-ledger`. Do NOT export if either command exits non-zero.
2. Spot-check consecutive pages (cover -> title/spine -> TOC -> chapter opener -> early/mid/late dialogue pages) to confirm uniform Vazir-Medium speech weight, natural Persian tone, and zero leftover defects.
3. Export lossless CBZ and lossless PDF (`revayat-comic export --doc <workdir>/comic.json --out ...`).
4. Verify each finished archive with `revayat-comic qa package --doc <workdir>/comic.json --package <output>` and inspect page count, page order, native dimensions, and integrity findings.
5. Write the final delivery log (`*.log.md`) recording source SHA-256, page count, region counts, `qa check --strict`, `qa review-pack --verify-ledger`, and `qa package` results.

Output: Verified lossless CBZ, lossless PDF, and delivery report ready for the user.
```
