"""Two reply addresses for one region must never select a winner."""
import copy

import pytest
from PIL import Image

import pageir as ir
import readers
import worksheet


@pytest.mark.parametrize("second", ["fa: دوم", "keep: yes", "fa: نخست"])
def test_alias_and_stable_id_refuse_the_page(tmp_path, second):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 100), "white").save(source)
    readers.import_source(source, tmp_path / "work", source_language="en")
    path = tmp_path / "work" / "comic.json"
    # Real protocol allocation establishes the alias; no invented region schema.
    folder = path.parent / "worksheets"
    folder.mkdir()
    reply = folder / "p0001.done.txt"
    stamp = ir.page_fingerprint(ir.load_doc(path)["pages"][0])
    ir.write_text(reply, f"# fingerprint: {stamp}\n@@ +extra sign horizontal\nbox: 10 10 30 20\nsrc: ONE\nfa: نخست\n")
    assert worksheet.merge_document(path)["added"]
    page = ir.load_doc(path)["pages"][0]
    region = page["regions"][0]
    before = copy.deepcopy(page["regions"])
    text = ir.read_text(reply) + f"\n@@ {region['id']} sign horizontal\nsrc: ONE\n{second}\n"
    ir.write_text(reply, text)
    report = worksheet.merge_document(path)
    assert not report["ok"], report
    assert region["id"] in report["duplicate_regions"]
    after = ir.load_doc(path)["pages"][0]
    assert after["regions"] == before
    assert after["worksheet_clean"] is False
