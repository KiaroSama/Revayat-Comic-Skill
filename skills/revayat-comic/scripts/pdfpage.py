"""What a PDF sheet actually SHOWS, as opposed to what it contains.

Hashing the embedded image proves the right bytes are in the file. It does not
prove a reader sees them. The same correct XObject can be rotated, mirrored,
scaled to a corner, clipped, drawn at 10% opacity or covered by an opaque
rectangle, and every one of those still matches the hash of the image that was
saved. A share-of-the-sheet threshold does not close it either: half a page is
enough to pass it and not enough to be the page.

So there are two answers here and no third:

* **shown** — the sheet is provably nothing but this image. One drawn image,
  covering the whole sheet, placed with an axis-aligned unmirrored transform,
  with no other drawing, text or annotation anywhere on it. Then the image's
  decoded pixels ARE the visible page and hashing them is exact.
* **anything else** — the structure is not provably equivalent, so the bytes
  are not evidence about the appearance. The sheet is rasterized within a
  bounded budget and compared against the appearance the export recorded. A
  package that carries no such reference is reported as unverifiable, never
  passed on its dimensions.

The appearance reference is a 8x8 grayscale reduction of the page as it was
exported: small enough to sit in every manifest row, coarse enough to survive
rasterization at a different scale, and specific enough that a swapped page, a
rotation, a crop or an opaque overlay moves it far outside the tolerance.
"""

from __future__ import annotations

import io
from typing import Any

import pageir as ir

#: The reduction every appearance is compared at. 8x8 grayscale is 64 bytes per
#: page — cheap enough to record for every page of every edition.
GRID = 8

#: A rasterization budget, in pixels of the rendered sheet. The comparison only
#: needs GRID x GRID, so this is generous by a wide margin and still refuses to
#: render a sheet that would cost real memory.
MAX_RASTER_PIXELS = 4_000_000

#: Mean absolute difference, per cell, between two appearance grids. Measured
#: between an exported page and the same page rasterized out of the PDF that
#: carries it: the two paths disagree by a few units of 255 from resampling
#: alone. A wrong, rotated, cropped or overlaid page moves tens of units.
APPEARANCE_TOLERANCE = 12


def appearance(payload: bytes) -> str:
    """The appearance reference for an image, as hex. Empty if unreadable."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(payload)) as image:
            return _reduce(image)
    except Exception:      # pragma: no cover - an unreadable page fails earlier
        return ""


def _reduce(image: Any) -> str:
    from PIL import Image

    grid = image.convert("L").resize((GRID, GRID), Image.Resampling.BOX)
    return grid.tobytes().hex()


def difference(one: str, other: str) -> int:
    """Mean absolute difference per cell, or -1 when they cannot be compared."""
    try:
        left, right = bytes.fromhex(one), bytes.fromhex(other)
    except ValueError:
        return -1
    if not left or len(left) != len(right):
        return -1
    return round(sum(abs(a - b) for a, b in zip(left, right)) / len(left))


def _is_plain_full_page(page: Any, placements: list[dict[str, Any]]) -> bool:
    """Is this sheet provably nothing but one image, drawn as the page?

    Every condition here is one of the ways a correct image can be on a sheet
    without being what the reader sees.
    """
    if len(placements) != 1:
        return False
    if page.get_drawings() or page.get_text("text").strip():
        return False
    if list(page.annots()):
        return False

    rect = page.rect
    area = abs(rect.width * rect.height)
    if not area:
        return False
    import pymupdf

    box = pymupdf.Rect(placements[0]["bbox"])
    drawn = box & rect
    covered = abs(drawn.width * drawn.height)
    # Both directions: the image has to fill the sheet AND not hang off it.
    if covered / area < 0.995 or covered / max(abs(box.width * box.height),
                                               1e-9) < 0.995:
        return False

    a, b, c, d = placements[0]["transform"][:4]
    scale = max(abs(a), abs(b), abs(c), abs(d), 1e-9)
    # Axis-aligned and unmirrored. A rotation puts the magnitude into `b`/`c`;
    # a reflection makes `a` or `d` negative.
    return (abs(b) / scale < 1e-3 and abs(c) / scale < 1e-3
            and a > 0 and d > 0)


def rasterized(page: Any) -> str:
    """The appearance of the sheet as a reader sees it, within the budget."""
    import pymupdf
    from PIL import Image

    rect = page.rect
    area = abs(rect.width * rect.height) or 1.0
    # Render a little above the grid so the reduction has something to average,
    # and never more than the budget allows.
    scale = min((GRID * 8) / max(rect.width, rect.height, 1e-9),
                (MAX_RASTER_PIXELS / area) ** 0.5)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                             colorspace=pymupdf.csGRAY, alpha=False)
    with Image.frombytes("L", (pixmap.width, pixmap.height),
                         pixmap.samples) as image:
        return _reduce(image)


def verify(document: Any, page: Any, row: dict[str, Any],
           index: int) -> tuple[str, str]:
    """`(code, message)` for this sheet; `("", "")` when it shows the page.

    `row` is the manifest row THIS package's export wrote for this page.
    """
    placements = [info for info in page.get_image_info(xrefs=True)
                  if info.get("bbox") and info.get("xref")]
    if not placements:
        return ("archive-invalid",
                f"page {index + 1} draws no image at all")

    if _is_plain_full_page(page, placements):
        wanted = row.get("pixels")
        if not wanted:
            return ("archive-unverified",
                    f"page {index + 1} was written by a build that recorded "
                    f"no pixels for it, so there is nothing to check it "
                    f"against. Export the chapter again")
        from PIL import Image

        try:
            payload = document.extract_image(placements[0]["xref"])["image"]
            with Image.open(io.BytesIO(payload)) as image:
                shown = ir.sha256_bytes(image.convert("RGB").tobytes())
        except Exception:
            return ("archive-invalid",
                    f"page {index + 1} carries an image the reader cannot open")
        if shown == wanted:
            return ("", "")
        return ("archive-invalid",
                f"page {index + 1} does not show the page this export wrote")

    # The sheet is not provably one plain image: something is placed, drawn or
    # transformed over or instead of it, and the embedded bytes say nothing
    # about what a reader sees. Only the rendered sheet can answer now.
    reference = row.get("appearance")
    if not reference:
        return ("archive-unverified",
                f"page {index + 1} is not a single full-page image, and this "
                f"package records no appearance to compare the rendered sheet "
                f"against. Export the chapter again to record one")
    try:
        drift = difference(rasterized(page), reference)
    except Exception as error:
        return ("archive-invalid",
                f"page {index + 1} could not be rendered: {error}")
    if drift < 0:
        return ("archive-unverified",
                f"page {index + 1} has an appearance reference this build "
                f"cannot read")
    if drift > APPEARANCE_TOLERANCE:
        return ("archive-invalid",
                f"page {index + 1} does not look like the page this export "
                f"wrote (difference {drift}, tolerance "
                f"{APPEARANCE_TOLERANCE})")
    return ("", "")
