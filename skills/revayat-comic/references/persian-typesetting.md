# Persian typesetting

How Persian gets onto the page, what can go wrong, and the two things to check
before blaming the renderer.

## Never reverse a string

Persian is stored in **logical order** — the order it is spoken — and displayed
right to left. Those are different things, and the renderer is what connects
them. Reversing the string yourself produces text that looks correct in one
viewer and is broken in every other, cannot be searched or copied, and breaks
again the moment a Latin word or a number appears in it.

`revayat-comic` never stores reversed text. `tests/test_typeset.py` asserts it.

## The font is Vazir

Persian in this project is set in **Vazir**. Vazirmatn is the current release of
that family and the one to install; the older `Vazir-*` files are the same design
under its first name. Any weight works, including the variable build.

    https://github.com/rastikerdar/vazirmatn/releases

No font ships with this repository — a font file is a separately licensed binary
and does not belong in a GPL source tree.

**A fallback face announces itself.** Tahoma, Noto Naskh Arabic and Geeza Pro all
draw correct Persian, so a run on one of them produces pages that look fine and
are not in the house face. `doctor` reports `"vazir": true|false` and `typeset`
puts the same flag plus a note in its report, because "readable" is exactly what
stops anyone from checking. Pass `--font` to name one explicitly.

This was not hypothetical: the preference list once held three Vazirmatn
filenames, this machine had it installed as `Vazirmatn-VariableFont_wght.ttf`,
and every page silently set in Tahoma. The list now matches the family.

## The two shaping paths

Arabic-script text needs two things done to it before it can be drawn:

- **Shaping** — each letter takes a different form depending on its neighbours.
  `ب` is `بـ` at the start of a word, `ـبـ` in the middle, `ـب` at the end.
- **Bidi** — resolving the direction of a mixed run, so `نسخهٔ 2.5 را دانلود کن`
  puts the numeral in the right place inside the Persian.

There are two ways this happens here, and `doctor` says which one you have.

### RAQM — the good path

Pillow, built against libraqm, does both properly through HarfBuzz and FriBidi.
The text stays logical all the way to the draw call, and Pillow is told
`direction="rtl", language="fa"`.

**RAQM is not a Linux-only feature, whatever this project used to say.**
Pillow's wheels carry libraqm on every platform; libraqm loads **FriBiDi** at run
time, and Linux images normally have one while Windows and macOS normally do not.
Put a FriBiDi DLL on `PATH` — `fribidi.dll`, `fribidi-0.dll` or
`libfribidi-0.dll` — and `features.check("raqm")` turns true on Windows.
Measured: one already on this machine beside another tool flipped it on, and the
RAQM test that had never run here passed. Beside `python.exe` is **not** enough;
it has to be a directory in the DLL search order.

There is no `pip install` that supplies FriBiDi; it is a system library. On
Windows it ships with several common tools, and any one of their DLLs will do.

### The reshaper fallback — what runs without FriBiDi

`arabic-reshaper` picks the right form for every letter, and `python-bidi`
reorders the result for display. The page is correct to read. Two things differ:

- The string drawn is **presentation forms in visual order**. It is a picture of
  Persian, so text copied out of the image would not be searchable Persian.
- Line breaking has to happen *before* shaping, on the logical text, or lines
  break in the wrong place. This is why `fit_region` wraps first and shapes each
  line separately, and why you must not pre-shape text in a worksheet.

Two settings matter and are set explicitly:

- `delete_harakat: False`. The default is `True`, and it deletes U+0654 — the
  hamza that carries the Persian ezafe. `خانهٔ ما` (*our house*) silently becomes
  `خانه ما`, which is a different construction. This was measured, not assumed.
- `support_zwj: True`, so the zero-width non-joiner does its job.

The ZWNJ itself does not survive into the drawn string, and that is correct: it
is a boundary-neutral character and the bidi algorithm removes it after it has
forced the letter forms. `کتاب‌ها` keeps its beh isolated; `کتابها` joins it.

## Fonts

`--font` takes a file path or a family name. Without it, the best Persian face
on the machine is used, searching in this order:

    Vazirmatn · Sahel · Shabnam · IRANSans · Noto Naskh Arabic ·
    Noto Sans Arabic · Tahoma · Arial · DejaVu Sans

The chosen font is then *tested*: a Persian word is drawn and the ink measured.
A font with no Persian coverage draws nothing, or a row of identical tofu boxes,
and either is refused rather than shipped.

No font is vendored with this repository. A font is a separately licensed binary
and does not belong in a GPL source tree. Vazirmatn is the usual choice and is
free:

    https://github.com/rastikerdar/vazirmatn/releases

For a comic specifically, prefer a face with a heavy weight available. Dialogue
in a balloon is small and sits on artwork; a light weight disappears.

## Fitting a balloon

A balloon is not a rectangle. A round one is narrow at the top, wide in the
middle and narrow again at the bottom, so a paragraph set to one constant width
either overflows the curve or wastes half the balloon.

The fitter measures the **interior of the balloon itself** on the cleaned page:
the connected region of paper inside the outline, eroded so the text keeps clear
of the border. Then, for each candidate font size, it asks each line how wide it
is allowed to be *in its own vertical band*, wraps to that, and accepts the
largest size where every line fits.

The number of lines and their positions depend on each other, so it settles in
up to four passes and gives up rather than looping.

Knobs:

| Flag | Default | Effect |
| --- | --- | --- |
| `--max-size` | 64 | ceiling; lower it if the type looks shouty |
| `--min-size` | 13 | **floor**; never crossed silently |
| `--font` | auto | a path or a family name |
| `--no-raqm` | off | force the fallback, for testing it |

`BALLOON_PADDING` (0.10 of the balloon's smaller side) is how far the text keeps
from the outline. `LINE_SPACING` is 1.30.

## Overflow

When a translation will not fit at `--min-size`, the region is reported as
`text-overflow` and left unset. That is deliberate. The alternatives are worse:

- shrinking below the floor produces type nobody can read
- letting it spill draws Persian over the artwork
- truncating loses what the character said

The fix is a shorter translation that still says everything. In order:

1. Re-read the balloon. Persian usually has a tighter way to say it.
2. Drop filler the original did not need in Persian.
3. If the balloon genuinely holds a paragraph, split it across the line breaks
   the original used — a `\n` in `fa:` is honoured.
4. Only then consider `--min-size 11` for that chapter, and look at the result.

## Colour and stroke

- A light balloon gets near-black text.
- A dark balloon gets near-white text.
- Lettering with **no balloon** — a sign, a caption over artwork — gets a stroke
  in the opposite colour, because without it the text disappears into the
  drawing at exactly the moment it matters.

## Checking a result

Two questions, in this order:

1. **Is the shaping right?** Look for disconnected letters (`ک ت ا ب` instead of
   `کتاب`). That means neither RAQM nor the fallback ran — check `doctor`.
2. **Is the direction right?** Look at a line with a numeral in it. If the digits
   land at the wrong end, bidi did not run.

If both are right and it still looks wrong, it is a font problem, not a
direction problem.
