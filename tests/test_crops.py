"""The two images the reading model actually looks at.

`crops` is the stage this project's whole design rests on: there is no OCR
engine in the default pipeline, so the overview and the crop sheets *are* the
input to transcription and translation. If a region is missing from the sheets,
it is missing from the chapter — silently, because every later gate only checks
regions the document already knows about.

Until now the only coverage was one assertion in `tests/test_worksheet.py` that
the worksheet mentions the file *names*. That proves the worksheet's text, not
that the images exist, contain anything, or show every region.

These tests are deliberately about structure and reachability rather than
pixels. What a crop looks like is a judgement; whether every region got one is
not.
"""

from __future__ import annotations

import numpy as np
import pytest

import crops
import pageir as ir


def test_every_page_gets_an_overview_and_at_least_one_sheet(detected):
    report = crops.build_document(detected)
    root = ir.doc_dir(detected)

    assert report["pages"], "no page produced crops"
    for entry in report["pages"]:
        overview = root / entry["overview"]
        assert overview.is_file(), f"{entry['page']}: no overview written"
        assert overview.stat().st_size > 0
        assert entry["sheets"], f"{entry['page']}: no crop sheet written"
        for name in entry["sheets"]:
            assert (root / name).is_file()


def test_the_document_records_where_the_images_are(detected):
    """The worksheet builder reads these keys off the page. If `crops` stops
    writing them, the worksheet points the reader at nothing and the failure
    surfaces three stages later as an empty translation."""
    crops.build_document(detected)
    doc = ir.load_doc(detected)

    for page in doc["pages"]:
        assert page["overview"] == f"crops/{page['id']}/overview.png"
        assert page["sheets"], f"{page['id']}: no sheets recorded"
        assert all(name.startswith(f"crops/{page['id']}/sheet")
                   for name in page["sheets"])
    # `pages` on a stage record is now the per-page revision map — what
    # each page was made from. The count this test means lives under
    # `rendered`.
    assert doc["stages"]["crops"]["rendered"] == len(doc["pages"])
    assert set(doc["stages"]["crops"]["pages"]) == {
        page["id"] for page in doc["pages"]}


def test_every_region_reaches_a_sheet(detected):
    """The one that matters. A region the sheets never show is a region nobody
    can transcribe, and no later gate catches it — `qa` checks that known
    regions have text, not that the reader was ever shown them."""
    report = crops.build_document(detected)
    doc = ir.load_doc(detected)

    counted = {entry["page"]: entry["regions"] for entry in report["pages"]}
    for page in doc["pages"]:
        live = [r for r in page.get("regions", []) if not r.get("dropped")]
        if not live:
            continue
        assert counted[page["id"]] >= len(live), (
            f"{page['id']}: {len(live)} regions but the sheets counted "
            f"{counted[page['id']]}")


def test_the_overview_draws_something_over_the_page(detected):
    """A blank overview would pass every structural check above. The labels and
    outlines are drawn in `KIND_COLOURS`, none of which is the greyscale the
    fixture page is made of, so a coloured pixel is proof the annotation ran."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    if not page.get("regions"):
        pytest.skip("fixture page has no detected region to outline")

    root = ir.doc_dir(detected)
    original = ir.load_image(root / page["image"]).convert("RGB")
    crops.build_document(detected)
    overview = ir.load_image(root / f"crops/{page['id']}/overview.png").convert("RGB")

    pixels = np.asarray(overview).astype(int)
    spread = pixels.max(axis=2) - pixels.min(axis=2)
    assert (spread > 40).any(), "the overview carries no colour: nothing was drawn"

    # And it is a view of this page, not a blank canvas: the aspect ratio
    # survives the downscale to OVERVIEW_MAX_SIDE.
    assert overview.width / overview.height == pytest.approx(
        original.width / original.height, rel=0.02)


def test_a_page_wider_than_the_overview_cap_is_scaled_down(detected):
    """`OVERVIEW_MAX_SIDE` exists because an agent reading a 6000px page gets it
    downscaled by its own viewer, undoing the enlargement the crops do."""
    crops.build_document(detected)
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)

    for page in doc["pages"]:
        overview = ir.load_image(root / page["overview"])
        assert max(overview.size) <= crops.OVERVIEW_MAX_SIDE


def test_rebuilding_is_idempotent(detected):
    """Re-running a stage is how this pipeline resumes. The second run must
    produce the same file list, not a second set beside the first."""
    first = crops.build_document(detected)
    second = crops.build_document(detected)

    assert [e["overview"] for e in first["pages"]] == \
           [e["overview"] for e in second["pages"]]
    assert [e["sheets"] for e in first["pages"]] == \
           [e["sheets"] for e in second["pages"]]

    root = ir.doc_dir(detected)
    page = ir.load_doc(detected)["pages"][0]
    written = sorted((root / "crops" / page["id"]).glob("sheet*.png"))
    assert len(written) == len(page["sheets"]), "a stale sheet was left behind"


def test_a_crop_is_enlarged_so_small_lettering_is_readable(detected):
    """`MAX_CROP_SIDE` and the minimum in `_fit` are the reason furigana is
    legible at all. A crop that comes back at its original tiny size means the
    enlargement silently stopped happening."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    region = next((r for r in page.get("regions", []) if not r.get("dropped")),
                  None)
    if region is None:
        pytest.skip("fixture page has no region to crop")

    root = ir.doc_dir(detected)
    image = ir.load_image(root / page["image"])
    crop = crops._crop_for(image, region, (page["width"], page["height"]))

    assert min(crop.size) > 0
    assert max(crop.size) <= crops.MAX_CROP_SIDE


# --- R16: a box read off the overview is in overview pixels ------------------

def _tall_chapter(tmp_path, width=1400, height=2600):
    """One page taller than OVERVIEW_MAX_SIDE, so the overview is downscaled.

    The shared fixtures are 1000x1500 — under the 1600 limit, so their overview
    is drawn at 1:1 and every coordinate claim about it happens to be true.
    That is exactly why nothing caught this.
    """
    import detect
    import readers
    from tests_support import manga_page

    source = tmp_path / "src"
    source.mkdir()
    manga_page(width, height).save(source / "001.png")
    readers.import_source(source, tmp_path / "work",
                          source_language="ja", direction="rtl")
    doc_path = tmp_path / "work" / "comic.json"
    detect.detect_document(doc_path)
    return doc_path


def test_the_overview_records_the_scale_it_was_drawn_at(tmp_path):
    """The overview is downscaled to fit 1600 pixels, and the factor was used
    and thrown away. Everything that tells a reader to read box coordinates off
    it — the worksheet, the watermark command — was therefore asking for numbers
    in a coordinate space nothing recorded."""
    doc_path = _tall_chapter(tmp_path)
    report = crops.build_document(doc_path)

    page = ir.load_doc(doc_path)["pages"][0]
    assert "overview_scale" in page, f"the transform is not recorded: {report}"

    overview = ir.load_image(ir.doc_dir(doc_path) / page["overview"])
    assert max(overview.size) <= crops.OVERVIEW_MAX_SIDE
    assert page["overview_scale"] == pytest.approx(
        overview.height / page["height"], rel=0.01)
    assert page["overview_scale"] < 1.0, "the fixture is not tall enough to scale"


def test_a_box_read_off_the_overview_converts_to_the_right_place(tmp_path):
    """The conversion has to exist and be right, or a visually correct box
    erases a different part of the page."""
    import watermark

    doc_path = _tall_chapter(tmp_path)
    crops.build_document(doc_path)
    page = ir.load_doc(doc_path)["pages"][0]
    scale = page["overview_scale"]

    # A mark a reader would outline on the overview: bottom-left corner.
    overview_box = [30, int(page["height"] * scale) - 70, 240, 40]
    report = watermark.mark_document(doc_path, overview_box, label="stamp",
                                     from_overview=True)
    assert report["marked"], report["refused"]

    marked = next(region for region in ir.load_doc(doc_path)["pages"][0]["regions"]
                  if region.get("erase"))
    x, y, w, h = marked["bbox"]
    assert w == pytest.approx(overview_box[2] / scale, rel=0.02)
    assert y + h == pytest.approx(page["height"] - 30 / scale, rel=0.05), (
        f"a box outlined at the foot of the overview landed at y={y}")


def test_a_page_that_needs_no_downscaling_is_unchanged(imported):
    """1:1 must stay 1:1, and a box in page pixels must not be rescaled."""
    import detect
    import watermark

    detect.detect_document(imported)
    crops.build_document(imported)
    page = ir.load_doc(imported)["pages"][0]
    assert page["overview_scale"] == 1.0

    watermark.mark_document(imported, [40, 1400, 260, 48], label="stamp",
                            from_overview=True)
    marked = next(region for region in ir.load_doc(imported)["pages"][0]["regions"]
                  if region.get("erase"))
    assert marked["bbox"] == [40, 1400, 260, 48]
