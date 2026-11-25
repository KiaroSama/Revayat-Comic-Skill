# Persian typesetting

How Persian gets onto the page, what can go wrong, and the two things to check
before blaming the renderer.

## Never reverse a string

Persian is stored in **logical order** — the order it is spoken — and displayed
right to left. Those are different things, and the renderer is what connects
them. Reversing the string yourself produces text that looks correct in one
viewer and is broken in every other, cannot be searched or copied, and breaks
again the moment a Latin word or a number appears in it.

`revayat-comic` stores logical text. The Rust shaping and pipeline tests are in
`rust/revayat-vision/src/typefont.rs` and
`rust/revayat-vision/tests/pipeline.rs`; regression cases for embedded isolates
and Persian join controls are in `tests/audit_regressions.rs` in that crate.

## The font is Vazir

The skill bundles the SIL OFL-1.1 **Vazir** family in `assets/fonts/`:
`Vazir-Regular.ttf`, `Vazir-Medium.ttf`, and `Vazir-Bold.ttf`, together with the
font license. The renderer loads those embedded faces into its own font
database. It does not depend on a font installed on the host, and the current
`typeset` command has no custom-font flag.

## Shaping and bidi

Arabic-script text needs two things done to it before it can be drawn:

- **Shaping** — each letter takes a different form depending on its neighbours.
  `ب` is `بـ` at the start of a word, `ـبـ` in the middle, `ـب` at the end.
- **Bidi** — resolving the direction of a mixed run, so `نسخهٔ 2.5 را دانلود کن`
  puts the numeral in the right place inside the Persian.

### Pure-Rust shaping via `cosmic-text`

`revayat-comic` shapes and orders Persian in Rust with `cosmic-text`, using
HarfRust for shaping, `unicode-bidi` for bidirectional layout, and Swash for
rasterization. No external RAQM, HarfBuzz, or FriBidi installation is required.
Logical UTF-8 text retains U+0654 (ezafe hamza), U+200C (ZWNJ, نیم‌فاصله), and
authored directional isolates. Isolates that span a wrapped line are closed and
reopened at the visual boundary; the stored source text remains logical.

Line spacing is at least `1.38x` the font size. The fitter checks the actual
glyph raster, outline, shadow, and occupied pixels before placing each line;
line spacing alone is not proof that a particular layout fits.

## Fitting a balloon

A balloon is not a rectangle. A round one is narrow at the top, wide in the
middle and narrow again at the bottom, so a paragraph set to one constant width
either overflows the curve or wastes half the balloon.

The fitter measures the **interior of the balloon itself** on the cleaned page:
the connected region of paper inside the outline, eroded so the text keeps clear
of the border. Then, for each candidate font size, it asks each line how wide it
is allowed to be *in its own vertical band*, wraps to that, and accepts the
largest size where every line fits.

The search is bounded: for each decreasing integer font size it tries up to six
wrap widths and five vertical offsets. It accepts only a placement whose ink
fits the current region and does not overlap already placed text.

The Rust `TextRegion` API exposes these settings. The CLI uses the defaults and
the page font-size cap; it does not expose font-size or shaping-backend flags.

| Rust field | Default | Effect |
| --- | --- | --- |
| `max_size` | 72 | upper bound, also constrained by the page cap |
| `min_size` | 8 | lower bound; the fitter does not cross it |
| `line_spacing` | 1.38 | line height relative to font size, clamped to at least 1.38 |
| `align` | center | horizontal line placement |

Text uses an interior inset of 4.5% of the balloon's smaller side, with a
minimum of one pixel. The fit adds clearance for its padding and any outline
or shadow. Cleaning uses a separate 3.5% outline inset.

## Overflow

When a translation will not fit at the configured lower bound, the typesetting
operation returns an overflow error instead of publishing a partial page. That
is deliberate. The alternatives are worse:

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
- Lettering over artwork can request a contrasting stroke with `style: outline`.
  Review the result against the actual drawing and the QA contrast check.

Regions can carry an optional `style:` field in worksheets (comma-separated
tokens, case-insensitive):

| Style token | Visual effect |
| --- | --- |
| `bold` | Selects the bundled bold weight |
| `italic` | Oblique shear on the already shaped raster so Persian letters stay connected |
| `bold-italic` | Combines bold weight and oblique shear |
| `outline` | Contrasting outer halo around glyphs (for titles, signs, and SFX over art) |
| `shadow` | Subtle 2px offset drop shadow behind glyphs |
| `shout` | Bold emphasis within the same page font-size cap |

`typeset` harmonizes font sizes across ordinary speech balloons on the same page
so a single short word beside a multi-line balloon does not jump to twice the
size. Even when `balloon` is unset, both `typefit` and `qa` detect bounded
white balloon enclosures around `bbox` and keep every rendered glyph pixel
strictly inside the eroded interior.

## Checking a result

Two questions, in this order:

1. **Is the shaping right?** Look for disconnected letters (`ک ت ا ب` instead of
   `کتاب`). Check `doctor`, the logical input, and the actual rendered page;
   unexpected disconnected letters need review.
2. **Is the direction right?** Look at a line with a numeral in it. If the digits
   land at the wrong end, bidi did not run.

If both are right, inspect font size, weight, line breaks, and the measured
interior. Keep the complete meaning and readable type when correcting layout.
