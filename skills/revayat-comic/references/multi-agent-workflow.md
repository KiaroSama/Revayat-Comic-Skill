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
| **5a** | بازبینی خصمانهٔ تصویر | Adversarial Visual Recheck Agent (read-only) | `revayat-comic qa review-pack` (`flags.json` + 2x side-by-side crops) + full rendered pages + `qa check --strict` | Signed `work/review/ledger.tsv` with per-crop `PASS` or `FAIL` + exact defect codes |
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
4. On English-source editions (`source_language: en`), confirm every Japanese kana/kanji-only SFX (`ゴゴゴ`, `うわあああ`) is marked `keep` and never translated or erased.
5. Confirm every region has an explicit terminal decision, natural spoken Persian tone, and zero unresolved glossary conflicts.

Output: Approved, review-signed worksheets ready for Stage 4 execution.
```

---

## Stage 4 — Apply Translation (`اعمال ترجمه`)

**Objective:** Clean only uniform speech balloons first. Edit on-art lettering in wide context crops using `references/gemini-flash-prompting.md` (Variant C for stylized art/SFX, Variant D clean-only + Rust Vazir for horizontal titles/credits, pure Rust Vazir for flat multi-line pages such as tables of contents), paste approved edits into an isolated external PNG folder, then typeset every speech balloon deterministically in bundled Vazir (`Vazir-Medium` / `Vazir-Bold`).

### Prompt Template (Stage 4)

```text
Role: Stage 4 — Apply Translation Agent (اعمال ترجمه) for Revayat Comic.
Input files:
- Approved Stage 3 worksheets and `comic.json`
- Page-level edit manifests (`revayat-comic fullpage-prompt`)
- Gemini 3.1 Flash prompting guide (`references/gemini-flash-prompting.md`)

Instructions:
1. Merge approved worksheets (`revayat-comic worksheet merge`), run `revayat-comic falint fix`, and rebuild masks (`revayat-comic mask`) for the current source, language, geometry, and keep/erase decisions. Retain approved free-lettering mask options.
2. Empty ONLY clean speech bubbles first (`revayat-comic clean --bubbles-only`) so zero residual ink dots remain inside emptied bubbles while speedlines, screentones, and on-art lettering stay untouched.
3. For every page containing `fullpage_edit` regions (on-art SFX, speedline shouts, map labels, covers, spines, chapter titles):
   - Follow `references/gemini-flash-prompting.md` and `references/fullpage-image-edit.md`. Use Variant C (4-part narrative prompt with explicit freeze zones, texture vocabulary, ink + outline/halo color and pixel width, and positive Persian glyph anatomy) for stylized/tilted art; use Variant D (clean-only artwork restoration + Rust Vazir) for straight horizontal titles/credits; use pure Rust Vazir with 0 model calls for flat solid-color lists (such as a table of contents).
   - Never overwrite the external PNG folder with rendered output pages; keep `$EDITED` strictly separate from `work/rendered/`.
4. Run `revayat-comic typeset --external-dir <approved-png-directory>` to composite approved on-art edits via solid clipped masks and set every speech balloon deterministically in Vazir. If there are no external edits, omit `--external-dir`.

Output: Rendered full pages at the paths recorded in each page's `rendered` field in `<workdir>/comic.json`, ready for adversarial visual inspection.
```

---

## Stage 5a — Adversarial Visual Recheck (`بازبینی خصمانهٔ تصویر`, read-only)

**Objective:** Separate inspection from repair so confirmation bias cannot hide defects. Generate 2x pixel-doubled `[SOURCE | RENDERED]` crops with `revayat-comic qa review-pack`, inspect EVERY flagged crop and spot-check at full crispness, and record an explicit fail-closed verdict in `work/review/ledger.tsv`. Stage 5a is strictly read-only on pages and worksheets.

### Prompt Template (Stage 5a)

```text
Role: Stage 5a — Adversarial Visual Recheck Agent (read-only) for Revayat Comic.
You are FORBIDDEN from editing pages, masks, or worksheets. Your job is to find every defect that would embarrass a published print edition.

Input files:
- Run first: `revayat-comic qa check --strict --doc <workdir>/comic.json`
- Run second: `revayat-comic qa review-pack --doc <workdir>/comic.json`
- Manifest: `<workdir>/review/flags.json`
- Fresh review template: `<workdir>/review/ledger.template.tsv`
- 2x zoomed side-by-side `[SOURCE | RENDERED]` crops: `<workdir>/review/crops/*.png`
- Full rendered pages (for page-wide weight/tone consistency): `<workdir>/rendered/p*.png`

Mandatory 9-point inspection checklist on EVERY crop in `flags.json` (open each PNG with Read):
1. `SPECKLE_OR_NOISE`: any salt-and-pepper dots, ghost English strokes, or flat blurry gray patches over halftone/speedlines.
2. `MISSING_OUTLINE`: missing white/black outer halo or inverted ink polarity compared to the left (SOURCE) half.
3. `PERSIAN_GLYPH`: any dotted Arabic `ي` at word end, broken letter join, malformed `ک`/`گ`/`پ`/`ی`, or Persian digits where ASCII digits are required.
4. `TINY_OR_CRAMPED`: spacious speech bubble filled with tiny text (< 15 px), awkward unbroken hyphenated name, or severe centering/alignment drift (especially TOC/credits).
5. `BIDI_PUNCT`: wrong-side punctuation on numeric or mixed bubbles (e.g., `3.` instead of `.3` in Persian RTL, flipped `?!`, or detached `…`).
6. `OVERLAP_OR_CLIP`: text colliding with another bubble/on-art region, volume badge (`15`), or balloon outline.
7. `JAPANESE_DAMAGED`: on English-source editions, any erased, smudged, or modified Japanese hiragana/katakana/kanji SFX (`ゴゴゴ`, `うわあああ`).
8. `WEIGHT_OR_FONT_DRIFT`: sudden font family, thin/gray stroke, or weight jump between consecutive pages or inside speech bubbles.
9. `ERASED_RESIDUAL`: leftover dots or unchanged source ink inside an erased balloon.

Output: Copy the current `ledger.template.tsv` to `<workdir>/review/ledger.tsv` and fill its verdict, defect_codes and notes columns. Preserve the exact header (`page_id\tregion_id\tstage\tverdict\tdefect_codes\tnotes\treview_id`), IDs, stage=5a and review_id. Record an explicit `PASS` or `FAIL` for EVERY manifest item, including each page's `region_id=*` full-page row. Resolve crop_path relative to flags.json. Never mark PASS without opening that current image; never copy approvals from an older review_id.
```

---

## Stage 5b — Targeted Defect Repair (`اصلاح هدفمند مشکلات`)

**Objective:** Fix ONLY the `FAIL` items recorded by Stage 5a in `work/review/ledger.tsv`, re-run `clean`/`typeset`/`qa check --strict`/`qa review-pack`, and return the updated crops to Stage 5a for independent verification.

### Prompt Template (Stage 5b)

```text
Role: Stage 5b — Targeted Defect Repair Agent for Revayat Comic.
Input files:
- `<workdir>/review/ledger.tsv` (`FAIL` rows only)
- `<workdir>/comic.json` and `references/gemini-flash-prompting.md`

Instructions:
1. For each `FAIL` row, apply the root fix (regenerate the single on-art crop with Variant C/D, switch flat multi-line layouts to pure Rust Vazir, adjust worksheet wording/breaks, or fix masking/keep flags) without touching passing regions.
2. Re-run `revayat-comic typeset --doc <workdir>/comic.json [--external-dir ...]` and `revayat-comic qa check --strict --doc <workdir>/comic.json`.
3. Regenerate `<workdir>/review/` with `revayat-comic qa review-pack --doc <workdir>/comic.json`. Changed evidence creates a new review_id; the retained old ledger is reference material, not approval of the new images. Return the new template and all current manifest images to Stage 5a for independent `FIXED` / `PASS` verdicts. Only Stage 5a writes the approval rows. Legacy six-column ledgers must be replaced from the current template and reviewed once.
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
