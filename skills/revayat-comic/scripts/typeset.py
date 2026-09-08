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
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import masks as mask_tools
import pageir as ir

ZWNJ = "\u200c"

#: Fonts that carry a full Persian glyph set, best first. Vazirmatn and Sahel
#: are the modern open Persian faces; the Noto and system entries are the
#: fallbacks that exist on a machine with nothing installed for Persian.
#: Note what is *not* here: DejaVu Sans. It is the fallback every Linux box has
#: and it contains no Arabic script at all, so it would be chosen and then draw
#: nothing. `_supports_persian` catches that, but not listing it is cheaper.
PERSIAN_FONTS = (
    "Vazirmatn-Medium.ttf", "Vazirmatn-Regular.ttf", "Vazirmatn.ttf",
    "Sahel.ttf", "Shabnam.ttf", "IRANSansWeb.ttf", "IRANSans.ttf",
    "NotoNaskhArabic-Regular.ttf", "NotoSansArabic-Regular.ttf",
    "NotoNaskhArabic.ttf", "NotoSansArabic.ttf",
    "NotoSansArabic-VariableFont_wdth,wght.ttf",
    # macOS ships these two and nothing else with Persian coverage.
    "GeezaPro.ttc", "Geeza Pro.ttc",
    # Windows ships Tahoma, which has a complete Persian set.
    "Tahoma.ttf", "tahoma.ttf",
    "Arial.ttf", "arial.ttf", "ArialUni.ttf",
    "Nazli.ttf", "Titr.ttf", "Mitra.ttf",
)

FONT_DIRS = {
    "Windows": (r"C:\Windows\Fonts",),
    "Darwin": ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
               "/Library/Fonts", "~/Library/Fonts"),
    "Linux": ("/usr/share/fonts", "/usr/local/share/fonts",
              "~/.fonts", "~/.local/share/fonts"),
}

DEFAULT_MAX_SIZE = 64
DEFAULT_MIN_SIZE = 13
LINE_SPACING = 1.30
#: Keep this much of the balloon clear at its edge, as a share of its size.
BALLOON_PADDING = 0.10


def _pil():
    ir.require("PIL", "pillow", "typesetting Persian")
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _numpy():
    ir.require("numpy", "numpy", "measuring balloons")
    import numpy

    return numpy


# --------------------------------------------------------------------------- #
# Shaping
# --------------------------------------------------------------------------- #

def _cv2():
    ir.require("cv2", "opencv-python-headless", "measuring stylised lettering")
    import cv2

    return cv2


def raqm_available() -> bool:
    """Whether Pillow can shape and reorder Persian itself."""
    try:
        from PIL import features

        return bool(features.check("raqm"))
    except Exception:  # pragma: no cover - very old Pillow
        return False


_RESHAPER = None


def _reshaper():
    """A reshaper configured for Persian rather than for its own defaults.

    ``delete_harakat`` defaults to **True** in arabic-reshaper, and that is not
    a cosmetic setting for Persian: it deletes U+0654, the hamza that carries
    the ezafe. ``خانهٔ ما`` (*our house*) silently becomes ``خانه ما``, which is a
    different construction. Measured, then fixed here rather than discovered in
    a finished chapter.
    """
    global _RESHAPER
    if _RESHAPER is None:
        module = ir.require("arabic_reshaper", "arabic-reshaper",
                            "Persian shaping without RAQM")
        _RESHAPER = module.ArabicReshaper(configuration={
            "delete_harakat": False,
            "support_zwj": True,
            "support_ligatures": False,
        })
    return _RESHAPER


def shape_fallback(text: str) -> str:
    """Pre-shape and reorder by hand, when RAQM is unavailable.

    This produces presentation forms in visual order. It renders correctly, but
    the result is a picture of Persian rather than Persian: the same string
    copied out of the image would not be searchable, and a line broken after
    shaping would break in the wrong place. Line breaking therefore happens on
    the logical text, before this is ever called.

    Not a rare path, and not the platform limit it was long documented as.
    Pillow's wheels carry libraqm everywhere; libraqm loads **FriBiDi** at run
    time, and Linux images normally have one while Windows and macOS normally do
    not. Put a `fribidi` DLL on PATH — `fribidi.dll`, `fribidi-0.dll` or
    `libfribidi-0.dll` — and `features.check("raqm")` turns true on Windows.
    Measured on this project's own machine, where the claim had been repeated in
    five files.
    """
    ir.require("bidi", "python-bidi", "Persian direction without RAQM")
    from bidi.algorithm import get_display

    return get_display(_reshaper().reshape(text))


class Shaper:
    """One place that decides how a Persian string becomes glyphs."""

    def __init__(self, force_fallback: bool = False) -> None:
        self.raqm = raqm_available() and not force_fallback
        _, _, ImageFont = _pil()
        self.layout = (
            ImageFont.Layout.RAQM if self.raqm else ImageFont.Layout.BASIC
        )

    @property
    def mode(self) -> str:
        return "raqm" if self.raqm else "reshaper"

    def prepare(self, text: str) -> str:
        return text if self.raqm else shape_fallback(text)

    def draw_kwargs(self) -> dict[str, Any]:
        # `direction` and `language` are RAQM-only; passing them without it
        # raises rather than degrading, so they are omitted in fallback mode.
        return {"direction": "rtl", "language": "fa"} if self.raqm else {}


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #

def _candidate_paths() -> list[Path]:
    roots = FONT_DIRS.get(platform.system(), FONT_DIRS["Linux"])
    found: list[Path] = []
    for root in roots:
        base = Path(os.path.expanduser(root))
        if not base.is_dir():
            continue
        try:
            found.extend(
                path for path in base.rglob("*")
                if path.suffix.lower() in {".ttf", ".otf", ".ttc"}
            )
        except OSError:  # pragma: no cover - unreadable font directory
            continue
    return found


def find_font(preferred: str | None = None) -> Path:
    """Locate a font that can actually draw Persian."""
    _, _, ImageFont = _pil()

    if preferred:
        direct = Path(os.path.expanduser(preferred))
        if direct.is_file():
            return direct
        try:
            loaded = ImageFont.truetype(preferred, 20)
            return Path(getattr(loaded, "path", preferred))
        except OSError:
            pass  # fall through to the search, but remember what was asked for

    for name in PERSIAN_FONTS:
        try:
            loaded = ImageFont.truetype(name, 20)
            return Path(getattr(loaded, "path", name))
        except OSError:
            continue

    wanted = {name.lower() for name in PERSIAN_FONTS}
    for path in _candidate_paths():
        if path.name.lower() in wanted:
            return path

    raise ir.MissingDependency(
        "No Persian-capable font was found on this machine.\n"
        "Install one and try again — Vazirmatn is the usual choice:\n"
        "    https://github.com/rastikerdar/vazirmatn/releases\n"
        "Then pass it explicitly:  --font /path/to/Vazirmatn-Medium.ttf\n"
        "Tahoma or Noto Naskh Arabic also work if either is already installed."
    )


def _supports_persian(font_path: Path) -> bool:
    """Reject a font that renders Persian as empty boxes."""
    Image, ImageDraw, ImageFont = _pil()
    try:
        font = ImageFont.truetype(str(font_path), 32)
    except OSError:
        return False
    canvas = Image.new("L", (200, 60), 255)
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((4, 4), "چگونه", font=font, fill=0)
    except Exception:
        return False
    np = _numpy()
    inked = (np.asarray(canvas) < 128).sum()
    # A face with no Persian coverage draws either nothing or a row of identical
    # tofu boxes; both are far from the ink a real word puts down.
    return 40 < int(inked) < 200 * 60 * 0.6


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


#: Below this the ink has no clear long axis and an angle read off it is noise.
#: Measured as the aspect ratio of the smallest rotated box around the ink: a
#: word set on a diagonal is long and thin, a compact cluster of overlapping
#: glyphs is not, and the fit then returns whatever angle it happened to land on.
SFX_MIN_ELONGATION = 1.7

#: Rotations smaller than this are not worth a resample pass: it costs a blur
#: and buys nothing anyone can see.
SFX_MIN_ANGLE = 5.0


def sfx_style(mask, np) -> dict[str, float] | None:
    """How the erased lettering sat on the page, or ``None`` when it sat straight.

    The lettering is gone by the time the typesetter runs — that is what `clean`
    did — so the slant cannot be measured from the pixels. It comes from the
    region's own mask, which is the *shape of what was erased*, and
    `minAreaRect` fits the tightest rotated box around it. That one box carries
    all three things a stylised redraw needs: the angle is the lettering's
    baseline, the width and height are the space it filled upright, and the
    aspect ratio is how far the angle can be trusted.

    ``None`` is the common and correct answer. Most sound effects are set
    straight, and a straight one belongs on the ordinary flat path.
    """
    cv2 = _cv2()
    points = cv2.findNonZero(mask)
    if points is None or len(points) < 5:
        return None
    (cx, cy), (width, height), angle = cv2.minAreaRect(points)
    if width < 1.0 or height < 1.0:
        return None
    # minAreaRect names the sides in the order it found them, so its "width" is
    # not reliably the long one and its angle is measured against that side.
    # Reading along the long axis is what makes the number a baseline instead of
    # a quarter turn away from one.
    if width < height:
        width, height = height, width
        angle += 90.0
    angle = (angle + 90.0) % 180.0 - 90.0
    if width / height < SFX_MIN_ELONGATION or abs(angle) < SFX_MIN_ANGLE:
        return None
    return {"cx": float(cx), "cy": float(cy), "width": float(width),
            "height": float(height), "angle": float(angle)}


def _row_widths(mask, np) -> tuple[list[int], list[int]]:
    """Per row: the widest continuous run of interior, and where it starts."""
    widths: list[int] = []
    starts: list[int] = []
    for row in mask:
        columns = np.flatnonzero(row)
        if columns.size == 0:
            widths.append(0)
            starts.append(0)
            continue
        # Longest run of consecutive interior columns in this row.
        breaks = np.flatnonzero(np.diff(columns) > 1)
        segments = np.split(columns, breaks + 1)
        best = max(segments, key=len)
        widths.append(int(best[-1] - best[0] + 1))
        starts.append(int(best[0]))
    return widths, starts


# --------------------------------------------------------------------------- #
# Wrapping
# --------------------------------------------------------------------------- #

def _tokens(text: str) -> list[str]:
    """Break points. A ZWNJ joins a word; a space separates two."""
    collapsed = re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()
    return [token for token in collapsed.split(" ") if token]


def _measure(draw, text: str, font, shaper: Shaper) -> tuple[int, int]:
    box = draw.textbbox((0, 0), shaper.prepare(text), font=font,
                        **shaper.draw_kwargs())
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


def _wrap(draw, tokens: Sequence[str], font, shaper: Shaper,
          width_for_line) -> list[str] | None:
    """Greedy wrap where each line asks how wide *it* is allowed to be."""
    lines: list[str] = []
    current = ""
    for token in tokens:
        available = width_for_line(len(lines))
        if available <= 0:
            return None
        trial = f"{current} {token}".strip()
        if _measure(draw, trial, font, shaper)[0] <= available:
            current = trial
            continue
        if current:
            lines.append(current)
            current = ""
            available = width_for_line(len(lines))
            if available <= 0:
                return None
        if _measure(draw, token, font, shaper)[0] > available:
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
    if current:
        lines.append(current)
    return lines or None


def fit_region(
    draw, text: str, mask, np, shaper: Shaper, font_path: Path,
    *, max_size: int, min_size: int,
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
    widths, starts = _row_widths(region_mask, np)
    tokens = _tokens(text)
    if not tokens:
        return None

    body_top, body_height = _body(widths)
    if body_height <= 0:
        return None

    for size in range(int(max_size), int(min_size) - 1, -1):
        font = ImageFont.truetype(str(font_path), size, layout_engine=shaper.layout)
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
                band = widths[start:start + step]
                return min(band) if band else 0

            lines = _wrap(draw, tokens, font, shaper, width_for_line)
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
            band = widths[start:start + step]
            band_starts = starts[start:start + step]
            if not band:
                overflow = True
                break
            available = min(band)
            text_width, _ = _measure(draw, line, font, shaper)
            if text_width > available:
                overflow = True
                break
            middle = start + step // 2
            centre_x = left + band_starts[len(band_starts) // 2] + available / 2.0
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


def _draw_stylised(canvas, text: str, style: dict[str, float], shaper: Shaper,
                   font_path: Path, fill, stroke, np,
                   *, max_size: int, min_size: int) -> list[int] | None:
    """Set the Persian at the slant the original lettering had.

    Rendered upright on its own transparent layer and only then rotated, so the
    glyphs are shaped, hinted and stroked exactly as they are everywhere else on
    the page and nothing but the finished bitmap is turned. Pillow cannot rotate
    a text call, and rotating the page is not an option.

    The sign is measured rather than assumed: `sfx_style` returns the negative
    of the rotation that produced the shape, so ``-angle`` puts it back. A test
    pins that round trip, because a silently mirrored angle looks deliberate and
    is wrong on every page.

    Returns the box it painted, or ``None`` when the words will not fit the
    space the original lettering filled. The caller then sets them flat: a less
    faithful effect that still says what the panel said, which is the trade this
    project makes everywhere else too.
    """
    Image, ImageDraw, ImageFont = _pil()
    width = max(1, int(round(style["width"])))
    height = max(1, int(round(style["height"])))

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    fitted = fit_region(
        layer_draw, text, np.full((height, width), 255, np.uint8), np, shaper,
        font_path, max_size=max_size, min_size=min_size,
    )
    if fitted is None:
        return None

    font = ImageFont.truetype(str(font_path), fitted["size"],
                              layout_engine=shaper.layout)
    options: dict[str, Any] = {"font": font, "fill": fill, "anchor": "mm",
                               **shaper.draw_kwargs()}
    if stroke:
        # A sound effect sits on artwork rather than inside a balloon, so the
        # outline is not decoration here — it is the only thing keeping the
        # word legible over whatever it was drawn across.
        options["stroke_width"] = max(2, fitted["size"] // 8)
        options["stroke_fill"] = stroke
    for line in fitted["lines"]:
        layer_draw.text((line["x"], line["y"]),
                        shaper.prepare(line["text"]), **options)

    turned = layer.rotate(-style["angle"], resample=Image.BICUBIC, expand=True)
    left = int(round(style["cx"] - turned.width / 2.0))
    top = int(round(style["cy"] - turned.height / 2.0))
    canvas.paste(turned, (left, top), turned)
    return [left, top, left + turned.width, top + turned.height]


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
    clean_rgb = np.asarray(canvas)
    draw = ImageDraw.Draw(canvas)
    size = (page["width"], page["height"])

    writable = np.zeros((page["height"], page["width"]), np.uint8)
    union = page.get("mask")
    if union:
        writable = np.maximum(writable, mask_tools.load_mask(root / union))

    placed = 0
    overflow: list[str] = []
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
        record: dict[str, Any]

        # A sound effect drawn on a slant, set on the same slant. Only ever
        # attempted where the mask says there was a slant to match; a straight
        # effect, a balloon, or a region with no mask of its own all take the
        # flat path below, which is the one that has always run.
        style = None
        if stylise and region["kind"] == "sfx" and region.get("mask"):
            style = sfx_style(mask_tools.load_mask(root / region["mask"]), np)
        if style is not None:
            box = _draw_stylised(canvas, text, style, shaper, font_path, fill,
                                 stroke, np, max_size=max_size,
                                 min_size=min_size)
            if box is None:
                style = None
            else:
                painted.append(box)
                record = {
                    "status": "ok", "style": "rotated",
                    "angle": round(style["angle"], 1),
                    "font": font_path.name, "shaping": shaper.mode,
                }

        if style is None:
            area = interior_mask(clean_rgb, region, size)
            fitted = fit_region(
                draw, text, area, np, shaper, font_path,
                max_size=max_size, min_size=min_size,
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
                    options["stroke_width"] = max(1, fitted["size"] // 12)
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

        for x0, y0, x1, y1 in painted:
            pad = 2
            x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
            x1 = min(page["width"], x1 + pad)
            y1 = min(page["height"], y1 + pad)
            writable[y0:y1, x0:x1] = 255

        region["typeset"] = record
        placed += 1

    relative = f"final/{page['id']}.png"
    ir.save_image(canvas, root / relative)
    page["final"] = relative

    writable_path = f"masks/{page['id']}/writable.png"
    ir.write_bytes(root / writable_path,
                   mask_tools._encode_png(Image.fromarray(writable, mode="L")))
    page["writable"] = writable_path

    return {"placed": placed, "overflow": overflow, "skipped": skipped}


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
        per_page.append({"page": page["id"], **result})

    ir.stamp_stage(doc, "typeset", {
        "placed": placed, "font": font_path.name, "shaping": shaper.mode,
    })
    ir.save_doc(doc, doc_path)

    return {
        "document": str(doc_path),
        "font": str(font_path),
        "shaping": shaper.mode,
        "placed": placed,
        "overflow": overflow[:30],
        "overflow_count": len(overflow),
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
