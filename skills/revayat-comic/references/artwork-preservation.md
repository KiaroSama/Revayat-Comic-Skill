# Artwork preservation

After merging worksheets or changing source text, source language, geometry, or keep/erase decisions, rebuild masks before cleaning. Retain any approved free-lettering mask option; target-text or target-language-only edits require typesetting again, without rebuilding masks or cleaning.

The guarantee this project is built around, how it is enforced, and what it does
not cover.

## The guarantee

> Every pixel outside the authorised mask is byte-identical to the page that
> came in.

Not "we try not to touch the artwork". Identical, and proved by comparison after
the fact. `qa check` reports `artwork_pixels_changed`, and on a correct run it
is `0`.

## Why this and not something else

Checking only whether text was replaced misses what else changed during the
replacement. That gap hides a whole
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

Generated authorization masks are binary. The compositor computes its feather
from the distance to the mask boundary and keeps the blend ramp *inside* the
authorized area. Pixels outside the mask have zero alpha.

Because `alpha` is zero everywhere the mask is zero, preservation holds by
construction rather than by good behaviour. That is what makes
`clean --external-dir` safe: hand it a page a generative model redrew from scratch,
and only the masked pixels of it are ever used.

### 3. QA proves it anyway

`qa check` re-opens the original page, the finished page and the mask, and
compares. It also re-hashes the original page file: if that changed after
import, every box and mask was measured against pixels that no longer exist,
and the run is invalid (`source-modified`).

Cleaning and typesetting keep 8-bit and 16-bit integer source samples, including
alpha, in their PNG artifacts. RGB8 processing edits are composited into a copy
of the native source: unmasked samples remain exact, unchanged color channels
retain their original precision, and alpha remains unchanged. Colored edits to
a grayscale source promote it to RGB or RGBA at the original bit depth. Native
QA compares integer RGBA values at 16-bit precision, so low-bit or alpha changes
cannot disappear in an RGB8 comparison. Floating-point/HDR processing is refused
because these PNG artifacts cannot preserve that source representation.

## The writable area is larger than the clean mask

Cleaning may repaint the glyph shapes. Typesetting may draw Persian anywhere in
the balloon — Persian usually needs more room than vertical Japanese did, so the
text mask alone would be too small.

So there are two authorised areas, and the union of them is what QA checks:

- `page.clean_mask` in `comic.json` — the pixels authorized by the cleaning pass
- `page.authorized_mask` — that mask plus independently approved balloon
  interiors or free-lettering areas used by typesetting

These fields point to content-addressed PNG artifacts. Follow the recorded
paths rather than assuming a fixed filename. Authorization comes from approved
geometry, never from whatever ink the renderer happened to paint.

**Each region is bounded by its own area, not by that union.** The union is
what QA measures the finished page against; it is not a permission the
typesetter may spend. Ink from one balloon landing inside the next balloon is
outside *this* region's authority however legitimately that balloon belongs to
somebody else. The fitter checks each region's own boundary and already occupied
pixels. If a requested region cannot fit, it returns an overflow error without
publishing a partially typeset page. Two balloons side by side are an ordinary
case, and their shared enclosure is partitioned before placement.

## The cleaning tiers

Escalate; do not reach for the expensive tool first.

| Tier | When | What it does |
| --- | --- | --- |
| `flat` | the background inside the balloon is uniform | reads the balloon's own colour and paints it back — exact, no model |
| `inpaint` | the unmasked background is not uniform | the pure-Rust cleaner diffuses neighboring RGB values into the masked area |
| `external` | you supply an approved reconstruction | your image, composited through the mask |
| `keep` | a sound effect under the `keep` or `annotate` policy | nothing; the artwork is the sound effect |

"Uniform" is measured on the pixels *inside the balloon* that are not being
repainted. Sampling the whole crop picks up the outline and the artwork behind
the balloon, and a plain white balloon on screentone then measures as textured —
nine balloons out of nine went to the inpainter before that was fixed.

Diffusion is not a generative model. It will not redraw a face or reconstruct
detailed screentone. Inspect the cleaned image and the `fill` strategy recorded
on free-lettering regions; the current CLI does not emit an
`inpaint_heavy_pages` summary.

## Plugging in a better cleaner

The CLI accepts page images made with an external editing tool. It does not
invoke an image model from `clean`; selecting an editor and submitting artwork
remain separate, explicit actions.

```bash
# clean the pages with whatever you like, into cleaned/pNNNN.png
revayat-comic clean --doc work/comic.json --external-dir cleaned/
```

The images must be the same size as the originals; a different size is refused
rather than resampled. Only their masked pixels are used, so the preservation
guarantee still holds — which is the point. A generative cleaner is exactly the
tool you most want a hard boundary around.

### Full-page editing with local balloon text

For titles and lettering integrated into the drawing, use the full-page prompt
workflow:

```bash
revayat-comic clean --doc work/comic.json --bubbles-only
revayat-comic fullpage-prompt --doc work/comic.json --page p0001 --model MODEL
# Submit the generated page/prompt with your editing tool and save p0001.png.
revayat-comic typeset --doc work/comic.json --external-dir edited/
```

The prompt command prepares instructions; it does not call the provider. Review
the returned image before supplying it. `typeset` composites only approved
on-art regions, shields closed balloons from the external page, and draws the
balloon text locally. Missing external pages use the local path; an external
image with different dimensions fails the operation instead of being resized.

`clean --external-dir` supplies reconstruction pixels for free lettering while
closed balloons still use deterministic cleaning. A solid free-lettering patch
needs an approved external repair; a failed or missing image does not authorize
blanking the artwork as a fallback. The implementation is in
`rust/revayat-vision/src/clean.rs` and
`rust/revayat-comic-cli/src/processing/lettering.rs`.

### Give it the whole patch, not the letter shapes

For lettering **drawn onto the artwork** — a sound effect, a sign, a caption with
no balloon around it — the default mask is the wrong shape to hand a model. It
is the glyph outlines, so a reconstruction gets clipped back to strokes a few
pixels wide: the model has to invent artwork inside each letter, and every seam
lands on a glyph edge, which is exactly where the eye goes. The result reads as
*repaired*, not as *redrawn*, no matter how good the model is.

```bash
revayat-comic mask  --doc work/comic.json --free-lettering solid
revayat-comic clean --doc work/comic.json --external-dir reconstructed/
```

`solid` covers each region with no balloon as one filled patch, so the model gets
a coherent area and can redraw what was under the lettering. Balloons are
untouched by the flag — a solid mask over a balloon would take its outline with
it, which is the defect the interior clip exists to prevent.

**This mode requires `--external-dir` for a repair.** `clean` refuses a solid
erase mask without an approved external image. Filling that patch with one
color or diffusing its edges cannot reconstruct the drawing it covers.

## And the other direction: did the lettering actually go?

Everything above proves nothing changed that *should not* have. On its own that
leaves the mirror-image hole: **nothing proved that what should have gone,
went.** A mask that misses the tail of a stroke leaves a rim of the source
script inside the balloon; the page has the right number of balloons, the right
translations, and Japanese still on it. `qa check` reports that as
`balloon-ink-survives`.

It measures inside the **balloon interior only**, and that restriction is the
whole reason it means anything: there the paper is flat, so ink left after
cleaning is a missed stroke and nothing else. Measured over the padded mask box
instead, it reads the balloon's own outline as un-removed text and returns 100%
on a perfect run. For lettering drawn straight onto artwork there is no such
separation — leftover ink is indistinguishable from the drawing it sits on — so
those regions are not judged, and that is listed below as a gap rather than
papered over.

Review the current text box, balloon enclosure, and polarity when it fires.
Correct a clipped box or wrong enclosure, then run `mask` and `clean` again.
The current CLI has no mask-growth flag; do not loosen the QA check to hide
remaining source ink.

## What this does not cover

- **Free lettering.** `balloon-ink-survives` judges balloons only. A sound
  effect on artwork whose mask missed a stroke is not caught by anything.
- **Inside the mask, anything goes.** If the inpainter produces a smear where
  the artwork had detail, the outside-mask comparison cannot judge that repair.
  Inspect every reconstructed region.
- **A sound effect that was replaced is gone.** Under `translate`, the original
  lettering is removed and the artwork under it reconstructed. That is the
  policy doing what it was asked; it is not reversible.
- **Lossy derivatives.** Re-encoding a delivered page as JPEG in another tool
  can change pixels outside text masks. Keep it separate from the certified
  primary edition. The current export command has no JPEG-quality option.

## Page dimensions, resolution and poor scans

The primary translated edition keeps page count/order, spreads, strip height,
aspect ratios and native raster dimensions. Never crop, pad, split, join or
downsample pages merely to fit Persian or reduce file size. Keep the lossless
processed pages, original source files, and their hashes.

PDF paper size is separate from pixel resolution: a 400x600 image placed on a
200x300-point sheet must retain both measurements. New PDF imports record the
visible page dimensions (after its existing crop/rotation), and PDF export
uses those point dimensions without resampling the embedded raster. The original
media/crop boxes and rotation remain in `source_pdf_geometry`; the exported
sheet is normalized to the same visible size. Legacy documents lack that data
and keep the historical pixel-as-point behavior until re-imported. Images with
no physical page metadata have no known paper size; do not invent a claim that
their output PDF matches an unknown print edition.

A complex PDF is rasterized at the selected import DPI or the densest embedded
image's effective resolution, whichever is higher, unlike a plain scan whose
native pixels can be extracted. Rotated/cropped scans retain that density too.
Inspect effective resolution and record
that conversion. Do not lower import DPI just to bypass a resource limit;
process a smaller chapter or report the limit. Integrity comparison never uses
a reduced thumbnail to certify a modified PDF.

At import, inspect small lettering, screentone, line edges, blur and compression
at native scale. Do not upscale an already legible high-quality page by default.
For a poor scan, first prefer a better source, then try conservative enhancement
on a **separate reading copy**. Record the tool/model version, settings, input
and output dimensions, and the observed benefit in the translation activity log.
Compare both versions: reject broken strokes, invented marks, haloing, moire,
lost tone dots and tile seams. Upsampling adds pixels, not proof of recovered
letters. If a word remains uncertain, keep it under review.

The reading copy can help transcription while all masks and the final primary
edition remain on the immutable native raster. Whole-page enhancement changes
artwork outside text masks, so it cannot claim `artwork_pixels_changed: 0`
against the original. If an enhanced delivery is wanted, keep it as an explicitly
labeled additional derivative with the original edition retained, preserve its
aspect ratio and known physical page size, never reduce its pixel dimensions,
and report the transformation honestly. Do not overwrite the source, reset its
hash, or silently substitute the enhanced copy for the certified edition.

No upscaler is bundled or required by this skill. Use an available suitable
tool when it improves the actual scan; if none is available, record the specific
quality issue and limitation instead of claiming enhancement happened.
