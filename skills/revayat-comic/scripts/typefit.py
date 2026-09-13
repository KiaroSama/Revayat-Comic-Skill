"""Where the words go: the balloon's real shape, wrapping, and the size that
fits.

Measurement only. Nothing here puts ink on a page — `typeset.py` does that, and
the two were one file until it ran past the size it stays readable at.

**The balloon is not a rectangle.** A round balloon is narrow at the top, wide
in the middle and narrow again at the bottom, so a paragraph set to a constant
width either overflows the curve or wastes half the balloon. Every line is
measured against the width available in its own vertical band, which is what a
letterer does by hand.

**Text never silently shrinks to nothing.** Persian runs longer than Japanese;
when a translation will not fit, the size floor holds and the region is
reported as overflowing, so the answer is a shorter sentence rather than
six-point type nobody can read.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

import masks as mask_tools
import pageir as ir
from typefont import Shaper, _numpy, _pil

LINE_SPACING = 1.30
BALLOON_PADDING = 0.10
DEFAULT_MAX_SIZE = 64
DEFAULT_MIN_SIZE = 13


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
