"""What a chapter has to prove before it is allowed to be published.

The subject here is provenance of the delivered bytes, not their content. Every
test drives the real pipeline through the `finished` fixture — import, detect,
translate, clean, typeset — and then damages one thing, because the defect this
file exists for was invisible to every count, status and preservation proof the
document already carried.
"""
from __future__ import annotations

import shutil

import pytest

import clean
import export
import masks
import pageir as ir
import qa
import typeset


# --------------------------------------------------------------------------- #
# The control: a real pipeline publishes.
# --------------------------------------------------------------------------- #

def test_a_finished_chapter_passes_the_gate_and_exports(finished, tmp_path):
    state = qa.publication_preflight(finished)
    assert state["ok"], state["blocking"]

    out = tmp_path / "chapter-fa.cbz"
    report = export.export_document(finished, out)
    assert out.exists() and report["pages"]


def test_typeset_signs_the_page_it_delivered(finished):
    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    for page in doc["pages"]:
        if not page.get("final"):
            continue
        delivery = page["delivery"]
        assert delivery["final"] == ir.sha256_file(root / page["final"])
        assert delivery["size"] == [page["width"], page["height"]]


# --------------------------------------------------------------------------- #
# The substitutions the gate could not see.
# --------------------------------------------------------------------------- #

def _rendered_page(doc_path):
    doc = ir.load_doc(doc_path)
    for page in doc["pages"]:
        if page.get("final") and page.get("delivery"):
            return doc, page
    raise AssertionError("the fixture rendered nothing")


def _blocking_codes(doc_path):
    return {item["code"] for item in qa.publication_preflight(doc_path)["blocking"]}


def test_the_cleaned_page_cannot_be_passed_off_as_the_finished_one(finished,
                                                                  tmp_path):
    """The whole reason this file exists.

    Copying `clean/` over `final/` keeps the size, keeps every status `ok`,
    keeps every count correct, and changes no pixel outside the authorised
    mask — so the preservation proof passes it. The page just has no Persian
    on it.
    """
    root = ir.doc_dir(finished)
    _doc, page = _rendered_page(finished)
    shutil.copyfile(root / page["clean"], root / page["final"])

    assert "delivery-mismatch" in _blocking_codes(finished)
    with pytest.raises(ValueError, match="publication QA"):
        export.export_document(finished, tmp_path / "out.cbz")


def test_a_finished_page_edited_by_hand_afterwards_is_refused(finished):
    root = ir.doc_dir(finished)
    _doc, page = _rendered_page(finished)
    image = ir.load_image(root / page["final"])
    pixels = image.load()
    pixels[4, 4] = (255, 0, 0)          # inside the artwork, nowhere near a mask
    ir.save_image(image, root / page["final"])

    codes = _blocking_codes(finished)
    # Both fire, and both should: one says the bytes are not the render's, the
    # other says the artwork changed. Neither is a substitute for the other —
    # the cleaned-copy swap above trips only the first.
    assert "delivery-mismatch" in codes and "artwork-modified" in codes


@pytest.mark.parametrize("asset", ["writable", "clean"])
def test_an_asset_the_render_consumed_cannot_go_missing(finished, asset):
    root = ir.doc_dir(finished)
    _doc, page = _rendered_page(finished)
    (root / page[asset]).unlink()

    assert "delivery-mismatch" in _blocking_codes(finished)


def test_a_mask_rebuilt_under_a_finished_render_is_refused(finished):
    """`mask` after `typeset` leaves a render drawn inside authority that no
    longer exists. The stage stamp catches the ordinary case; this catches the
    asset itself being replaced."""
    import masks

    _doc, page = _rendered_page(finished)
    masks.build_document(finished, pages=[page["id"]], grow=0.12)

    assert not qa.publication_preflight(finished)["ok"]


def test_re_rendering_certifies_the_page_again(finished, tmp_path):
    """The route back. A refusal that cannot be cleared is a trap, not a gate."""
    root = ir.doc_dir(finished)
    _doc, page = _rendered_page(finished)
    shutil.copyfile(root / page["clean"], root / page["final"])
    assert not qa.publication_preflight(finished)["ok"]

    typeset.typeset_document(finished)

    state = qa.publication_preflight(finished)
    assert state["ok"], state["blocking"]
    export.export_document(finished, tmp_path / "again.cbz")


def test_a_render_from_a_build_that_never_signed_it_is_unverified_not_refused(
        finished):
    """A chapter finished by an older build is not evidence of anything wrong,
    and making people render again to satisfy new bookkeeping would be a defect
    of the upgrade."""
    doc = ir.load_doc(finished)
    for page in doc["pages"]:
        page.pop("delivery", None)
    ir.save_doc(doc, finished)

    report = qa.check_document(finished)
    assert report["ok"], report["findings"]
    assert report["by_code"].get("delivery-unverified")


# --------------------------------------------------------------------------- #
# The verdict is computed from all of the findings.
# --------------------------------------------------------------------------- #

def test_every_error_is_counted_not_the_first_sixty(translated):
    """`findings` is capped so a person can read it. Deciding from the capped
    list reported a document with 82 errors as having 60 — and published the
    other 22."""
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    template = dict(page["regions"][0])
    for index in range(70):
        extra = dict(template)
        extra["id"] = f"{page['id']}x{index:03d}"
        extra["reading_order"] = 900 + index
        extra["typeset"] = None          # approved Persian, never rendered
        page["regions"].append(extra)
    ir.save_doc(doc, translated)

    report = qa.check_document(translated)
    state = qa.publication_preflight(translated)

    assert len(report["findings"]) == 60 and report["truncated"]
    assert report["errors"] >= 70
    assert state["blocking_count"] == report["errors"]
    assert len(state["blocking"]) == 20        # still readable


# --------------------------------------------------------------------------- #
# A page with no Persian on it still has to prove what it ships.
# --------------------------------------------------------------------------- #

def _erase_only(doc_path):
    """A watermark-removal chapter: every region erased, nothing translated.

    The honest workflow for one of these ends at `clean` — there is no Persian,
    so `typeset` has nothing to draw and nobody runs it. That is also the whole
    difficulty: the delivery certificate is written by `typeset`, so a chapter
    that legitimately never reaches it ships uncertified bytes.
    """
    doc = ir.load_doc(doc_path)
    for _page, region in ir.iter_regions(doc):
        region["erase"] = True
        for key in ("target_text", "target_full", "locked"):
            region.pop(key, None)
    ir.save_doc(doc, doc_path)
    masks.build_document(doc_path)
    clean.clean_document(doc_path)
    return ir.load_doc(doc_path)


def test_an_erase_only_chapter_publishes_its_cleaned_pages(translated, tmp_path):
    """The control. Erasure is finished work, and it must be publishable
    without a render that would have nothing to put on the page."""
    _erase_only(translated)

    state = qa.publication_preflight(translated)
    assert state["ok"], state["blocking"]
    report = export.export_document(translated, tmp_path / "erased.cbz")

    assert set(report["sources"].values()) == {"clean"}


def test_a_missing_cleaned_page_is_not_replaced_by_the_untouched_original(
        translated, tmp_path):
    """The defect this section exists for. `export` resolves the most finished
    file that EXISTS, so deleting the cleaned page silently promoted the
    original — with the watermark the reader approved removing still on it —
    into an approved edition, counted as an untouched page and nothing else."""
    doc = _erase_only(translated)
    root = ir.doc_dir(translated)
    (root / doc["pages"][0]["clean"]).unlink()

    assert not qa.publication_preflight(translated)["ok"]
    with pytest.raises(ValueError):
        export.export_document(translated, tmp_path / "erased.cbz")


def test_a_cleaned_status_without_a_cleaned_page_is_not_proof(translated):
    """A stale success status is not evidence of current work: every region
    still says `clean_status: cleaned` and there is no cleaned page at all."""
    doc = _erase_only(translated)
    root = ir.doc_dir(translated)
    page = doc["pages"][0]
    (root / page.pop("clean")).unlink()
    ir.save_doc(doc, translated)

    assert {region["clean_status"] for region in page["regions"]} == {"cleaned"}
    assert not qa.publication_preflight(translated)["ok"]


def test_a_cleaned_page_edited_after_cleaning_is_refused(translated):
    """Nothing looked at these bytes. The preservation proof runs against a
    render, and an erase-only chapter has none — so a hand-edited cleaned page
    outside every mask was published unexamined."""
    doc = _erase_only(translated)
    root = ir.doc_dir(translated)
    path = root / doc["pages"][0]["clean"]
    image = ir.load_image(path)
    image.paste((255, 0, 0), (0, 0, 24, 24))
    ir.save_image(image, path)

    assert not qa.publication_preflight(translated)["ok"]


def test_restoring_the_original_over_the_cleaned_page_is_refused(translated):
    """The erasure undone, at the right size, with every status still `cleaned`."""
    doc = _erase_only(translated)
    root = ir.doc_dir(translated)
    page = doc["pages"][0]
    shutil.copyfile(root / page["image"], root / page["clean"])

    assert not qa.publication_preflight(translated)["ok"]


def test_re_cleaning_certifies_the_page_again(translated, tmp_path):
    """The route back, for the same reason the render has one."""
    doc = _erase_only(translated)
    root = ir.doc_dir(translated)
    page = doc["pages"][0]
    shutil.copyfile(root / page["image"], root / page["clean"])
    assert not qa.publication_preflight(translated)["ok"]

    clean.clean_document(translated, pages=[page["id"]])

    state = qa.publication_preflight(translated)
    assert state["ok"], state["blocking"]
    export.export_document(translated, tmp_path / "again.cbz")


@pytest.mark.parametrize("field", ["final", "clean", "writable"])
def test_a_delivery_record_missing_one_field_does_not_skip_that_check(
        finished, field):
    """`if not recorded: continue` — so deleting a line of the certificate
    bought exemption from the check it was there to make."""
    doc = ir.load_doc(finished)
    page = next(p for p in doc["pages"] if p.get("final") and p.get("clean"))
    page["delivery"].pop(field)
    ir.save_doc(doc, finished)

    assert "delivery-mismatch" in _blocking_codes(finished)


def test_a_cleaned_chapter_from_a_build_that_never_signed_it_is_unverified(
        translated):
    """Same upgrade rule as the render: an older build's work is not evidence
    of anything wrong, and re-cleaning to satisfy new bookkeeping would be a
    defect of the upgrade."""
    doc = _erase_only(translated)
    for page in doc["pages"]:
        page.pop("cleaning", None)
    ir.save_doc(doc, translated)

    report = qa.check_document(translated)
    assert report["ok"], report["findings"]
