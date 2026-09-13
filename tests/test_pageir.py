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


# --- Freshness: what a stage was made from, and what that makes stale ---------
#
# Every fixture here is built with the production constructors. The first
# version of these tests wrote `{"translation": ...}` and `{"drop": ...}` into
# a hand-made dict — two keys no region has ever carried — so the freshness
# code read empty strings, the tests read the same empty strings, and the two
# agreed with each other while disagreeing with every real document.


def _doc(pages=2, regions=1):
    doc = ir.new_doc(title="t", chapter="1")
    for index in range(pages):
        page = ir.new_page(f"p{index + 1:04d}", index, f"pages/{index}.png",
                           800, 1200, f"{index:064d}")
        for ordinal in range(regions):
            region = ir.new_region(ir.region_id_for(page, ordinal),
                                   [10 * ordinal, 20, 100, 40], kind="speech")
            region["source_text"] = "やめろ"
            region["target_text"] = "بس کن"
            page["regions"].append(region)
        doc["pages"].append(page)
    return doc


def _all_fresh(doc, *stages_):
    for stage in stages_:
        stages.stamp_stage(doc, stage, {"ran": True})
    assert not stages.stale_stages(doc), stages.stale_stages(doc)


def test_a_stage_records_what_each_page_it_touched_ran_on():
    doc = _doc()
    stages.stamp_stage(doc, "typeset", {"placed": 1})
    record = doc["stages"]["typeset"]
    assert set(record["pages"]) == {"p0001", "p0002"}
    assert record["scheme"] == stages.SCHEME
    assert not stages.stale_stages(doc)


def test_correcting_an_approved_line_stales_the_page_rendered_from_it():
    """**The one that matters.** The render on disk was made from Persian
    somebody has since corrected, and it stayed stamped `typeset` and shipped.
    """
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean", "typeset")

    doc["pages"][0]["regions"][0]["target_text"] = "بس کن، حالت چطور است؟"

    stale = stages.stale_stages(doc)
    assert "typeset" in stale, stale
    assert "p0001" in stale["typeset"] and "p0002" not in stale["typeset"]


def test_the_text_facet_reads_the_fields_a_region_actually_has():
    """A contract test, not a behaviour test: it fails if `target_text` or
    `dropped` is renamed in the freshness logic, which is exactly how this
    broke — the code read `translation`/`drop` and nothing noticed."""
    doc = _doc()
    page = doc["pages"][0]
    before = stages._page_facet(page, "text")

    page["regions"][0]["translation"] = "a key no region carries"
    page["regions"][0]["drop"] = True
    assert stages._page_facet(page, "text") == before, (
        "the text facet moved for a field the document does not use")

    page["regions"][0]["target_text"] = "چیز دیگری"
    assert stages._page_facet(page, "text") != before
    del page["regions"][0]["translation"], page["regions"][0]["drop"]

    after_text = stages._page_facet(page, "text")
    page["regions"][0]["dropped"] = True
    assert stages._page_facet(page, "text") != after_text


def test_correcting_a_line_does_not_stale_the_detection_that_found_the_box():
    """Named facets exist so that this does not happen: re-detecting on every
    edit would renumber the regions and throw away every reply already written
    against the old ids."""
    doc = _doc()
    _all_fresh(doc, "detect", "worksheet")
    doc["pages"][0]["regions"][0]["target_text"] = "چیز دیگری"
    assert not stages.stale_stages(doc)


def test_a_polarity_correction_stales_the_mask_and_not_the_worksheet():
    """A worksheet reply is filed against ids, boxes, kinds and orientations.
    A mask is also measured from the polarity — which the one shared geometry
    hash did not cover at all, so `polarity: dark` changed nothing."""
    doc = _doc()
    _all_fresh(doc, "detect", "worksheet", "masks")
    doc["pages"][0]["regions"][0]["polarity"] = "dark"

    stale = stages.stale_stages(doc)
    assert "masks" in stale and "worksheet" not in stale


def test_a_traced_balloon_stales_the_render_it_changes():
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean", "typeset")
    doc["pages"][0]["regions"][0]["balloon"] = {"cx": 50, "cy": 40, "r": 30}
    assert "typeset" in stages.stale_stages(doc)


def test_locking_a_glossary_name_stales_the_translation_that_predates_it():
    """Translation depended on neither the glossary nor the title policy, so
    locking a name left every line translated before the lock looking
    current."""
    doc = _doc()
    _all_fresh(doc, "detect", "translate")
    doc["glossary"] = {"entries": {"ハルカ": {"target": "هاروکا",
                                            "locked": True, "version": 1}}}
    assert "translate" in stages.stale_stages(doc)


def test_a_title_policy_change_stales_what_reads_it():
    """The title policy constrains the WORDS. A render depends on the words
    themselves, which is a different fact and already covered — so changing a
    honorific rule invalidates the translation and the sheet that prints it,
    and does not claim every page needs setting again."""
    doc = _doc()
    _all_fresh(doc, "detect", "worksheet", "translate", "masks", "clean",
               "typeset")
    doc["meta"]["title_policy"] = {"honorifics": "keep -senpai"}

    stale = stages.stale_stages(doc)
    assert {"translate", "worksheet"} <= set(stale), stale
    assert "masks" not in stale and "typeset" not in stale


def test_filling_in_the_glossary_does_not_stale_the_masks():
    """`glossary scan` is the stage whose whole job is to fill that table in,
    and it reported the masks of every page as out of date — on the ordinary
    order of operations, caught by the end-to-end pipeline in CI. Masking and
    cleaning know nothing about names."""
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean", "typeset")

    doc["glossary"] = {"entries": {"ハルカ": {"target": "هاروکا",
                                            "locked": False, "version": 1}}}

    assert not stages.stale_stages(doc), stages.stale_stages(doc)


def test_a_sound_effect_policy_change_still_stales_the_render():
    """The narrowing must not go too far: `--sfx-policy` decides whether an
    effect is replaced or left in the artwork, and that is a render."""
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean", "typeset")
    doc["meta"]["sfx_policy"] = "translate"

    stale = stages.stale_stages(doc)
    assert {"masks", "clean", "typeset"} <= set(stale), stale


def test_remasking_then_recleaning_settles_instead_of_staying_stale_forever():
    """`masks -> clean -> masks -> clean` left `clean` stale no matter how many
    times it ran: a re-run whose summary came out identical kept its old
    sequence number, which stayed below the number masks had just taken. The
    identity is the inputs now, so consuming the new masks is what ends it."""
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean")

    stages.stamp_stage(doc, "masks", {"written": 1}, options={"grow": 6})
    assert "clean" in stages.stale_stages(doc)

    # The SAME clean summary as before — equal counts, different pixels.
    stages.stamp_stage(doc, "clean", {"ran": True})
    assert not stages.stale_stages(doc), stages.stale_stages(doc)


def test_a_different_option_is_a_different_answer():
    """Equal counts, different pixels: the summary cannot tell them apart, so
    the options the run used are part of its identity."""
    doc = _doc()
    _all_fresh(doc, "detect")
    stages.stamp_stage(doc, "masks", {"written": 2}, options={"grow": 3})
    first = doc["stages"]["masks"]["pages"]["p0001"]
    stages.stamp_stage(doc, "masks", {"written": 2}, options={"grow": 9})
    assert doc["stages"]["masks"]["pages"]["p0001"] != first


def test_running_one_page_does_not_claim_the_others_were_done():
    """`mask --pages p0003` is an ordinary thing to do, and a document-wide
    hash called every other page freshly masked because one was."""
    doc = _doc(pages=3)
    _all_fresh(doc, "detect")
    stages.stamp_stage(doc, "masks", {"written": 1}, pages=["p0002"])

    stale = stages.stale_stages(doc)
    assert "masks" in stale
    assert "p0001" in stale["masks"] and "p0002" not in stale["masks"]

    stages.stamp_stage(doc, "masks", {"written": 3})
    assert not stages.stale_stages(doc)


def test_watermarking_does_not_wait_for_a_render_that_comes_after_it():
    """`watermark` was recorded as depending on `typeset`, which is backwards:
    a mark is placed before the page is masked, cleaned or set."""
    assert "typeset" not in stages.STAGE_NEEDS.get("watermark", ())
    assert not stages.prerequisites("watermark")


def test_the_dependency_graph_has_no_cycle():
    for stage in stages.STAGE_NEEDS:
        assert stage not in stages.prerequisites(stage), stage


def test_an_obsolete_export_does_not_block_checking_the_new_render():
    """QA asks about the render. A package from a previous session is not a
    prerequisite of checking the current pages, and reporting it stopped a
    corrected chapter from being verified before it was packaged again."""
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean", "typeset", "export")

    doc["pages"][0]["regions"][0]["target_text"] = "متن اصلاح‌شده"
    for stage in ("masks", "clean", "typeset"):
        stages.stamp_stage(doc, stage, {"ran": True})

    assert "export" in stages.stale_stages(doc)
    assert not stages.stale_stages(doc, needed_for="typeset")


def test_a_second_unchanged_run_reports_nothing_new_and_changes_nothing():
    doc = _doc()
    _all_fresh(doc, "detect", "masks", "clean", "typeset")
    before = ir.dumps(doc)

    for stage in ("detect", "masks", "clean", "typeset"):
        stages.stamp_stage(doc, stage, {"ran": True})

    assert ir.dumps(doc) == before, "an identical re-run rewrote the document"
    assert not stages.stale_stages(doc)


def test_a_stamp_from_an_older_build_is_unverified_rather_than_stale():
    """An upgrade must not look like a defect, and must never be answered by
    translating an unchanged chapter again."""
    doc = _doc()
    doc["stages"] = {"typeset": {"fingerprint": "whatever", "placed": 1}}

    assert not stages.stale_stages(doc)
    unverified = stages.unverified_stages(doc)
    assert "typeset" in unverified and "re-run" in unverified["typeset"]


def test_the_retired_counter_is_not_left_behind():
    doc = _doc()
    doc["meta"]["stage_seq"] = 7
    stages.stamp_stage(doc, "detect", {"ran": True})
    assert "stage_seq" not in doc["meta"]
