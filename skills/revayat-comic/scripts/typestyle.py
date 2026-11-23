"""Worksheet style tokens and the shared lettering effect geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass

from typefont import _pil

STYLE_TOKENS = ("bold", "italic", "bold-italic", "outline", "shadow", "shout")
SHEAR = -0.16
SHADOW_OFFSET = 2
SHADOW_PAD = 3


def normalize_style(value: str) -> str:
    tokens = {token.strip().lower() for token in value.split(",") if token.strip()}
    if tokens.difference(STYLE_TOKENS):
        raise ValueError(f"Unknown lettering style: {', '.join(sorted(tokens.difference(STYLE_TOKENS)))}")
    if "bold-italic" in tokens or {"bold", "italic"} <= tokens:
        tokens.difference_update(("bold", "italic"))
        tokens.add("bold-italic")
    return ", ".join(token for token in STYLE_TOKENS if token in tokens)


def style_flags(value: str) -> frozenset[str]:
    return frozenset(value.lower().replace(" ", "").split(",")) & frozenset(STYLE_TOKENS)


def wants_bold(flags: frozenset[str]) -> bool:
    return not flags.isdisjoint({"bold", "bold-italic", "shout"})


@dataclass(frozen=True)
class LineEffects:
    halo: int
    faux_bold: int
    italic: bool
    shadow: bool

    @property
    def stroke(self) -> int:
        return max(self.halo, self.faux_bold)

    def bounds(self, box):
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            return box
        pad = math.ceil(abs(SHEAR) * (bottom - top) / 2) + 2 if self.italic else 0
        if self.shadow:
            before, after = SHADOW_PAD, SHADOW_PAD + SHADOW_OFFSET
        else:
            before = after = 0
        return left - pad - before, top - before, right + pad + after, bottom + after


def effects_for(size: int, flags: frozenset[str], *, faux_bold: bool, plain_outline: int) -> LineEffects:
    return LineEffects(
        max(2, round(size * 0.10)) if "outline" in flags else plain_outline,
        max(1, size // 24) if faux_bold else 0,
        bool(flags & {"italic", "bold-italic"}),
        "shadow" in flags,
    )


def draw_line(canvas, draw, xy, text, font, shaper, effects: LineEffects, fill, halo):
    """Paint a shaped line and return the page-space bounds reserved for it."""
    options = {"font": font, "anchor": "mm", **shaper.draw_kwargs()}
    shaped = shaper.prepare(text)
    box = draw.textbbox(tuple(map(int, xy)), shaped, stroke_width=effects.stroke, **options)
    if box[2] <= box[0] or box[3] <= box[1]:
        return box

    def paint(brush, point) -> None:
        if effects.halo:
            brush.text(point, shaped, fill=fill, stroke_width=effects.halo, stroke_fill=halo, **options)
        if effects.faux_bold or not effects.halo:
            brush.text(point, shaped, fill=fill, stroke_width=effects.faux_bold, **options)

    if not (effects.italic or effects.shadow):
        paint(draw, xy)
        return box

    from PIL import ImageFilter

    Image, ImageDraw, _ = _pil()
    x, y, right, bottom = effects.bounds(box)
    layer = Image.new("RGBA", (right - x, bottom - y))
    paint(ImageDraw.Draw(layer), (xy[0] - x, xy[1] - y))
    if effects.italic:
        middle = (box[1] + box[3]) / 2 - y
        # Pillow expects the inverse map. The top of the ink leans right.
        layer = layer.transform(layer.size, Image.Transform.AFFINE,
                                (1, -SHEAR, SHEAR * middle, 0, 1, 0), Image.Resampling.BICUBIC)
    if effects.shadow:
        alpha = Image.new("L", layer.size)
        alpha.paste(layer.getchannel("A"), (SHADOW_OFFSET, SHADOW_OFFSET))
        alpha = alpha.filter(ImageFilter.GaussianBlur(0.9)).point(lambda pixel: round(pixel * 0.28))
        canvas.paste((0, 0, 0), (x, y, right, bottom), alpha)
    canvas.paste(layer, (x, y), layer)
    return x, y, right, bottom
