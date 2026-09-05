# Revayat Comic — روایت کمیک

**Translate manga, manhwa, manhua and Western comics into Persian, and get a CBZ or PDF with the artwork intact.**

An agent skill for Claude Code, Claude Desktop, Codex, Antigravity, Hermes,
OpenCode, Kiro, Cursor, Cline and any other coding agent that can read a
`SKILL.md`. It handles the parts that make comic translation actually hard:
finding a balloon to the pixel, removing the original lettering without damaging
the drawing, and Persian right-to-left typesetting that has to be right rather
than approximately right.

<div align="left"><a href="LICENSE">GPL-3.0 licensed</a></div>
<div align="right"><a href="README.md">فارسی</a></div>

---

## What it does that a generic manga translator does not

| | |
| --- | --- |
| **The model sees the page** | Instead of an OCR engine handing a context-free string to a translator, two images are rendered per page: the whole page with every region numbered in reading order, and the crops themselves, enlarged and labelled. The model reads both and transcribes and translates in one pass — with the character's face, the balloon answering back and the tone of the scene in front of it. |
| **Artwork preservation is a guarantee, not an intention** | "We try not to touch the art" is not enough. The finished page is compared against the original and every pixel outside the authorised mask is proved **byte-identical**. `qa check` reports `artwork_pixels_changed`, and on a correct run it is zero. |
| **The mask is the balloon's shape, not its box** | The corners of a box around an ellipse are outside the balloon. Clipping to the box repaints the artwork in those corners and erases the outline crossing them. Here the mask is clipped to the balloon's **real interior**. |
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

### A Persian font

No font ships with this repository — a font file is a separately licensed binary
and does not belong in a GPL source tree. If the machine has no Persian face,
install [Vazirmatn](https://github.com/rastikerdar/vazirmatn/releases).
`doctor` reports what it found.

## Use

Tell the agent:

> Translate this manga chapter into Persian: `chapter-01.cbz`

It does the rest. `SKILL.md` holds eleven steps and the agent runs them in
order. Step 5 — reading the page and translating it — is the agent's own work,
not a script's.

To drive it directly:

```bash
PY=python   # or python3
SKILL=skills/revayat-comic

$PY $SKILL/scripts/revayat-comic.py doctor
$PY $SKILL/scripts/revayat-comic.py import chapter-01.cbz --out work/ --source-language ja --direction rtl
$PY $SKILL/scripts/revayat-comic.py detect --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py mask   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py crops  --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py worksheet build --doc work/comic.json
#  … translate the worksheets …
$PY $SKILL/scripts/revayat-comic.py worksheet merge --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py falint fix --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py clean   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py typeset --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py qa check --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py export --doc work/comic.json --out out/chapter-fa.cbz
```

## In and out

**In:** CBZ, CBR, a comic PDF, a folder of images, or one image.
**Out:** CBZ, PDF, or a folder of pages — with a `ComicInfo.xml` that records the
reading direction, so readers do not pair every two-page spread back to front.

**Source languages:** Japanese, Korean, Chinese, English — and anything else the
agent can read off a crop.
**Target:** Persian.

## Architecture

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
original's hash is re-checked at the end.

| Module | Role |
| --- | --- |
| `pageir.py` | the page document, geometry, reading order, script detection |
| `readers.py` | CBZ / CBR / PDF / folder → immutable page images |
| `detect.py` | panels, balloons, free lettering |
| `masks.py` | glyph shapes clipped to the balloon interior |
| `crops.py` | the overview and crop sheets the reader looks at |
| `worksheet.py` | the `@@` protocol, and every named way a reply can be wrong |
| `glossary.py` | names and terms, and the drift check |
| `falint.py` | Persian typography, mechanically |
| `clean.py` | tiered repair and the mask-bounded composite |
| `typeset.py` | shaping, balloon-shaped fitting, rendering |
| `qa.py` | the gate, including the pixel-preservation proof |
| `export.py` | CBZ, PDF, folder |

## Development

```bash
pip install -r skills/revayat-comic/requirements.txt
python -m pytest tests -q
python tests/e2e_pipeline.py
```

Fixtures are generated, not committed. There are no comic pages in this
repository: they bloat it and the content is usually someone else's.

## Licence

GPL-3.0-or-later. Full text in [LICENSE](LICENSE).

Fonts, models and the artwork this tool processes carry their own licences, and
none of them are distributed with this repository.
