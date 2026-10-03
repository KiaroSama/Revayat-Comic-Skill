"""Corrected boxes update context order without erasing manual text-only choices."""

import copy
import logging

import pytest

import context as chapter_context
import pageir as ir
import worksheet

LOG = logging.getLogger(__name__)


@pytest.fixture
def geometry_page(tmp_path):
    doc = ir.new_doc(source_language="en", reading_direction="ltr")
    page = ir.new_page("p0001", 0, "page.png", 300, 180, "0" * 64)
    page["panels"] = [{"id": "left", "bbox": [0, 0, 120, 180]},
                      {"id": "right", "bbox": [180, 0, 120, 180]}]
    for number, box, panel in ((1, [10, 20, 20, 20], "left"),
                               (2, [210, 20, 20, 20], "right")):
        region = ir.new_region(f"p0001r{number:03d}", box, kind="speech")
        region.update(source_text=f"Line {number}", target_text=f"سلام {number}",
                      panel=panel, reading_order=number, locked=True)
        page["regions"].append(region)
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    LOG.info("Created a minimal two-panel worksheet fixture")
    return path


def _merge(path, fields=None, added=""):
    worksheet.build_document(path)
    folder = path.parent / "worksheets"
    text = ir.read_text(folder / "p0001.txt")
    for region_id, field in (fields or {}).items():
        needle = f"@@ {region_id} speech horizontal"
        text = text.replace(needle, needle + "\n" + field)
    ir.write_text(folder / "p0001.done.txt", text + added)
    return worksheet.merge_document(path)


def test_moved_existing_boxes_refresh_panel_and_order(geometry_page):
    assert _merge(geometry_page, {"p0001r001": "box: 240 20 20 20",
                                  "p0001r002": "box: 20 20 20 20"})["ok"]
    page = ir.load_doc(geometry_page)["pages"][0]
    assert [r["id"] for r in page["regions"]] == ["p0001r002", "p0001r001"]
    assert [r["panel"] for r in page["regions"]] == ["left", "right"]
    assert [r["reading_order"] for r in page["regions"]] == [1, 2]


@pytest.mark.parametrize("direction,expected", [("ltr", ["p0001r002", "p0001r001"]),
                                               ("rtl", ["p0001r001", "p0001r002"])])
def test_corrected_context_follows_current_direction(geometry_page, direction, expected):
    doc = ir.load_doc(geometry_page)
    doc["meta"]["reading_direction"] = direction
    ir.save_doc(doc, geometry_page)
    assert _merge(geometry_page, {"p0001r001": "box: 240 20 20 20",
                                  "p0001r002": "box: 20 20 20 20"})["ok"]
    doc = ir.load_doc(geometry_page)
    assert [r["id"] for r in doc["pages"][0]["regions"]] == expected
    doc["pages"].append(ir.new_page("p0002", 1, "next.png", 300, 180, "0" * 64))
    previous = chapter_context.build(doc, "p0002")["context"]["translation_memory"]
    assert [row["src"] for row in previous] == (["Line 2", "Line 1"] if direction == "ltr"
                                               else ["Line 1", "Line 2"])


def test_move_into_gutter_clears_stale_panel(geometry_page):
    assert _merge(geometry_page, {"p0001r001": "box: 140 20 20 20"})["ok"]
    page = ir.load_doc(geometry_page)["pages"][0]
    moved = next(r for r in page["regions"] if r["id"] == "p0001r001")
    assert not moved.get("panel")
    assert page["regions"][-1]["id"] == moved["id"]


def test_added_box_is_assigned_before_panel_dialogue(geometry_page):
    added = "\n@@ +first speech horizontal\nbox: 2 2 20 10\nsrc: First\nfa: اول\n"
    assert _merge(geometry_page, added=added)["ok"]
    page = ir.load_doc(geometry_page)["pages"][0]
    assert page["regions"][0]["added_as"] == "first"
    assert page["regions"][0]["panel"] == "left"
    assert worksheet.merge_document(geometry_page)["unchanged"] == ["p0001"]


def test_text_only_merge_preserves_manual_panel_and_order(geometry_page):
    doc = ir.load_doc(geometry_page)
    page = doc["pages"][0]
    page["regions"][0]["panel"] = "right"
    page["regions"][0]["reading_order"] = 2
    page["regions"][1]["reading_order"] = 1
    before = [(r["id"], r["panel"], r["reading_order"]) for r in page["regions"]]
    ir.save_doc(doc, geometry_page)
    assert _merge(geometry_page, {"p0001r001": "speaker: Reader"})["ok"]
    page = ir.load_doc(geometry_page)["pages"][0]
    assert [(r["id"], r["panel"], r["reading_order"]) for r in page["regions"]] == before


def test_invalid_geometry_reply_rolls_back_all_regions(geometry_page):
    before = copy.deepcopy(ir.load_doc(geometry_page)["pages"][0]["regions"])
    result = _merge(geometry_page, {"p0001r001": "box: 240 20 20 20",
                                    "p0001r002": "box: invalid"})
    assert not result["ok"] and result["bad_added_regions"]
    assert ir.load_doc(geometry_page)["pages"][0]["regions"] == before
