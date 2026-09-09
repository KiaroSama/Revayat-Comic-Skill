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

`japanese_page` is the one exception, and it is opt-in: it returns `None` when
no CJK font is installed, so the test that uses it skips exactly the way the
RAQM and unrar tests do. What it buys is the thing shapes cannot stand in for —
a vertical column of real kanji with real furigana beside it, which is denser
ink at a smaller size than any block of rectangles, and is the case the whole
`orientation` path exists for.
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


def _texture(image, box, spacing=9, width=2):
    """Hatching, so a region over it needs real inpainting and not a flat fill.

    Drawn on its own layer and pasted, because PIL clips a line to the *image*
    and not to the box: drawing these diagonals directly put hatching across the
    whole page, which made the panel gutters look inked and broke panel
    detection everywhere. The fixture has to stay inside the panel it claims to
    be filling.
    """
    x0, y0, x1, y1 = (int(value) for value in box)
    box_w, box_h = max(1, x1 - x0), max(1, y1 - y0)
    patch = Image.new("RGB", (box_w, box_h), WHITE)
    hatch = ImageDraw.Draw(patch)
    for offset in range(0, box_w + box_h, spacing):
        hatch.line([(offset, 0), (0, offset)], fill=(70, 70, 70), width=width)
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
    """One page: two panel rows, balloons with lettering, optionally an SFX.

    **Line weights scale with the page.** Every detector threshold is a fraction
    of the page, so the fixture has to be a fraction of the page too — and a real
    scan is: a tankobon at 300 dpi has a proportionally thicker balloon outline
    than the same art at 96 dpi, because it is the same ink measured with more
    pixels. Drawing a fixed four-pixel outline on a 2480-pixel page produces a
    hairline no real scan contains, and detection collapses on it (measured:
    1 balloon of 3, and one panel lost). Scaled, it is exact at every size.
    """
    scale = min(width, height) / 1000.0
    border = max(2, round(5 * scale))
    outline = max(2, round(4 * scale))

    page = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(page)

    margin, gutter = 40 * scale, 34 * scale
    panel_w = (width - 2 * margin - gutter) / 2
    panel_h = (height - 2 * margin - gutter) / 2
    panels = []
    for row in range(2):
        for column in range(2):
            x0 = margin + column * (panel_w + gutter)
            y0 = margin + row * (panel_h + gutter)
            box = [x0, y0, x0 + panel_w, y0 + panel_h]
            draw.rectangle(box, outline=BLACK, width=border)
            panels.append(box)

    if with_texture:
        px0, py0, px1, py1 = panels[1]
        inset = 12 * scale
        _texture(page, [px0 + inset, py0 + inset, px1 - inset, py1 - inset],
                 spacing=max(3, round(9 * scale)), width=max(1, round(2 * scale)))

    placed = 0
    for index, (px0, py0, px1, py1) in enumerate(panels):
        if placed >= balloons:
            break
        bw, bh = (px1 - px0) * 0.62, (py1 - py0) * 0.42
        bx0 = px0 + (px1 - px0 - bw) / 2
        by0 = py0 + (26 + index * 5) * scale
        box = [bx0, by0, bx0 + bw, by0 + bh]
        fill, ink = ((30, 30, 30), (240, 240, 240)) if dark_balloon else (WHITE, BLACK)
        draw.ellipse(box, fill=fill, outline=BLACK if not dark_balloon else WHITE,
                     width=outline)
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
            [px0 + 40 * scale, py1 - 130 * scale,
             px0 + 300 * scale, py1 - 40 * scale],
            rows=1, columns=4, colour=BLACK, seed=2, gaps=False,
        )
    return page


#: Faces that carry kanji and kana, most specific first. Windows ships the first
#: two; the Noto builds are what a Linux runner is likely to have if it has any.
CJK_FACES = (
    "msgothic.ttc", "YuGothM.ttc", "YuGothR.ttc",
    "NotoSansCJKjp-Regular.otf", "NotoSansJP-Regular.otf",
    "NotoSerifCJK-Regular.ttc", "DroidSansFallbackFull.ttf",
)


def cjk_font(size: int):
    """A font that can draw Japanese, or `None` on a machine without one.

    Checked by asking for a glyph rather than by trusting the filename: a face
    can be installed under a promising name and still have no kanji, and a
    fixture that silently draws tofu tests nothing.
    """
    from PIL import ImageFont

    roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"),
             Path("/Library/Fonts"), Path("/System/Library/Fonts")]
    for name in CJK_FACES:
        for root in roots:
            if not root.is_dir():
                continue
            found = next(root.rglob(name), None) if root.name != "Fonts" \
                else (root / name if (root / name).exists() else None)
            if found is None:
                found = next(root.rglob(name), None)
            if found is None:
                continue
            try:
                font = ImageFont.truetype(str(found), size)
                # 力 is a kanji every CJK face has and no Latin face does.
                box = font.getbbox("\u529b")
            except OSError:
                continue
            if box and box[2] > box[0]:
                return font
    return None


def japanese_page(width: int = 1000, height: int = 1500):
    """A page whose lettering is real Japanese, or `None` without a CJK font.

    Three things a block of rectangles cannot produce:

    * **a vertical column** — glyphs stacked in square em boxes, which is what
      the detector has to read as one region running the other way;
    * **furigana** — a second, much smaller column beside the first. It is the
      case that breaks a naive merge, because it is close enough to the main
      column to be swallowed and is not part of the line;
    * **kanji density** — many strokes inside one em, so the mask has far more
      internal edges per glyph than Latin does.

    **The balloons hug their text**, and that is not cosmetic. The detector
    requires a balloon interior to hold at least `ink_min` (1.5%) of ink, and
    the first version of this fixture drew three glyphs in an ellipse five times
    their size: 1.3%, just under, and detection found none of them. A real manga
    balloon is drawn around its text with a margin of roughly half a character,
    so a fixture that leaves more says more about the fixture than the page.
    """
    font = cjk_font(40)
    if font is None:
        return None
    small = cjk_font(18)

    scale = min(width, height) / 1000.0
    page = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(page)
    border = max(2, round(5 * scale))
    outline = max(2, round(4 * scale))

    panels = []
    margin, gutter = 40 * scale, 34 * scale
    panel_w = (width - 2 * margin - gutter) / 2
    panel_h = (height - 2 * margin - gutter) / 2
    for row in range(2):
        for column in range(2):
            x0 = margin + column * (panel_w + gutter)
            y0 = margin + row * (panel_h + gutter)
            box = [x0, y0, x0 + panel_w, y0 + panel_h]
            draw.rectangle(box, outline=BLACK, width=border)
            panels.append(box)

    # --- a vertical balloon, the column running top to bottom ----------------
    px0, py0, _, _ = panels[0]
    step = 46 * scale
    column_text = "\u3084\u3081\u308d\u3063\u3066"          # やめろって
    cx = px0 + panel_w * 0.52
    top = py0 + 60 * scale
    pad_x, pad_y = 42 * scale, 34 * scale
    draw.ellipse([cx - pad_x, top - pad_y,
                  cx + 40 * scale + pad_x, top + step * len(column_text) + pad_y],
                 fill=WHITE, outline=BLACK, width=outline)
    y = top
    for glyph in column_text:
        draw.text((cx, y), glyph, font=font, fill=BLACK)
        y += step
    # Furigana: a smaller column to the *right* of the main one, which is where
    # a reading goes in vertical Japanese.
    if small is not None:
        ry = top + 4 * scale
        for glyph in "\u3061\u304b\u3089":                    # ちから
            draw.text((cx + 42 * scale, ry), glyph, font=small, fill=BLACK)
            ry += 21 * scale

    # --- a horizontal balloon, so the page carries both orientations ---------
    px0, py0, _, _ = panels[1]
    line = "\u305d\u3046\u304b\u3001\u3068\u601d\u3046"   # そうか、と思う
    text_w = 40 * scale * len(line)
    mid = (px0 + panel_w / 2, py0 + 110 * scale)
    draw.ellipse([mid[0] - text_w / 2 - 34 * scale, mid[1] - 52 * scale,
                  mid[0] + text_w / 2 + 34 * scale, mid[1] + 52 * scale],
                 fill=WHITE, outline=BLACK, width=outline)
    draw.text(mid, line, font=font, fill=BLACK, anchor="mm")

    # --- a sound effect drawn onto the artwork, no balloon around it ---------
    px0, py0, _, py1 = panels[3]
    effect = cjk_font(int(110 * scale)) or font
    draw.text((px0 + 44 * scale, py1 - 190 * scale),
              "\u30c9\u30ab\u30f3", font=effect, fill=BLACK)   # ドカン
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
