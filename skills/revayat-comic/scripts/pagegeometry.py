"""Keep PDF paper dimensions separate from the immutable raster dimensions."""

import math
from pathlib import Path

import pageir as ir


def pdf_points(page: dict) -> tuple[float, float]:
    """Legacy/non-PDF documents retain the historical one-pixel-per-point size."""
    value = page.get("pdf_points", [page["width"], page["height"]])
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("page PDF dimensions must be two finite positive point values")
    points: list[float] = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("page PDF dimensions must be two finite positive point values")
        try:
            f = float(v)
        except OverflowError:
            raise ValueError("page PDF dimensions must be two finite positive point values") from None
        if not math.isfinite(f) or f <= 0:
            raise ValueError("page PDF dimensions must be two finite positive point values")
        points.append(f)
    return (points[0], points[1])


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


def _native_scale(page, minimum: float, pymupdf) -> float:
    """Measure image placements without the TextPage opacity filter.

    ``get_image_info`` omits visible low-opacity images. The read-only MuPDF
    device sees their native dimensions and matrices, including nested forms,
    without allocating decoded images or changing the PDF's graphics state.
    This binding is documented by PyMuPDF's maintainers:
    https://github.com/pymupdf/PyMuPDF/discussions/3633
    """
    core = getattr(pymupdf, "mupdf", None)
    device_type = getattr(core, "FzDevice2", None)
    if device_type is None:
        raise ValueError("PDF native image geometry is unavailable; install a supported "
                         "PyMuPDF build instead of lowering the source resolution")

    class ImageDensity(device_type):
        def __init__(self):
            super().__init__()
            self.scale = minimum
            self.use_virtual_fill_image()
            self.use_virtual_fill_image_mask()

        def fill_image(self, ctx, image, matrix, alpha, color_params):
            if alpha <= 0:
                return
            seen = set()
            for _ in range(8):
                if image is None:
                    return
                identity = int(image.this)
                if identity in seen or image.w <= 0 or image.h <= 0:
                    self.scale = math.inf
                    return
                seen.add(identity)
                self.measure(image, matrix)
                # A high-resolution soft mask can contain the page's finest
                # detail even when its color image is a small flat bitmap.
                image = image.mask
            if image is not None:
                self.scale = math.inf

        def measure(self, image, matrix):
            a, b = matrix.a / image.w, matrix.b / image.w
            c, d = matrix.c / image.h, matrix.d / image.h
            if not all(math.isfinite(value) for value in (a, b, c, d)):
                self.scale = math.inf
                return
            # Bound the most compressed direction of the source-pixel affine
            # map, including shear. Column lengths alone can lose whole rows.
            # sigma_min = abs(det) / sigma_max avoids subtracting near equals.
            determinant = abs(a * d - b * c)
            if determinant > 0:
                largest = (math.hypot(a + d, b - c) + math.hypot(a - d, b + c)) / 2
                self.scale = max(self.scale, largest / determinant)

        def fill_image_mask(self, ctx, image, matrix, colorspace, color,
                            alpha, color_params):
            self.fill_image(ctx, image, matrix, alpha, color_params)

    device = ImageDensity()
    try:
        core.fz_run_page(page.this, device, core.FzMatrix(), core.FzCookie())
    finally:
        core.fz_close_device(device)
    return device.scale


def render_native(page, dpi: int, max_pixels: int):
    """Render composite/cropped/rotated pages without decimating embedded scans."""
    pymupdf = ir.require("pymupdf", "pymupdf", "rendering PDF pages")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("PDF DPI must be a positive integer")
    scale = _native_scale(page, dpi / 72, pymupdf)
    rect = page.rect
    if (not math.isfinite(scale) or not math.isfinite(rect.width * rect.height)
            or rect.width <= 0 or rect.height <= 0
            or math.ceil(rect.width * scale) * math.ceil(rect.height * scale) > max_pixels):
        raise ValueError("PDF native-resolution rendering exceeds the page pixel limit; "
                         "split or inspect the source instead of lowering its resolution")
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    pixmap.set_dpi(round(scale * 72), round(scale * 72))
    return pixmap
