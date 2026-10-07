"""Encoded loose input is admitted before copying or decoding."""
import pytest
from PIL import Image

import pageimages
import pageir as ir
import readers


@pytest.mark.parametrize("folder", [False, True])
def test_oversized_encoded_image_refuses_without_import_output(tmp_path, monkeypatch, folder):
    source = tmp_path / "source"
    source.mkdir()
    image = source / "page.png"
    Image.new("RGB", (4, 4), "white").save(image)
    with image.open("ab") as stream:
        stream.write(b"trailing" * 32)
    monkeypatch.setattr(readers, "MAX_MEMBER_BYTES", 128)
    out = tmp_path / "work"
    with pytest.raises(ValueError, match="encoded-byte"):
        readers.import_source(source if folder else image, out)
    assert not (out / "comic.json").exists()


def test_aggregate_loose_budget_refuses_before_any_copy(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(2):
        Image.new("RGB", (4, 4), "white").save(source / f"{index}.png")
    monkeypatch.setattr(readers, "MAX_TOTAL_BYTES", 100)
    with pytest.raises(ValueError, match="encoded-byte"):
        readers.import_source(source, tmp_path / "work")
    assert not (tmp_path / "work/comic.json").exists()


def test_counted_copy_preserves_existing_operator_target(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    target = tmp_path / "p0001.png"
    target.write_bytes(b"operator")
    with pytest.raises(FileExistsError):
        pageimages.copy_loose_images([source], tmp_path, member_limit=100, total_limit=100)
    assert target.read_bytes() == b"operator"


def test_host_imageio_module_is_not_shadowed(monkeypatch):
    import importlib
    import sys
    import types

    host = types.ModuleType("imageio")
    monkeypatch.setitem(sys.modules, "imageio", host)
    assert importlib.reload(ir).load_image is pageimages.load_image
    assert sys.modules["imageio"] is host


def test_file_backed_read_closes_handle_and_preserves_pixels(tmp_path):
    source = tmp_path / "page.png"
    Image.new("RGB", (8, 8), (17, 23, 29)).save(source)
    result = ir.load_image(source)
    source.unlink()
    assert result.getpixel((0, 0)) == (17, 23, 29)


def test_loader_checks_encoded_size_before_pillow_open(tmp_path, monkeypatch):
    source = tmp_path / "page.png"
    source.write_bytes(b"x" * 129)
    monkeypatch.setattr(pageimages, "MAX_MEMBER_BYTES", 128)
    with pytest.raises(ValueError, match="encoded-byte"):
        ir.load_image(source)
