"""Import must refuse unsupported multi-frame scans before replacing a chapter."""

import zipfile

import pytest
from PIL import Image

import pageir as ir
import readers


def _source(tmp_path, fmt, route, *, frames):
    suffix = {"TIFF": ".tiff", "GIF": ".gif", "PNG": ".png", "WEBP": ".webp"}[fmt]
    folder = tmp_path / "incoming"
    folder.mkdir()
    image = folder / ("page1" + suffix)
    options = {"save_all": True, "append_images": [Image.new("RGB", (40, 60), "blue")]} if frames > 1 else {}
    Image.new("RGB", (40, 60), "white").save(image, format=fmt, **options)
    if route == "directory":
        return folder, image
    if route == "cbz":
        archive = tmp_path / "incoming.cbz"
        with zipfile.ZipFile(archive, "w") as output:
            output.write(image, image.name)
        return archive, image
    return image, image


@pytest.mark.parametrize("fmt", ["TIFF", "GIF", "PNG", "WEBP"])
@pytest.mark.parametrize("route", ["image", "directory", "cbz"])
def test_multiframe_input_is_refused_without_losing_existing_work(tmp_path, fmt, route):
    original = tmp_path / "original.png"
    Image.new("RGB", (32, 48), "red").save(original)
    readers.import_source(original, tmp_path / "work")
    document = tmp_path / "work" / "comic.json"
    before = document.read_bytes()
    baseline = (tmp_path / "work" / "pages" / "p0001.png").read_bytes()
    source, image = _source(tmp_path, fmt, route, frames=2)
    with Image.open(image) as scanned:
        assert scanned.n_frames == 2
    digest = ir.sha256_file(image)
    with pytest.raises(ValueError, match="multi-frame"):
        readers.import_source(source, tmp_path / "work")
    assert document.read_bytes() == before
    assert (tmp_path / "work" / "pages" / "p0001.png").read_bytes() == baseline
    assert ir.sha256_file(image) == digest


@pytest.mark.parametrize("fmt", ["TIFF", "GIF"])
@pytest.mark.parametrize("route", ["image", "directory", "cbz"])
def test_single_frame_scans_keep_original_bytes(tmp_path, fmt, route):
    source, image = _source(tmp_path, fmt, route, frames=1)
    expected = image.read_bytes()
    report = readers.import_source(source, tmp_path / "work")
    assert report["pages"] == 1
    page = ir.load_doc(report["document"])["pages"][0]
    assert (page["width"], page["height"]) == (40, 60)
    assert (tmp_path / "work" / page["image"]).read_bytes() == expected
