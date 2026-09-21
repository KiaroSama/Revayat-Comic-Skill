"""Keep PDF paper dimensions separate from the immutable raster dimensions."""

import math
from pathlib import Path

import pageir as ir


def pdf_points(page: dict) -> tuple[float, float]:
    """Legacy/non-PDF documents retain the historical one-pixel-per-point size."""
    value = page.get("pdf_points", [page["width"], page["height"]])
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or v <= 0 for v in value)):
        raise ValueError("page PDF dimensions must be two finite positive point values")
    return tuple(float(v) for v in value)


def record_pdf(source: Path, doc: dict) -> None:
    """Record visible paper size, including crop/rotation, before import commits."""
    pymupdf = ir.require("pymupdf", "pymupdf", "reading PDF page dimensions")
    with pymupdf.open(source) as pdf:
        if pdf.page_count != len(doc["pages"]):
            raise ValueError("PDF page count changed while importing")
        for page, original in zip(doc["pages"], pdf):
            page["pdf_points"] = [original.rect.width, original.rect.height]
            pdf_points(page)
            page["raster_dpi"] = [page["width"] * 72 / original.rect.width,
                                  page["height"] * 72 / original.rect.height]
            page["source_pdf_geometry"] = {
                "mediabox": list(original.mediabox),
                "cropbox": list(original.cropbox), "rotation": original.rotation,
            }


def render_native(page, dpi: int, max_pixels: int):
    """Render composite/cropped/rotated pages without decimating embedded scans."""
    pymupdf = ir.require("pymupdf", "pymupdf", "rendering PDF pages")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("PDF DPI must be a positive integer")
    scale = dpi / 72
    for image in page.get_image_info():
        a, b, c, d, _, _ = image["transform"]
        width, height = math.hypot(a, b), math.hypot(c, d)
        # Singular placements draw no visible area. All other images retain at
        # least their own sampling density, even when the page itself is rotated.
        if width > 0 and height > 0:
            scale = max(scale, image["width"] / width, image["height"] / height)
    rect = page.rect
    if (not math.isfinite(scale) or not math.isfinite(rect.width * rect.height)
            or rect.width <= 0 or rect.height <= 0
            or math.ceil(rect.width * scale) * math.ceil(rect.height * scale) > max_pixels):
        raise ValueError("PDF native-resolution rendering exceeds the page pixel limit; "
                         "split or inspect the source instead of lowering its resolution")
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    pixmap.set_dpi(round(scale * 72), round(scale * 72))
    return pixmap
