# Artwork preservation

The guarantee this project is built around, how it is enforced, and what it does
not cover.

## The guarantee

> Every pixel outside the authorised mask is byte-identical to the page that
> came in.

Not "we try not to touch the artwork". Identical, and proved by comparison after
the fact. `qa check` reports `artwork_pixels_changed`, and on a correct run it
is `0`.

## Why this and not something else

Every automated comic translator asks whether the text was replaced. None of
them ask what else changed while it was being replaced. That gap hides a whole
class of failure that no completeness check can see, because nothing is missing:

- an inpainter that smeared past its region and softened a face
- a renderer that drew a descender across a panel border
- a resize that resampled the whole page and blurred the screentone
- a generative model that quietly redrew an eye two panels away

Each of those produces a page with the right number of balloons, the right
translations, and damaged artwork. The sibling novel project shipped a bug of
exactly this shape: every gate measured whether something was *missing*, and
none asked whether something was there twice.

## How it is enforced

Three layers, and the last one is not trusted to the first two.

### 1. The mask is the glyph shapes, not the box

A box is not a mask. Painting the whole box white erases the balloon outline and
whatever artwork the box overlaps. So the mask is the ink shapes themselves,
grown by a measured amount to swallow the anti-aliased edge of a glyph, and then
clipped.

The clip is to the balloon's **real interior**, not its bounding box. The corners
of a box around an ellipse are outside the balloon; clipping to the box repaints
the artwork in those corners and erases the parts of the outline that cross
them. Measured — it left every balloon as a pair of arcs with a white rectangle
punched through the screentone behind it.

The interior is then inset by `OUTLINE_INSET` (3.5% of the balloon's smaller
side), which puts the outline structurally out of reach.

### 2. The composite can only touch the mask

Whatever produced the repaired pixels, they are composited back through the
mask:

    out = original * (1 - alpha) + repaired * alpha        where alpha <= mask

`alpha` is a blurred mask clamped back to the hard mask, so the blend ramp lives
*inside* the authorised area. A Gaussian spreads outward, and without the clamp
the ramp leaks a few pixels past the mask and fails the very check it exists to
pass.

Because `alpha` is zero everywhere the mask is zero, preservation holds by
construction rather than by good behaviour. That is what makes
`clean --external` safe: hand it a page a generative model redrew from scratch,
and only the masked pixels of it are ever used.

### 3. QA proves it anyway

`qa check` re-opens the original page, the finished page and the mask, and
compares. It also re-hashes the original page file: if that changed after
import, every box and mask was measured against pixels that no longer exist,
and the run is invalid (`source-modified`).

## The writable area is larger than the clean mask

Cleaning may repaint the glyph shapes. Typesetting may draw Persian anywhere in
the balloon — Persian usually needs more room than vertical Japanese did, so the
text mask alone would be too small.

So there are two authorised areas, and the union of them is what QA checks:

- `masks/pNNNN/union.png` — the cleaning mask, the glyph shapes
- `masks/pNNNN/writable.png` — that, plus the boxes actually painted by the
  typesetter, written at typeset time

`writable.png` records what was *actually drawn*, not what might have been.

**Each region is bounded by its own area, not by that union.** The union is
what QA measures the finished page against; it is not a permission the
typesetter may spend. Ink from one balloon landing inside the next balloon is
outside *this* region's authority however legitimately that balloon belongs to
somebody else, so the line is reported as `text-overflow` and taken back off
the page. Two balloons side by side is the ordinary case, not a corner one.

A rejected line restores the page **as it stands**, with every region already
set on it — not as it was before any region drew. Restoring the older snapshot
erased the finished translation of every neighbour whose ink shared a rectangle
with the one that did not fit.

## The cleaning tiers

Escalate; do not reach for the expensive tool first.

| Tier | When | What it does |
| --- | --- | --- |
| `flat` | the background inside the balloon is uniform | reads the balloon's own colour and paints it back — exact, no model |
| `inpaint` | there is line art or texture under the lettering | OpenCV Telea propagates the surrounding structure inwards |
| `external` | you have something better | your image, composited through the mask |
| `external` via `--provider` | an image model, called for you | its page, composited through the same mask |
| `keep` | a sound effect under the `keep` or `annotate` policy | nothing; the artwork is the sound effect |

"Uniform" is measured on the pixels *inside the balloon* that are not being
repainted. Sampling the whole crop picks up the outline and the artwork behind
the balloon, and a plain white balloon on screentone then measures as textured —
nine balloons out of nine went to the inpainter before that was fixed.

Telea is not a generative model. It will not invent a face; on a screentone
gradient it produces a smooth patch. That is the honest failure and it is
visible in review, which is why `clean` reports `inpaint_heavy_pages`.

## Plugging in a better cleaner

There is no LaMa, no diffusion model and no cloud image API in this repository,
on purpose: each is a large dependency, a separately licensed model checkpoint,
and a decision about sending someone's artwork to a third party. The hook is
one flag instead.

```bash
# clean the pages with whatever you like, into cleaned/pNNNN.png
revayat-comic clean --doc work/comic.json --external cleaned/
```

The images must be the same size as the originals; a different size is refused
rather than resampled. Only their masked pixels are used, so the preservation
guarantee still holds — which is the point. A generative cleaner is exactly the
tool you most want a hard boundary around.

### Or let `clean` make the call for you

```bash
revayat-comic clean --doc work/comic.json --provider <name>
```

Same composite, one fewer step: the model's page goes through the identical
per-region masking and participates in none of the arithmetic that bounds it.

One real provider ships: `openai-compatible-image`, which posts to whatever is
at `REVAYAT_API_BASE` — a hosted image endpoint or a server on your own machine.
Set `REVAYAT_IMAGE_MODEL`, and `REVAYAT_API_KEY` when the endpoint wants one.
See the module docstring in `scripts/adapters.py` for writing another; it is
about twenty lines and nothing in this file changes for it.

**But it is not treated like `--external`, and the difference is deliberate.**

| | who decided | which regions |
| --- | --- | --- |
| `--external` | a person, about the whole page | **every** authorised region |
| `--provider` | the pipeline, per region | only where the deterministic tiers give up |

`--external` means somebody looked at the chapter and replaced these pages. It
would be wrong to second-guess that region by region and quietly use only a
fraction of what they supplied.

A provider is the pipeline choosing to spend a model call, so it escalates: a
flat balloon is repaired by reading its own colour and painting it back — exact,
instant, better than any model — and the provider is reached only for a region
that needs inpainting, or a solid free-lettering patch.

**Which means an all-flat page never calls the model at all.** The call is made
lazily, at the first region that actually needs it, once per page. A chapter of
ordinary dialogue balloons costs nothing.

**Proved against a hostile provider, not a polite one.** The test fake discards
the page entirely and returns flat red — every pixel changed — and the assertion
is that **zero** pixels outside the mask differ from the original, on every page.
The same test then checks that pixels *inside* the mask did change, because a
guarantee that passes because nothing happened proves nothing.

Any failure at all — a timeout, an exception, a refusal, a page that came back
the wrong size — falls back to the classical tiers above and records why. A
generative cleaner having a bad day cannot stall a chapter or leave a page
half-written.

### Give it the whole patch, not the letter shapes

For lettering **drawn onto the artwork** — a sound effect, a sign, a caption with
no balloon around it — the default mask is the wrong shape to hand a model. It
is the glyph outlines, so a reconstruction gets clipped back to strokes a few
pixels wide: the model has to invent artwork inside each letter, and every seam
lands on a glyph edge, which is exactly where the eye goes. The result reads as
*repaired*, not as *redrawn*, no matter how good the model is.

```bash
revayat-comic mask  --doc work/comic.json --free-lettering solid
revayat-comic clean --doc work/comic.json --external reconstructed/
```

`solid` covers each region with no balloon as one filled patch, so the model gets
a coherent area and can redraw what was under the lettering. Balloons are
untouched by the flag — a solid mask over a balloon would take its outline with
it, which is the defect the interior clip exists to prevent.

**This mode only works with `--external`.** The choice is recorded in the
document, and `clean` refuses to run its own cleaners against it: painting a
solid patch flat, or handing it to Telea, blanks a rectangle out of the drawing.
Measured with Telea standing in for a model, it erased the speed lines around a
`BUMP` and left a soft grey blob — worse than the glyph mask, and a fair picture
of what "not a generative model" means.

## And the other direction: did the lettering actually go?

Everything above proves nothing changed that *should not* have. On its own that
leaves the mirror-image hole: **nothing proved that what should have gone,
went.** A mask that misses the tail of a stroke leaves a rim of the source
script inside the balloon; the page has the right number of balloons, the right
translations, and Japanese still on it. `qa check` reports that as
`source-text-survived`.

It measures inside the **balloon interior only**, and that restriction is the
whole reason it means anything: there the paper is flat, so ink left after
cleaning is a missed stroke and nothing else. Measured over the padded mask box
instead, it reads the balloon's own outline as un-removed text and returns 100%
on a perfect run. For lettering drawn straight onto artwork there is no such
separation — leftover ink is indistinguishable from the drawing it sits on — so
those regions are not judged, and that is listed below as a gap rather than
papered over.

The fix when it fires is a wider mask, not a looser check: re-run `mask` with a
larger `--grow` for that page, then `clean` again.

## What this does not cover

- **Free lettering.** `source-text-survived` judges balloons only. A sound
  effect on artwork whose mask missed a stroke is not caught by anything.
- **Inside the mask, anything goes.** If the inpainter produces a smear where
  the artwork had detail, no check here will notice. Look at
  `inpaint_heavy_pages`.
- **A sound effect that was replaced is gone.** Under `translate`, the original
  lettering is removed and the artwork under it reconstructed. That is the
  policy doing what it was asked; it is not reversible.
- **JPEG round-tripping.** Exporting with `--jpeg-quality` re-encodes every page
  and changes pixels everywhere, by design. Verify with `qa check` *before*
  exporting, and note that JPEG is not even smaller for line art — flat whites
  and hard ink edges compress better as PNG.
