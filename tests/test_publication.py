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

import export
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
