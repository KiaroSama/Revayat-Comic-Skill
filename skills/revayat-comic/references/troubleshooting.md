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

No. Pillow's wheels carry a working RAQM only on Linux x64, because libraqm
loads libfribidi at runtime and Windows and macOS do not ship one. The fallback
runs, the pages are correct to read, and `doctor` says so. See
`persian-typesetting.md` for what differs.

## Import

| Symptom | Cause | Fix |
| --- | --- | --- |
| `no images` | the CBZ holds something else | check it opens in a comic reader |
| an error naming `rarfile` | CBR support is optional | `pip install rarfile`, and install an unrar binary — or convert to CBZ |
| an error naming `unrar` | rarfile is installed but has no backend | Linux/macOS: install `unrar` or `libarchive-tools`; Windows: install WinRAR |
| pages in the wrong order | rare; the archive uses a naming scheme nothing can sort | extract to a folder, rename `0001.png`… and import the folder |
| `webtoon_strips` is not empty | this is a webtoon | `--direction ltr` |
| PDF import is slow | pages are being rendered, not extracted | expected when a page is not one embedded image |

## Detection

| Symptom | Fix |
| --- | --- |
| `pages_without_text` on most pages | thresholds do not fit this book — see `detection.md` |
| whole panels detected as balloons | lower `--balloon-max-area` |
| balloons missed | raise `--ink-max`, lower `--balloon-min-solidity` |
| dozens of low-confidence regions | `--no-sfx`, then `drop: yes` on what is left |
| `reading-order-broken` at QA | re-run `detect` for that page |

Detection never runs on a page whose regions have been answered. If you *want*
to re-detect a page after translating it, clear `locked` on its regions — and
accept that its worksheet is then stale.

## Masks

`excessive_coverage` means a mask would repaint more than 28% of a page. Almost
always a detection problem, not a mask problem: a region matched artwork rather
than lettering. Fix the detection, or `drop: yes` the region, before cleaning.

Growing the mask cannot cause this on a balloon — a balloon's mask is clipped to
the balloon and cannot spread past it.

## Worksheets

| Field in the merge report | What happened | Fix |
| --- | --- | --- |
| `missing_outputs` | a page was never translated | translate it |
| `missing_regions` | an id was deleted from a worksheet | re-do that page |
| `unknown_regions` | an id was invented or mistyped | re-do that page |
| `duplicate_regions` | an id appears twice | re-do that page |
| `empty_translation` | `src:` filled, `fa:` empty | fill it, or `drop: yes` |
| `bad_kind` | `kind:` is not one of the six | fix the value |
| `stale_worksheets` | regions changed after translation | re-do those pages |

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
