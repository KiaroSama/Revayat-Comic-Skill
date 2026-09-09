"""Set Persian to match lettering that was drawn, not typed.

A sound effect is not text in a box. It leans, it arcs across a panel, it
recedes with the perspective of what it is drawn on, and it was made by a hand
that was thinking about the drawing. Replacing it with horizontal type in a
rectangle is the single most obvious tell of a machine translation.

This module measures what the letterer did and reproduces as much of it as can
be measured honestly. Three things make that possible and one makes it safe:

**The mask is the evidence.** By the time anything here runs, `clean` has erased
the lettering, so nothing can be measured from the pixels. What survives is the
region's mask — the exact shape of what was erased — and every number here comes
out of it.

**The shaped strip is the unit, never the glyph.** Persian joins. Placing
characters one at a time along an arc breaks the joining and produces something
that is not a word. So the whole line is shaped and rendered once, horizontally,
by the same code that draws every balloon, and only the finished *bitmap* is
bent. Every letter keeps the form its neighbours gave it.

**Every transform is gated on a measurement, and the gate is the point.**
`minAreaRect` always returns an angle; a quadratic always fits. What decides
whether the answer means anything is the elongation of the ink, the residual of
the fit, and the sample count — and when those say the measurement is noise, the
answer is not "try anyway".

**Unreliable means keep, not guess.** A verdict of `unreliable` leaves the
lettering drawn and asks for a human look. Replacing hand lettering with type
that is confidently wrong about its own geometry is worse than leaving the
Japanese in place, which is the judgement `sound-effects.md` has always made.
"""

from __future__ import annotations

from typing import Any, Sequence

import pageir as ir

#: Below this the ink has no long axis and every measurement taken along one is
#: noise. Aspect ratio of the smallest rotated box around the ink: a word set on
#: a diagonal is long and thin, a compact cluster of overlapping glyphs is not.
MIN_ELONGATION = 1.7

#: Rotations smaller than this are not worth a resample: it costs a blur and
#: buys nothing anyone can see.
MIN_ANGLE = 5.0

#: Sagitta over chord length, above which the lettering is following an arc
#: rather than sitting on a line. 0.04 is about a 9-degree turn end to end —
#: visible to a reader, and comfortably outside what a straight line of
#: hand lettering wanders by.
MIN_CURVE = 0.04

#: How far the ink's thickness at one end may differ from the other before the
#: lettering counts as receding. 0.25 means one end a quarter thinner.
MIN_TAPER = 0.25

#: Curvature past this is not an arc any more — it is a broken measurement, a
#: mask that caught two separate effects, or lettering wrapped around an object.
#: Above it the verdict is `unreliable` rather than a wilder guess.
MAX_CURVE = 0.35

#: The shadow a drawn effect usually carries, as a fraction of type size.
SHADOW_OFFSET = 0.11

#: How heavy an outline may get, as a fraction of the type size. A drawn effect
#: with a very thick stroke would otherwise close up the counters of the Persian
#: and turn a word into a blob.
MAX_STROKE = 0.22

#: And how light. Below this the outline stops doing its job, which on artwork
#: is the only thing keeping the word readable.
MIN_STROKE = 0.06

#: How lopsided the weight along an effect has to be before it is treated as a
#: brush thickening rather than measurement noise. A hand-drawn effect that
#: genuinely swells reaches 0.4 easily; a machine-set one sits near zero.
MIN_MODULATION = 0.22

#: And the cap. Past this the light end thins to nothing and the word stops
#: reading as one word.
MAX_MODULATION = 0.8

#: How far a rendered effect may spill outside the area the original occupied,
#: as a fraction of that area's size. Rotation and warping both grow a bitmap;
#: this bounds the growth so a replacement cannot wander across the panel.
MAX_SPILL = 0.35

#: Every verdict `measure` can return. `flat` is not a failure — most lettering
#: is straight, and straight lettering belongs on the ordinary path.
VERDICTS = ("flat", "rotated", "curved", "warped", "unreliable")


def _cv2():
    ir.require("cv2", "opencv-python-headless", "measuring drawn lettering")
    import cv2

    return cv2


def _numpy():
    ir.require("numpy", "numpy", "measuring drawn lettering")
    import numpy as np

    return np


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #

def _stroke_weight(mask, np, cv2) -> float:
    """How thick the erased lettering was drawn, relative to its own height.

    The distance transform gives every ink pixel its distance to the nearest
    edge, so the *ridge* of that field is the half-width of the stroke it sits
    in. Taking a high percentile rather than the maximum keeps a junction where
    three strokes meet from speaking for the whole hand.

    Returned as a fraction of the lettering's height, because that is the number
    the renderer needs: type is set at a size, and the outline has to be a
    fraction of that size to look like the same weight.
    """
    ink = (mask > 0).astype(np.uint8)
    if not ink.any():
        return 0.0
    rows = np.flatnonzero(ink.any(axis=1))
    height = float(rows[-1] - rows[0] + 1)
    if height < 4.0:
        return 0.0
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    inside = distance[distance > 0]
    if inside.size == 0:
        return 0.0
    half = float(np.percentile(inside, 92))
    return round(min(1.0, (2.0 * half) / height), 4)


def _stroke_modulation(upright, np, cv2) -> float:
    """How much heavier one end of the lettering is than the other.

    `_stroke_weight` answers *how thick*, as one number for the whole effect.
    This answers *how evenly* — the thing a brush does that a typeface does not.
    A drawn effect often starts light and swells, or lands heavy and lifts off;
    replacing both with one uniform weight throws that away.

    Measured on the **upright** mask, so "along the effect" is simply left to
    right. The ink is split into five bands, each band's stroke half-width taken
    at the same high percentile `_stroke_weight` uses, and the two ends
    compared. Five is enough to see a trend and few enough that one gap between
    words does not become the signal.

    Returns a signed fraction: positive means the right-hand end is heavier,
    negative the left. Near zero means evenly drawn, which is the common case
    and the one that must stay cheap.
    """
    ink = (upright > 0).astype(np.uint8)
    columns = np.flatnonzero(ink.any(axis=0))
    if columns.size < 25:
        return 0.0
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)

    bands = np.array_split(columns, 5)
    weights = []
    for band in bands:
        inside = distance[:, band]
        inside = inside[inside > 0]
        # A band that is nearly all gap says nothing about the hand; skip it
        # rather than let a thin sample drag the trend.
        if inside.size < 12:
            return 0.0
        weights.append(float(np.percentile(inside, 92)))

    first, last = weights[0], weights[-1]
    total = first + last
    if total <= 0.0:
        return 0.0
    trend = (last - first) / total

    # One end being heavier is only a brush stroke if the bands in between go
    # the same way. Without this a single blot at one end reads as a swell.
    steps = np.diff(weights)
    if steps.size and float(np.sign(trend)) != 0.0:
        agreeing = float((np.sign(steps) == np.sign(trend)).mean())
        if agreeing < 0.6:
            return 0.0
    return round(float(np.clip(trend, -MAX_MODULATION, MAX_MODULATION)), 4)


def _upright(mask, angle: float, np, cv2):
    """The mask turned so its long axis is horizontal.

    Curvature and taper are properties of the lettering's own baseline, so they
    have to be measured in the lettering's frame. Turning the mask once here is
    what lets both of them be a straightforward column-wise scan afterwards.
    """
    height, width = mask.shape[:2]
    centre = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(centre, -angle, 1.0)
    # Grow the canvas so the rotation cannot clip the ink off its own corners.
    span = int(round((width ** 2 + height ** 2) ** 0.5)) + 2
    matrix[0, 2] += span / 2.0 - centre[0]
    matrix[1, 2] += span / 2.0 - centre[1]
    return cv2.warpAffine(mask, matrix, (span, span), flags=cv2.INTER_NEAREST)


def _baseline(upright, np) -> tuple[Any, Any, Any]:
    """Per column that has ink: its index, the ink's centre, and its thickness."""
    columns = np.flatnonzero(upright.any(axis=0))
    if columns.size == 0:
        return columns, columns, columns
    rows = np.arange(upright.shape[0])
    block = upright[:, columns] > 0
    weight = block.sum(axis=0)
    centre = (block * rows[:, None]).sum(axis=0) / np.maximum(1, weight)
    return columns, centre, weight


def _curvature(columns, centre, np) -> tuple[float, float]:
    """``(sagitta / chord, fit residual)`` for the lettering's baseline.

    A straight line of lettering gives a flat fit and a sagitta near zero; an arc
    gives a real one. The residual comes back too because a quadratic fits *any*
    scatter — it is the residual, not the coefficient, that says whether the
    scatter was ever a curve.
    """
    if columns.size < 12:
        return 0.0, 1.0
    x = columns.astype(np.float64)
    y = centre.astype(np.float64)
    span = float(x[-1] - x[0])
    if span < 1.0:
        return 0.0, 1.0
    coefficients = np.polyfit(x, y, 2)
    model = np.polyval(coefficients, x)
    spread = float(y.max() - y.min())
    residual = float(np.abs(y - model).mean() / max(1.0, spread))
    # Sagitta: how far the middle of the fitted arc departs from the chord
    # joining its ends. That is the quantity a reader actually sees.
    ends = np.polyval(coefficients, np.array([x[0], x[-1]]))
    middle = float(np.polyval(coefficients, (x[0] + x[-1]) / 2.0))
    sagitta = abs(middle - float(ends.mean()))
    return sagitta / span, residual


def _taper(weight, np) -> float:
    """Thickness at the far end over thickness at the near end.

    Lettering drawn in perspective is thicker where it is near. Measured over a
    fifth of the run at each end so one tall glyph cannot decide it.
    """
    if weight.size < 10:
        return 1.0
    edge = max(2, weight.size // 5)
    near = float(np.median(weight[:edge]))
    far = float(np.median(weight[-edge:]))
    if near <= 0.0 or far <= 0.0:
        return 1.0
    return far / near


def measure(mask, np, origin: Sequence[float] = (0.0, 0.0)) -> dict[str, Any] | None:
    """What the letterer did, in page coordinates, or ``None`` if there is no ink.

    **``origin`` is not optional in practice.** A stored region mask is a *local*
    array covering ``region["mask_box"]``, so everything here is measured in that
    little array's frame and the centre is meaningless on the page until the
    box's top-left is added back. Pass ``region["mask_box"][:2]``. This shipped
    once without it and put every rotated effect near the page origin.

    The returned ``verdict`` is the whole contract: `flat` and `rotated` and
    `curved` and `warped` are things to draw, and `unreliable` is a request to
    leave the artwork alone and let a person look at it.
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
    elongation = width / height

    style = {
        "cx": float(cx) + float(origin[0]),
        "cy": float(cy) + float(origin[1]),
        "width": float(width),
        "height": float(height),
        "angle": float(angle),
        "elongation": float(elongation),
        "curvature": 0.0,
        "taper": 1.0,
        "stroke": _stroke_weight(mask, np, cv2),
        "modulation": 0.0,
        "verdict": "flat",
    }

    if elongation < MIN_ELONGATION:
        # No long axis, so the angle is whichever way the fit happened to land
        # and curvature and taper are measured along a direction that does not
        # exist. Nothing here can be trusted, and guessing is the one option
        # that is worse than doing nothing.
        style["verdict"] = "unreliable"
        style["reason"] = (
            f"the ink is {elongation:.1f}x as long as it is wide, which is too "
            f"square to read a baseline from"
        )
        return style

    upright = _upright(mask, style["angle"], np, cv2)
    style["modulation"] = _stroke_modulation(upright, np, cv2)
    columns, centre, weight = _baseline(upright, np)
    curvature, residual = _curvature(columns, centre, np)
    taper = _taper(weight, np)
    style["curvature"] = round(float(curvature), 4)
    style["taper"] = round(float(taper), 3)

    if curvature > MAX_CURVE:
        style["verdict"] = "unreliable"
        style["reason"] = (
            f"the baseline bends by {curvature:.2f} of its own length, which is "
            f"not an arc — most likely two effects caught in one mask"
        )
        return style

    # A quadratic fits any scatter. The residual is what separates an arc from a
    # cloud, and without this gate a ragged straight effect reads as curved.
    if curvature >= MIN_CURVE and residual < 0.25:
        style["verdict"] = "curved"
    elif abs(taper - 1.0) >= MIN_TAPER:
        style["verdict"] = "warped"
    elif abs(style["angle"]) >= MIN_ANGLE:
        style["verdict"] = "rotated"
    return style


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _strip(text: str, style: dict[str, Any], shaper, font_path, fill, stroke,
           np, fit_region, pil, *, max_size: int, min_size: int):
    """The Persian, shaped and drawn once, horizontally, with its shadow.

    Everything downstream bends this bitmap. Drawing it exactly once, through
    the same fitter every balloon uses, is what keeps a curved sound effect
    spelled the same way as the dialogue next to it.
    """
    Image, ImageDraw, ImageFont = pil
    width = max(1, int(round(style["width"])))
    height = max(1, int(round(style["height"])))

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    fitted = fit_region(draw, text, np.full((height, width), 255, np.uint8), np,
                        shaper, font_path, max_size=max_size, min_size=min_size)
    if fitted is None:
        return None, None

    font = ImageFont.truetype(str(font_path), fitted["size"],
                              layout_engine=shaper.layout)
    options: dict[str, Any] = {"font": font, "fill": fill, "anchor": "mm",
                               **shaper.draw_kwargs()}
    if stroke:
        # A sound effect sits on artwork rather than on paper, so the outline is
        # not decoration here — it is the only thing keeping the word legible
        # over whatever it was drawn across.
        #
        # Its weight is taken from the lettering that was erased, measured off
        # the mask, so a delicate effect stays delicate and a heavy one stays
        # heavy. Clamped at both ends: too thick closes the counters of the
        # Persian and turns the word into a blob, too thin stops working over
        # artwork. Falls back to `size // 8` when there is nothing to measure.
        measured = float(style.get("stroke") or 0.0)
        if measured > 0.0:
            fraction = min(MAX_STROKE, max(MIN_STROKE, measured / 2.0))
            options["stroke_width"] = max(2, int(round(fitted["size"] * fraction)))
        else:
            options["stroke_width"] = max(2, fitted["size"] // 8)
        options["stroke_fill"] = stroke

    offset = max(1, int(round(fitted["size"] * SHADOW_OFFSET)))
    shadow = dict(options, fill=(0, 0, 0, 110))
    shadow.pop("stroke_fill", None)
    shadow.pop("stroke_width", None)
    for line in fitted["lines"]:
        shaped = shaper.prepare(line["text"])
        # The shadow goes down and right, under everything, the way a letterer
        # would ink it — and before the outline, so the outline stays crisp.
        draw.text((line["x"] + offset, line["y"] + offset), shaped, **shadow)

    swell = float(style.get("modulation") or 0.0)
    if abs(swell) >= MIN_MODULATION and options.get("stroke_width"):
        # The original was drawn with a brush that changed weight along the
        # word. Two passes at two weights, cross-faded along the same axis the
        # measurement ran down, put that back.
        base = options["stroke_width"]
        light = dict(options)
        heavy = dict(options)
        light["stroke_width"] = max(1, int(round(base * (1.0 - abs(swell) / 2.0))))
        heavy["stroke_width"] = max(light["stroke_width"] + 1,
                                    int(round(base * (1.0 + abs(swell) / 2.0))))
        body = _swell(_body(layer.size, fitted, light, shaper, pil),
                      _body(layer.size, fitted, heavy, shaper, pil),
                      swell, np, Image)
    else:
        body = _body(layer.size, fitted, options, shaper, pil)
    layer.alpha_composite(body)
    return layer, fitted


def _body(size, fitted, options: dict[str, Any], shaper, pil):
    """The lettering alone, on its own transparent layer.

    Separate from the shadow so the two weights below can be blended without
    the shadow being blended twice along with them.
    """
    Image, ImageDraw, _ = pil
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for line in fitted["lines"]:
        draw.text((line["x"], line["y"]), shaper.prepare(line["text"]), **options)
    return layer


def _swell(light, heavy, modulation: float, np, Image):
    """Cross-fade a light pass into a heavy one along the effect's long axis.

    **Why the weight is carried by the outline rather than a variable font
    axis.** Vazirmatn ships a `wght` axis and Pillow can set it, so the obvious
    route is to render the same string at two weights and blend. It does not
    work: the advance widths differ — measured here, 104 px against 113 px for
    one word at size 40, about 9% — so the two renders drift apart across the
    strip and the blend ghosts. Growing the outline instead leaves every glyph
    at exactly the same position in both passes, which is what makes the fade
    clean, and it grows the mark the way a heavier brush does.

    The blend is done premultiplied. A straight lerp of non-premultiplied RGBA
    drags the new ring's colour toward the transparent side's black and leaves a
    dark fringe around a coloured outline.
    """
    ramp = np.linspace(0.0, 1.0, light.width, dtype=np.float32)
    if modulation < 0:
        ramp = ramp[::-1]
    ramp = ramp[None, :, None]

    a = np.asarray(light).astype(np.float32)
    b = np.asarray(heavy).astype(np.float32)
    a = np.dstack([a[..., :3] * (a[..., 3:4] / 255.0), a[..., 3:4]])
    b = np.dstack([b[..., :3] * (b[..., 3:4] / 255.0), b[..., 3:4]])

    out = a + (b - a) * ramp
    alpha = out[..., 3:4]
    rgb = np.where(alpha > 0.0, out[..., :3] * 255.0 / np.maximum(alpha, 1e-6), 0.0)
    blended = np.dstack([rgb, alpha])
    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8), "RGBA")


def _bend(layer, curvature: float, np, Image):
    """Slide each column of the strip along a parabola.

    The alternative is placing glyphs one at a time around the arc, which breaks
    Persian joining and yields a string of isolated letters. Displacing columns
    of an already-shaped bitmap keeps every join and every ligature; what it
    costs is that very tight arcs shear rather than rotate, which is why
    `MAX_CURVE` exists.
    """
    array = np.asarray(layer)
    height, width = array.shape[:2]
    if width < 2:
        return layer
    # A parabola through (0,0), (mid, sagitta), (width, 0).
    x = np.linspace(-1.0, 1.0, width)
    sagitta = curvature * width
    shift = np.rint((x ** 2 - 1.0) * sagitta).astype(int)

    grown = int(abs(sagitta)) + 1
    out = np.zeros((height + 2 * grown, width, array.shape[2]), array.dtype)
    rows = np.arange(height)
    for column in range(width):
        target = rows + grown + shift[column]
        out[target, column] = array[:, column]
    return Image.fromarray(out, mode="RGBA")


def _recede(layer, taper: float, np, Image, cv2):
    """Warp the strip into the trapezoid the lettering actually occupied.

    Perspective in hand lettering shows up as one end being drawn smaller than
    the other. A four-point warp reproduces exactly that and nothing else: this
    is not a 3D projection and does not pretend to be one, which is why the gate
    is a measured thickness ratio rather than a guessed vanishing point.
    """
    array = np.asarray(layer)
    height, width = array.shape[:2]
    ratio = max(0.35, min(2.85, taper))
    far = height * ratio
    inset = (height - far) / 2.0

    source = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    target = np.float32([
        [0, 0], [width, inset], [width, inset + far], [0, height],
    ])
    top = max(0.0, -inset)
    target[:, 1] += top
    canvas_height = int(round(max(height, inset + far + top))) + 1
    matrix = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(
        array, matrix, (width, canvas_height),
        flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    return Image.fromarray(warped, mode="RGBA")


def _within_bounds(style: dict[str, Any], bitmap) -> bool:
    """Whether the rendered effect still covers roughly the area it replaced.

    Rotating and warping both grow a bitmap, and a transform that has gone wrong
    grows it a lot. This is the backstop that keeps a bad measurement from
    stamping type across a neighbouring panel: the pixels are bounded by the
    region the lettering came from, plus a margin, or the render is refused.
    """
    limit_w = style["width"] * (1.0 + MAX_SPILL) + style["height"]
    limit_h = style["height"] * (1.0 + MAX_SPILL) + style["width"]
    return bitmap.width <= limit_w and bitmap.height <= limit_h


def render(canvas, text: str, style: dict[str, Any], shaper, font_path, fill,
           stroke, np, fit_region, pil, *, max_size: int,
           min_size: int) -> dict[str, Any] | None:
    """Draw `text` the way the original lettering was drawn.

    Returns a record of what was done plus the page box it painted, or ``None``
    when the words will not fit the space the lettering filled or the transform
    grew past its bounds. ``None`` means the caller should fall back — to flat
    type for a `rotated` effect, and to leaving the artwork alone for anything
    the measurement was not sure about.
    """
    Image = pil[0]
    cv2 = _cv2()
    layer, fitted = _strip(text, style, shaper, font_path, fill, stroke, np,
                           fit_region, pil, max_size=max_size, min_size=min_size)
    if layer is None:
        return None

    verdict = style["verdict"]
    if verdict == "curved":
        layer = _bend(layer, style["curvature"], np, Image)
    elif verdict == "warped":
        layer = _recede(layer, style["taper"], np, Image, cv2)

    if abs(style["angle"]) >= MIN_ANGLE or verdict in {"curved", "warped"}:
        # Measured, not assumed: `measure` returns the negative of the rotation
        # that produced the shape, so `-angle` puts it back.
        layer = layer.rotate(-style["angle"], resample=Image.BICUBIC,
                             expand=True)

    if not _within_bounds(style, layer):
        return None

    left = int(round(style["cx"] - layer.width / 2.0))
    top = int(round(style["cy"] - layer.height / 2.0))
    canvas.paste(layer, (left, top), layer)
    return {
        "style": verdict,
        "angle": round(style["angle"], 1),
        "curvature": style["curvature"],
        "taper": style["taper"],
        "stroke": style.get("stroke", 0.0),
        "modulation": style.get("modulation", 0.0),
        "size": fitted["size"],
        "lines": fitted["line_count"],
        "font": fitted["font"],
        "shaping": shaper.mode,
        "box": [left, top, left + layer.width, top + layer.height],
    }
