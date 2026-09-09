# Detection

What the detector finds, what it does not, and which knob to turn.

## What it is

Classical computer vision, deliberately. A vision model describes a page far
better than this code can, but it cannot return a box accurate to the pixel —
and a box that is wrong by four pixels leaves a rim of Japanese around every
cleaned balloon. So geometry is measured here, and judgement is left to the
reader looking at the crops.

Three things are found, in descending order of reliability.

### 1. Balloons — reliable

A speech balloon is a light region enclosed by its own outline, so it survives
as one connected component while the page background stays a different one.
Both polarities are searched: white balloons with black lettering, and black
balloons with white lettering.

The lettering inside is absorbed first, so a balloon crossed by a long vertical
line of kanji comes back as one region rather than two. That fill is by
*solidity*, not by size: a letter is a solid blob and a balloon outline is a
thin ring, and only the blobs are filled. Filling every enclosed hole fills the
outline as well, and welds the balloon to the page background.

Then the text box inside is the bounding box of the glyph-sized components,
with the outline's own ring excluded.

### 2. Panels — approximate, and only used for order

A recursive cut along the gutters: rows of near-zero ink that run the width of
a block become horizontal splits, columns become vertical ones, and each piece
recurses up to six levels deep.

Panels are only used to order the balloons, so being approximately right is
enough. If the page has no clean gutters — a splash page, or artwork bleeding
across the whole sheet — no panels are reported and reading order falls back to
plain geometry, which is the right answer for that page anyway.

### 3. Free lettering — unreliable, and marked as such

Sound effects, signs, captions drawn straight onto the artwork. Glyph-sized
marks are found and then clustered by proximity *relative to their own size*,
because letters in a word sit closer together than a word sits to the artwork
around it.

A single dilation cannot do this clustering. Its reach is one number for the
whole page, so a value that groups small dialogue type leaves a large sound
effect as four unrelated blobs and drops it silently, while a value that catches
the sound effect welds every line of dialogue into one block.

Every region from this path is given confidence `0.35` — below any sensible
review threshold — and the worksheet marks it `LOW CONFIDENCE`. That is not
hedging: hand-drawn lettering leans, stretches, outlines itself and merges into
the artwork, and this finds the obvious ones and is wrong about the rest.

## Reading order

Panels first, then bands within a panel, then position within a band:

- Panels are ordered by band, right-to-left for `rtl` and left-to-right for
  `ltr`.
- Within a panel, regions are grouped into bands that overlap vertically. Two
  balloons side by side are one band even when one sits four pixels higher —
  sorting by `y` alone reads wrong on every page that has a pair.
- Within a band, right-to-left or left-to-right.
- A region belonging to no panel is read last: it is usually a caption in the
  gutter or a sound effect spilling across the page.

`--direction` is how the **source** is read. Japanese manga is `rtl`. Korean
webtoons, Chinese manhua and Western comics are `ltr`. Getting it wrong does not
fail — it numbers the balloons backwards, and the translation then answers
questions that have not been asked yet.

## The knobs

Every threshold is a fraction of the page, and every one is on the command line,
because the right value is a property of the book rather than of this code. A
900-pixel web scan and a 4000-pixel tankobon scan disagree about what "small"
means.

| Flag | Default | What it controls |
| --- | --- | --- |
| `--balloon-min-area` | 0.0006 | smallest balloon, as a share of page area |
| `--balloon-max-area` | 0.13 | largest; the ceiling that keeps panels out |
| `--balloon-min-side` | 0.05 | smallest side, as a share of the page's smaller side |
| `--balloon-min-solidity` | 0.42 | how blobby a balloon is |
| `--ink-min` / `--ink-max` | 0.015 / 0.55 | how much lettering a balloon holds |
| `--glyph-min` / `--glyph-max` | 0.004 / 0.22 | what counts as a letter |
| `--gutter-max-ink` | 0.008 | how clean a gutter must be |
| `--gutter-min-span` | 0.012 | how wide a gutter must be |
| `--panel-min-area` | 0.02 | smallest panel worth reporting |
| `--sfx-min-side` | 0.035 | smallest piece of free lettering |
| `--sfx-min-glyphs` | 3 | how many marks make a word |
| `--sfx-size-uniformity` | 0.80 | how alike those marks must be |
| `--sfx-max-spread` | 1.5 | how far they may stray across their own line |

## Symptoms and fixes

| What you see | Why | What to do |
| --- | --- | --- |
| whole panels detected as balloons | sparse pages; a panel interior is also a light region inside an outline | lower `--balloon-max-area` |
| balloons missed | thin or broken outlines, or heavy screentone inside | raise `--ink-max`, lower `--balloon-min-solidity` |
| every line of text sprouts small extra regions | the gaps between letters passing as balloons | raise `--balloon-min-side` |
| dozens of low-confidence regions on a textured page | screentone clustering as lettering | `--no-sfx`, then `drop: yes` on anything left |
| a sound effect comes back as several regions | letters spaced further apart than usual | raise `--sfx-min-side` is *wrong* here; the clustering is size-relative, so check the marks were seeded at all with `--glyph-max` |
| one page-sized panel | no clean gutters | expected on a splash page; order falls back to geometry |
| `pages_without_text` on most pages | the thresholds do not fit this book | start with `--balloon-min-area 0.0003 --ink-min 0.008` |
| balloons missed **only** on a high-resolution scan | the outline is a hairline relative to the page | see *Resolution* below |

## Free lettering, and what those three knobs are for

An eye and a letter O are the same blob, so nothing about a *single* mark can
say which is which. What separates writing is how a **set** of marks relates:
several of them, near enough one size, sitting along a line. That is all three
knobs above, and on real artwork they do the heavy lifting — a textless splash
page produced nineteen regions without them, and three with.

`--sfx-size-uniformity` is the one to reach for first and the one to trust: a
font's letters are within a factor of two of each other, while hair, screentone
and cloth folds produce every size at once, and it is the only test here that
does not care about orientation or how many lines the lettering runs to.
`--sfx-max-spread` catches what passes on size. Lower `--sfx-min-glyphs` below 3
only if you are losing two-character effects and can live with the noise.

The pass is still the weak one, and it stays that way: everything it returns is
low confidence, and the reader is asked to drop what is not text.

## Correcting a region

You do not edit boxes by hand. The worksheet is where corrections go, because
that is where the reader is already looking at the crop:

- `drop: yes` — there is no text here
- `keep: yes` — there *is* text, and it stays in the artwork
- `kind:` — it is a sign, not speech
- `speaker:` — who is talking
- `@@ +<name>` with `box: x y w h` — **there is text here and no region on it**

The last one is the counterpart to `drop`, and a real page needs both. Free
lettering is missed, adjacent balloons come back welded into one region, and a
panel is sometimes taken for a balloon and swallows what is drawn inside it —
each of those loses text that is plainly there in `overview.png`.

**Splitting a merged pair** is a drop plus two adds:

```
@@ p0005r011 speech horizontal
drop: yes

@@ +eh speech horizontal
box: 744 434 50 26
src: EH?
fa: ها؟

@@ +leaving speech horizontal
box: 612 522 138 78
src: YOU'RE LEAVING ALREADY?
fa: به این زودی می‌ری؟
```

Say `speech` on the header and `mask` finds the balloon around each box for you,
so both halves are clipped to their own interior like any detected balloon. Say
nothing, or `sfx`, and the box is treated as lettering on open artwork. Re-run
`mask` after a merge that added regions; merging again updates the same regions
rather than making more, and re-drawing a `box:` moves the one that is there.

Draw the box around **all** of the lettering. One drawn a few pixels too tight
on the left left the `A` of `ALREADY` on the cleaned page — `source-text-survived`
caught it, and the fix was a wider box, not a looser gate.

A region that has been answered is **locked**, and a later `detect` run skips
its page rather than renumbering ids the worksheet already refers to.

## Webtoons

A webtoon strip is one very tall image with no panels and no gutters. `import`
flags it (`webtoon_strips`) and the right settings are `--direction ltr` and low
expectations of the panel pass. Balloon detection itself works normally; it is
the ordering that has nothing to work with beyond top-to-bottom, which for a
webtoon is the correct order anyway.

## Resolution

Every threshold here is a fraction of the page, so the detector is
scale-invariant **provided the artwork scales with the raster**. A real scan
does: a tankobon at 300 dpi has a proportionally thicker balloon outline than
the same art at 96 dpi, because it is the same ink measured with more pixels.
Measured on A4 at 300 dpi (2480×3508), detection is exact — every balloon, every
panel, at the same numbers as a 1000×1500 page.

The counter-case is art whose line weight did **not** scale with the raster: a
small drawing upsampled, or vector line art rendered thin at high DPI. A
four-pixel outline on a 2480-pixel page is 0.16% of the width — thinner than the
ink and solidity heuristics expect — and balloons are missed.

That is a property of the input, not a threshold bug. Loosening the heuristics
enough to catch a hairline also makes every screentone gradient a balloon. On
such a book, try in this order:

1. `--balloon-min-solidity 0.30` — the usual fix. A hairline-outlined balloon
   still reads as blobby, just less so.
2. `--ink-min 0.008` — thin lettering holds less ink than the default assumes.
3. Downsample the pages before importing. If the extra pixels came from
   upsampling they carry no more detail, and they cost detection accuracy.

`tests/test_resolution.py` pins both the working case and this limit across four
page sizes, so neither can move silently. The weekly
`.github/workflows/integration.yml` runs a whole four-page chapter at 300 dpi
end to end.

## A character is not a connected component

The free-lettering test asks whether a cluster's marks are alike in size, and it
is the strongest of the three because letters cut from one font are within a
factor of two of each other while artwork is not. It has one blind spot, and it
took a page drawn with a real Japanese face to find it.

**ド is ト plus two tiny dakuten. ン is two strokes.** So a three-character
katakana effect arrives as six components — measured at 110 px: three around
85 px and three around 20 px — and the size test scores 3/6 against a threshold
of 0.80 and throws the whole effect away. Both balloons on the same page were
found at 0.80 while the effect was invisible.

Marks far below the cluster's median that sit right against a bigger one are
now folded into it before the test runs. The threshold is the same 0.55 the size
test uses as its lower bound, on purpose: it absorbs exactly the marks that test
would have rejected and nothing else. Merging can only lower the count, so it
can make the glyph minimum harder to reach but never invents a cluster.

The same shape exists in Latin — an i and its tittle, a j, an exclamation mark —
so this is not a Japanese special case. Measured across four real English pages
already on disk: 71 regions before, 72 after.
