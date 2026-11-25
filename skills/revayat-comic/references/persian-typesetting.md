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

### Pure-Rust shaping via `cosmic-text`

`revayat-comic` shapes and orders Persian directly in Rust with `cosmic-text`
(HarfBuzz + FriBidi) and the bundled Vazir font family (`Regular`, `Medium`,
`Bold`). There is no external `libraqm`, FriBidi DLL, or Python fallback
dependency: logical UTF-8 Persian is shaped and wrapped consistently on both
Linux and Windows (x64 and arm64), preserving U+0654 (ezafe hamza) and U+200C
(ZWNJ, نیم‌فاصله). Line spacing stays at least `1.38x` the font size so tall
ascenders and stacked lines never collide, and narrow bubbles keep punctuation
inside the bubble boundary.

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

Treat overflow as layout first, without lowering the agreed size floor:

1. Reflow the complete Persian and use the original's meaningful line breaks;
   a `\n` in `fa:` is honoured.
2. Re-read the source and choose a tighter complete rendering without dropping
   meaning, register or plot-relevant detail.
3. If a shorter displayed variant is needed, retain the complete rendering in
   `fa_full` and review the current source/full/display pair before approval.
4. Re-run merge, typography, typesetting and QA. If it still cannot fit, keep
   the region under review rather than shrinking below the floor or truncating.

## Colour, stroke, and text styles

- A light balloon gets near-black text.
- A dark balloon gets near-white text.
- Lettering with **no balloon** — a sign, a caption over artwork — gets a stroke
  in the opposite colour, because without it the text disappears into the
  drawing at exactly the moment it matters.

The skill ships official SIL OFL-1.1 **Vazir** fonts (`Vazir-Regular.ttf`,
`Vazir-Medium.ttf`, and `Vazir-Bold.ttf`) inside `assets/fonts/` and selects
them by default before checking system fonts, unless `--font` overrides it.

Regions can carry an optional `style:` field in worksheets (comma-separated
tokens, case-insensitive):

| Style token | Visual effect |
| --- | --- |
| `bold` | Selects bundled `Vazir-Bold.ttf` (or bold sibling of `--font`) |
| `italic` | Oblique shear on the HarfBuzz/RAQM-shaped layer so Persian letters stay connected |
| `bold-italic` | Combines bold weight and oblique shear |
| `outline` | Contrasting outer halo around glyphs (for titles, signs, and SFX over art) |
| `shadow` | Subtle 2px offset drop shadow behind glyphs |
| `shout` | Bold emphasis with a higher font-size harmonization ceiling |

`typeset` harmonizes font sizes across ordinary speech balloons on the same page
so a single short word beside a multi-line balloon does not jump to twice the
size. Even when `balloon` is unset, both `typefit` and `qa` detect bounded
white balloon enclosures around `bbox` and keep every rendered glyph pixel
strictly inside the eroded interior.

## Checking a result

Two questions, in this order:

1. **Is the shaping right?** Look for disconnected letters (`ک ت ا ب` instead of
   `کتاب`). That means neither RAQM nor the fallback ran — check `doctor`.
2. **Is the direction right?** Look at a line with a numeral in it. If the digits
   land at the wrong end, bidi did not run.

If both are right and it still looks wrong, it is a font problem, not a
direction problem.
