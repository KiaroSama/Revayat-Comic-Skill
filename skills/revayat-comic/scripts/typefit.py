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

import hotcore
import pageir as ir
from qachecks import BALLOON_TEXT_INSET, balloon_text_interior
from typefont import Shaper, _numpy, _pil

LINE_SPACING = 1.30
BALLOON_PADDING = BALLOON_TEXT_INSET
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
    enclosed = balloon_text_interior(clean_rgb, region, page_size)
    if enclosed is not None:
        return enclosed
    # Unenclosed lettering stays in its own box.
    canvas = np.zeros((height, width), np.uint8)
    x, y, w, h = ir.clamp_bbox(region["bbox"], width, height)
    canvas[y:y + h, x:x + w] = 255
    return canvas


def _row_widths(mask, np) -> list[int]:
    """Per row: the widest continuous run of interior."""
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
    """``span(first_row, last_row) -> (left column, width)`` for a band of rows."""
    height, width = mask.shape
    counts = np.zeros((height + 1, width), np.int32)
    np.cumsum((mask > 0).astype(np.int32), axis=0, out=counts[1:])
    cache: dict[tuple[int, int], tuple[int, int]] = {}

    def span(first: int, last: int) -> tuple[int, int]:
        clamped_first = max(0, int(first))
        clamped_last = min(height, int(last))
        if clamped_last <= clamped_first:
            return 0, 0
        key = (clamped_first, clamped_last)
        if key not in cache:
            shared = np.flatnonzero(
                (counts[clamped_last] - counts[clamped_first]) == clamped_last - clamped_first
            )
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
    if not text.strip():
        return []
    # RAQM expects one paragraph per shaped line (Pillow #10317).
    lines = re.split(r"\r\n|[\r\n\u0085\u2028\u2029]", text)
    paragraphs = []
    for line in lines:
        tokens = [token for token
                  in re.sub(r"[ \t]+", " ", line).strip().split(" ") if token]
        paragraphs.append(tokens)
    return paragraphs


#: What a STYLED effect draws, as a fraction of the type size, taken from
#: `lettering`'s own constants and kept honest by a test that recomputes them
#: from that module.
#:
#: `MAX_STROKE` is the widest outline the styled renderer will ask for, and the
#: modulated pass then draws it again at `1 + MAX_MODULATION / 2` — the heavy
#: half of a brush that changes weight along the word. Reserving the outline
#: without that factor reserved about two thirds of what gets painted.
STYLED_STROKE = 0.22 * (1.0 + 0.8 / 2.0)
STYLED_SHADOW = 0.11

#: And what the PLAIN renderer adds when a region is outlined for contrast on a
#: dark balloon: `size // 12`, about 8%, and no shadow, no modulation, no nib.
PLAIN_STROKE_DIVISOR = 12


def stroke_for(size: int, styled: bool = False) -> int:
    """The outline width the renderer adds at this size.

    Asked in ONE place, because the fitter and the renderer disagreeing about
    it is the whole of the bug below — and they did disagree for the styled
    path, which is the one that draws the most. The plain renderer adds
    `size // 12` on every side, about 8%; a styled effect adds up to 22%
    widened by the modulated pass, plus a shadow, so an 80x50 strip accepted
    size 35, was drawn with an outline bounding box of (-6, 11, 86, 52), and
    was clipped by the page.

    The extra pixel is the heavy half of a modulated stroke, which the renderer
    adds to `stroke_width` and the fitter never knew about.
    """
    size = int(size)
    if styled:
        return max(1, int(round(size * STYLED_STROKE)) + 1)
    return max(1, size // PLAIN_STROKE_DIVISOR)


def shadow_for(size: int, styled: bool = False) -> int:
    """How far past the glyphs a styled effect's shadow reaches.

    Down and to the right only, but the fit is measured as a box, so it is
    reserved on every side rather than modelled as a direction — the cheaper
    answer, and the one that cannot be wrong in the direction that clips.
    """
    return max(1, int(round(int(size) * STYLED_SHADOW))) if styled else 0


def envelope_for(size: int, *, outline: bool = False,
                 styled: bool = False) -> int:
    """What a renderer puts down beyond the glyphs, at its widest.

    ONE boolean used to decide this and it was the wrong one: both callers pass
    `stroke=bool(stroke)`, where `stroke` is a COLOUR — "does this text get an
    outline for contrast" — and the fitter read it as "is this a styled sound
    effect". So a dialogue balloon on a dark page reserved the whole styled
    envelope, three times what its plain outline draws, and was set small or
    refused for want of room it was never going to use; while a styled effect
    with no outline colour reserved nothing at all and still got a shadow.

    Two questions, both asked here:

    * **outline** — the flat renderer's contrast outline. `size // 12` on every
      side, no shadow, no modulation.
    * **styled** — the sound-effect renderer at its heaviest: a shadow, which
      it draws whether or not the effect is outlined, and the widest modulated
      outline it will ask for.

    The styled answer is the WORST case. A particular effect draws less than
    that, and `lettering.strip_envelope` computes what that one will actually
    draw from its own measured style — which is what the fitter is given, so a
    delicate effect is not refused the room a heavy one would have needed.
    """
    if styled:
        return (shadow_for(size, styled=True)
                + (stroke_for(size, styled=True) if outline else 0))
    return stroke_for(size) if outline else 0


def _anchored_box(draw, text: str, font, shaper: Shaper, stroke_width: int = 0):
    return draw.textbbox((0, 0), shaper.prepare(text), font=font, anchor="mm",
                        stroke_width=stroke_width, **shaper.draw_kwargs())


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
    box = _anchored_box(draw, text, font, shaper, stroke_width)
    return box[2] - box[0], box[3] - box[1]


#: A row counts as part of a balloon's body once it is at least this wide,
#: relative to the widest row. Below it, the shape is a tail or a spur.
BODY_WIDTH = 0.5


def _body(widths: Sequence[int], *, reference: int | None = None) -> tuple[int, int]:
    """``(first row, height)`` of the part of the shape text can actually go in."""
    ref = -1 if reference is None else int(reference)
    start, length = hotcore.body_bounds(list(widths), ref, BODY_WIDTH)
    return int(start), int(length)


def _candidate_bodies(widths: Sequence[int]) -> list[tuple[int, int]]:
    """Primary `_body(widths)` plus robust quantile fallbacks when a thin wide
    edge spike (open margin or twin-balloon bridge) starves the primary band."""
    return [
        (int(start), int(length))
        for start, length in hotcore.candidate_bodies(list(widths), BODY_WIDTH)
    ]


def _wrap(draw, paragraphs: Sequence[Sequence[str]], font, shaper: Shaper,
          width_for_line, stroke_width: int = 0, *, measure_width=None) -> list[str] | None:
    """Greedy wrap where each line asks how wide *it* is allowed to be.

    Each paragraph starts a new line: a break the translation put there is a
    decision about the balloon, not whitespace to reflow.
    """
    if measure_width is None:
        def measure_width(line):
            return _measure(draw, line, font, shaper, stroke_width)[0]
    lines: list[str] = []
    for tokens in paragraphs:
        if not tokens:
            lines.append("")
            continue
        current = _wrap_one(tokens, width_for_line, measure_width, lines)
        if current is None:
            return None
        if current:
            lines.append(current)
    return lines or None


def _wrap_one(tokens: Sequence[str], width_for_line, measure_width, lines: list[str]) -> str | None:
    """One paragraph, appending its full lines to `lines` and returning the
    part still open. ``None`` when a word will not fit on a line of its own."""
    current = ""
    for token in tokens:
        available = width_for_line(len(lines))
        if available <= 0:
            return None
        trial = f"{current} {token}".strip()
        if measure_width(trial) <= available:
            current = trial
            continue
        if current:
            lines.append(current)
            current = ""
            available = width_for_line(len(lines))
            if available <= 0:
                return None
        if measure_width(token) > available:
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
    *, max_size: int, min_size: int, outline: bool = False,
    styled: bool = False, envelope: Any = None, line_effects=None,
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
    if not any(paragraphs):
        return None

    bodies = _candidate_bodies(widths)
    if not bodies:
        return None

    probe = " ".join(token for paragraph in paragraphs for token in paragraph)

    def _try_size(body_top: int, body_height: int, size: int) -> dict[str, Any] | None:
        font = ImageFont.truetype(str(font_path), size, layout_engine=shaper.layout)
        effects = line_effects(size) if line_effects is not None else None
        stroke_px = effects.stroke if effects is not None else (
            int(envelope(size)) if envelope is not None
            else envelope_for(size, outline=outline, styled=styled)
        )
        boxes = {}

        def bounds(line):
            if line not in boxes:
                box = _anchored_box(draw, line, font, shaper, stroke_px) if line else (0, 0, 0, 0)
                boxes[line] = effects.bounds(box) if effects is not None else box
            return boxes[line]

        def measure_width(line):
            x0, _, x1, _ = bounds(line)
            return x1 - x0

        _, probe_top, _, probe_bottom = bounds(probe)
        step = max(1, round(size * LINE_SPACING), probe_bottom - probe_top)

        placement: list[int] | None = None
        lines: list[str] | None = None
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

            lines = _wrap(draw, paragraphs, font, shaper, width_for_line, measure_width=measure_width)
            if lines is None:
                break
            if len(lines) == count:
                placement = [offset, step]
                break
            count = len(lines)
        if lines is None or placement is None:
            return None

        offset, step = placement
        rendered: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            start = offset + index * step
            box = bounds(line)
            text_width, text_height = box[2] - box[0], box[3] - box[1]
            if text_height > step:
                return None
            ink_top = start + (step - text_height) // 2
            # The entire rendered rectangle must fit every row it occupies.
            band_left, available = span(ink_top, ink_top + text_height) if text_height else (0, 0)
            if text_width > available:
                return None
            anchor_x = left + band_left + (available - text_width) // 2 - box[0]
            anchor_y = top + ink_top - box[1]
            rendered.append({
                "text": line,
                "x": float(anchor_x),
                "y": float(anchor_y),
            })
        if not rendered:
            return None
        return {
            "size": size,
            "lines": rendered,
            "line_count": len(rendered),
            "font": font_path.name,
        }

    lo_bound, hi_bound = int(min_size), int(max_size)
    if hi_bound < lo_bound:
        return None

    for body_top, body_height in bodies:
        lo, hi = lo_bound, hi_bound
        best_result: dict[str, Any] | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            res = _try_size(body_top, body_height, mid)
            if res is not None:
                best_result = res
                lo = mid + 1
            else:
                hi = mid - 1
        if best_result is not None:
            # Check a small neighborhood above the binary-search pivot in case a
            # discrete word-wrap break makes `pivot + 1` or `pivot + 2` fit too.
            for probe_size in range(min(hi_bound, best_result["size"] + 2), best_result["size"], -1):
                higher = _try_size(body_top, body_height, probe_size)
                if higher is not None:
                    best_result = higher
                    break
            return best_result
    return None


def partition_shared_interiors(
    authority: dict[str, tuple[int, int, Any]],
    enclosed: set[str],
    regions: list[dict[str, Any]],
    page_size: tuple[int, int],
    np,
    *,
    seam_margin: int = 2,
) -> None:
    """Split connected multi-lobe balloon interiors among their member regions.

    When two or more translatable regions share one flood-filled white cavity
    (for example a figure-8 double balloon), every region otherwise receives
    the whole cavity and the first region in reading order steals the widest
    lobe — swapping reading order upside-down. Assigning each cavity pixel to
    the member whose original ``bbox`` is closest keeps every region inside its
    own lobe without altering the outer balloon walls.
    """
    def _unpack(entry: Any) -> tuple[int, int, Any, bool]:
        if isinstance(entry, tuple):
            return entry[0], entry[1], entry[2], True
        return 0, 0, entry, False

    members = [
        region for region in regions
        if region["id"] in enclosed
        and region.get("bbox")
        and region["id"] in authority
        and _unpack(authority[region["id"]])[2] is not None
        and _unpack(authority[region["id"]])[2].size > 0
    ]
    if len(members) < 2:
        return

    def _overlaps(a_id: str, b_id: str) -> bool:
        ax, ay, ap, _ = _unpack(authority[a_id])
        bx, by, bp, _ = _unpack(authority[b_id])
        x0, y0 = max(ax, bx), max(ay, by)
        x1 = min(ax + ap.shape[1], bx + bp.shape[1])
        y1 = min(ay + ap.shape[0], by + bp.shape[0])
        if x1 <= x0 or y1 <= y0:
            return False
        sa = ap[y0 - ay:y1 - ay, x0 - ax:x1 - ax]
        sb = bp[y0 - by:y1 - by, x0 - bx:x1 - bx]
        return bool(np.any((sa > 0) & (sb > 0)))

    # Group mutually overlapping enclosed regions into connected components.
    n = len(members)
    adj: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if _overlaps(members[i]["id"], members[j]["id"]):
                adj[i].append(j)
                adj[j].append(i)

    seen = [False] * n
    for start in range(n):
        if seen[start] or not adj[start]:
            continue
        stack = [start]
        seen[start] = True
        comp: list[dict[str, Any]] = []
        while stack:
            idx = stack.pop()
            comp.append(members[idx])
            for nxt in adj[idx]:
                if not seen[nxt]:
                    seen[nxt] = True
                    stack.append(nxt)

        unpacked = {r["id"]: _unpack(authority[r["id"]]) for r in comp}
        ux0 = min(unpacked[r["id"]][0] for r in comp)
        uy0 = min(unpacked[r["id"]][1] for r in comp)
        ux1 = max(unpacked[r["id"]][0] + unpacked[r["id"]][2].shape[1] for r in comp)
        uy1 = max(unpacked[r["id"]][1] + unpacked[r["id"]][2].shape[0] for r in comp)
        uw, uh = ux1 - ux0, uy1 - uy0
        if uw <= 0 or uh <= 0:
            continue

        union = np.zeros((uh, uw), dtype=bool)
        for r in comp:
            ax, ay, ap, _ = unpacked[r["id"]]
            union[ay - uy0:ay - uy0 + ap.shape[0], ax - ux0:ax - ux0 + ap.shape[1]] |= (ap > 0)

        ys, xs = np.nonzero(union)
        if ys.size == 0:
            continue
        px = (xs + ux0).astype(np.int64)
        py = (ys + uy0).astype(np.int64)

        best_owner = np.zeros(px.size, dtype=np.int32)
        best_rect = np.full(px.size, np.iinfo(np.int64).max, dtype=np.int64)
        best_cen = np.full(px.size, np.inf, dtype=np.float64)

        for owner_idx, r in enumerate(comp):
            bx, by, bw, bh = ir.clamp_bbox(r["bbox"], *page_size)
            dx = np.maximum(0, np.maximum(bx - px, px - (bx + max(1, bw) - 1)))
            dy = np.maximum(0, np.maximum(by - py, py - (by + max(1, bh) - 1)))
            rect_d2 = dx * dx + dy * dy
            cx = bx + bw / 2.0
            cy = by + bh / 2.0
            cen_d2 = (px - cx) ** 2 + (py - cy) ** 2
            better = (rect_d2 < best_rect) | ((rect_d2 == best_rect) & (cen_d2 < best_cen))
            best_owner[better] = owner_idx
            best_rect[better] = rect_d2[better]
            best_cen[better] = cen_d2[better]

        owner_grid = np.full((uh, uw), -1, dtype=np.int32)
        owner_grid[ys, xs] = best_owner

        for owner_idx, r in enumerate(comp):
            rid = r["id"]
            ax, ay, ap, is_tuple = unpacked[rid]
            sub = np.zeros((uh, uw), dtype=bool)
            sub[ay - uy0:ay - uy0 + ap.shape[0], ax - ux0:ax - ux0 + ap.shape[1]] = (ap > 0)
            mine = sub & (owner_grid == owner_idx)
            if seam_margin > 0:
                other = (owner_grid >= 0) & (owner_grid != owner_idx)
                # Trim only pixels adjacent to another lobe's partition, never outer walls.
                near_other = other.copy()
                for _ in range(seam_margin):
                    grown = near_other.copy()
                    grown[1:, :] |= near_other[:-1, :]
                    grown[:-1, :] |= near_other[1:, :]
                    grown[:, 1:] |= near_other[:, :-1]
                    grown[:, :-1] |= near_other[:, 1:]
                    near_other = grown
                trimmed = mine & ~near_other
                if trimmed.any():
                    mine = trimmed
            rows = np.flatnonzero(mine.any(axis=1))
            cols = np.flatnonzero(mine.any(axis=0))
            if rows.size and cols.size:
                nx = ux0 + int(cols[0])
                ny = uy0 + int(rows[0])
                npatch = (mine[int(rows[0]):int(rows[-1]) + 1, int(cols[0]):int(cols[-1]) + 1].astype(np.uint8)) * 255
                if is_tuple:
                    authority[rid] = (nx, ny, npatch)
                else:
                    full = np.zeros_like(ap)
                    full[ny:ny + npatch.shape[0], nx:nx + npatch.shape[1]] = npatch
                    authority[rid] = full
            else:
                # No assigned pixels means no permission to render. Keeping the
                # original patch here gives a losing region the whole cavity again.
                authority[rid] = ((ax, ay, np.zeros((0, 0), dtype=ap.dtype))
                                  if is_tuple else np.zeros_like(ap))

