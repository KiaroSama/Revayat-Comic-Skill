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
* **anything else** — compare every visible RGB pixel at native resolution
  with the committed render. An absent reference or incompatible renderer is
  unverifiable. The old 8x8 average remains diagnostic only: losing a whole
  balloon can disappear in that average.
"""

from __future__ import annotations

import io
import math
import re
from typing import Any

import pageir as ir

#: The reduction every appearance is compared at. 8x8 grayscale is 64 bytes per
#: page — cheap enough to record for every page of every edition.
GRID = 8

#: Exact comparison's rasterization budget. Larger native packages rely on the
#: committed byte hash; a modified container cannot fall back to thumbnail proof.
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
    if page.rotation or page.cropbox != page.mediabox:
        return False
    if page.get_drawings() or page.get_text("text").strip():
        return False
    if list(page.annots()) or list(page.widgets()):
        return False
    # Admit only the native single-image drawing program. Unknown PDF graphics
    # state (clipping, opacity, forms, extra transforms) cannot prove visibility.
    number = rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    program = (rb"\s*q\s+" + (number + rb"\s+") * 6
               + rb"cm\s+/[A-Za-z0-9_]+\s+Do\s+Q\s*")
    if not re.fullmatch(program, page.read_contents()):
        return False
    for key in ("SMask", "Mask"):
        if page.parent.xref_get_key(placements[0]["xref"], key)[0] != "null":
            return False
    if page.parent.xref_get_key(page.xref, "Group")[0] != "null":
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
    if any(abs(a - b) > 1e-5 for a, b in zip(box, rect)) or covered != area:
        return False

    a, b, c, d = placements[0]["transform"][:4]
    # Axis-aligned and unmirrored. A rotation puts the magnitude into `b`/`c`;
    # a reflection makes `a` or `d` negative.
    return b == 0 and c == 0 and a > 0 and d > 0


def visible_proof(page: Any, *, scale=None) -> dict[str, Any]:
    """Exact native-resolution appearance; never downsample integrity evidence."""
    import pymupdf

    rect = page.rect
    zoom = (1.0, 1.0) if scale is None else scale
    if (not isinstance(zoom, (list, tuple)) or len(zoom) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or v <= 0 for v in zoom)):
        raise ValueError("invalid PDF verification scale")
    if (not all(math.isfinite(value) and value > 0 for value in (rect.width, rect.height))
            or math.ceil(rect.width * zoom[0]) * math.ceil(rect.height * zoom[1])
            > MAX_RASTER_PIXELS):
        raise ValueError("native-resolution PDF exceeds the verification budget")
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(*zoom),
                             colorspace=pymupdf.csRGB, alpha=False, annots=True)
    return {"engine": pymupdf.VersionBind, "size": [pixmap.width, pixmap.height],
            "rotation": page.rotation, "cropbox": list(page.cropbox),
            "mediabox": list(page.mediabox),
            **({"scale": list(zoom)} if scale is not None else {}),
            "sha256": ir.sha256_bytes(pixmap.samples)}


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
    reference = row.get("visible")
    if reference:
        try:
            from pagegeometry import pdf_points

            width_pt, height_pt = pdf_points(row)
            if any(type(row.get(key)) is not int or row[key] <= 0 for key in ("width", "height")):
                raise ValueError("missing native pixel dimensions")
            native = [row["width"] / width_pt, row["height"] / height_pt]
            if not isinstance(reference, dict):
                raise ValueError("invalid native render reference")
            scale = reference.get("scale")
            if scale is not None and (
                not isinstance(scale, list) or len(scale) != 2
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value <= 0 for value in scale)
            ):
                raise ValueError("invalid native render scale")
            if (scale is None and native != [1.0, 1.0]) or (scale is not None and scale != native):
                raise ValueError("render reference does not use the native pixel grid")
            shown = visible_proof(page, scale=None if scale is None else native)
        except Exception as error:
            return "archive-unverified", f"page {index + 1}: {error}"
        if not isinstance(reference, dict) or reference.get("engine") != shown["engine"]:
            return "archive-unverified", f"page {index + 1}: incompatible render reference"
        if reference != shown:
            return "archive-invalid", f"page {index + 1} does not show the committed pixels"
        return "", ""
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
            # Embedded pixel identity alone omits image Decode/colour state.
            # Reconstruct the known image's ordinary sheet and compare what
            # both sheets actually show at native resolution.
            import pymupdf

            try:
                with pymupdf.open() as control:
                    from pagegeometry import pdf_points
                    width, height = pdf_points(row)
                    expected = control.new_page(width=width, height=height)
                    expected.insert_image(expected.rect, stream=payload, keep_proportion=False)
                    zoom = (row["width"] / width, row["height"] / height)
                    if visible_proof(page, scale=zoom) == visible_proof(expected, scale=zoom):
                        return ("", "")
            except (ValueError, KeyError) as error:
                return "archive-unverified", f"page {index + 1}: {error}"
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
    return ("archive-unverified",
            f"page {index + 1} has only a coarse similarity reference; "
            "that cannot prove the dialogue or artwork is intact")
