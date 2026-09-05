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

## Correcting a region

You do not edit boxes by hand. The worksheet is where corrections go, because
that is where the reader is already looking at the crop:

- `drop: yes` — there is no text here
- `kind:` — it is a sign, not speech
- `speaker:` — who is talking

A region that has been answered is **locked**, and a later `detect` run skips
its page rather than renumbering ids the worksheet already refers to.

## Webtoons

A webtoon strip is one very tall image with no panels and no gutters. `import`
flags it (`webtoon_strips`) and the right settings are `--direction ltr` and low
expectations of the panel pass. Balloon detection itself works normally; it is
the ordering that has nothing to work with beyond top-to-bottom, which for a
webtoon is the correct order anyway.
