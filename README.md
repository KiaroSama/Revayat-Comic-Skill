# Revayat Comic — روایت کمیک

**Translate manga, manhwa, manhua and Western comics into Persian, and get a CBZ or PDF with the artwork provably untouched.**

An agent skill for Claude Code, Claude Desktop, Codex, Antigravity, Hermes,
OpenCode, Kiro, Cursor, Cline and any other coding agent that can read a
`SKILL.md`. It handles the parts that make comic translation actually hard:
finding a balloon to the pixel, removing the original lettering without damaging
the drawing, and Persian right-to-left typesetting that has to be right rather
than approximately right.

<div align="left"><a href="LICENSE">GPL-3.0 licensed</a></div>
<div align="right"><a href="README.fa.md">فارسی</a></div>

---

## What it does that a generic manga translator does not

| | |
| --- | --- |
| **The model sees the page** | Instead of an OCR engine handing a context-free string to a translator, two images are rendered per page: the whole page with every region numbered in reading order, and the crops themselves, enlarged and labelled. The model reads both and transcribes and translates in one pass — with the character's face, the balloon answering back and the tone of the scene in front of it. |
| **Artwork preservation is a guarantee, not an intention** | "We try not to touch the art" is not enough. The finished page is compared against the original and every pixel outside the authorised mask is proved **byte-identical**. `qa check` reports `artwork_pixels_changed`, and on a correct run it is zero. |
| **The mask is the balloon's shape, not its box** | The corners of a box around an ellipse are outside the balloon. Clipping to the box repaints the artwork in those corners and erases the outline crossing them. Here the mask is clipped to the balloon's **real interior**, inset so the outline is structurally out of reach. |
| **Cleaning escalates** | A flat balloon is filled with its own colour — exact, no model involved. Only lettering that sits on artwork goes to a reconstructor. A better cleaner plugs in with `--external`, and still only its masked pixels are used. |
| **Text is fitted to the balloon's actual shape** | A round balloon is narrow at the top, wide in the middle and narrow again at the bottom. Every line asks how wide it is allowed to be *in its own vertical band* — which is what a letterer does by hand. |
| **Right-to-left done properly** | No string is ever reversed. Direction and letter joining are HarfBuzz and FriBidi's job — or, on Windows and macOS, `arabic-reshaper` and `python-bidi`. `doctor` says which path is active. |
| **Panel-aware reading order** | A balloon at the top of the next panel is read after one at the bottom of this panel, even though it sits higher on the paper. Right-to-left for manga, left-to-right for webtoons and Western comics. |
| **The size floor is a floor** | When Persian will not fit, the text does not silently shrink: the region is reported as `text-overflow` so the translation can be shortened instead. |
| **Sound effects are artwork** | SFX are classified separately from dialogue and the default is `keep`. Erasing hand-lettering to put a guess in its place is worse than not translating it. |
| **Deterministic quality gates** | Untranslated regions, source script surviving inside the Persian, text overflow, broken reading order, modified artwork, glossary drift. Counts and pixel comparisons, not a second opinion from a model. |

## Install

```bash
git clone https://github.com/KiaroSama/Revayat-Comic-Skill.git
cd Revayat-Comic-Skill
pip install -r skills/revayat-comic/requirements.txt
```

Then install the skill into whichever agents you use:

```bash
# macOS / Linux
./install/install.sh

# Windows
powershell -ExecutionPolicy Bypass -File .\install\install.ps1
```

By default this installs into every agent it finds — Claude Code, Kiro, Codex,
Cursor, Cline, Hermes, OpenCode and Antigravity. The last two also get an
`AGENTS.md` pointer, because that is how they discover instructions. Use
`--agent claude` for one, and `--scope project --path <dir>` for a single
project. Both installers behave identically on Linux, macOS and Windows.

### As a Claude Code plugin

```
/plugin marketplace add KiaroSama/Revayat-Comic-Skill
/plugin install revayat-comic@KiaroSama/Revayat-Comic-Skill
```

### Check the install

```bash
python skills/revayat-comic/scripts/revayat-comic.py doctor
```

`"ready": true` and you are done. Two fields under `persian` decide whether the
output is *correct* rather than merely present:

- **`"font"`** and **`"vazir"`** — the Persian face it will draw with, and
  whether that face is the house one. **Persian here is set in Vazir**;
  [Vazirmatn](https://github.com/rastikerdar/vazirmatn/releases) is the current
  release of that family and any weight works, including the variable build. No
  font ships with this repository: a font file is a separately licensed binary
  and does not belong in a GPL source tree. Tahoma, Noto Naskh Arabic and Geeza
  Pro all draw correct Persian, so a run on one of them looks fine and is not
  the house face — which is why `"vazir": false` comes with a note instead of
  passing quietly.
- **`"raqm"`** — whether Pillow shapes Arabic script itself. **This is not a
  platform limit.** Pillow ships libraqm in the wheel on every platform; what
  libraqm loads at run time is **FriBiDi**, and Linux images usually have one
  while Windows and macOS usually do not. Put a `fribidi.dll` — `fribidi-0.dll`
  or `libfribidi-0.dll` also work — in a directory on `PATH` (a directory in the
  DLL search order; beside `python.exe` is not enough) and `raqm` turns true on
  Windows. On Linux and macOS, install `libfribidi`. Without it the
  `arabic-reshaper` + `python-bidi` fallback runs and the pages are still
  correct to read.

## Use

Tell the agent:

> Translate this manga chapter into Persian: `chapter-01.cbz`

It does the rest. `SKILL.md` holds eleven steps and the agent runs them in
order. Step 5 — reading the page and translating it — is the agent's own work,
not a script's.

### Or drive it yourself

```bash
PY=python   # or python3
SKILL=skills/revayat-comic

$PY $SKILL/scripts/revayat-comic.py doctor
$PY $SKILL/scripts/revayat-comic.py import chapter-01.cbz --out work/ --source-language ja --direction rtl
$PY $SKILL/scripts/revayat-comic.py detect --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py mask   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py crops  --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py worksheet build --doc work/comic.json
#   … look at work/crops/pNNNN/*.png and translate the worksheets …
$PY $SKILL/scripts/revayat-comic.py worksheet merge --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py glossary scan --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py falint fix --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py clean   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py typeset --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py qa check --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py export --doc work/comic.json --out out/chapter-fa.cbz
```

**In:** CBZ, CBR, a comic PDF, a folder of images, or one image.
**Out:** CBZ, PDF, or a folder of pages — with a `ComicInfo.xml` that records the
reading direction, so readers do not pair every two-page spread back to front.

**Source languages:** Japanese, Korean, Chinese, English — and anything else the
agent can read off a crop. **Target:** Persian.

## How it works

```
import → detect → mask → crops → worksheet ⇄ [ the agent reads and translates ]
                                     ↓
                            merge → glossary → falint
                                     ↓
                              clean → typeset → qa → export
```

Every stage talks to `comic.json` and never to another stage, so a detector can
be swapped or a renderer rewritten without any of the others noticing. The
original page is never written to; each stage writes a new file, and the
original's SHA-256 is re-checked at the end.

| Module | Role |
| --- | --- |
| `pageir.py` | the page document, atomic UTF-8 IO, geometry, reading order, script detection |
| `readers.py` | CBZ / CBR / PDF / folder / image → immutable page images |
| `detect.py` | panels, balloons in both polarities, free lettering |
| `masks.py` | glyph shapes clipped to the balloon interior |
| `crops.py` | the overview and crop sheets the reader looks at |
| `worksheet.py` | the `@@` protocol, and every named way a reply can be wrong |
| `glossary.py` | names and terms, and the drift check |
| `falint.py` | Persian typography, mechanically |
| `clean.py` | tiered repair and the mask-bounded composite |
| `typeset.py` | shaping, balloon-shaped fitting, rendering |
| `qa.py` | the gate, including the pixel-preservation proof |
| `export.py` | CBZ, PDF, folder |
| `lettering.py` | matching a drawn sound effect's slant, arc and recession |
| `providers.py` | the optional second-opinion boundary, and its fakes |
| `context.py` | the bounded chapter context a translator gets |
| `ocr.py` | the optional OCR stage — off by default |
| `translate.py` | the optional machine translator — off by default |

**Two stages are optional and off by default**, because the model running the
skill already reads and already sees:

```
ocr         a second opinion on the source text, when a specialist beats the
            host (vertical Japanese) or the host has no vision at all
qa visual   a model's opinions about things a deterministic check cannot judge,
            advisory only — it can never pass or fail a run
context     the bounded chapter package a translator is given: locked glossary,
            the previous pages' dialogue, who has spoken. Cheap and offline —
            paste its JSON into the translating sub-agent's prompt
translate   machine translation for a run with nobody reading the page. It
            fills empty regions only and never touches a locked one
```

Neither is in the diagram above and neither runs unless you name a provider.
`providers.py` explains when one is worth the second inference bill and when it
is not; every role ships a deterministic fake, so the suite tests the boundary
offline with no credential anywhere.

The preservation guarantee is one line, and it is why an external cleaner is
safe to plug in:

```
out = original × (1 − alpha) + repaired × alpha        where alpha ≤ mask
```

Because `alpha` is zero everywhere the mask is zero, every pixel outside the
authorised area is the original byte by construction rather than by good
behaviour. Hand `--external` a page a generative model redrew from scratch and
only its masked pixels are ever used.

## What it is honest about

- **Two real volumes have been through it; that is not a corpus.** Chapters of
  *Sekirei* and *Gleipnir* were translated, cleaned, typeset and exported, and
  each one found defects the generated fixtures could not. Two books is enough to
  show the pipeline holds and nowhere near enough to have met every drawing
  style: the second book's borderless balloons and white-on-black lettering were
  both invisible until it arrived. Expect to move the knobs in
  `references/detection.md` on a new scan — they are all command-line flags for
  exactly that reason.
- **Free lettering is the weak detector, and merged balloons are the weak
  region.** Two speech balloons drawn touching come back as one; five automatic
  ways of splitting them were measured and none is good enough to ship. You fix
  it from the crop with `drop: yes` and two `@@ +name` blocks, which takes a few
  seconds and is documented.
- **Sound effects drawn into the artwork stay drawn** under the default policy.
  Redrawing hand-lettering — matching slant, stroke weight, outline and
  perspective — is a lettering job, and a half-hearted version looks worse than
  leaving the Japanese in place.
- **Free-lettering detection is the weak half.** It finds the obvious sound
  effects and is wrong about the rest, which is why everything it returns is
  marked low-confidence and shown to you as a crop.
- **Telea smooths, it does not redraw.** Lettering over detailed artwork gets a
  reconstruction, not an invention. `clean` reports `inpaint_heavy_pages` so you
  know which pages to look at.
- **The reshaper fallback draws presentation forms.** On Windows and macOS the
  text on the page is correct to read but is a picture of Persian rather than
  searchable Persian.

## Documentation

- [`SKILL.md`](skills/revayat-comic/SKILL.md) — the eleven steps, and the QA
  code table
- [`references/translation-policy.md`](skills/revayat-comic/references/translation-policy.md)
  — what to give the translating sub-agent
- [`references/persian-typesetting.md`](skills/revayat-comic/references/persian-typesetting.md)
  — RTL, shaping, fonts, fitting a balloon
- [`references/detection.md`](skills/revayat-comic/references/detection.md) —
  thresholds, difficult pages, correcting a region
- [`references/artwork-preservation.md`](skills/revayat-comic/references/artwork-preservation.md)
  — masks, cleaning tiers, what QA proves
- [`references/sound-effects.md`](skills/revayat-comic/references/sound-effects.md)
  — the four policies and how to choose
- [`references/ocr.md`](skills/revayat-comic/references/ocr.md) — reading with
  your own eyes, and when a model helps
- [`references/troubleshooting.md`](skills/revayat-comic/references/troubleshooting.md)
  — the failures you are most likely to hit
- [`AGENTS.md`](AGENTS.md) — for agents working *on* this repository

## Development

```bash
pip install -r skills/revayat-comic/requirements.txt
python -m pytest tests -q
python tests/e2e_pipeline.py
```

Fixtures are generated, not committed. There are no comic pages in this
repository: they bloat it and the content is usually someone else's. A CI check
enforces that.

Pages are drawn with plain shapes rather than real Japanese, deliberately — the
detector measures geometry and does not care which script the ink came from, and
a CJK font is not installed on a stock CI runner.

`tests/e2e_pipeline.py` runs every stage through the real CLI against a
generated chapter, so a break in the dispatcher, an argument name or a report
field shows up even when each module's own tests pass. CI runs it on Linux,
macOS and Windows.

A second tier runs weekly rather than per commit — CBR through a real archive
backend, and a whole chapter at A4/300 dpi — because apt and a third-party
archive backend flaking must not block an unrelated commit.

## Credits

The problem shape — detect, OCR, translate, clean, typeset — is the one worked
out by the open manga-translation projects that came before this:
[manga-image-translator](https://github.com/zyddnys/manga-image-translator),
[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) and
[comic-translate](https://github.com/ogkalu2/comic-translate). This one differs
in where the reading happens and in treating artwork preservation as something
to prove, but the ground was theirs.

Persian text layout rests on [HarfBuzz](https://harfbuzz.github.io/) and
[FriBidi](https://github.com/fribidi/fribidi) through
[Pillow](https://github.com/python-pillow/Pillow), with
[arabic-reshaper](https://github.com/mpcabd/python-arabic-reshaper) and
[python-bidi](https://github.com/MeirKriheli/python-bidi) where Pillow has no
RAQM. Detection, masking and inpainting use
[OpenCV](https://github.com/opencv/opencv); PDF input and output use
[PyMuPDF](https://github.com/pymupdf/PyMuPDF).

## Donate

If this project helps you, donations are appreciated.

| Currency | Network | Address |
| --- | --- | --- |
| Bitcoin (BTC) | Bitcoin | `bc1qmth5m03pu5hujw5xw5jmywam3jj3sqwqupesdt` |
| USDT, BNB, USDC, etc. | BEP20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| USDT, TRX, USDC, etc. | TRC20 | `TWBA3xFTqgZAeAYMxqo85xWnzvty3DcAhw` |
| Ethereum (ETH) | ERC20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| TON | TON | `UQCN8Umo_OfOWqImZetQsrNStPcmLkMAKajFyiCOhso23NDb` |
| Litecoin (LTC) | LTC | `ltc1qntqnnrunadurnw4cshv3qgspywrueyyeyngwuy` |
| Solana (SOL) | Solana | `7B2wkczUjmkDhETwQuknBL8sUsbuV7nErxc317TmQuwR` |
| Polygon (POL) | Polygon | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |

## Author

Author: Kiaro Sama
GitHub: https://github.com/KiaroSama

## License

[GNU General Public License v3.0 or later](LICENSE).

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the licence for details.

Fonts, models and the artwork this tool processes carry their own licences, and
none of them are distributed with this repository.
