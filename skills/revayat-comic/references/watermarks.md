# Removing a watermark

A watermark, a site stamp, a scan credit, a preview overlay — ink on the page
that is not part of the story and that you want gone, with nothing put in its
place.

## First, whether it is yours to remove

The pipeline cannot tell one mark from another, and it will erase whatever box
you give it. The difference is yours to know:

**Ordinary work.** Your own watermark on your own pages. A preview or proof
mark on material you bought or licensed. A scan whose group told you it was
fine. A stamp you added yourself and now want off.

**Not.** Another group's credit, or a publisher's mark, stripped off someone
else's book so it can be passed on. That is removing the attribution and the
copyright notice from a work, which in a number of jurisdictions is its own
offence separate from the copying — and this repository's own README already
says the artwork this tool processes is usually someone else's.

There is no flag for this and no prompt asking you to confirm. It is a judgement,
you are the one making it, and it is worth making deliberately rather than by
default.

## What it is, technically

Nothing new. A watermark is an ordinary region carrying one extra fact:

```
erase: yes
```

which means *remove this and put nothing back*. It is the fifth terminal state,
beside `translated`, `kept_by_policy`, `dropped_false_detection` and
`needs_review` — and it exists because none of the other four says this:

| you mean | say | what happens |
| --- | --- | --- |
| there is no ink here, the detector was wrong | `drop: yes` | not masked, not cleaned |
| there IS ink and I want it left alone | `keep: yes` | stays drawn, counted as a decision |
| there is text and here is the Persian | `fa: …` | cleaned, then Persian set over it |
| **remove this, put nothing back** | **`erase: yes`** | **cleaned, nothing set** |

An erase region goes through the *same* path as everything else: masked by
`mask`, cleaned by `clean` through the ordinary tier ladder — flat fill, then
classical inpainting, then an image-edit provider — skipped by `typeset` because
there is no Persian to set, and held by `qa` to the same proof as every other
region.

**The preservation guarantee is unchanged.** Not one pixel outside the box you
gave can move, and that is arithmetic rather than a promise:
`out = original × (1 − alpha) + repaired × alpha` with `alpha ≤ mask`. Measured
on a page with a corner stamp: 5267 dark pixels inside the box before, 0 after,
and `artwork_pixels_changed: 0` from the gate.

## The three shapes, and what each one needs

### 1. The same place on every page

A site stamp in the corner of all two hundred pages. One command:

```bash
revayat-comic watermark --doc work/comic.json --box "12 1840 300 44"
revayat-comic mask  --doc work/comic.json     # the new boxes need masks
revayat-comic clean --doc work/comic.json
```

`--box` is `x y w h` in the page's own pixels — read them straight off
`crops/pNNNN/overview.png`, which is drawn at page scale.

Re-running **moves** the box rather than adding a second one; they are
identified by `--label`, so a wrong box on two hundred pages is fixed by running
the command again with the right numbers. Use a different `--label` when there
are genuinely two marks.

`--pages p0001,p0002` limits it. Pages the box does not fit — a double spread, a
colour insert at another size — are listed in `refused` rather than marked with
a sliver at the edge.

Two guards worth knowing about, because they will occasionally refuse a box you
meant: one under `4×4` is treated as a dropped digit, and one covering more than
**25%** of the page is treated as a mistyped coordinate. A mark is a mark on a
page; a box over most of the page asks the inpainter to invent a panel.

### 2. A different place on each page

This is the reading model's job, not a script's. It is already looking at
`overview.png` and the crop sheets to transcribe the page — a watermark is one
more thing it can see, and it can see it in context, which is exactly what a
detector cannot do.

If the detector already found the mark as a region, mark that region:

```
@@ p0004r007 sign horizontal
erase: yes
```

More often it did not — a stamp is not lettering in a balloon. Then add it, with
the same `+slug` and `box:` that any missed region uses:

```
@@ +stamp sign horizontal
box: 742 1836 300 44
erase: yes
```

Then `mask` again before `clean`, because a new box has no mask yet.

Marking `keep: yes` and `erase: yes` on the same region is refused and reported
under `conflicting_actions` — they are opposite instructions and guessing which
one was meant is how a mark stays on the page while the report says it went.

### 3. Over the artwork, not in a corner

A translucent mark spread across the whole page, tiled, or sitting on top of a
face.

**Be clear-eyed about what happens here.** Masking and inpainting do not
*recover* what was under a watermark — that information is not in the file. They
replace it: flat fill copies the surrounding paper, classical inpainting
diffuses from the edges, and a generative provider draws something plausible.
Over flat paper or simple screentone the result is usually indistinguishable.
Over a face, detailed line art, or a tiled overlay covering a quarter of the
page, it is a reconstruction, and it will look like one.

So:

- A **small** mark over artwork: mark it and let the ladder work. Check the
  result; the region is yours to re-mark or revert.
- A mark over a **face or fine line art**: use an image-edit provider
  (`clean --provider openai-compatible-image`, see
  `artwork-preservation.md`). It is still reconstruction, but a better one.
- A **tiled or full-page** overlay: the 25% guard will refuse it, and that
  refusal is doing its job. There is no honest way to take a translucent layer
  off a flattened image — the pixels are mixed, and un-mixing them needs the
  original. If you have a cleaner source, use the cleaner source.

## What the report tells you

After `clean`, the terminal-state census in `qa check` counts them:

```json
"states": { "translated": 41, "erased": 2, "kept_by_policy": 3 }
```

`erased` means the cleaner actually acted. A region you marked but that the
cleaner declined — a solid free-lettering mask with no provider configured, for
instance — comes back as `needs_review`, not `erased`. That distinction is the
point: reporting `erased` on intent alone would say a watermark is gone while it
is still on the page, which is the same failure the census exists to prevent,
pointed the other way.

## What is not here

**No automatic detection by a script.** There is no CV pass that hunts for
watermarks. The reading model finding them is better — it sees the page and
knows what belongs to the story — and a script that guesses would erase artwork
on its false positives, which is unrecoverable in a way a missed watermark is
not.

**No re-watermarking.** Putting your own mark on is a different job and a
different tool; nothing here adds ink.
