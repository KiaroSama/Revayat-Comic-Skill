"""Resume compares what the current renderer supplies, not stale cache bytes."""
from pathlib import Path

from PIL import Image

import crops
import ocr
import pageir as ir
import providers
import readers


def test_renderer_change_invalidates_resume_without_geometry_change(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 100), "white").save(source)
    readers.import_source(source, tmp_path / "work", source_language="en")
    path = tmp_path / "work" / "comic.json"
    doc = ir.load_doc(path)
    region = ir.new_region("p0001r001", [10, 10, 30, 20], kind="sign")
    doc["pages"][0]["regions"] = [region]
    ir.save_doc(doc, path)

    class Reader:
        name = "crop-reader"
        def __init__(self):
            self.seen = []
        role = "ocr"
        def read(self, crop, language):
            self.seen.append(ir.sha256_file(Path(crop)))
            return "ONE"

    reader = Reader()
    monkeypatch.setitem(providers._REGISTRY["ocr"], "crop-reader", lambda: reader)
    ocr.read_document(path, provider="crop-reader")
    assert len(reader.seen) == 1
    original = crops._crop_for

    def changed(*args):
        crop = original(*args)
        return Image.new("RGB", crop.size, (13, 17, 19))

    monkeypatch.setattr(crops, "_crop_for", changed)
    ocr.read_document(path, provider="crop-reader")
    assert len(reader.seen) == 2
    assert reader.seen[0] != reader.seen[1]
    ocr.read_document(path, provider="crop-reader")
    assert len(reader.seen) == 2
