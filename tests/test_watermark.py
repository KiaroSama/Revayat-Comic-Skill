"""Erasing a mark, and the guarantee that it cannot take the artwork with it.

A watermark here is not a new pipeline. It is an ordinary region carrying
`erase: True` — *remove this and put nothing back* — masked, cleaned and gated
by the same code every balloon goes through. So these tests are about the two
things that are genuinely new: the fifth terminal state, and the fact that a
tool whose whole job is deleting pixels still cannot reach one it was not
pointed at.

The load-bearing test is `test_nothing_outside_the_box_moves`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import ImageDraw

import clean
import masks
import pageir as ir
import qa
import readers
import watermark
import worksheet
from tests_support import manga_page


def _stamped_page(width=1000, height=1500):
    """A page with a deliberate corner stamp, so there is real ink to remove."""
    page = manga_page(width, height)
    draw = ImageDraw.Draw(page)
    draw.rectangle([40, height - 100, 300, height - 54],
                   fill=(255, 255, 255), outline=(20, 20, 20), width=3)
    for index in range(6):
        left = 56 + index * 38
        draw.rectangle([left, height - 88, left + 22, height - 64],
                       fill=(20, 20, 20))
    return page


#: The stamp drawn above, as `x y w h` on a 1000x1500 page.
STAMP = [40, 1400, 262, 48]


@pytest.fixture
def stamped(tmp_path):
    """A one-page chapter carrying a corner stamp, detected but not translated."""
    import detect

    folder = tmp_path / "src"
    folder.mkdir()
    _stamped_page().save(folder / "001.png")
    report = readers.import_source(folder, tmp_path / "work",
                                   source_language="ja", direction="rtl")
    doc_path = Path(report["document"])
    detect.detect_document(doc_path)
    return doc_path


# --- the command, for a mark in the same place on every page ------------------

def test_one_box_reaches_every_page(imported):
    """The case the command exists for: a site stamp on all of them. Marking
    two hundred pages by hand is not a workflow."""
    report = watermark.mark_document(imported, [30, 1380, 240, 44],
                                     label="site-stamp")
    doc = ir.load_doc(imported)
    assert len(report["marked"]) == len(doc["pages"])
    assert not report["refused"]

    for page in doc["pages"]:
        erased = [r for r in page["regions"] if r.get("erase")]
        assert len(erased) == 1, f"{page['id']}: {len(erased)} erase regions"
        assert erased[0]["locked"], "an unlocked box is renumbered by `detect`"


def test_running_it_again_moves_the_box_rather_than_adding_one(imported):
    """A wrong box on two hundred pages has to be fixable by re-running, not by
    unpicking. The `--label` is what identifies it across runs."""
    watermark.mark_document(imported, [30, 1380, 240, 44], label="site-stamp")
    second = watermark.mark_document(imported, [40, 1390, 250, 40],
                                     label="site-stamp")

    doc = ir.load_doc(imported)
    for page in doc["pages"]:
        erased = [r for r in page["regions"] if r.get("erase")]
        assert len(erased) == 1, "the second run added a duplicate"
        assert erased[0]["bbox"] == [40, 1390, 250, 40]
        assert erased[0]["mask"] is None, "a moved box kept its old mask"
    assert second["moved"], "the move was not reported"


def test_a_second_label_is_a_second_mark(imported):
    """Two genuinely different marks on one page must not fight over one slot."""
    watermark.mark_document(imported, [30, 1380, 240, 44], label="corner")
    watermark.mark_document(imported, [700, 40, 200, 40], label="header")
    page = ir.load_doc(imported)["pages"][0]
    assert len([r for r in page["regions"] if r.get("erase")]) == 2


def test_a_dropped_digit_is_refused(imported):
    """`--box "12 1840 30 4"` is a typo, not a 30x4 watermark. Accepting it
    marks a few pixels and looks like it worked."""
    with pytest.raises(ValueError, match="too small"):
        watermark.parse_box("12 1840 30 2")
    with pytest.raises(ValueError, match="four numbers"):
        watermark.parse_box("12 1840 300")


def test_a_box_over_most_of_the_page_is_refused(imported):
    """A mark is a mark on a page. A box over a quarter of it is a mistyped
    coordinate, and the inpainter would be asked to invent a panel."""
    report = watermark.mark_document(imported, [0, 0, 900, 1200], label="oops")
    assert not report["marked"]
    assert all("of the page" in line for line in report["refused"])


def test_a_box_off_the_page_is_reported_not_slivered(imported):
    """Pages in one chapter are not always the same size. Marking a two-pixel
    strip at the edge of the odd one is worse than saying it did not fit."""
    report = watermark.mark_document(imported, [5000, 5000, 200, 40],
                                     label="elsewhere")
    assert not report["marked"]
    assert all("falls outside" in line for line in report["refused"])


# --- the terminal state -------------------------------------------------------

def test_an_erased_region_is_its_own_terminal_state(stamped):
    """Not `kept_by_policy`, which means the opposite — left in the artwork —
    and not `translated`, which would claim Persian nobody wrote."""
    watermark.mark_document(stamped, STAMP, label="stamp")
    masks.build_document(stamped)
    clean.clean_document(stamped)

    doc = ir.load_doc(stamped)
    mark = next(r for r in doc["pages"][0]["regions"] if r.get("erase"))
    assert ir.region_state(mark, "keep") == "erased"
    assert ir.state_census(doc)["erased"] == 1
    assert "erased" in ir.REGION_STATES


def test_an_erased_region_is_not_a_hole_in_the_translation(stamped):
    """`qa` must not report a watermark as untranslated. It is a decision."""
    watermark.mark_document(stamped, STAMP, label="stamp")
    masks.build_document(stamped)
    clean.clean_document(stamped)

    doc = ir.load_doc(stamped)
    mark = next(r for r in doc["pages"][0]["regions"] if r.get("erase"))
    assert ir.translatable(mark, "keep") is False

    findings = qa.check_document(stamped)["findings"]
    # Keyed `where`, not `region`: this read the wrong key and passed
    # whatever the gate said.
    blamed = [f for f in findings
              if f.get("where") == mark["id"] and "untranslated" in f["code"]]
    assert not blamed, f"the erased mark was reported as a hole: {blamed}"


def test_a_mark_the_cleaner_declined_is_review_not_erased(stamped):
    """THE ONE THAT KEEPS THE CENSUS HONEST. Reporting `erased` on the reader's
    intent alone would say a watermark is gone while it is still on the page —
    the same "quietly disappeared" failure the census exists to rule out,
    pointed the other way."""
    watermark.mark_document(stamped, STAMP, label="stamp")
    masks.build_document(stamped)

    doc = ir.load_doc(stamped)
    mark = next(r for r in doc["pages"][0]["regions"] if r.get("erase"))
    # Before `clean` there is no fill at all.
    assert ir.region_state(mark, "keep") == "needs_review"

    # And a cleaner that declined leaves `keep`, which is not erasure either.
    mark["fill"] = "keep"
    assert ir.region_state(mark, "keep") == "needs_review"


# --- the worksheet path, for a mark that moves --------------------------------

def test_the_reader_can_mark_a_mark_the_detector_missed(stamped):
    """The AI-first path, and the one this project is built around: the model
    is already looking at the page to transcribe it. A stamp is one more thing
    it can see — and unlike a detector, it sees it in context."""
    worksheet.build_document(stamped)
    doc = ir.load_doc(stamped)
    page = doc["pages"][0]
    sheet = ir.doc_dir(stamped) / "worksheets" / f"{page['id']}.txt"

    text = sheet.read_text(encoding="utf-8")
    assert "erase:" in text, "the worksheet never offers the action"
    x, y, w, h = STAMP
    sheet.write_text(
        text + f"\n@@ +stamp sign horizontal\nbox: {x} {y} {w} {h}\nerase: yes\n",
        encoding="utf-8")
    sheet.with_suffix(".done.txt").write_text(
        sheet.read_text(encoding="utf-8"), encoding="utf-8")

    report = worksheet.merge_document(stamped)
    assert report["erased"], "the added box did not come back as erased"

    masks.build_document(stamped)
    clean.clean_document(stamped)
    mark = next(r for r in ir.load_doc(stamped)["pages"][0]["regions"]
                if r.get("erase"))
    assert ir.region_state(mark, "keep") == "erased"


def test_keep_and_erase_together_are_refused(stamped):
    """Opposite instructions. Guessing which was meant is how a mark stays on
    the page while the report says it went."""
    region = {"id": "r1", "kind": "sign"}
    report = {key: [] for key in
              ("dropped", "kept", "erased", "reclassified", "bad_kind",
               "conflicting_actions")}
    worksheet._apply(region, {"keep": "yes", "erase": "yes"}, report)

    assert report["conflicting_actions"]
    assert not region.get("erase"), "erase won a conflict it should have lost"


# --- the guarantee ------------------------------------------------------------

def test_the_ink_actually_goes(stamped):
    """A test that only checked the metadata would pass with the stamp still
    printed on the page."""
    doc = ir.load_doc(stamped)
    root = ir.doc_dir(stamped)
    page = doc["pages"][0]
    x, y, w, h = STAMP
    before = np.asarray(ir.load_image(root / page["image"]).convert("L"))
    assert int((before[y:y + h, x:x + w] < 128).sum()) > 500, "no stamp drawn"

    watermark.mark_document(stamped, STAMP, label="stamp")
    masks.build_document(stamped)
    clean.clean_document(stamped)

    page = ir.load_doc(stamped)["pages"][0]
    after = np.asarray(ir.load_image(root / page["clean"]).convert("L"))
    assert int((after[y:y + h, x:x + w] < 128).sum()) == 0, "the stamp survived"


def test_nothing_outside_the_mask_moves(stamped):
    """THE ONE THAT MATTERS. This is a tool whose entire job is deleting pixels,
    pointed at a page by a box somebody typed.

    The authorised area is the *mask*, not the box around it — a mask is a few
    thousand lettering pixels inside a rectangle that is mostly artwork, and a
    version of this test that allowed the whole rectangle passed with the
    mask-bounded compositing deliberately removed. So the comparison is against
    each region's own mask, laid back down at its `mask_box`, and against the
    page as it was imported rather than an already-cleaned copy.
    """
    import masks as mask_tools
    import typeset

    root = ir.doc_dir(stamped)
    page = ir.load_doc(stamped)["pages"][0]
    before = np.asarray(ir.load_image(root / page["image"]).convert("RGB"))

    watermark.mark_document(stamped, STAMP, label="stamp")
    masks.build_document(stamped)
    clean.clean_document(stamped)
    typeset.typeset_document(stamped)

    page = ir.load_doc(stamped)["pages"][0]
    allowed = np.zeros(before.shape[:2], bool)
    for region in page["regions"]:
        if not region.get("mask") or not region.get("mask_box"):
            continue
        mask = mask_tools.load_mask(root / region["mask"]) > 0
        mx, my, mw, mh = region["mask_box"]
        allowed[my:my + mh, mx:mx + mw] |= mask[:mh, :mw]

    for stage in ("clean", "final"):
        assert page.get(stage), f"{stage} was never written; this proves nothing"
        after = np.asarray(ir.load_image(root / page[stage]).convert("RGB"))
        changed = (before != after).any(axis=2)
        leaked = int((changed & ~allowed).sum())
        assert leaked == 0, f"{stage}: {leaked} pixel(s) changed outside every mask"

    # And the shipped gate agrees, on the page a reader would actually receive.
    assert qa.check_document(stamped)["stats"]["artwork_pixels_changed"] == 0
