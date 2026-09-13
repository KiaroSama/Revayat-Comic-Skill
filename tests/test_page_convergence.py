"""Two pages with different settings, and a page whose last region is gone.

Every test here runs the real stages twice and compares what the second run
says about the first run's work. The failures this file exists for are all the
same shape: a per-page decision recorded in a document-wide place, so touching
one page moves the answer for every other.
"""
from __future__ import annotations

import pytest

import clean
import masks
import pageir as ir
import stages
import typeset


def _two_pages(doc_path):
    doc = ir.load_doc(doc_path)
    return doc["pages"][0]["id"], doc["pages"][1]["id"]


# --------------------------------------------------------------------------- #
# R1: two legitimate page settings coexist
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("order", [("solid", "glyphs"), ("glyphs", "solid")])
def test_two_pages_masked_with_different_modes_both_stay_current(translated,
                                                                 order):
    """`mask --free-lettering solid` on one page and `glyphs` on another is the
    ordinary reason the page selector exists. The mode was recorded in
    `meta.free_lettering_mask` and hashed into the document-wide `policy`
    facet, so masking the second page rewrote a value every page's revision was
    computed from — and the first page went stale for a change that did not
    touch it."""
    first, second = _two_pages(translated)
    masks.build_document(translated, pages=[first],
                         solid_free=order[0] == "solid")
    masks.build_document(translated, pages=[second],
                         solid_free=order[1] == "solid")

    stale = stages.stale_pages(ir.load_doc(translated), "masks")

    assert stale == [], stale
    doc = ir.load_doc(translated)
    modes = {page["id"]: page.get("free_lettering_mask")
             for page in doc["pages"][:2]}
    assert modes[first] == order[0] and modes[second] == order[1], modes


def test_repairing_one_page_does_not_stale_the_other(translated):
    """The second half of the same defect: fixing the page a gate named must
    not name a different page in its place."""
    first, second = _two_pages(translated)
    masks.build_document(translated, pages=[first], solid_free=True)
    masks.build_document(translated, pages=[second], solid_free=False)
    assert stages.stale_pages(ir.load_doc(translated), "masks") == []

    # A real repair of the first page, with its own setting kept.
    masks.build_document(translated, pages=[first], solid_free=True)

    assert stages.stale_pages(ir.load_doc(translated), "masks") == []


@pytest.mark.parametrize("grow,pad", [(0.03, 0.02), (0.09, 0.06)])
def test_per_page_geometry_options_also_coexist(translated, grow, pad):
    first, second = _two_pages(translated)
    masks.build_document(translated, pages=[first], grow=grow, pad=pad)
    masks.build_document(translated, pages=[second], grow=0.05, pad=0.04)

    assert stages.stale_pages(ir.load_doc(translated), "masks") == []


# --------------------------------------------------------------------------- #
# R1: a rebuild retires what it owns, and only that
# --------------------------------------------------------------------------- #

def test_a_mask_rebuild_does_not_delete_the_render_s_writable_mask(finished):
    """`typeset` writes `masks/<page>/writable.png` — the record of what it was
    allowed to draw in, and one of the three files the delivery certificate
    checks. The mask sweep removed every name its own run did not write, so an
    ordinary `mask` rerun deleted a downstream artifact and the page failed
    publication for a file nobody had touched."""
    root = ir.doc_dir(finished)
    doc = ir.load_doc(finished)
    page = next(p for p in doc["pages"] if p.get("writable"))
    writable = root / page["writable"]
    assert writable.is_file()

    masks.build_document(finished, pages=[page["id"]])

    assert writable.is_file(), "the mask sweep deleted the render's own mask"


def test_a_mask_rebuild_leaves_an_operator_s_own_file_alone(translated):
    """Anything else in that folder is not ours to remove."""
    masks.build_document(translated)
    root = ir.doc_dir(translated)
    page_id = ir.load_doc(translated)["pages"][0]["id"]
    keepsake = root / "masks" / page_id / "notes-from-the-letterer.txt"
    keepsake.write_text("do not delete", encoding="utf-8")

    masks.build_document(translated, pages=[page_id])

    assert keepsake.is_file(), "an operator's file was swept"
    assert keepsake.read_text(encoding="utf-8") == "do not delete"


def test_an_unchanged_rebuild_changes_no_bytes(translated):
    """Two complete passes, identical output. An unchanged rerun that rewrites
    anything is a rerun that can invalidate downstream work for nothing."""
    masks.build_document(translated)
    root = ir.doc_dir(translated)
    before = {path.relative_to(root).as_posix(): path.read_bytes()
              for path in sorted((root / "masks").rglob("*")) if path.is_file()}
    stamp = ir.dumps(ir.load_doc(translated)["stages"]["masks"])

    masks.build_document(translated)

    after = {path.relative_to(root).as_posix(): path.read_bytes()
             for path in sorted((root / "masks").rglob("*")) if path.is_file()}
    assert after == before
    assert ir.dumps(ir.load_doc(translated)["stages"]["masks"]) == stamp


# --------------------------------------------------------------------------- #
# R1: removing the last region is a transition, not a skip
# --------------------------------------------------------------------------- #

def _strip_regions(doc_path, page_id):
    doc = ir.load_doc(doc_path)
    page = next(p for p in doc["pages"] if p["id"] == page_id)
    page["regions"] = []
    ir.save_doc(doc, doc_path)
    return page_id


def test_a_page_whose_last_region_went_is_cleaned_back_to_its_original(finished):
    """Every region removed means there is nothing to repair and nothing to
    draw, so the page a reader gets is the page that was imported. `clean` and
    `typeset` skipped such a page entirely, leaving the previous run's repaired
    image and rendered text on disk and referenced."""
    root = ir.doc_dir(finished)
    doc = ir.load_doc(finished)
    page_id = doc["pages"][0]["id"]
    original = ir.sha256_file(root / doc["pages"][0]["image"])
    _strip_regions(finished, page_id)

    masks.build_document(finished, pages=[page_id])
    clean.clean_document(finished, pages=[page_id])
    typeset.typeset_document(finished, pages=[page_id])

    page = ir.load_doc(finished)["pages"][0]
    for key in ("clean", "final"):
        if page.get(key):
            assert ir.sha256_file(root / page[key]) == original, (
                f"{key} still carries work from when the page had regions")


def test_a_page_whose_last_region_went_has_no_dangling_references(finished):
    page_id = ir.load_doc(finished)["pages"][0]["id"]
    _strip_regions(finished, page_id)

    masks.build_document(finished, pages=[page_id])
    clean.clean_document(finished, pages=[page_id])
    typeset.typeset_document(finished, pages=[page_id])

    root = ir.doc_dir(finished)
    page = ir.load_doc(finished)["pages"][0]
    for key in ("clean", "final", "writable", "mask"):
        if page.get(key):
            assert (root / page[key]).is_file(), f"{key} points at nothing"
    assert not (page.get("annotations") or []), page.get("annotations")
    assert page.get("mask_coverage") == 0


def test_a_zero_region_page_passes_the_gate(finished):
    """A page with nothing on it is finished, not unfinished."""
    import qa

    page_id = ir.load_doc(finished)["pages"][0]["id"]
    _strip_regions(finished, page_id)
    masks.build_document(finished, pages=[page_id])
    clean.clean_document(finished, pages=[page_id])
    typeset.typeset_document(finished, pages=[page_id])

    report = qa.check_document(finished)

    blocking = [item for item in report["findings"]
                if item["severity"] == "error" and item["where"] == page_id]
    assert not blocking, blocking


# --------------------------------------------------------------------------- #
# R1: an empty selection is not "every page"
# --------------------------------------------------------------------------- #

def test_an_empty_page_selection_is_not_all_pages(translated):
    """`--pages ''` splits to an empty list. Treating that as "no filter"
    stamped every page as freshly masked when none of them had run — so a page
    that genuinely needed re-masking came back current without being touched.

    A page is made stale first, because that is the only observation that tells
    the two readings apart: "no pages" leaves it stale, "all pages" clears it.
    """
    doc = ir.load_doc(translated)
    page_id = doc["pages"][0]["id"]
    doc["pages"][0]["regions"][0]["keep"] = True  # authority changed: re-mask
    ir.save_doc(doc, translated)
    assert stages.stale_pages(ir.load_doc(translated), "masks") == [page_id]

    masks.build_document(translated, pages=[])

    assert stages.stale_pages(ir.load_doc(translated), "masks") == [page_id], (
        "an empty selection stamped a page nothing had masked")
