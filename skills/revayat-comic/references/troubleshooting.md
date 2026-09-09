# Troubleshooting

The failures you are most likely to hit, in the order they happen.

## `doctor` says `"ready": false`

Read the `required` block. A `MISSING` line names the package and what it is
for.

```bash
pip install -r $SKILL_DIR/requirements.txt
```

If `persian.font` is `null`, no font on this machine can draw Persian. Install
Vazirmatn from https://github.com/rastikerdar/vazirmatn/releases and pass it at
step 9 with `--font`.

If `persian.shaping_error` appears, there is neither RAQM nor the fallback:

```bash
pip install arabic-reshaper python-bidi
```

## `"raqm": false` — is this broken?

No — and it is fixable, which this page used to deny. Pillow carries libraqm on
every platform; what is missing is **FriBiDi**, which libraqm loads at run time.
Put `fribidi.dll`, `fribidi-0.dll` or `libfribidi-0.dll` on `PATH` and `doctor`
reports `"raqm": true` on the next run. It must be a directory in the DLL search
order — beside `python.exe` does not work.

Without it the fallback runs, the pages are correct to read, and `doctor` says
so. See `persian-typesetting.md` for what differs between the two paths.

## Import

| Symptom | Cause | Fix |
| --- | --- | --- |
| `no images` | the CBZ holds something else | check it opens in a comic reader |
| an error naming `rarfile` | CBR support is optional | `pip install rarfile`, and install an unrar binary — or convert to CBZ |
| an error naming `unrar` | rarfile is installed but has no backend | Linux/macOS: install `unrar` or `libarchive-tools`; Windows: install WinRAR |
| pages in the wrong order | rare; the archive uses a naming scheme nothing can sort | extract to a folder, rename `0001.png`… and import the folder |
| `webtoon_strips` is not empty | this is a webtoon | `--direction ltr` |
| PDF import is slow | pages are being rendered, not extracted | expected when a page is not one embedded image |
| an error naming a page count, a GB total, an MB entry or megapixels | the import guards — 2000 pages, 2 GB, 512 MB an entry, 80 MP a page | split a series into volumes, or lower `--dpi` for a PDF whose page rectangle is huge |

## Providers (optional, off by default)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `no <role> provider named 'x'` | the name is not registered | the error lists what is; a provider is registered by importing the module that calls `providers.register` |
| `--provider` was set and `provider_calls` is empty | every region was repaired exactly by the deterministic tiers | working as intended — an all-flat page costs no model call; check `totals.inpaint` if you expected escalation |
| `clean` ran but `provider_calls` says `fell_back` | the model errored, timed out, refused or returned the wrong size | the reason is in the same record; the classical cleaners ran instead and the page is complete |
| `ocr` wrote nothing | every reading was below `--min-confidence` (0.65) | look at the crops; a low-confidence reading is deliberately never written |
| `ocr` reports disagreements | the engine read a **locked** region differently | not an error: the committed value was kept and the reading recorded beside it |
| an OCR adapter's `orientation` argument is never set | the stage passes it only to a method whose signature names it, and a C callable or an un-introspectable wrapper is declined | name `orientation` (or `**kwargs`) directly on `read`; `stages.ocr.orientation_aware` in `comic.json` says which way it went |
| `qa visual` findings look wrong | they are a model's opinions | they are advisory and never gate; `qa check` is the gate |
| `context` refused: pages are translated but not merged | an earlier page’s `.done.txt` has not reached `comic.json`, so its Persian would be missing from this package | run `worksheet merge`, then build the context again; `--allow-unmerged` overrides and lists what is missing |
| a sound effect’s outline looks too heavy or too light | it is matched to the weight the original was drawn at, clamped by `MIN_STROKE`/`MAX_STROKE` | `typeset.stroke` on the region records what was measured; `--flat-sfx` opts out of matching entirely |
| `translate` skipped everything | the regions already have Persian, or no `src:` yet | it fills empty regions only; a value already there is never replaced |
| `translate`/`ocr` re-run did nothing | that work is recorded as complete | by design — rerunning costs no calls; edit the text to have it looked at again |

## Detection

| Symptom | Fix |
| --- | --- |
| `pages_without_text` on most pages | thresholds do not fit this book — see `detection.md` |
| whole panels detected as balloons | lower `--balloon-max-area`, or `drop: yes` the region and add the real balloons back with `box:` — see `detection.md` |
| two balloons come back as one region | the same fix: drop it, add each one back with `box:` |
| text on the page with no region on it | add it: `@@ +<name>` with `box: x y w h` |
| balloons missed | raise `--ink-max`, lower `--balloon-min-solidity` |
| dozens of low-confidence regions | `--no-sfx`, then `drop: yes` on what is left |
| `reading-order-broken` at QA | a region has no reading order, or two share one. **Not** caused by `drop: yes` — dropping leaves a gap and that is fine |

Detection never runs on a page whose regions have been answered. If you *want*
to re-detect a page after translating it, clear `locked` on its regions — and
accept that its worksheet is then stale.

## Masks

`excessive_coverage` means a mask would repaint more than 28% of a page. Almost
always a detection problem, not a mask problem: a region matched artwork rather
than lettering. Fix the detection, or `drop: yes` the region, before cleaning.

Growing the mask cannot cause this on a balloon — a balloon's mask is clipped to
the balloon and cannot spread past it.

`clean` refusing with *"the masks for this document were built with
`mask --free-lettering solid`"* is not a fault: solid masks cover each piece of
free lettering as a whole patch, which is for a generative cleaner. Pass
`--external` with your reconstructed pages, or rebuild the masks with
`--free-lettering glyphs`.

`source-text-survived` at QA, on a region you added yourself, usually means the
`box:` was drawn a little too tight and clipped a letter. Widen the box; do not
widen the gate.

## Worksheets

| Field in the merge report | What happened | Fix |
| --- | --- | --- |
| `missing_outputs` | a page was never translated | translate it |
| `missing_regions` | an id was deleted from a worksheet | re-do that page |
| `unknown_regions` | an id was invented or mistyped | re-do that page |
| `duplicate_regions` | an id appears twice | re-do that page |
| `empty_translation` | `src:` filled, `fa:` empty | fill it, or `drop: yes` |
| `bad_kind` | `kind:` is not one of the six | fix the value |
| `bad_added_regions` | an `@@ +<name>` block has no usable `box: x y w h` | add one; there is no default for *where* |
| `stale_worksheets` | regions changed after translation | re-do those pages |

`added` in the report lists regions you created with `@@ +<name>`. They have no
mask yet, so run `mask` again before `clean`. Merging the same sheet twice
updates those regions rather than making more, and re-drawing a `box:` moves the
one that is already there.

`refused: stale-worksheets` from `worksheet build` means the same thing earlier:
finished worksheets no longer match the regions. `--force` overrides it and
should only be used when you know the regions did not really move.

**A field that swallowed the wrong text.** Fields continue onto the next line
until the next field or the next `@@`. If a `speaker:` came out as
`هاروکا horizontal`, something was inserted in the middle of the `@@` line
instead of after it.

## Typesetting

| Symptom | Cause | Fix |
| --- | --- | --- |
| letters not joined up (`ک ت ا ب`) | no shaping ran at all | check `doctor` |
| digits at the wrong end of a line | no bidi ran | check `doctor` |
| empty boxes instead of letters | the font has no Persian | `--font` with one that does |
| `overflow` lists regions | Persian too long for the balloon | shorten the translation |
| text sits high or low in a balloon | the interior was measured on artwork | check the balloon was detected, not just the text |
| text over the balloon border | should be impossible; report it | check `qa` for `artwork-modified` |
| a sound effect set at an angle you did not want | its mask showed the original lettering on a slant, so the Persian matched it | `--flat-sfx` sets every effect horizontally; `typeset.style` in the region says which path ran |

Overflow is not a bug to work around. Lowering `--min-size` until it fits
produces type nobody can read. See `persian-typesetting.md`.

## Cleaning

| Symptom | Cause | Fix |
| --- | --- | --- |
| all `inpaint`, no `flat` | balloons sit on textured backgrounds — or detection is off | look at a cleaned page |
| a smear where artwork was | Telea on a gradient; it smooths, it does not redraw | `--external` with a better cleaner |
| a rim of the original text survives | the mask did not reach the anti-aliased edge | raise `--grow` a little |
| the balloon outline is gone | should be impossible; the interior clip prevents it | check `qa` and report it |

## QA

`artwork-modified` is the one to take seriously. It means pixels outside the
authorised mask differ from the original. Do not ship the page. Re-run `clean`
and `typeset` for it; if it persists, something outside this pipeline edited the
file.

`source-modified` means an original page file changed after import. Every box
and mask was measured against pixels that no longer exist. Restore the file or
re-import from scratch.

## Export

| Symptom | Fix |
| --- | --- |
| `already contains ... image(s)` | you pointed `--out` at a folder that has other images in it; use an empty one |
| `archive-page-count` | a page failed to write; re-run export |
| pages in the wrong order in a reader | check `ComicInfo.xml` has `<Manga>Yes</Manga>` for a right-to-left comic |
| the file is bigger with `--jpeg-quality` | expected for line art; PNG compresses flat whites better |

## Windows

- Use `PY=python` or `PY="py -3"`. `python3` does not exist on most Windows
  installations.
- Persian in the console needs UTF-8. Every entry point sets it; a bare
  `python -c` of your own does not, and will raise `UnicodeEncodeError` on the
  first Persian character.
- Paths with spaces need quoting, including `$SKILL_DIR` and `$WORK`.

## Nothing here matches

Re-run the failing stage on **one page** and read its whole report:

```bash
$PY $SKILL_DIR/scripts/revayat-comic.py detect --doc $WORK/comic.json --pages p0007
```

Then look at `work/crops/p0007/overview.png`. Most of what looks like a mystery
in a JSON report is obvious in the picture.
