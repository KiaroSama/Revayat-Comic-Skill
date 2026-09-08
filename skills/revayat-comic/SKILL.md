---
name: revayat-comic
description: Translate manga, manhwa, manhua and Western comics into Persian and produce a finished CBZ, PDF or folder of pages. Detects panels, speech balloons and sound effects, reads them with your own eyes from rendered crops, removes the original lettering without altering the artwork, and typesets real right-to-left Persian into each balloon. Use for translating a manga chapter, a webtoon, a comic, a CBZ/CBR archive or a comic PDF into Persian (فارسی).
license: GPL-3.0-or-later
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task, Agent, AskUserQuestion
metadata: {"homepage":"https://github.com/KiaroSama/Revayat-Comic-Skill","requires":{"bins":["python3"],"pip":["pillow","numpy","opencv-python-headless","pymupdf","arabic-reshaper","python-bidi"],"optional":["rarfile","manga-ocr"]}}
---

# Revayat Comic — comics into Persian

Run the eleven steps below **in order**. Each is a command plus a rule for what
to do with its output. Do not improvise a different order, and do not skip a
step because the previous one looked fine.

Set three variables once, then use them everywhere:

- `SKILL_DIR` — the folder holding this file. In a Claude Code plugin it is
  `${CLAUDE_PLUGIN_ROOT}/skills/revayat-comic`.
- `WORK` — a working folder for this chapter, e.g. `work/`.
- `PY` — the Python interpreter. **Resolve it once**; `python3` does not exist
  on most Windows installations, so a command line that hard-codes it works on
  two platforms out of three:
  - macOS / Linux: `PY=python3`
  - Windows: `PY=python` — or `PY="py -3"` if the launcher is what is installed
  - if neither runs, `doctor` in step 1 will not start, and that is the signal

Every command is `$PY $SKILL_DIR/scripts/revayat-comic.py <stage> …`.

---

## The five rules that must never be broken

1. **Never reverse Persian text**, and never paste pre-shaped Persian into the
   worksheet. Write ordinary Persian in logical order. The renderer puts it on
   the page in the right direction; reversing it produces something that looks
   right in one viewer and is broken everywhere else.
2. **Never invent, drop, renumber or reorder a `@@` region id.** Return exactly
   the ids you were given. To say a region has no text in it, use `drop: yes` —
   that is what it is for.
3. **Never hand-edit `comic.json` to fix a translation.** Fix the worksheet and
   re-run merge. The one exception is the glossary table, which is edited there
   on purpose.
4. **Never replace a whole page with a regenerated one.** Only the pixels
   inside an authorised mask may change; `qa check` proves it, and a page that
   fails that check does not ship.
5. **Never shorten a balloon to make it fit.** If Persian overflows, the answer
   is a shorter *translation* that still says everything, not a summary and not
   six-point type.

---

## Step 1 — Check the tools

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py doctor
```

- `"ready": true` → continue.
- `"ready": false` → run `pip install -r $SKILL_DIR/requirements.txt`, then run
  `doctor` again.

Two fields in `persian` decide whether the output is correct rather than merely
present. Read them now, not after building a chapter:

| Field | Meaning | Action |
| --- | --- | --- |
| `"raqm": true` | Pillow shapes and reorders Persian itself, through HarfBuzz and FriBidi | nothing; this is the good path |
| `"raqm": false` | Persian will be pre-shaped by hand into presentation forms | works, and it is fixable: libraqm is in every Pillow wheel and needs a **FriBiDi** library at run time. Put `fribidi.dll` / `fribidi-0.dll` / `libfribidi-0.dll` on PATH (Windows) or install `libfribidi` (Linux/macOS) |
| `"font"` is a path | a Persian-capable font was found | nothing |
| `"font": null` | there is no font on this machine that can draw Persian | install Vazirmatn, then pass `--font` at step 9 |
| `"font_draws_persian": false` | the font was found but renders tofu | pick another; `--font` at step 9 |

## Step 2 — Import the chapter

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py import "<chapter.cbz>" --out $WORK \
  --source-language ja --direction rtl
```

`--direction` is how the **source** is read, not the target. Japanese manga is
`rtl`; Korean webtoons, Chinese manhua and Western comics are `ltr`. Getting it
wrong does not fail — it silently numbers the balloons backwards, and the
translation then answers questions that have not been asked yet.

Accepted input: CBZ, CBR, a comic PDF, a folder of images, or one image.

| What you see | What to do |
| --- | --- |
| `"pages": N` matching the chapter | continue |
| `webtoon_strips` is not empty | this is a webtoon; use `--direction ltr` and expect one long column per file |
| an error naming `rarfile` or `unrar` | CBR needs an unrar binary; convert to CBZ instead if that is easier |

The original pages are copied to `$WORK/pages/` and hashed. **Nothing in the
pipeline ever writes to them.** Every later stage writes a new file.

## Step 3 — Find the text

Three commands, always run together:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py detect --doc $WORK/comic.json
$PY $SKILL_DIR/scripts/revayat-comic.py mask   --doc $WORK/comic.json
$PY $SKILL_DIR/scripts/revayat-comic.py crops  --doc $WORK/comic.json
```

| What you see | What to do |
| --- | --- |
| `totals.speech` in the right region of plausible | continue |
| `pages_without_text` covering many pages | the thresholds do not fit this book — see `references/detection.md` |
| a `warning` about excessive coverage | the mask matched artwork, not lettering; fix it before cleaning |

`detect` finds balloons well and free-floating sound effects badly. That is
expected and it is why step 5 exists: you will see the page and can correct it.

## Step 4 — Worksheets

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py worksheet build --doc $WORK/comic.json
```

One worksheet per page in `$WORK/worksheets/pNNNN.txt`.

If this refuses with `"refused": "stale-worksheets"`, regions moved after some
pages were already translated, so their ids no longer point at the same
balloons. Re-translate those pages, or pass `--force` once you have decided the
regions did not really move.

## Step 5 — Read the page and translate it

**This is the step that makes the result good, and it is yours, not a
script's.** For each `$WORK/worksheets/pNNNN.txt`, write
`$WORK/worksheets/pNNNN.done.txt`.

Use a separate sub-agent per page when your runtime has them, 6 at a time. If
it does not, do them one at a time — the result is the same, only slower.

**Give the sub-agent exactly this:**

> Read `$WORK/worksheets/pNNNN.txt` and write `$WORK/worksheets/pNNNN.done.txt`.
>
> **Look at both images the worksheet names before you write anything.** Use the
> Read tool on each:
> - `crops/pNNNN/overview.png` — the whole page with every region numbered in
>   reading order. This is your context: who is speaking, what they are looking
>   at, which balloon answers which.
> - `crops/pNNNN/sheet*.png` — the crops themselves, enlarged and labelled with
>   the region ids.
>
> Read `$SKILL_DIR/references/translation-policy.md` first and follow it.
>
> Output format — this is mechanical, get it exactly right:
> - Copy each `@@ <id> …` line **unchanged**, in the same order.
> - Under it, `src:` is what the balloon says in the original, and `fa:` is the
>   Persian.
> - A field continues on the following lines until the next field or the next
>   `@@`. Output nothing else: no preamble, no commentary, no summary.
>
> Rules:
> - The names table at the top of the worksheet is binding. Use exactly the
>   Persian it gives.
> - Translate what the character is *saying*, in the register they are saying it
>   in. A shout is short and blunt; a thought is quieter. Match the art.
> - Persian runs longer than Japanese. Keep balloons tight — this is dialogue in
>   a small space, not prose.
> - Never summarise, never skip a balloon, never merge two.
> - If a crop shows the detector was wrong, correct it:
>   - `drop: yes` when there is no text there at all
>   - `keep: yes` when there **is** text and it should stay in the artwork — a
>     background shop sign, a logo, an effect you do not want replaced. Do not
>     reach for `drop` here: it means "no text", and using it makes the terminal
>     census count real lettering as a false detection. `kind:`, `speaker:` and
>     `note:` still apply beside it, and a `keep` counts as a review: it locks
>     the region, so a later `detect` run leaves the decision alone.
>   - `kind: sfx` / `sign` / `narration` / `thought` when it is misclassified
>   - `speaker: <short stable name>` — the same name every time, on every page
> - **Check every crop for two balloons in one box.** This is the commonest way
>   the page loses text, it happens several times a volume, and the detector
>   cannot see it — four different measurements were tried and none separates a
>   touching pair from one balloon with a tail. **You can see it instantly**: the
>   crop shows two outlines and two blocks of text. When it does, `drop: yes` the
>   region and add each balloon back with its own `box:`.
> - **If the overview shows text with no region on it, add one.** Free lettering
>   is the weak case, and a whole panel is occasionally taken for a balloon and
>   swallows what is drawn inside it — so a full worksheet is not the same as a
>   full page.
>
>   ```
>   @@ +bump sfx horizontal
>   box: 742 436 58 24
>   src: BUMP
>   fa: تلپ
>   ```
>
>   `box:` is `x y w h` in the page's own pixels, which is what `overview.png`
>   is drawn at, so read the numbers straight off it. Add `polarity: dark` for
>   white lettering on black. Merging allocates the real region id.

Check what is left at any time:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py worksheet status --doc $WORK/comic.json
```

## Step 6 — Merge

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py worksheet merge --doc $WORK/comic.json
```

| Field | Meaning | Action |
| --- | --- | --- |
| `"ok": true` | everything landed | continue |
| `missing_outputs` | those pages were never translated | translate them |
| `missing_regions` | ids were dropped from a worksheet | re-do those pages |
| `unknown_regions` | ids were invented | re-do those pages |
| `duplicate_regions` | an id appears twice | re-do that page |
| `empty_translation` | a region has `src:` but no `fa:` | fill it in, or `drop: yes` |
| `stale_worksheets` | regions changed after translation | re-do those pages |

Re-running merge after a fix is always safe.

## Step 7 — Names and typography

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py glossary scan --doc $WORK/comic.json
```

Open `$WORK/comic.json` and, for each entry under `glossary.entries` that has an
empty `target`, fill in the Persian and set `"locked": true`. This is the one
hand-edit that *is* expected. Names decided once here stay consistent for the
rest of the chapter, and every later worksheet prints the table.

Then the mechanical Persian pass — safe to run twice:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py falint fix --doc $WORK/comic.json
```

Add `--digits keep` if the comic must keep Latin numerals.

## Step 8 — Clean the artwork

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py clean --doc $WORK/comic.json
```

| Field | Meaning |
| --- | --- |
| `totals.flat` | balloons repainted in their own colour — the good case |
| `totals.inpaint` | lettering that sat on artwork and had to be reconstructed |
| `totals.keep` | sound effects deliberately left in the drawing |
| `inpaint_heavy_pages` | look at these; Telea smooths, it does not redraw |

To use a better cleaner than this ships with, clean the pages elsewhere and
pass the folder: `--external cleaned/`, named `pNNNN.png`. **Only the masked
pixels of those images are used**, so even a generative model that redrew half
the page cannot change artwork it was not asked to touch.

For lettering drawn **onto the artwork**, give the model the whole patch rather
than the letter shapes — clipped back to strokes a few pixels wide, even a good
reconstruction reads as repaired rather than redrawn:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py mask  --doc $WORK/comic.json --free-lettering solid
$PY $SKILL_DIR/scripts/revayat-comic.py clean --doc $WORK/comic.json --external reconstructed/
```

Balloons ignore the flag. `clean` **refuses** solid masks without `--external`,
because painting one flat or inpainting it blanks a rectangle out of the drawing.
See `references/artwork-preservation.md`.

## Step 9 — Set the Persian

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py typeset --doc $WORK/comic.json \
  --font "Vazirmatn-Medium.ttf"
```

`--font` is optional; without it the best Persian face on the machine is used.

| Field | Meaning | Action |
| --- | --- | --- |
| `"shaping": "raqm"` | correct shaping and direction | nothing |
| `"shaping": "reshaper"` | the fallback ran | works; mention it in the report |
| `overflow` is empty | everything fitted | continue |
| `overflow` lists regions | those translations are too long | shorten them in the worksheet, re-run merge, falint and typeset |

`--min-size` is a floor, not a suggestion. It will not go below it silently.

## Step 10 — Gate

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py qa check --doc $WORK/comic.json
```

**Do not export while `"ok"` is false.** Fix by code:

| Code | Meaning | Action |
| --- | --- | --- |
| `artwork-modified` | pixels changed outside the authorised mask | do not ship; re-run clean and typeset for that page |
| `source-text-survived` | the mask missed part of the lettering, so the original script is still on the cleaned page | re-run `mask` with a larger `--grow` for that page, then `clean` |
| `source-modified` | an original page file was edited after import | restore it, or re-import |
| `page-missing` / `page-size-changed` | an output is gone or resized | re-run the stage that makes it |
| `untranslated-region` | a region has no Persian | translate it, or `drop: yes` |
| `source-script-left` | Japanese, Korean or Chinese survives inside the Persian | re-do that region |
| `not-persian` | the target text is not Persian at all | re-do that region |
| `text-overflow` | it does not fit at the minimum size | shorten the translation |
| `reading-order-broken` | the numbering is not `1..n` | re-run detect for that page |
| `mask-excessive` (warning) | more than 28% of a page would be repainted | tighten detection |
| `duplicate-translation` (warning) | different sources, identical Persian | a reply was pasted twice; re-do both |
| `low-confidence-region` (warning) | the detector guessed and nobody checked | look at the crop |
| `glossary-drift` (warning) | a locked name was rendered differently | re-do that region |
| `typography` (warning) | Arabic letter forms, Latin quotes, stray punctuation | run `falint fix` |
| `sfx-untranslated` (warning) | a sound effect was left drawn | expected under the `keep` policy |
| `visual-note` (advice) | a model's opinion from the optional `qa visual` pass | read it and decide; it never passes or fails a run |

Add `--strict` to make warnings blocking, for publication work.

**Read `stats.states` as well as `ok`.** Every detected region lands in exactly
one terminal state, and there is deliberately no state meaning "it quietly
disappeared":

| State | Meaning |
| --- | --- |
| `translated` | carries Persian |
| `kept_by_policy` | left as drawn on purpose — a sound effect under `keep` |
| `dropped_false_detection` | you said there is no text there |
| `needs_review` | seen but unresolved: overflowing, or a doubt you noted |
| `unresolved` | **must be zero** — detected and then forgotten |

`unresolved` is not its own error — every region in it is already blocked by
`untranslated-region`, and two codes on the same rows is noise. The census is
there to be *read*: the other four are all decisions, so report the counts to
the user rather than only the total.

## Step 11 — Export and report

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py export --doc $WORK/comic.json \
  --out out/chapter-fa.cbz
$PY $SKILL_DIR/scripts/revayat-comic.py qa package --doc $WORK/comic.json \
  --file out/chapter-fa.cbz
```

`--out` decides the format: `.cbz`, `.pdf`, or a folder.

**Do not tell the user the file is ready while `qa package` reports
`"ok": false`.**

| Code | Meaning | Action |
| --- | --- | --- |
| `archive-invalid` | the package will not open, or its page names do not sort into reading order | re-run export |
| `archive-page-count` | the package has a different number of pages from the document | re-run export; if it repeats, a page failed to write |

Then report: where the file is, how many pages and balloons, which sound-effect
policy was used, whether shaping used RAQM or the fallback, anything QA flagged
that you chose not to act on, and this limitation —

> Sound effects drawn into the artwork are kept as drawn unless you asked for
> them to be replaced. Redrawing hand-lettered art is a lettering job, not a
> translation job, and doing it badly damages the page.

---

## Sound effects

Set the policy before step 8, in `comic.json` under `meta.sfx_policy`:

| Policy | Behaviour | When |
| --- | --- | --- |
| `keep` | the original stays, untouched | the default, and right for most chapters |
| `translate` | the original is removed and Persian is set in its place | clean, simple lettering |
| `bilingual` | the original stays and a small Persian gloss is added | reference and study editions |
| `annotate` | the artwork is untouched and the meaning is noted beside it | busy pages |

If an SFX reading is uncertain, prefer `keep`. Erasing hand-drawn lettering to
replace it with a guess is worse than leaving it.

---

## References

Read these only when the step points at them:

- `references/translation-policy.md` — what to give the translating sub-agent
- `references/persian-typesetting.md` — RTL, shaping, fonts, fitting a balloon
- `references/detection.md` — thresholds, difficult pages, correcting a region
- `references/artwork-preservation.md` — masks, cleaning tiers, what QA proves
- `references/sound-effects.md` — the four policies and how to choose
- `references/ocr.md` — reading with your own eyes, and when a model helps
- `references/troubleshooting.md` — the failures you are most likely to hit
