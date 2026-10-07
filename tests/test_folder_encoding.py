"""Folder planning never pays for discarded page encoding."""
import pytest
from PIL import Image

import export
import package
import readers
import writers


@pytest.mark.parametrize("quality,suffix", [(0, ".png"), (80, ".jpg")])
def test_folder_export_encodes_each_real_page_once(tmp_path, monkeypatch, quality, suffix):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 40), "white").save(source)
    readers.import_source(source, tmp_path / "work", source_language="en")
    path = tmp_path / "work" / "comic.json"
    calls = []
    original = writers._encode

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(writers, "_encode", counted)
    output = tmp_path / "book"
    export.export_document(path, output, fmt="dir", quality=quality, draft=True)
    assert len(calls) == 1
    assert (output / f"0001{suffix}").is_file()
    assert package.check_package(output, path)["ok"]
