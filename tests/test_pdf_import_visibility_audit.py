"""PDF extraction must preserve the visible page, including graphics state."""

import io

import pytest
from PIL import Image, ImageDraw

import pageir as ir
import readers


def _pdf(path, effect, codec="PNG", *, compact=False):
    pymupdf = pytest.importorskip("pymupdf")
    operation = effect.removeprefix("form-")
    image = Image.new("RGB", (240, 320), (30, 60, 90))
    ImageDraw.Draw(image).rectangle((12, 16, 36, 40), fill=(240, 200, 20))
    if operation == "soft-mask":
        image = image.convert("RGBA")
        image.putalpha(128)
    stream = io.BytesIO()
    image.save(stream, codec)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=120, height=160)
        xref = page.insert_image(page.rect, stream=stream.getvalue())
        content = page.get_contents()[0]
        if operation == "clip":
            pdf.update_stream(content, b"q 0 0 60 160 re W n\n"
                              + pdf.xref_stream(content) + b"\nQ")
        elif operation == "color-key":
            pdf.xref_set_key(xref, "Mask", "[30 30 60 60 90 90]")
        elif operation == "decode":
            pdf.xref_set_key(xref, "Decode", "[1 0 1 0 1 0]")
        elif operation == "calibrated":
            pdf.xref_set_key(xref, "ColorSpace", "[/CalRGB << /WhitePoint "
                             "[0.9505 1 1.089] /Gamma [1 1 1] >>]")
        elif operation == "default-rgb":
            pdf.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
            resources = int(pdf.xref_get_key(page.xref, "Resources")[1].split()[0])
            pdf.xref_set_key(resources, "ColorSpace", "<< /DefaultRGB [/CalRGB "
                             "<< /WhitePoint [0.9505 1 1.089] /Gamma [1 1 1] >>] >>")
        elif operation == "icc":
            from PIL import ImageCms

            profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
            color = pdf.get_new_xref()
            pdf.update_object(color, "<< /N 3 /Alternate /DeviceRGB >>")
            pdf.update_stream(color, profile)
            pdf.xref_set_key(xref, "ColorSpace", f"[/ICCBased {color} 0 R]")
        elif operation == "opacity":
            resources = int(pdf.xref_get_key(page.xref, "Resources")[1].split()[0])
            pdf.xref_set_key(resources, "ExtGState", "<< /Faded << /Type /ExtGState "
                             "/ca 0.25 /CA 0.25 >> >>")
            pdf.update_stream(content, b"q /Faded gs\n"
                              + pdf.xref_stream(content) + b"\nQ")
        elif operation == "annotation":
            annotation = page.add_rect_annot(pymupdf.Rect(20, 40, 100, 120))
            annotation.set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
            annotation.update()
        if effect.startswith("form-"):
            with pymupdf.open() as wrapper:
                outer = wrapper.new_page(width=120, height=160)
                outer.show_pdf_page(outer.rect, pdf, 0)
                wrapper.save(path, deflate=compact)
        else:
            pdf.save(path, deflate=compact)
    return path


@pytest.mark.parametrize("effect", [
    "clip", "form-clip", "color-key", "opacity", "form-opacity",
    "annotation", "soft-mask",
])
def test_import_retains_visible_pdf_graphics_state(tmp_path, effect):
    pymupdf = pytest.importorskip("pymupdf")
    source = _pdf(tmp_path / "source.pdf", effect)
    with pymupdf.open(source) as pdf:
        visible = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2),
                                    colorspace=pymupdf.csRGB, alpha=False, annots=True)
        expected = Image.frombytes("RGB", (visible.width, visible.height), visible.samples)

    report = readers.import_source(source, tmp_path / "work", dpi=72)
    doc = ir.load_doc(report["document"])
    page = doc["pages"][0]
    actual = ir.load_image(tmp_path / "work" / page["image"])
    assert (page["width"], page["height"]) == (240, 320)
    assert page["pdf_points"] == [120, 160]
    assert actual.tobytes() == expected.tobytes(), effect


def test_requested_density_above_native_is_retained(tmp_path):
    source = _pdf(tmp_path / "source.pdf", "opacity")
    report = readers.import_source(source, tmp_path / "work", dpi=216)
    page = ir.load_doc(report["document"])["pages"][0]
    assert (page["width"], page["height"]) == (360, 480)
    assert page["pdf_points"] == [120, 160]


def test_low_opacity_native_resolution_still_obeys_pixel_limit(tmp_path, monkeypatch):
    source = _pdf(tmp_path / "source.pdf", "form-opacity")
    monkeypatch.setattr(readers, "MAX_PAGE_PIXELS", 50_000)
    with pytest.raises(ValueError, match="native-resolution.*pixel limit"):
        readers.import_source(source, tmp_path / "work", dpi=72)
    assert not (tmp_path / "work" / "comic.json").exists()


def test_missing_native_density_api_refuses_instead_of_downsampling(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    source = _pdf(tmp_path / "source.pdf", "opacity")
    monkeypatch.delattr(pymupdf.mupdf, "FzDevice2")
    with pytest.raises(ValueError, match="native image geometry is unavailable"):
        readers.import_source(source, tmp_path / "work", dpi=72)
    assert not (tmp_path / "work" / "comic.json").exists()


@pytest.mark.parametrize("codec", ["PNG", "JPEG"])
@pytest.mark.parametrize("compact", [False, True])
def test_safe_scan_still_extracts_exact_bytes_at_native_resolution(tmp_path, codec, compact):
    pymupdf = pytest.importorskip("pymupdf")
    source = _pdf(tmp_path / "source.pdf", "plain", codec, compact=compact)
    with pymupdf.open(source) as pdf:
        expected = pdf.extract_image(pdf[0].get_images(full=True)[0][0])["image"]
        assert readers._single_embedded_image(pdf, pdf[0]) == expected

    report = readers.import_source(source, tmp_path / "work", dpi=300)
    page = ir.load_doc(report["document"])["pages"][0]
    assert (tmp_path / "work" / page["image"]).read_bytes() == expected
    assert (page["width"], page["height"]) == (240, 320)
    assert page["pdf_points"] == [120, 160]


@pytest.mark.parametrize("codec", ["PNG", "JPEG"])
@pytest.mark.parametrize("effect", ["decode", "calibrated", "icc", "default-rgb"])
def test_import_preserves_nondefault_image_color_state(tmp_path, codec, effect):
    pymupdf = pytest.importorskip("pymupdf")
    source = _pdf(tmp_path / "source.pdf", effect, codec)
    with pymupdf.open(source) as pdf:
        pixmap = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2),
                                  colorspace=pymupdf.csRGB, alpha=False)
        expected = pixmap.samples
    report = readers.import_source(source, tmp_path / "work", dpi=72)
    page = ir.load_doc(report["document"])["pages"][0]
    assert ir.load_image(tmp_path / "work" / page["image"]).tobytes() == expected


def test_strong_shear_cannot_bypass_native_pixel_budget(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    import pagegeometry

    buffer = io.BytesIO()
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, 100, 2):
        draw.line((0, y, 99, y), fill="black")
    image.save(buffer, "PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_image(page.rect, stream=buffer.getvalue(), keep_proportion=False)
        content = page.get_contents()[0]
        pdf.update_stream(content, b"q 100 0 100 1 0 0 cm /fzImg0 Do Q")
        # One hundred source rows occupy one perpendicular PDF point. The
        # source column lengths alone incorrectly permit a 200x100 render.
        with pytest.raises(ValueError, match="native-resolution.*pixel limit"):
            pagegeometry.render_native(page, dpi=72, max_pixels=100_000)


@pytest.mark.parametrize("over_budget", [False, True])
def test_native_density_includes_associated_soft_mask(tmp_path, monkeypatch, over_budget):
    pymupdf = pytest.importorskip("pymupdf")
    image_stream, mask_stream = io.BytesIO(), io.BytesIO()
    Image.new("RGB", (100, 100), "black").save(image_stream, "PNG")
    mask = Image.new("L", (1000, 1000), 0)
    draw = ImageDraw.Draw(mask)
    for x in range(0, 1000, 2):
        draw.line((x, 0, x, 999), fill=255)
    mask.save(mask_stream, "PNG")
    source = tmp_path / "source.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        xref = page.insert_image(page.rect, stream=image_stream.getvalue())
        contents = page.get_contents()
        mask_xref = page.insert_image(page.rect, stream=mask_stream.getvalue())
        pdf.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{ref} 0 R" for ref in contents) + "]")
        pdf.xref_set_key(xref, "SMask", f"{mask_xref} 0 R")
        pdf.save(source)
        expected = page.get_pixmap(matrix=pymupdf.Matrix(10, 10), alpha=False).samples
    if over_budget:
        monkeypatch.setattr(readers, "MAX_PAGE_PIXELS", 100_000)
        with pytest.raises(ValueError, match="native-resolution.*pixel limit"):
            readers.import_source(source, tmp_path / "work", dpi=72)
        assert not (tmp_path / "work" / "comic.json").exists()
    else:
        report = readers.import_source(source, tmp_path / "work", dpi=72)
        page = ir.load_doc(report["document"])["pages"][0]
        assert (page["width"], page["height"]) == (1000, 1000)
        assert ir.load_image(tmp_path / "work" / page["image"]).tobytes() == expected


def _stencil_pdf(path, *, pattern, nested):
    """A thousand alternating source columns painted in one hundred points."""
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        mask = pdf.get_new_xref()
        pdf.update_object(mask, "<< /Type /XObject /Subtype /Image /Width 1000 "
                          "/Height 1000 /ImageMask true /BitsPerComponent 1 "
                          "/Decode [0 1] >>")
        pdf.update_stream(mask, b"\xaa" * 125_000)
        paint = pdf.get_new_xref()
        pdf.update_object(paint, "<< /Type /Pattern /PatternType 1 /PaintType 1 "
                          "/TilingType 1 /BBox [0 0 10 10] /XStep 10 /YStep 10 "
                          "/Resources << >> >>")
        pdf.update_stream(paint, b"0 g 0 0 10 10 re f")
        pdf.xref_set_key(page.xref, "Resources", f"<< /XObject << /M {mask} 0 R >> "
                         f"/Pattern << /P {paint} 0 R >> >>")
        content = pdf.get_new_xref()
        pdf.update_object(content, "<< >>")
        color = b"/Pattern cs /P scn" if pattern else b"0 g"
        pdf.update_stream(content, b"q " + color + b" 100 0 0 100 0 0 cm /M Do Q")
        pdf.xref_set_key(page.xref, "Contents", f"{content} 0 R")
        if nested:
            with pymupdf.open() as wrapper:
                outer = wrapper.new_page(width=100, height=100)
                outer.show_pdf_page(outer.rect, pdf, 0)
                wrapper.save(path)
        else:
            pdf.save(path)
    return path


@pytest.mark.parametrize("pattern", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_import_preserves_native_stencil_detail(tmp_path, pattern, nested):
    pymupdf = pytest.importorskip("pymupdf")
    source = _stencil_pdf(tmp_path / "source.pdf", pattern=pattern, nested=nested)
    with pymupdf.open(source) as pdf:
        reference = pdf[0].get_pixmap(matrix=pymupdf.Matrix(10, 10), alpha=False)
        assert set(reference.samples) == {0, 255}
        expected = reference.samples

    result = readers.import_source(source, tmp_path / "work", dpi=72)
    page = ir.load_doc(result["document"])["pages"][0]
    assert (page["width"], page["height"]) == (1000, 1000)
    assert page["pdf_points"] == [100, 100]
    assert ir.load_image(tmp_path / "work" / page["image"]).tobytes() == expected


@pytest.mark.parametrize("nested", [False, True])
def test_pattern_stencil_limit_refuses_before_raster_allocation(tmp_path, monkeypatch, nested):
    pymupdf = pytest.importorskip("pymupdf")
    source = _stencil_pdf(tmp_path / "source.pdf", pattern=True, nested=nested)
    monkeypatch.setattr(readers, "MAX_PAGE_PIXELS", 100_000)

    def forbidden(*args, **kwargs):
        pytest.fail("an over-budget stencil reached raster allocation")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", forbidden)
    with pytest.raises(ValueError, match="native-resolution.*pixel limit"):
        readers.import_source(source, tmp_path / "work", dpi=72)
    assert not (tmp_path / "work" / "comic.json").exists()
