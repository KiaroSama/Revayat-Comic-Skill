"""The document model: geometry, reading order, script detection, staleness."""

from __future__ import annotations

import pytest

import pageir as ir
import stages


# --- Geometry ---------------------------------------------------------------

def test_intersection_of_disjoint_boxes_is_empty():
    assert ir.bbox_area(ir.bbox_intersection([0, 0, 10, 10], [50, 50, 10, 10])) == 0


def test_iou_is_one_for_identical_boxes():
    assert ir.bbox_iou([4, 4, 20, 20], [4, 4, 20, 20]) == pytest.approx(1.0)


def test_contains_uses_area_share_not_strict_containment():
    outer = [0, 0, 100, 100]
    assert ir.bbox_contains(outer, [10, 10, 50, 50])
    # 90% inside is still "in this panel"; a balloon may lean over a border.
    assert ir.bbox_contains(outer, [95, 10, 40, 20], slack=0.1)
    assert not ir.bbox_contains(outer, [95, 10, 40, 20], slack=0.9)


def test_clamp_keeps_boxes_on_the_page():
    assert ir.clamp_bbox([-20, -20, 60, 60], 100, 100) == [0, 0, 40, 40]
    assert ir.clamp_bbox([80, 80, 100, 100], 100, 100) == [80, 80, 20, 20]


def test_expand_cannot_leave_the_page():
    box = ir.expand_bbox([5, 5, 10, 10], 50, 100, 100)
    assert box[0] == 0 and box[1] == 0
    assert box[0] + box[2] <= 100 and box[1] + box[3] <= 100


# --- Reading order ----------------------------------------------------------

def _page(regions, panels=()):
    page = ir.new_page("p0001", 0, "pages/p0001.png", 1000, 1500, "x" * 64)
    page["regions"] = [
        ir.new_region(f"r{index:03d}", box) for index, box in enumerate(regions)
    ]
    page["panels"] = [
        {"id": f"n{index:02d}", "bbox": box} for index, box in enumerate(panels)
    ]
    return page


def test_right_to_left_orders_the_rightmost_balloon_first():
    page = _page([[100, 100, 80, 80], [800, 100, 80, 80]])
    ordered = ir.assign_reading_order(page, "rtl")
    assert [region["bbox"][0] for region in ordered] == [800, 100]


def test_left_to_right_reverses_that():
    page = _page([[100, 100, 80, 80], [800, 100, 80, 80]])
    ordered = ir.assign_reading_order(page, "ltr")
    assert [region["bbox"][0] for region in ordered] == [100, 800]


def test_a_few_pixels_of_height_do_not_reorder_a_row():
    """Two balloons side by side are one tier even when one sits slightly higher.

    Sorting by `y` alone puts the higher one first, which reads wrong on every
    page that has a pair — the whole reason bands exist.
    """
    page = _page([[100, 104, 80, 80], [800, 100, 80, 80]])
    ordered = ir.assign_reading_order(page, "rtl")
    assert [region["bbox"][0] for region in ordered] == [800, 100]


def test_panels_outrank_height_on_the_page():
    """A balloon at the top of the next panel comes after one at the bottom of
    this panel, even though it sits higher on the paper."""
    page = _page(
        regions=[[600, 900, 60, 60], [100, 100, 60, 60]],
        panels=[[50, 50, 400, 700], [500, 50, 400, 1400]],
    )
    for region in page["regions"]:
        for panel in page["panels"]:
            if ir.bbox_contains(panel["bbox"], region["bbox"], slack=0.6):
                region["panel"] = panel["id"]
    ordered = ir.assign_reading_order(page, "rtl")
    # Right panel first (rtl), so its low balloon precedes the left panel's high one.
    assert [region["bbox"] for region in ordered][0] == [600, 900, 60, 60]


def test_reading_order_is_a_permutation():
    page = _page([[i * 90, (i % 3) * 400, 60, 60] for i in range(9)])
    ordered = ir.assign_reading_order(page, "rtl")
    assert sorted(region["reading_order"] for region in ordered) == list(range(1, 10))


# --- Script detection -------------------------------------------------------

@pytest.mark.parametrize(
    "text, language",
    [
        ("بس کن! این‌جا چه خبر است؟", "fa"),
        ("やめろ！ここで何をしている", "ja"),
        ("아무도 모른다", "ko"),
        ("Nobody knows where he went.", "en"),
    ],
)
def test_looks_like_accepts_its_own_language(text, language):
    assert ir.looks_like(text, language)


def test_japanese_is_not_persian():
    assert not ir.looks_like("やめろ！", "fa")


def test_persian_is_distinguished_from_arabic():
    assert ir.is_persian("چگونه می‌شود؟")
    # Arabic with no Persian-only letters and no Persian spelling.
    assert not ir.is_persian("هذا كتاب")


def test_script_counts_separate_the_japanese_scripts():
    counts = ir.script_counts("かなカナ漢字")
    assert counts["hiragana"] == 2 and counts["katakana"] == 2 and counts["han"] == 2


# --- Staleness --------------------------------------------------------------

def test_fingerprint_changes_when_a_region_moves():
    page = _page([[10, 10, 40, 40]])
    doc = ir.new_doc()
    doc["pages"] = [page]
    before = ir.fingerprint(doc)
    page["regions"][0]["bbox"] = [11, 10, 40, 40]
    assert ir.fingerprint(doc) != before


def test_fingerprint_ignores_the_translation():
    """Translating must not invalidate the worksheets that carry the translation."""
    page = _page([[10, 10, 40, 40]])
    doc = ir.new_doc()
    doc["pages"] = [page]
    before = ir.fingerprint(doc)
    page["regions"][0]["target_text"] = "سلام"
    assert ir.fingerprint(doc) == before


# --- Policy -----------------------------------------------------------------

def test_sfx_is_only_expected_to_be_translated_under_the_right_policy():
    sfx = ir.new_region("r1", [0, 0, 10, 10], kind="sfx")
    speech = ir.new_region("r2", [0, 0, 10, 10], kind="speech")
    assert not ir.translatable(sfx, "keep")
    assert ir.translatable(sfx, "translate")
    assert ir.translatable(speech, "keep")


def test_unknown_region_kind_is_refused():
    with pytest.raises(ValueError):
        ir.new_region("r1", [0, 0, 10, 10], kind="balloon")


# --- IO ---------------------------------------------------------------------

def test_written_files_keep_their_newlines(tmp_path):
    """Without newline="" Python rewrites \\n to \\r\\n on Windows, and the same
    document written on two platforms then hashes differently."""
    path = ir.write_text(tmp_path / "a.txt", "one\ntwo\n")
    assert path.read_bytes() == b"one\ntwo\n"


def test_a_document_from_a_future_schema_is_refused(tmp_path):
    path = tmp_path / "comic.json"
    ir.write_text(path, '{"version": 99}')
    with pytest.raises(ValueError, match="schema"):
        ir.load_doc(path)


def test_missing_dependency_names_the_package():
    with pytest.raises(ir.MissingDependency, match="pip install"):
        ir.require("no_such_module_here", "no-such-package", "testing")


# --- R03: what a stage ran against, and what that makes stale ----------------

def _doc():
    return {
        "meta": {"sfx_policy": "keep", "target_language": "fa"},
        "pages": [{
            "id": "p0001", "sha256": "a" * 64, "width": 100, "height": 100,
            "regions": [{
                "id": "r001", "bbox": [1, 2, 3, 4], "kind": "speech",
                "orientation": "horizontal",
                "source_text": "hello", "translation": "سلام",
            }],
        }],
    }


def test_a_stage_records_what_it_read_and_when():
    doc = _doc()
    stages.stamp_stage(doc, "typeset", {"placed": 1})
    record = doc["stages"]["typeset"]
    assert set(record["inputs"]) == {"geometry", "text", "policy"}
    assert record["seq"] == 1
    assert not stages.stale_stages(doc)


def test_correcting_an_approved_line_stales_the_page_already_rendered_from_it():
    """**The one that matters.** The render on disk was made from Persian
    somebody has since corrected, and it stayed stamped `typeset` and shipped.
    Nothing anywhere asked."""
    doc = _doc()
    stages.stamp_stage(doc, "typeset", {"placed": 1})
    doc["pages"][0]["regions"][0]["translation"] = "سلام، حالت چطور است؟"

    stale = stages.stale_stages(doc)
    assert "typeset" in stale
    assert "text" in stale["typeset"]


def test_correcting_a_line_does_not_stale_the_detection_that_found_the_box():
    """Named facets rather than one document hash, exactly so that this does
    not happen: re-detecting on every edit would renumber the regions and throw
    away every reply written against the old ids."""
    doc = _doc()
    stages.stamp_stage(doc, "detect", {"totals": {}})
    stages.stamp_stage(doc, "worksheet", {"merged": 1})
    doc["pages"][0]["regions"][0]["translation"] = "چیز دیگری"

    assert not stages.stale_stages(doc)


def test_moving_a_box_stales_the_worksheet_and_the_masks():
    doc = _doc()
    stages.stamp_stage(doc, "worksheet", {"merged": 1})
    stages.stamp_stage(doc, "masks", {"written": 1})
    doc["pages"][0]["regions"][0]["bbox"] = [9, 9, 3, 4]

    stale = stages.stale_stages(doc)
    assert set(stale) == {"worksheet", "masks"}


def test_changing_the_sfx_policy_stales_the_masks_not_the_worksheet():
    doc = _doc()
    stages.stamp_stage(doc, "worksheet", {"merged": 1})
    stages.stamp_stage(doc, "masks", {"written": 1})
    doc["meta"]["sfx_policy"] = "translate"

    assert set(stages.stale_stages(doc)) == {"masks"}


def test_re_running_a_stage_stales_everything_downstream_of_it():
    """A path in `comic.json` does not change when the file behind it is
    redrawn, so content hashing cannot see this. Order can."""
    doc = _doc()
    for stage in ("masks", "clean", "typeset"):
        stages.stamp_stage(doc, stage, {"written": 1})
    assert not stages.stale_stages(doc)

    stages.stamp_stage(doc, "masks", {"written": 2})   # re-run, new masks
    stale = stages.stale_stages(doc)
    assert stale["clean"] == "masks has run since"
    # `typeset` depends on `clean`, which has not re-run yet, so it is not
    # reported twice for the same cause.
    assert "typeset" not in stale


def test_re_running_a_stage_that_changed_nothing_stales_nothing():
    """`seq` counts changes, not runs. Running `mask` twice with the same
    options is an ordinary thing to do, and it must not tell `clean` and every
    page rendered from it that they are out of date."""
    doc = _doc()
    for stage in ("masks", "clean", "typeset"):
        stages.stamp_stage(doc, stage, {"written": 1})
    before = ir.dumps(doc)

    stages.stamp_stage(doc, "masks", {"written": 1})

    assert ir.dumps(doc) == before, "an identical re-run changed the document"
    assert not stages.stale_stages(doc)


def test_a_stamp_from_an_older_build_is_unknown_rather_than_stale():
    """An upgrade must not look like a defect: a record with no `inputs` is a
    build that never recorded them, not proof that anything moved."""
    doc = _doc()
    doc["stages"] = {"typeset": {"fingerprint": "whatever", "placed": 1}}
    assert not stages.stale_stages(doc)
