# AGENTS.md

Repository guide for coding agents working **on** this project. If you want to
*use* the skill to translate a comic, read `skills/revayat-comic/SKILL.md`
instead.

## What this repository is

An agent skill that translates comics into Persian and produces a finished CBZ,
PDF or folder of pages. It ships as three things from one tree:

- a **skill** — `skills/revayat-comic/`, self-contained, copyable into any
  agent's skill directory
- a **plugin** — `.claude-plugin/`, `.cursor-plugin/`, `.codex-plugin/` plus
  root `commands/`
- a **marketplace** — `.claude-plugin/marketplace.json`, so the repo installs
  itself

## Layout

```
skills/revayat-comic/
  SKILL.md          the skill; `name: revayat-comic` is the activation key
  scripts/*.py      the pipeline (see below)
  references/*.md   loaded on demand, not up front
  requirements.txt  the single dependency manifest
commands/           slash commands for plugin hosts
install/            install.ps1, install.sh — copy the skill into agents
tests/              pytest; fixtures are generated, never committed
```

## The pipeline

| Module | Role |
| --- | --- |
| `pageir.py` | the page document, atomic UTF-8 IO, geometry, reading order, script detection |
| `readers.py` | CBZ / CBR / PDF / folder / image → immutable page images |
| `detect.py` | panels, balloons, free lettering |
| `masks.py` | glyph shapes clipped to the balloon's real interior |
| `crops.py` | the overview and crop sheets the reader looks at |
| `worksheet.py` | the `@@` protocol, and every named way a reply can be wrong |
| `glossary.py` | names and terms, and the drift check |
| `falint.py` | Persian typography, mechanically |
| `clean.py` | tiered repair and the mask-bounded composite |
| `typeset.py` | shaping, balloon-shaped fitting, rendering |
| `qa.py` | the gate, including the pixel-preservation proof |
| `export.py` | CBZ, PDF, folder |
| `lettering.py` | matching a drawn effect's slant, arc and recession |
| `providers.py` | the optional second-opinion boundary, and its fakes |
| `adapters.py` | real providers — currently `manga-ocr`, local and keyless |
| `context.py` | the bounded chapter context handed to a translator |
| `ocr.py` | the optional OCR stage, off by default |
| `translate.py` | the optional machine translator, off by default |

The last three are **optional and unused by default**. Read the module docstring
in `providers.py` before adding a provider: the default is none, because the
model running this skill already reads and already sees, and the boundary exists
mainly to hold the invariants — a provider's output never becomes the page, a
locked region is never overwritten, and failure is a status rather than an
exception.
| `revayat-comic.py` | CLI dispatcher and `doctor` |

## Rules that are load-bearing

1. **The original page is immutable.** Every page records the SHA-256 of the
   file it came from. Nothing writes to that file; a stage that needs different
   pixels writes a new one. `qa` re-hashes it and reports `source-modified`.
2. **Only masked pixels may change.** Repairs are composited as
   `original * (1 - alpha) + repaired * alpha` with `alpha <= mask`, so
   preservation holds by construction. `qa check` proves it and reports
   `artwork_pixels_changed`; on a correct run it is `0`.
3. **A mask is clipped to the balloon's interior, not its bounding box.** The
   corners of a box around an ellipse are outside the balloon. Clipping to the
   box repaints the artwork there and erases the outline crossing it —
   `masks.balloon_interior` exists because that shipped once.
4. **Every region reaches exactly one terminal state.** `pageir.region_state`
   returns `translated`, `kept_by_policy`, `dropped_false_detection`,
   `needs_review` or `unresolved` — and there is deliberately no state meaning
   "it quietly disappeared". Completeness was previously inferred from a scatter
   of fields, so a region falling between them was invisible to every gate. The
   census is reported by `qa`, not gated: `unresolved` is a strict subset of
   what `untranslated-region` already blocks on.
5. **Region ids never move.** They are allocated at detection and are what the
   worksheet, the mask filenames, the glossary and every QA finding refer to. A
   region that has been answered is `locked`, and `detect` skips its page.
6. **Never reverse Persian, and never store presentation forms.** The document
   holds logical text; shaping happens at draw time. `tests/test_typeset.py`
   asserts it.
7. **Every CLI entry point calls `ir.use_utf8_stdio()` first.** A Windows
   console defaults to a legacy code page and raises on the first Persian
   character.
8. **Write files with `ir.write_text` / `ir.write_bytes`.** They are atomic and
   use `newline=""`, so a document written on Windows still hashes the same as
   one written on Linux.
9. **Every QA code is declared in `qa.CODES` and documented in `SKILL.md`.** A
   test enforces both, so a check that emits an undeclared code, or one the
   skill has no action for, fails the build.
10. **Detection thresholds are command-line flags, not constants.** The right
   value is a property of the book. A 900-pixel web scan and a 4000-pixel
   tankobon scan disagree about what "small" means.

## Working on it

```bash
pip install -r skills/revayat-comic/requirements.txt
python -m pytest tests -q
python tests/e2e_pipeline.py
```

`tests/e2e_pipeline.py` runs every stage through the real CLI against a
generated chapter, so a break in the dispatcher, an argument name or a report
field shows up even when each module's own tests still pass.

`.github/workflows/integration.yml` is the other tier, off the push path and run
weekly: CBR through a real archive backend, and a whole four-page chapter at
A4/300 dpi. Both need something the unit tier deliberately does not install, and
a flake in either must not block an unrelated commit.

Fixtures are drawn with plain shapes rather than real Japanese, deliberately:
the detector measures geometry and does not care which script the ink came from,
and drawing with a CJK font would make the suite depend on a font a stock CI
runner does not have.

Do not commit comic pages. They bloat the repository and the content is usually
someone else's.

Keep the three plugin manifests at the same `version` — CI enforces it.

Every tracked text file must be UTF-8; CI enforces that too.

## Two things that are true and surprising

**RAQM is not a Linux-only feature, whatever this project used to say.**
Pillow's wheels carry libraqm on every platform; libraqm loads **FriBiDi** at run
time, and Linux images normally have one while Windows and macOS normally do not.
Put a FriBiDi DLL on `PATH` — `fribidi.dll`, `fribidi-0.dll` or
`libfribidi-0.dll` — and `features.check("raqm")` turns true on Windows.
Measured: one already on this machine beside another tool flipped it on, and the
RAQM test that had never run here passed. Beside `python.exe` is **not** enough;
it has to be a directory in the DLL search order.

Without one the `arabic-reshaper` + `python-bidi` fallback runs, the pages are
correct to read, and that is a note rather than a broken install.

**`arabic-reshaper` deletes harakat by default**, and U+0654 is not decoration
in Persian: it carries the ezafe, so `خانهٔ ما` silently becomes `خانه ما`. The
reshaper is configured with `delete_harakat: False` for that reason, and a test
guards it.
