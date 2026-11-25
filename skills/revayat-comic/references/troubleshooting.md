# Troubleshooting

The failures you are most likely to hit, in the order they happen.

## `doctor` says `"ready": false`

Rebuild or download the `revayat-comic` binary for your platform (Linux or Windows 64-bit):

```bash
cargo build --release --locked -p revayat-comic-cli
./target/release/revayat-comic doctor --json
```

The binary embeds the Vazir font family (`Regular`, `Medium`, `Bold`); the
current CLI does not select a custom font. A source build goes into
`target/release/`, unless `CARGO_TARGET_DIR` selects a different directory.

## Persian shaping

Pure-Rust shaping via `cosmic-text` (HarfRust, `unicode-bidi`, and Swash) with bundled Vazir
fonts is compiled into `revayat-comic` on both Linux and Windows (x64 and
arm64). No external `libraqm`, FriBidi DLL, or fallback library is needed.

## Input and provider byte limits

Loose page files use the same encoded budgets as archive members: 512 MiB per
image and 2 GiB per import. Copying counts actual bytes, including a file that
grows after admission. Image decoding uses a file-backed reader, closes the
handle before returning decoded pixels and retains the 80-million-pixel limit.
A rejected input is not fixed by shrinking the immutable baseline.

Provider redirects are refused. Point the configured base directly at the
canonical endpoint. Successful JSON responses are limited to 64 MiB; an
oversized or invalid response fails the operation.

## Import

| Symptom | Cause | Fix |
| --- | --- | --- |
| `no images` | the CBZ holds something else | check it opens in a comic reader |
| CBR archive fails to decode | unsupported or corrupted RAR entry | verify the archive is readable, or re-pack as lossless CBZ |
| pages in the wrong order | rare; the archive uses a naming scheme nothing can sort | extract to a folder, rename `0001.png`… and import the folder |
| `webtoon_strips` is not empty | this is a webtoon | `--direction ltr` |
| PDF import is slow | pages are being rendered, not extracted | expected when a page is not one embedded image |
| an error naming a page count, a GB total, an MB entry or megapixels | the import guards — 2000 pages, 2 GB, 512 MB an entry, 80 MP a page | process smaller chapters or report the limit; keep native preservation resolution and use separately identified reading derivatives, not lower import DPI to bypass the guard |

## Providers (optional, off by default)

| Symptom | Cause | Fix |
| --- | --- | --- |
| OCR provider name is refused | this binary supports `openai` only | use `ocr --provider openai --model MODEL`; there is no Python registration step |
| `ocr` wrote nothing | the regions were locked, already had source text, were inactive, or the provider returned no reading | inspect the crops and eligibility; existing readings are not re-requested or compared automatically |
| `ocr` or `translate` fails | the request timed out, failed, or returned invalid data | correct the endpoint/model and retry; the document write is transactional |
| `clean` rejects an image-provider flag | cleaning accepts local external pages | obtain and review the repair separately, then use `clean --external-dir` |
| `serve --http 127.0.0.1:PORT` answers 401 | the token is missing or wrong | set `REVAYAT_HTTP_TOKEN` before starting and send that value as `X-Revayat-Token` |
| `serve --http ADDRESS` refuses to start | the address is not loopback or the token is missing | use a loopback address and configure `REVAYAT_HTTP_TOKEN` |
| an MCP client hangs at the handshake | it is waiting for a reply to a notification | notifications have no `id` and are never answered; check the client, this server does not reply to them |
| `REVAYAT_API_BASE is not set` | the provider has nowhere to send the request | use the canonical compatible base and set `REVAYAT_OCR_MODEL` or `REVAYAT_TRANSLATION_MODEL`, or pass `--model` |
| `refusing to send REVAYAT_API_KEY ... over plain http` | a key is set and `REVAYAT_API_BASE` is a cleartext address off this machine, so the key would cross the network readable | switch the base to `https://`, or unset `REVAYAT_API_KEY` if that endpoint needs no credential; loopback (`http://127.0.0.1:1234/v1`) is exempt and still works |
| `context` refused: pages are translated but not merged | an earlier page’s `.done.txt` has not reached `comic.json`, so its Persian would be missing from this package | run `worksheet merge`, then build the context again; `--allow-unmerged` overrides and lists what is missing |
| `translate` skipped everything | the regions already have Persian, or no `src:` yet | it fills empty regions only; a value already there is never replaced |
| `translate`/`ocr` re-run did nothing | destination fields are already filled or locked | inspect the accepted text; these commands fill empty fields rather than replacing a reviewed reading |

Provider failure details intentionally omit arbitrary network/SDK exception messages,
response bodies and credential-bearing headers. Public errors use
fixed configuration/service guidance. The Rust provider client uses
bounded single-line public guidance; never include secrets in that contract or enable
HTTP wire logging to recover raw errors. `REVAYAT_API_KEY` must be printable ASCII
without whitespace; invalid values are refused before request/opener construction,
not trimmed or echoed. Keyless local endpoints and valid HTTPS/loopback keys remain
supported. Already-exposed credentials need owner-controlled rotation and cleanup;
this repair does not rewrite old chapter files silently.

## Detection

| Symptom | Fix |
| --- | --- |
| detected pages contain few or no text regions | thresholds may not fit this book — see `detection.md` |
| whole panels detected as balloons | lower `--balloon-max-area`, or `drop: yes` the region and add the real balloons back with `box:` — see `detection.md` |
| two balloons come back as one region | the same fix: drop it, add each one back with `box:` |
| text on the page with no region on it | add it: `@@ +<name>` with `box: x y w h` |
| balloons missed | raise `--ink-max`, lower `--balloon-min-solidity` |
| dozens of low-confidence regions | `--no-sfx`, then `drop: yes` on what is left |
| numbered crops follow the wrong reading order | inspect the source direction and recorded region order; a dropped detection may leave a harmless gap, but narrative order still needs review |

Detection skips pages with locked or answered regions and reports them in
`skipped`. Preserve accepted text and review the current crops before replacing
any detection mapping; clearing a lock alone does not erase the answered state.

## Masks

Inspect the generated mask before cleaning. An unexpectedly broad mask usually
means a region matched artwork rather than lettering. Correct the box or use
`drop: yes` for a false detection. Balloon masks are clipped to the recovered
interior; the current CLI has no configurable growth or page-coverage flag.

`clean` refusing with *"a solid erase mask needs an approved external repair"*
means solid masks cover each piece of
free lettering as a whole patch, which is for a generative cleaner. Pass
`--external-dir` with your reconstructed pages, or rebuild the masks with
`--free-lettering glyph`.

`balloon-ink-survives` at QA, on a region you added yourself, can mean the
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
| `bad_kind` | `kind:` is not an accepted region kind | fix the value |
| `bad_added_regions` | an `@@ +<name>` block has no usable `box: x y w h` | add one; there is no default for *where* |
| `stale_worksheets` | the reply cannot prove the current region mapping | preserve its Persian and review/reconcile only the affected pages; see `recovery.md` |
| `invalid_fields` | a `keep`, `drop`, `erase` or `polarity` value is not understood | correct the exact field spelling before merge; do not guess a decision |
| worksheet status finds no external replies after changing working directory | an old recorded relative folder may have meant a different invocation directory | pass the actual folder once with `--worksheets`; preserve existing reply files and see `recovery.md` |

`added` in the report lists regions you created with `@@ +<name>`. They have no
mask yet, so run `mask` again before `clean`. Merging the same sheet twice
updates those regions rather than making more, and re-drawing a `box:` moves the
one that is already there.

`refused: stale-worksheets` from `worksheet build` means the same thing earlier:
finished worksheets no longer prove the current mapping. Use the explicit
page reconciliation described in `recovery.md` after reviewing the current crops.

**A field that swallowed the wrong text.** Fields continue onto the next line
until the next field or the next `@@`. If a `speaker:` came out as
`هاروکا horizontal`, something was inserted in the middle of the `@@` line
instead of after it.

## Typesetting

| Symptom | Cause | Fix |
| --- | --- | --- |
| letters not joined up (`ک ت ا ب`) | no shaping ran at all | check `doctor` |
| digits at the wrong end of a line | no bidi ran | check `doctor` |
| empty boxes instead of letters | unsupported characters or a rendering defect | check the logical input and bundled-font result; report the specific characters |
| `overflow` lists regions | actual glyph ink does not fit | reflow first; preserve full meaning in `fa_full` if a reviewed shorter variant is needed |
| text sits high or low in a balloon | the interior was measured on artwork | check the balloon was detected, not just the text |
| text over the balloon border | placement crossed its approved interior | inspect `text-crosses-outline` and `artwork-changed`; do not deliver it |
| a sound effect needs a drawn angle or shape | the CLI local path does not automatically match brush geometry | use a reviewed full-page edit; see `sound-effects.md` |

Treat overflow as a layout and translation review problem. Do not shrink text
below the agreed readable size to make a report pass. The current CLI does not
expose a minimum-size flag. See `persian-typesetting.md`.

## Cleaning

| Symptom | Cause | Fix |
| --- | --- | --- |
| all `inpaint`, no `flat` | balloons sit on textured backgrounds — or detection is off | look at a cleaned page |
| a smear where artwork was | diffusion smooths neighboring colors rather than redrawing detail | supply a reviewed reconstruction with `--external-dir` |
| a rim of the original text survives | the region or enclosure may omit part of a glyph | correct the box/polarity, then rerun mask and clean |
| the balloon outline is gone | should be impossible; the interior clip prevents it | check `qa` and report it |

## QA

`artwork-changed` means pixels outside the
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
| pages in the wrong order in a reader | check `ComicInfo.xml` has `<Manga>YesAndRightToLeft</Manga>` for a right-to-left comic |
| a lossless file is larger than expected | retain the primary edition's exact pixels; any lossy reading derivative must be separately labeled |

## Windows

- Use PowerShell 7 (`pwsh`) with `.\bin\revayat-comic.exe`.
- Console output and run logs are always UTF-8; quote paths with spaces (`"$WORK"`).

## Nothing here matches

Re-run the failing stage on **one page** and read its whole report:

```bash
revayat-comic detect --doc "$WORK/comic.json" --pages p0007
```

Then look at `work/crops/p0007/overview.png`. Most of what looks like a mystery
in a JSON report is obvious in the picture.

## `export` says the chapter does not pass publication QA

It runs the whole gate now, not its own narrower question. Before, it asked
only "is there a rendered file for every page that wants one", so a chapter
whose render was stale, whose lines had overflowed, or whose erasures had never
been cleaned went into a package without `qa` ever running.

```bash
revayat-comic qa check --doc "$WORK/comic.json" --strict
```

Fix what it names and export again. `--draft` still ships what is there —
and says so in the report *and* in the package's `ComicInfo.xml`, so a draft
cannot be mistaken for an approved edition later.

## `stale-stages`, on a stage I definitely ran

The result is real; what changed is one of its inputs. Each stage records the
page-by-page facts it was made from, so:

- correcting an approved Persian line stales `typeset` for that page, and only
  that page;
- correcting a polarity stales `masks`, and does **not** stale the worksheet —
  a reply is filed against ids, boxes, kinds and orientations, and a polarity
  is none of those;
- re-running `mask` stales `clean`, which stales `typeset`;
- locking a glossary name stales `translate`.

Re-run the stage it names. Running it with no change rewrites identical bytes,
so doing it twice costs nothing and settles nothing wrongly.

`unverified-stages` is different: the required stage proof is missing or not
comparable to the current build, so
its freshness cannot be judged at all. Run it once and the question is answered
— it is never a reason to translate a chapter again.

## Solid-patch cleaning was refused

`clean` had no repair for a solid free-lettering patch and left the original
lettering on the page. The region takes no Persian overlay — drawing one would
ship two layers of text in one balloon — and publication is blocked. Give it
`--external-dir`, or rebuild the masks with
`mask --free-lettering glyph` after reviewing the intended repair.
