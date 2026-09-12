"""Set Persian into the balloons — shaped, wrapped to the balloon's real shape.

Three things here are non-negotiable, and each of them is a way this goes wrong
in almost every automated translation people publish:

**No string reversal, ever.** Persian is written right to left, but the
characters are stored in logical order and the *renderer* is what puts them on
the page. Reversing the string produces something that looks correct in one
viewer and is broken everywhere else, and it is unsearchable and uncopyable
even where it looks right. Direction comes from HarfBuzz and FriBidi through
Pillow's RAQM layout engine. If RAQM is missing, the reshaper fallback runs and
says so loudly, because pre-shaped text has the same defects in miniature.

**The balloon is not a rectangle.** A round balloon is narrow at the top, wide
in the middle and narrow again at the bottom, so a paragraph set to a constant
width either overflows the curve or wastes half the balloon. Every line is
measured against the width actually available in its own vertical band, which is
what a letterer does by hand.

**Text never silently shrinks to nothing.** Persian runs longer than Japanese;
when a translation will not fit, the size floor holds and the region is reported
as overflowing, so the answer is a shorter sentence rather than six-point type
nobody can read.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import lettering
import masks as mask_tools
import pageir as ir
import stages
from typefont import (  # noqa: F401 - re-exported: `typeset.find_font`
    FONT_DIRS,                                # and friends are the names
    PERSIAN_FONTS,                            # the CLI, `doctor` and the
    VAZIR_FONTS,                              # tests have always used.
    ZWNJ,
    Shaper,
    _numpy,
    _pil,
    _supports_persian,
    find_font,
    is_vazir,
    raqm_available,
    shape_fallback,
)

DEFAULT_MAX_SIZE = 64
DEFAULT_MIN_SIZE = 13
LINE_SPACING = 1.30
#: Keep this much of the balloon clear at its edge, as a share of its size.
BALLOON_PADDING = 0.10


# --------------------------------------------------------------------------- #
# Balloon interior
# --------------------------------------------------------------------------- #

def interior_mask(clean_rgb, region: dict[str, Any], page_size: tuple[int, int]):
    """The area available to write on, as a 0/255 mask over the whole page.

    Measured on the *cleaned* page, where the lettering is gone, so what is left
    inside the outline is exactly the space the Persian has. It is the same
    measurement the mask builder makes, with a larger inset: text needs to keep
    clear of the outline by more than a repair does.
    """
    np = _numpy()
    width, height = page_size
    balloon = region.get("balloon")

    if not balloon:
        # No balloon: the region's own box is all there is, which is right for a
        # sound effect or a caption drawn straight onto the artwork.
        canvas = np.zeros((height, width), np.uint8)
        x, y, w, h = ir.clamp_bbox(region["bbox"], width, height)
        canvas[y:y + h, x:x + w] = 255
        return canvas

    return mask_tools.balloon_interior(
        clean_rgb, balloon, region.get("polarity", "light"), (width, height),
        inset=BALLOON_PADDING,
    )


def _row_widths(mask, np) -> list[int]:
    """Per row: the widest continuous run of interior.

    Used for ONE question — how wide is the shape at this height — which is
    what tells a balloon's body from its tail. Placement does not come from
    here; a line spans many rows, and `_band_span` answers for the band.
    """
    widths: list[int] = []
    for row in mask:
        columns = np.flatnonzero(row)
        if columns.size == 0:
            widths.append(0)
            continue
        breaks = np.flatnonzero(np.diff(columns) > 1)
        segments = np.split(columns, breaks + 1)
        best = max(segments, key=len)
        widths.append(int(best[-1] - best[0] + 1))
    return widths


def _band_span(mask, np):
    """``span(first_row, last_row) -> (left column, width)`` for a band of rows.

    A line of text is one block of ink lying across every row of its band, so
    the columns it may use are the columns that are interior in **every** one
    of those rows. That is not what was asked before. Before, the width came
    from the narrowest row's own longest run and the position came from the
    middle row's, and on any shape whose rows do not line up — a leaning side,
    a tail, a hole, a row split into two runs by a balloon's divider — those
    are different columns. A line was then measured against one span and
    centred on another, so it could be declared to fit and still be drawn over
    the outline.

    Keeping only the longest run per row lost the rest of the row as well:
    a row split in two contributed one run, and which one depended on a pixel.
    The intersection uses the whole row and never has to choose.

    A prefix sum down the columns makes each band a subtraction, so asking
    forty times per size stays cheap.
    """
    height, width = mask.shape
    counts = np.zeros((height + 1, width), np.int32)
    # `> 0`, because a mask arrives as 0/255 as often as it arrives as booleans
    # and a sum of 255s compares against nothing useful.
    np.cumsum((mask > 0).astype(np.int32), axis=0, out=counts[1:])
    cache: dict[tuple[int, int], tuple[int, int]] = {}

    def span(first: int, last: int) -> tuple[int, int]:
        first, last = max(0, int(first)), min(height, int(last))
        if last <= first:
            return 0, 0
        key = (first, last)
        if key not in cache:
            shared = np.flatnonzero((counts[last] - counts[first]) == last - first)
            if shared.size == 0:
                cache[key] = (0, 0)
            else:
                runs = np.split(shared, np.flatnonzero(np.diff(shared) > 1) + 1)
                best = max(runs, key=len)
                cache[key] = (int(best[0]), int(best[-1] - best[0] + 1))
        return cache[key]

    return span


# --------------------------------------------------------------------------- #
# Wrapping
# --------------------------------------------------------------------------- #

def _tokens(text: str) -> list[list[str]]:
    """Break points, one list per hard line the translation asked for.

    A ZWNJ joins a word; a space separates two; a newline ends a line. The
    newline used to do none of those three. It is not `[ \t]`, so it was not
    collapsed, and it is not `" "`, so `split` left it sitting INSIDE a token —
    which was then measured as one word and handed to Pillow, which draws a
    string containing a newline as two lines of its own. Those extra lines fall
    below the band the fitter measured and outside a tight balloon, and nothing
    upstream had asked for them to be there.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraphs = []
    for line in lines:
        tokens = [token for token
                  in re.sub(r"[ \t]+", " ", line).strip().split(" ") if token]
        if tokens:
            paragraphs.append(tokens)
    return paragraphs


def stroke_for(size: int) -> int:
    """The outline width the renderer adds at this size.

    Asked in ONE place, because the fitter and the renderer disagreeing about
    it is the whole of the bug below.
    """
    return max(1, int(size) // 12)


def _measure(draw, text: str, font, shaper: Shaper,
             stroke_width: int = 0) -> tuple[int, int]:
    """The ink `text` puts down, INCLUDING the outline that will be drawn on it.

    `stroke_width` was not passed here while the draw added `size // 12` on
    every side, so the fitter accepted a line by measuring a box smaller than
    the one that got painted. With the house face the difference stayed inside
    the balloon and nothing noticed; with the fallback face the Persian spilled
    52 pixels past the balloon and the preservation gate — once it stopped
    deriving its own authorisation from the drawing — said so.
    """
    box = draw.textbbox((0, 0), shaper.prepare(text), font=font,
                        stroke_width=stroke_width, **shaper.draw_kwargs())
    return box[2] - box[0], box[3] - box[1]


#: A row counts as part of a balloon's body once it is at least this wide,
#: relative to the widest row. Below it, the shape is a tail or a spur.
BODY_WIDTH = 0.5


def _body(widths: Sequence[int]) -> tuple[int, int]:
    """``(first row, height)`` of the part of the shape text can actually go in.

    A speech balloon is not its bounding box: it has a **tail**, and the tail can
    be as tall as the balloon. Centring a block of text in the bounding box then
    lands it in the tail, where every row is a few pixels wide, and the region is
    reported as overflowing at every size down to the floor — measured on a real
    page, on a balloon with plenty of room in it.

    So the block is centred on the longest run of rows that are wide enough to
    be the body. On a shape with no tail every row qualifies and this is the
    bounding box again.
    """
    if not widths:
        return 0, 0
    threshold = max(widths) * BODY_WIDTH
    best_start = best_length = run_start = run_length = 0
    for index, width in enumerate(widths):
        if width >= threshold:
            if run_length == 0:
                run_start = index
            run_length += 1
            if run_length > best_length:
                best_start, best_length = run_start, run_length
        else:
            run_length = 0
    return best_start, best_length


def _wrap(draw, paragraphs: Sequence[Sequence[str]], font, shaper: Shaper,
          width_for_line, stroke_width: int = 0) -> list[str] | None:
    """Greedy wrap where each line asks how wide *it* is allowed to be.

    Each paragraph starts a new line: a break the translation put there is a
    decision about the balloon, not whitespace to reflow.
    """
    lines: list[str] = []
    for tokens in paragraphs:
        current = _wrap_one(draw, tokens, font, shaper, width_for_line,
                            stroke_width, lines)
        if current is None:
            return None
        if current:
            lines.append(current)
    return lines or None


def _wrap_one(draw, tokens: Sequence[str], font, shaper: Shaper,
              width_for_line, stroke_width: int, lines: list[str]) -> str | None:
    """One paragraph, appending its full lines to `lines` and returning the
    part still open. ``None`` when a word will not fit on a line of its own."""
    current = ""
    for token in tokens:
        available = width_for_line(len(lines))
        if available <= 0:
            return None
        trial = f"{current} {token}".strip()
        if _measure(draw, trial, font, shaper, stroke_width)[0] <= available:
            current = trial
            continue
        if current:
            lines.append(current)
            current = ""
            available = width_for_line(len(lines))
            if available <= 0:
                return None
        if _measure(draw, token, font, shaper, stroke_width)[0] > available:
            # One word that does not fit on a line of its own. Splitting a
            # Persian word is worse than a smaller font, so the caller retries.
            #
            # This measures the TOKEN, not `current`. Measuring `current` looked
            # equivalent and was not: when the very first word of a line is too
            # wide, `current` is still empty, an empty string measures 0, the
            # guard never fires and the word is dropped on the floor. The loop
            # then does the same to every word that follows, and returns whatever
            # short token happened to fit last — one line, status `ok`, the rest
            # of the sentence gone. Measured on a real page: a balloon reading
            # `پس بهتره بری خونه، نه؟` was typeset as `نه؟` at size 64 and
            # reported as placed.
            return None
        current = token
    return current


def fit_region(
    draw, text: str, mask, np, shaper: Shaper, font_path: Path,
    *, max_size: int, min_size: int, stroke: bool = False,
) -> dict[str, Any] | None:
    """Largest size at which `text` sets inside `mask`. ``None`` if it never does."""
    _, _, ImageFont = _pil()
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or columns.size == 0:
        return None
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    left, right = int(columns[0]), int(columns[-1]) + 1
    region_mask = mask[top:bottom, left:right]
    widths = _row_widths(region_mask, np)
    span = _band_span(region_mask, np)
    paragraphs = _tokens(text)
    if not paragraphs:
        return None

    body_top, body_height = _body(widths)
    if body_height <= 0:
        return None

    for size in range(int(max_size), int(min_size) - 1, -1):
        font = ImageFont.truetype(str(font_path), size, layout_engine=shaper.layout)
        # What this size will really cost once the outline is on it.
        stroke_px = stroke_for(size) if stroke else 0
        step = max(1, int(round(size * LINE_SPACING)))

        placement: list[int] | None = None
        lines: list[str] | None = None
        # The block's vertical position depends on how many lines it has, and
        # the number of lines depends on how wide each one is allowed to be,
        # which depends on the position. Two or three passes settle it.
        count = 1
        for _ in range(4):
            block = count * step
            if block > body_height:
                lines = None
                break
            offset = body_top + (body_height - block) // 2

            def width_for_line(index: int, offset=offset, step=step) -> int:
                start = offset + index * step
                return span(start, start + step)[1]

            lines = _wrap(draw, paragraphs, font, shaper, width_for_line,
                          stroke_px)
            if lines is None:
                break
            if len(lines) == count:
                placement = [offset, step]
                break
            count = len(lines)
        if lines is None or placement is None:
            continue

        offset, step = placement
        rendered: list[dict[str, Any]] = []
        overflow = False
        for index, line in enumerate(lines):
            start = offset + index * step
            band_left, available = span(start, start + step)
            if available <= 0:
                overflow = True
                break
            text_width, text_height = _measure(draw, line, font, shaper,
                                               stroke_px)
            if text_width > available:
                overflow = True
                break
            middle = start + step // 2
            # And the HEIGHT, which was measured and then thrown away. The only
            # vertical test was `count * step <= body_height`, and `step` is a
            # nominal `size * 1.30` — not what the face actually inks. With the
            # house font the difference stayed inside the balloon; with the
            # fallback face the line's ink reached past it, and the preservation
            # gate counted 52 pixels on the artwork. A line is drawn centred on
            # `middle`, so its ink runs half its height either side of that.
            half = text_height / 2.0
            if middle - half < 0 or middle + half > (bottom - top):
                overflow = True
                break
            centre_x = left + band_left + available / 2.0
            rendered.append({
                "text": line,
                "x": float(centre_x),
                "y": float(top + middle),
            })
        if overflow or not rendered:
            continue

        return {
            "size": size,
            "lines": rendered,
            "line_count": len(rendered),
            "font": font_path.name,
        }
    return None


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _text_colour(region: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int] | None]:
    """``(fill, stroke)``. A dark balloon needs light letters, and lettering on
    bare artwork needs an outline or it disappears into the drawing."""
    if region.get("polarity") == "dark":
        return (245, 245, 245), (12, 12, 12)
    if not region.get("balloon"):
        return (18, 18, 18), (250, 250, 250)
    return (18, 18, 18), None


def _restore(canvas, region: dict[str, Any], root: Path, np) -> None:
    """Put a region's original pixels back, bounded by its own mask.

    The mirror of `clean._composite` and bounded the same way: only pixels the
    mask authorises are written, so restoring can no more damage neighbouring
    artwork than cleaning could. Needed because the decision to leave an effect
    drawn can only be *finally* made once the Persian has been fitted, and by
    then `clean` has already erased it.
    """
    Image, _, _ = _pil()
    original = np.asarray(ir.load_image(root / region["_page_image"]))
    x, y, w, h = region["mask_box"]
    mask = mask_tools.load_mask(root / region["mask"])
    # `np.asarray(canvas)` is a read-only view of Pillow's own buffer; crop to a
    # real array, choose per pixel, and paste the result back.
    patch = np.array(canvas.crop((x, y, x + w, y + h)))
    keep = mask[..., None] > 0
    patch = np.where(keep, original[y:y + h, x:x + w], patch).astype(patch.dtype)
    canvas.paste(Image.fromarray(patch), (x, y))


def typeset_page(
    doc_path: Path,
    page: dict[str, Any],
    shaper: Shaper,
    font_path: Path,
    *,
    policy: str,
    max_size: int,
    min_size: int,
    stylise: bool = True,
) -> dict[str, Any]:
    Image, ImageDraw, ImageFont = _pil()
    np = _numpy()
    root = ir.doc_dir(doc_path)

    source = page.get("clean") or page["image"]
    canvas = ir.load_image(root / source).copy()
    for region in page.get("regions", []):
        # `_restore` needs the untouched page, not the cleaned one.
        region["_page_image"] = page["image"]
    clean_rgb = np.asarray(canvas)
    # An explicit copy, kept as the reference for "did this line land where
    # it was allowed to". `canvas` is drawn on in place below.
    before_draw = np.array(canvas)
    draw = ImageDraw.Draw(canvas)
    size = (page["width"], page["height"])

    # What this page is ALLOWED to have changed. It is built here, from the
    # geometry a person or the detector approved, and it is never widened
    # afterwards.
    #
    # It used to start as the lettering mask and then absorb the bounding box
    # of every line that was actually drawn. That made the preservation proof
    # circular: whatever the typesetter painted became, by definition, the
    # area it had been allowed to paint, so an overflow could not fail the
    # gate. Measured on a page whose text was shoved 260 px off its balloon,
    # the authorised area grew from 60,051 px to 531,746 — about a third of
    # the page — and `qa` reported no error at all.
    #
    # The balloon interior is the right authority rather than the lettering
    # mask: Persian set into a repainted balloon legitimately covers paper
    # the source glyphs never touched, and that paper is inside the balloon.
    writable = np.zeros((page["height"], page["width"]), np.uint8)
    union = page.get("mask")
    if union:
        writable = np.maximum(writable, mask_tools.load_mask(root / union))
    for region in page.get("regions", []):
        if region.get("dropped") or not (region.get("target_text") or "").strip():
            continue
        if region.get("balloon"):
            # `inset=0` deliberately, unlike `clean`. The inset is a CLEANING
            # conservatism — do not repaint the balloon's own outline — not a
            # statement about where text may go. Measured on a real Japanese
            # page: six pixels of one glyph's anti-aliased edge landed on the
            # outline it was set against, every one of them within two pixels
            # of the inset interior. The balloon is still the boundary; text
            # shoved off it entirely is still caught.
            interior = mask_tools.balloon_interior(
                before_draw, region["balloon"],
                region.get("polarity", "light"), size, inset=0.0,
            )
            writable = np.maximum(writable, np.asarray(interior, np.uint8))
        elif region.get("mask_box"):
            # Free lettering has no balloon, so the authorised area is the
            # box the region was masked at — approved geometry either way.
            bx, by, bw, bh = region["mask_box"]
            writable[by:by + bh, bx:bx + bw] = 255

    placed = 0
    overflow: list[str] = []
    unreliable: list[str] = []
    skipped = 0
    for region in page.get("regions", []):
        text = (region.get("target_text") or "").strip()
        if region.get("dropped") or not text:
            skipped += 1
            continue
        if region.get("keep") or (
                region["kind"] == "sfx" and policy == "keep"):
            skipped += 1
            continue

        fill, stroke = _text_colour(region)
        painted: list[list[int]] = []
        record: dict[str, Any] | None = None

        # Lettering that was drawn rather than typed: slant, arc and recession
        # measured from the mask `clean` erased, and matched only where the
        # measurement holds up. A balloon, a straight effect, or a region with
        # no mask of its own all take the flat path below.
        # `clean` measured this already, before it erased anything — reuse its
        # answer rather than measuring a second time. Two measurements of one
        # region can disagree, and only one of them decided whether the original
        # ink is still on the page.
        drawn = region.get("lettering")
        if drawn is None and stylise and region["kind"] == "sfx" \
                and region.get("mask"):
            drawn = lettering.measure(
                mask_tools.load_mask(root / region["mask"]), np,
                origin=region.get("mask_box", (0, 0))[:2],
            )
        if not stylise:
            drawn = None

        if drawn is not None and drawn["verdict"] == "unreliable":
            # `clean` saw this coming and did not erase it, so the lettering is
            # still on the page and "left as drawn" is true about actual pixels.
            # Stamping type that is confidently wrong about its own angle over
            # hand lettering is worse than leaving the original.
            #
            # This is the code declining to replace, never overriding a reader:
            # an explicit `keep: yes` was already honoured further up the loop.
            # `clean` already left this drawn and recorded `keep`; do not
            # overwrite that with "none", which claims nothing was decided.
            region["fill"] = "keep"
            region["typeset"] = {"status": "unreliable",
                                 "style": "unreliable",
                                 "reason": drawn.get("reason", "")}
            note = f"sound effect left as drawn: {drawn.get('reason', '')}"
            if note not in region.get("review", []):
                region.setdefault("review", []).append(note)
            unreliable.append(region["id"])
            skipped += 1
            continue

        if drawn is not None and drawn["verdict"] != "flat":
            done = lettering.render(
                canvas, text, drawn, shaper, font_path, fill, stroke, np,
                fit_region, _pil(), max_size=max_size, min_size=min_size)
            if done is not None:
                painted.append(done.pop("box"))
                record = {"status": "ok", **done}
            elif drawn["verdict"] in {"curved", "warped"}:
                # A strongly stylised effect that will not fit its own shape.
                # Setting it flat would replace an arc of hand lettering with a
                # horizontal line of type — the "visibly worse" case
                # `sound-effects.md` exists to avoid. `clean` already erased it,
                # so the honest answer is to put the original ink back under its
                # own mask and ask for a person.
                _restore(canvas, region, root, np)
                # The original ink is back on the page, so that is what `fill`
                # has to say — whatever `clean` did has been undone.
                region["fill"] = "keep"
                region["typeset"] = {"status": "unreliable", "style": drawn["verdict"],
                                     "reason": "the Persian does not fit the "
                                               "shape the lettering was drawn in"}
                region.setdefault("review", []).append(
                    f"sound effect restored as drawn: the Persian does not fit "
                    f"the {drawn['verdict']} shape it was lettered in")
                unreliable.append(region["id"])
                skipped += 1
                continue

        if record is None:
            area = interior_mask(clean_rgb, region, size)
            fitted = fit_region(
                draw, text, area, np, shaper, font_path,
                max_size=max_size, min_size=min_size, stroke=bool(stroke),
            )
            if fitted is None:
                overflow.append(region["id"])
                region["typeset"] = {"status": "overflow"}
                continue

            font = ImageFont.truetype(str(font_path), fitted["size"],
                                      layout_engine=shaper.layout)
            for line in fitted["lines"]:
                shaped = shaper.prepare(line["text"])
                options: dict[str, Any] = {
                    "font": font, "fill": fill, "anchor": "mm",
                    **shaper.draw_kwargs(),
                }
                if stroke:
                    options["stroke_width"] = stroke_for(fitted["size"])
                    options["stroke_fill"] = stroke
                draw.text((line["x"], line["y"]), shaped, **options)
                box = draw.textbbox((line["x"], line["y"]), shaped, **{
                    k: v for k, v in options.items()
                    if k != "fill" and k != "stroke_fill"
                })
                painted.append([int(box[0]), int(box[1]),
                                int(box[2]), int(box[3])])
            record = {
                "status": "ok",
                "style": "flat",
                "size": fitted["size"],
                "lines": fitted["line_count"],
                "font": fitted["font"],
                "shaping": shaper.mode,
            }

        # The check that replaces the old widening. Compare the pixels that
        # actually changed against the area this region was authorised for,
        # and say so when ink landed outside it. A bounding box would be too
        # crude: the corners of a box around a line of Persian sit outside
        # the balloon on a curve, while the ink itself does not.
        if painted:
            x0 = max(0, min(box[0] for box in painted))
            y0 = max(0, min(box[1] for box in painted))
            x1 = min(page["width"], max(box[2] for box in painted))
            y1 = min(page["height"], max(box[3] for box in painted))
            if x1 > x0 and y1 > y0:
                after = np.asarray(canvas)[y0:y1, x0:x1]
                changed = (before_draw[y0:y1, x0:x1] != after).any(axis=2)
                stray = int((changed & (writable[y0:y1, x0:x1] == 0)).sum())
                if stray:
                    # Painted, checked, and taken back off again. Noticing the
                    # overflow after the ink is down is not enough — the ink is
                    # down, and the gate is right to count it. Restoring the
                    # rectangle leaves the cleaned page exactly as it was and
                    # the region honestly marked `overflow`, which is what "the
                    # words do not fit this balloon" has always meant here: the
                    # Persian is shortened and merged again, not shipped over
                    # the artwork.
                    Image = _pil()[0]
                    canvas.paste(
                        Image.fromarray(before_draw[y0:y1, x0:x1]), (x0, y0))
                    painted.clear()
                    record["status"] = "overflow"
                    record["outside_authorised"] = stray
                    if region["id"] not in overflow:
                        overflow.append(region["id"])

        region["typeset"] = record
        placed += 1

    for region in page.get("regions", []):
        region.pop("_page_image", None)

    relative = f"final/{page['id']}.png"
    ir.save_image(canvas, root / relative)
    page["final"] = relative

    writable_path = f"masks/{page['id']}/writable.png"
    ir.write_bytes(root / writable_path,
                   mask_tools._encode_png(Image.fromarray(writable, mode="L")))
    page["writable"] = writable_path

    return {"placed": placed, "overflow": overflow, "skipped": skipped,
            "unreliable": unreliable}


def typeset_document(
    doc_path: str | Path,
    *,
    font: str | None = None,
    max_size: int = DEFAULT_MAX_SIZE,
    min_size: int = DEFAULT_MIN_SIZE,
    force_fallback: bool = False,
    pages: Sequence[str] | None = None,
    stylise: bool = True,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    policy = doc["meta"].get("sfx_policy", "keep")

    font_path = find_font(font)
    if not _supports_persian(font_path):
        raise ir.MissingDependency(
            f"{font_path.name} does not draw Persian — the test word came out "
            "blank or as tofu boxes.\nInstall Vazirmatn and pass it with "
            "--font, or name another Persian face you have."
        )
    shaper = Shaper(force_fallback=force_fallback)

    placed = 0
    overflow: list[str] = []
    unreliable: list[str] = []
    per_page: list[dict[str, Any]] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        if not page.get("regions"):
            continue
        result = typeset_page(
            doc_path, page, shaper, font_path,
            policy=policy, max_size=max_size, min_size=min_size,
            stylise=stylise,
        )
        placed += result["placed"]
        overflow += result["overflow"]
        unreliable += result["unreliable"]
        per_page.append({"page": page["id"], **result})

    stages.stamp_stage(doc, "typeset", {
        "placed": placed, "font": font_path.name, "shaping": shaper.mode,
        "vazir": is_vazir(font_path),
    })
    ir.save_doc(doc, doc_path)

    note = None
    if not is_vazir(font_path):
        note = (
            f"Persian in this project is set in Vazir; this run used "
            f"{font_path.name}. The pages are readable and the type is not the "
            f"house face. Install Vazirmatn "
            f"(https://github.com/rastikerdar/vazirmatn/releases) or pass "
            f"--font /path/to/Vazirmatn-Medium.ttf."
        )

    return {
        "document": str(doc_path),
        "font": str(font_path),
        "vazir": is_vazir(font_path),
        "font_note": note,
        "shaping": shaper.mode,
        "placed": placed,
        "overflow": overflow[:30],
        "overflow_count": len(overflow),
        "unreliable": unreliable[:30],
        "unreliable_count": len(unreliable),
        "pages": per_page,
        "warning": None if shaper.raqm else (
            "Pillow has no RAQM here, so Persian was shaped and reordered by "
            "arabic-reshaper and python-bidi instead of HarfBuzz and FriBidi. "
            "The pages are correct to read, so this is a note, not a fault. "
            "Pillow's wheels DO carry libraqm on Windows and macOS as well as Linux; what is missing here is FriBiDi, which libraqm loads at run time. On Windows, put a `fribidi.dll` (or `fribidi-0.dll` / `libfribidi-0.dll`) on PATH and RAQM turns on — beside python.exe is not enough, it has to be a directory in the DLL search order. Measured: with one on PATH this machine reports raqm true. See references/persian-typesetting.md for what differs."
        ),
        "next": (
            f"{len(overflow)} region(s) did not fit at the minimum size. Shorten "
            "those translations in the worksheet and re-run merge and typeset."
        ) if overflow else "Run `qa check`.",
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic typeset",
        description="Set the Persian translations into the cleaned pages.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--font", default=None,
                        help="a Persian font file or family name")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE)
    parser.add_argument("--min-size", type=int, default=DEFAULT_MIN_SIZE,
                        help="never set smaller than this; report overflow instead")
    parser.add_argument("--no-raqm", action="store_true",
                        help="force the reshaper fallback (for testing it)")
    parser.add_argument("--flat-sfx", action="store_true",
                        help="set every sound effect horizontally, even where "
                             "the mask shows the original was on a slant")
    args = parser.parse_args(argv)

    report = typeset_document(
        args.doc,
        font=args.font,
        max_size=args.max_size,
        min_size=args.min_size,
        force_fallback=args.no_raqm,
        pages=[p for p in args.pages.split(",") if p] or None,
        stylise=not args.flat_sfx,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
