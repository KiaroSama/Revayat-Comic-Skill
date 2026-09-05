"""Fixture drawing. Nothing here is committed as a binary.

The pages are generated rather than vendored for three reasons: the suite stays
fast, the repository stays small, and no third-party artwork ends up in a GPL
tree it does not belong in.

They are drawn with plain shapes rather than real Japanese, deliberately. The
detector measures geometry — a balloon is a light region enclosed by an outline,
and lettering is a cluster of glyph-sized ink — and it neither knows nor cares
which script the ink came from. Drawing with a CJK font instead would make the
suite depend on a font that is not installed on a stock CI runner, and would
test the font rather than the detector. Script-specific behaviour is unit-tested
directly on strings, where it belongs.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

WHITE = (255, 255, 255)
BLACK = (20, 20, 20)


def _glyph_block(draw, box, *, rows=3, columns=6, colour=BLACK, seed=0, gaps=True):
    """A cluster of glyph-sized marks — what lettering looks like to a detector."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    cell_w, cell_h = width / columns, height / rows
    glyph_w, glyph_h = cell_w * 0.62, cell_h * 0.60
    for row in range(rows):
        for column in range(columns):
            # A deterministic gap pattern, so the marks read as separate glyphs
            # rather than one solid bar, without importing a random source.
            if gaps and (row * columns + column + seed) % 7 == 3:
                continue
            gx = x0 + column * cell_w + (cell_w - glyph_w) / 2
            gy = y0 + row * cell_h + (cell_h - glyph_h) / 2
            draw.rectangle([gx, gy, gx + glyph_w, gy + glyph_h], fill=colour)


def _texture(image, box, spacing=9):
    """Hatching, so a region over it needs real inpainting and not a flat fill.

    Drawn on its own layer and pasted, because PIL clips a line to the *image*
    and not to the box: drawing these diagonals directly put hatching across the
    whole page, which made the panel gutters look inked and broke panel
    detection everywhere. The fixture has to stay inside the panel it claims to
    be filling.
    """
    x0, y0, x1, y1 = (int(value) for value in box)
    width, height = max(1, x1 - x0), max(1, y1 - y0)
    patch = Image.new("RGB", (width, height), WHITE)
    hatch = ImageDraw.Draw(patch)
    for offset in range(0, width + height, spacing):
        hatch.line([(offset, 0), (0, offset)], fill=(70, 70, 70), width=2)
    image.paste(patch, (x0, y0))


def manga_page(
    width: int = 1000,
    height: int = 1500,
    *,
    balloons: int = 3,
    with_texture: bool = True,
    with_sfx: bool = True,
    dark_balloon: bool = False,
) -> Image.Image:
    """One page: two panel rows, balloons with lettering, optionally an SFX."""
    page = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(page)

    margin, gutter = 40, 34
    panel_w = (width - 2 * margin - gutter) / 2
    panel_h = (height - 2 * margin - gutter) / 2
    panels = []
    for row in range(2):
        for column in range(2):
            x0 = margin + column * (panel_w + gutter)
            y0 = margin + row * (panel_h + gutter)
            box = [x0, y0, x0 + panel_w, y0 + panel_h]
            draw.rectangle(box, outline=BLACK, width=5)
            panels.append(box)

    if with_texture:
        px0, py0, px1, py1 = panels[1]
        _texture(page, [px0 + 12, py0 + 12, px1 - 12, py1 - 12])

    placed = 0
    for index, (px0, py0, px1, py1) in enumerate(panels):
        if placed >= balloons:
            break
        bw, bh = (px1 - px0) * 0.62, (py1 - py0) * 0.42
        bx0 = px0 + (px1 - px0 - bw) / 2
        by0 = py0 + 26 + index * 5
        box = [bx0, by0, bx0 + bw, by0 + bh]
        fill, ink = ((30, 30, 30), (240, 240, 240)) if dark_balloon else (WHITE, BLACK)
        draw.ellipse(box, fill=fill, outline=BLACK if not dark_balloon else WHITE,
                     width=4)
        inset_x, inset_y = bw * 0.20, bh * 0.24
        _glyph_block(
            draw,
            [box[0] + inset_x, box[1] + inset_y, box[2] - inset_x, box[3] - inset_y],
            rows=3, columns=5, colour=ink, seed=index,
        )
        placed += 1

    if with_sfx:
        # Lettering drawn straight onto the artwork, with no balloon around it.
        px0, py0, px1, py1 = panels[3]
        # No gaps here: a sound effect is one contiguous piece of lettering,
        # and the detector is meant to return it as one region.
        _glyph_block(
            draw,
            [px0 + 40, py1 - 130, px0 + 300, py1 - 40],
            rows=1, columns=4, colour=BLACK, seed=2, gaps=False,
        )
    return page


def page_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


def write_cbz(path: Path, pages: int = 3, **options) -> Path:
    """A CBZ whose member names deliberately sort badly byte-wise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(pages):
            image = manga_page(dark_balloon=(index == 1), **options)
            # page1, page2, ... page10 — the order every naive sort gets wrong.
            archive.writestr(f"page{index + 1}.png", page_bytes(image))
    return path


def write_pages(folder: Path, pages: int = 2, **options) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(pages):
        (folder / f"{index + 1:03d}.png").write_bytes(
            page_bytes(manga_page(**options))
        )
    return folder
