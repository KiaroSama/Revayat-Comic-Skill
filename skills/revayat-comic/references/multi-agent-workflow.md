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
| **5** | چک مجدد فایل و اصلاح مشکلات | Visual Recheck & Defect Repair Agent | Every page's recorded `rendered` artifact + strict QA output for `comic.json` | Defect ledger + targeted repairs until zero leftover dots, overlaps, halos, or spacing bugs remain |
| **6** | بازبینی نهایی و تحویل | Final Review & Delivery Agent | Verified final pages + strict QA report | `qa package`, lossless CBZ + lossless PDF export, translation & QA log |

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
   - `typeset`: clean interior speech bubbles with uniform white/solid background -> emptied cleanly in `clean`, rendered with bundled Vazir TTF via pure-Rust `cosmic-text` RTL shaping.
   - `fullpage_edit`: on-art lettering over speedlines, screentones, character art, maps, covers, chapter titles, and stylized SFX -> routed to Stage 4's cropped editing workflow using the page-level manifest (`revayat-comic fullpage-prompt`).
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
4. Confirm every region has an explicit terminal decision and zero unresolved glossary conflicts.

Output: Approved, review-signed worksheets ready for Stage 4 execution.
```

---

## Stage 4 — Apply Translation (`اعمال ترجمه`)

**Objective:** Clean only uniform speech balloons first. Edit on-art lettering in wide context crops, paste only the approved, feathered edit back at its original coordinates, then typeset the balloons with the bundled Vazir fonts.

### Prompt Template (Stage 4)

```text
Role: Stage 4 — Apply Translation Agent (اعمال ترجمه) for Revayat Comic.
Input files:
- Approved Stage 3 worksheets and `comic.json`
- Page-level edit manifests (`revayat-comic fullpage-prompt`)

Instructions:
1. Merge approved worksheets (`revayat-comic worksheet merge`) and run `revayat-comic falint fix`.
2. Empty ONLY clean speech bubbles first (`revayat-comic clean --bubbles-only`) with interior speckle sweep so zero residual ink dots remain inside emptied bubbles while speedlines, screentones, and on-art lettering stay 100% untouched.
3. For every page containing `fullpage_edit` regions (on-art SFX, speedline shouts, map labels, covers, spines, chapter titles):
   - Follow `references/fullpage-image-edit.md` for crop sizing, the exact-text prompt, and paste-back. Give `antigravity/gemini-3.1-flash-image` 120-240 px of context beyond the full lettering effects. Ask it to remove the letters and their entire shadow, glow, and outline before drawing Persian at the source angle and weight.
   - Include the whole old and new lettering footprint in the paste mask and feather outside those effects. Keep standalone digits and sketch frames untouched. If a reviewer spots a seam, repair only that strip. Save each approved composite as `<page_id>.png` at the original page dimensions.
4. Run `revayat-comic typeset --external-dir <approved-png-directory>` to apply the approved on-art edits and set the speech balloons in Vazir. If there are no external edits, omit `--external-dir`.

Output: Rendered full pages at the paths recorded in each page's `rendered` field in `<workdir>/comic.json`, ready for visual inspection.
```

---

## Stage 5 — File Recheck & Defect Repair (`چک مجدد فایل و اصلاح مشکلات`)

**Objective:** Inspect EVERY single rendered page with your own eyes alongside strict automated QA, list every visual or textual defect, and fix them immediately before delivery.

### Prompt Template (Stage 5)

```text
Role: Stage 5 — Visual Recheck & Defect Repair Agent (چک مجدد فایل و اصلاح مشکلات) for Revayat Comic.
Input files:
- Rendered pages: each page's `rendered` path from <workdir>/comic.json
- Original pages: <workdir>/pages/pNNNN.*
- Strict QA output: `revayat-comic qa check --strict --doc <workdir>/comic.json`

Instructions:
1. Run `revayat-comic qa check --strict --doc <workdir>/comic.json` and inspect EVERY rendered page visually with the Read tool (side-by-side with the original whenever anything looks suspicious).
2. Actively hunt for these specific failure modes:
   - Leftover black dots, punctuation specks, or slivers inside cleaned bubbles.
   - Noisy black/white rectangular patches or dirty white halos over speedlines/screentones.
   - Broken line spacing (cramped or overlapping lines in maps/captions/bubbles).
   - Overlapping elements (e.g., volume circle colliding with title letters).
   - Misspelled Persian glyphs from image editing (e.g., extra maddas `آآآآ`, `آه` instead of `اِه`, disconnected letters, Persian digits instead of ASCII digits).
   - Unintended artwork distortion, missing panel edges, or untranslated English remnants.
3. Fix every defect immediately (revise the crop prompt and rerun only the affected zone or strip, adjust bubble line breaks/font size, or expand bubble interior sweep) and re-verify the repaired page visually until ZERO defects remain.

Output: Zero-defect verified final pages and a clean `qa check --strict` report (`errors: 0`).
```

---

## Stage 6 — Final Review & Delivery (`بازبینی نهایی و تحویل`)

**Objective:** Perform final chapter-wide editorial & package verification and deliver lossless CBZ, lossless PDF, and the translation/QA report.

### Prompt Template (Stage 6)

```text
Role: Stage 6 — Final Review & Delivery Agent (بازبینی نهایی و تحویل) for Revayat Comic.
Input files:
- Stage 5 verified pages at the `rendered` paths recorded in `<workdir>/comic.json`
- `<workdir>/comic.json`

Instructions:
1. Spot-check reading flow across consecutive pages (cover -> title/spine -> TOC -> chapter opener -> dialogue pages -> spreads) to confirm tone continuity, consistent names, and clean typography.
2. Export lossless CBZ and lossless PDF (`revayat-comic export --doc <workdir>/comic.json --out ...`).
3. Verify each finished archive with `revayat-comic qa package --doc <workdir>/comic.json --package <output>` and inspect its actual integrity findings for page count, page order, native dimensions, and changed or corrupt page data.
4. Write the final delivery log (`*.log.md`) recording source SHA-256, page count, region counts, QA status, and any honest notes on visual checks.

Output: Verified lossless CBZ, lossless PDF, and delivery report ready for the user.
```
