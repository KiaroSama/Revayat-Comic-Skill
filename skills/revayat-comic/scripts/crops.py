"""Render what the reader has to look at: the page, and every crop on it.

This is where the design differs from a conventional manga translator. Those
pipelines run an OCR model, hand a bare string to a translator, and hope. The
string is all the translator ever gets — not the face above the balloon, not the
balloon it is answering, not whether the character is shouting.

Here the reader *is* the model running the skill, and it can see. So two images
are produced per page:

* **overview.png** — the whole page, downscaled, with every region outlined and
  numbered in reading order. This carries the context: who is speaking, what
  they are looking at, which balloon answers which.
* **sheet.png** — the crops themselves, stacked and labelled with their region
  ids, each one enlarged until the lettering is actually legible.

The reader transcribes and translates from those two together, which is what a
human scanlator does and why the result is better than OCR-then-translate. The
ids on the sheet are the ids the worksheet expects back, so nothing has to be
matched up by position afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import pageir as ir

#: Enlarge every crop until its shorter side reaches this, so small furigana is
#: readable rather than a suggestion of a shape.
MIN_CROP_SIDE = 150
MAX_CROP_SIDE = 1100

#: A sheet taller than this is split. Very tall images get downscaled by the
#: viewer, which undoes the enlargement above.
SHEET_MAX_HEIGHT = 4200
OVERVIEW_MAX_SIDE = 1600

LABEL_WIDTH = 190
GUTTER = 14
BACKGROUND = (250, 250, 248)
RULE = (196, 196, 190)

#: Region kinds, and the colour each is outlined in on the overview.
KIND_COLOURS = {
    "speech": (0, 122, 204),
    "thought": (128, 90, 200),
    "narration": (0, 150, 110),
    "sfx": (216, 88, 20),
    "sign": (170, 140, 0),
    "unknown": (140, 140, 140),
}


def _pil():
    ir.require("PIL", "pillow", "rendering crops")
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _label_font(size: int = 15):
    _, _, ImageFont = _pil()
    # A real TrueType face keeps the label readable when the sheet is scaled.
    # The bitmap default is always present, so labelling never fails outright.
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(image, minimum: int, maximum: int):
    width, height = image.size
    if width <= 0 or height <= 0:
        return image
    scale = 1.0
    shorter = min(width, height)
    if shorter < minimum:
        scale = minimum / shorter
    longer = max(width, height) * scale
    if longer > maximum:
        scale = maximum / max(width, height)
    if abs(scale - 1.0) < 0.02:
        return image
    Image, _, _ = _pil()
    resample = Image.LANCZOS if scale < 1 else Image.BICUBIC
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))), resample
    )


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #

def render_overview(page_image, page: dict[str, Any]):
    Image, ImageDraw, _ = _pil()
    canvas = page_image.convert("RGB").copy()
    scale = min(1.0, OVERVIEW_MAX_SIDE / max(canvas.size))
    if scale < 1.0:
        canvas = canvas.resize(
            (max(1, int(canvas.width * scale)), max(1, int(canvas.height * scale))),
            Image.LANCZOS,
        )
    draw = ImageDraw.Draw(canvas)
    font = _label_font(max(13, int(canvas.width / 62)))
    stroke = max(2, int(canvas.width / 400))

    for panel in page.get("panels", []):
        x, y, w, h = (value * scale for value in panel["bbox"])
        draw.rectangle([x, y, x + w, y + h], outline=(220, 220, 220), width=1)

    for region in page.get("regions", []):
        colour = KIND_COLOURS.get(region["kind"], KIND_COLOURS["unknown"])
        x, y, w, h = (value * scale for value in region["bbox"])
        draw.rectangle([x, y, x + w, y + h], outline=colour, width=stroke)

        tag = str(region.get("reading_order") or "?")
        box = draw.textbbox((0, 0), tag, font=font)
        pad = 4
        tw, th = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
        # The badge goes above the box, or inside it when the box is at the very
        # top of the page and there is nowhere above to put it.
        by = y - th if y - th >= 0 else y
        draw.rectangle([x, by, x + tw, by + th], fill=colour)
        draw.text((x + pad, by + pad - box[1]), tag, font=font, fill=(255, 255, 255))

    return canvas


# --------------------------------------------------------------------------- #
# Crop sheets
# --------------------------------------------------------------------------- #

def _crop_for(page_image, region: dict[str, Any], page_size: tuple[int, int]):
    width, height = page_size
    # Show the balloon, not just the letters: the shape of the balloon is what
    # separates speech from a thought and from a shout.
    source = region.get("balloon") or region["bbox"]
    margin = 0.03 * max(source[2], source[3])
    box = ir.expand_bbox(source, margin, width, height)
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return None
    return _fit(page_image.crop((x, y, x + w, y + h)), MIN_CROP_SIDE, MAX_CROP_SIDE)


def render_sheets(page_image, page: dict[str, Any]) -> list[Any]:
    Image, ImageDraw, _ = _pil()
    font = _label_font(15)
    small = _label_font(13)
    size = (page["width"], page["height"])

    entries: list[tuple[dict[str, Any], Any]] = []
    for region in page.get("regions", []):
        crop = _crop_for(page_image, region, size)
        if crop is not None:
            entries.append((region, crop))
    if not entries:
        return []

    sheets: list[Any] = []
    batch: list[tuple[dict[str, Any], Any]] = []
    used = 0
    for region, crop in entries:
        cost = crop.height + GUTTER + 26
        if batch and used + cost > SHEET_MAX_HEIGHT:
            sheets.append(_compose(batch, font, small))
            batch, used = [], 0
        batch.append((region, crop))
        used += cost
    if batch:
        sheets.append(_compose(batch, font, small))
    return sheets


def _compose(entries, font, small):
    Image, ImageDraw, _ = _pil()
    width = LABEL_WIDTH + GUTTER + max(crop.width for _, crop in entries) + GUTTER
    height = GUTTER + sum(max(crop.height, 44) + GUTTER for _, crop in entries)
    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)

    y = GUTTER
    for region, crop in entries:
        row = max(crop.height, 44)
        colour = KIND_COLOURS.get(region["kind"], KIND_COLOURS["unknown"])
        draw.rectangle([0, y - GUTTER // 2, width, y - GUTTER // 2], fill=RULE)
        draw.rectangle([6, y, 12, y + row], fill=colour)

        lines = [
            region["id"],
            f"#{region.get('reading_order') or '?'}  {region['kind']}",
            region["orientation"],
        ]
        if region.get("panel"):
            lines.append(f"panel {region['panel'][-2:]}")
        if region.get("confidence", 1.0) < 0.5:
            lines.append("LOW CONFIDENCE")
        draw.text((22, y), lines[0], font=font, fill=(20, 20, 20))
        for index, line in enumerate(lines[1:], start=1):
            draw.text((22, y + 4 + index * 17), line, font=small, fill=(90, 90, 90))

        sheet.paste(crop, (LABEL_WIDTH + GUTTER, y))
        draw.rectangle(
            [LABEL_WIDTH + GUTTER - 1, y - 1,
             LABEL_WIDTH + GUTTER + crop.width, y + crop.height],
            outline=RULE, width=1,
        )
        y += row + GUTTER
    return sheet


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def build_document(
    doc_path: str | Path, *, pages: Sequence[str] | None = None
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)

    produced: list[dict[str, Any]] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        image = ir.load_image(root / page["image"])
        folder = f"crops/{page['id']}"

        overview = f"{folder}/overview.png"
        ir.save_image(render_overview(image, page), root / overview)

        sheets = render_sheets(image, page)
        names: list[str] = []
        for index, sheet in enumerate(sheets, start=1):
            name = f"{folder}/sheet{index:02d}.png"
            ir.save_image(sheet, root / name)
            names.append(name)

        page["overview"] = overview
        page["sheets"] = names
        produced.append({
            "page": page["id"],
            "overview": overview,
            "sheets": names,
            "regions": len(page.get("regions", [])),
        })

    ir.stamp_stage(doc, "crops", {"pages": len(produced)})
    ir.save_doc(doc, doc_path)
    return {
        "document": str(doc_path),
        "pages": produced,
        "read": "Open overview.png for context and sheet*.png for the text, "
                "then fill in the worksheet.",
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic crops",
        description="Render the page overview and the labelled crop sheets.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="")
    args = parser.parse_args(argv)

    report = build_document(
        args.doc, pages=[p for p in args.pages.split(",") if p] or None
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
