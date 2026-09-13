"""How much room the Persian really needs, and what a run says it did.

The fitter and the renderer are two pieces of code that must agree about one
number: how far past the glyphs the ink reaches. They did not — the renderer
draws a styled effect with an outline of up to 22% of the type size plus a
shadow, and the fitter reserved about 8% for both — so a strip was accepted at
a size that could not be drawn inside it.

The second half is what the run then reports: a placement taken back off the
page is not a placement, and a run that could not do its required work has to
say so in its exit code.
"""
from __future__ import annotations

import numpy as np
import pytest

import lettering
import pageir as ir
import typefit
import typeset
from test_lettering import _arc, _sfx_page


# --------------------------------------------------------------------------- #
# One envelope
# --------------------------------------------------------------------------- #

def test_a_styled_envelope_is_wider_than_a_plain_one():
    plain = typefit.stroke_for(36)
    styled = (typefit.stroke_for(36, styled=True)
              + typefit.shadow_for(36, styled=True))

    assert styled > plain * 2, (plain, styled)


@pytest.mark.parametrize("size", [12, 24, 36, 48, 72])
def test_the_styled_envelope_covers_the_renderers_own_constants(size):
    """Read from `lettering`'s constants, so the two cannot drift apart again
    without this failing."""
    reserved = (typefit.stroke_for(size, styled=True)
                + typefit.shadow_for(size, styled=True))
    drawn = (int(round(size * lettering.MAX_STROKE)) + 1
             + max(1, int(round(size * lettering.SHADOW_OFFSET))))

    assert reserved >= drawn, (size, reserved, drawn)


@pytest.mark.parametrize("sagitta", [34, -34])
def test_a_styled_strip_is_not_drawn_outside_its_own_box(translated, sagitta):
    """The real operation, both curve directions, with the style MEASURED off
    the mask the way the pipeline measures it.

    The assertion is the one that matters everywhere in this project: not a
    pixel outside the area the cleaner was authorised over."""
    import clean

    page, _region = _sfx_page(translated, mask=_arc(sagitta),
                              box=(60, 60, 320, 160), text="بوم")
    root = ir.doc_dir(translated)
    clean.clean_document(translated)
    before = np.asarray(ir.load_image(
        root / ir.load_doc(translated)["pages"][0]["clean"])).copy()

    typeset.typeset_document(translated)

    after_doc = ir.load_doc(translated)
    after = np.asarray(ir.load_image(root / after_doc["pages"][0]["final"]))
    writable = after_doc["pages"][0]["writable"]
    allowed = np.asarray(ir.load_image(root / writable).convert("L")) > 0
    changed = (before != after).any(axis=2) & ~allowed

    assert not changed.any(), f"{int(changed.sum())} pixel(s) drawn outside"


# --------------------------------------------------------------------------- #
# What a run reports about itself
# --------------------------------------------------------------------------- #

def _impossible(doc_path):
    """One region whose Persian cannot fit its box at any allowed size."""
    doc = ir.load_doc(doc_path)
    page = doc["pages"][0]
    for region in page["regions"]:
        region["target_text"] = ""
    region = page["regions"][0]
    region["target_text"] = "یک جملهٔ بسیار بسیار بلند که هرگز جا نمی‌شود " * 12
    region["bbox"] = [10, 10, 40, 20]
    region["mask_box"] = [10, 10, 40, 20]
    ir.save_doc(doc, doc_path)
    return page["id"]


def test_an_overflowing_region_is_not_counted_as_placed(detected):
    """A region whose ink never stayed on the page was counted alongside the
    rest, so the headline number described ink that is not there."""
    page_id = _impossible(detected)

    report = typeset.typeset_document(detected, pages=[page_id],
                                      min_size=20)

    assert report["overflow"], report
    after = ir.load_doc(detected)["pages"][0]
    ok = sum(1 for region in after["regions"]
             if (region.get("typeset") or {}).get("status") == "ok")
    assert report["placed"] == ok, report


def test_a_run_with_an_overflow_exits_non_zero(detected, capsys):
    """It exited zero with its only line overflowing, so a script that checked
    the status code shipped a page with no Persian on it."""
    _impossible(detected)

    status = typeset.main(["--doc", str(detected), "--min-size", "20"])

    capsys.readouterr()
    assert status == 1


def test_a_clean_run_exits_zero(finished, capsys):
    status = typeset.main(["--doc", str(finished)])

    capsys.readouterr()
    assert status == 0


# --------------------------------------------------------------------------- #
# Annotations converge
# --------------------------------------------------------------------------- #

def _glossed(doc_path, policy="bilingual"):
    doc = ir.load_doc(doc_path)
    doc["meta"]["sfx_policy"] = policy
    region = doc["pages"][0]["regions"][0]
    region.update({"kind": "sfx", "target_text": "بوم", "keep": False})
    ir.save_doc(doc, doc_path)
    return doc["pages"][0]["id"]


def test_repeated_annotation_runs_do_not_pile_up(detected):
    """A rerun of a `bilingual` chapter added the same unresolved note again
    every time, so a page typeset three times carried three copies."""
    page_id = _glossed(detected)

    for _ in range(3):
        typeset.typeset_document(detected, pages=[page_id])

    notes = ir.load_doc(detected)["pages"][0].get("annotations") or []
    assert len(notes) == 1, notes


def test_a_policy_change_clears_the_annotation_it_produced(detected):
    """`translate` replaces the effect instead of glossing it, so the gloss
    that had nowhere to go no longer exists — and `qa` must stop reporting it."""
    page_id = _glossed(detected)
    typeset.typeset_document(detected, pages=[page_id])
    assert ir.load_doc(detected)["pages"][0]["annotations"]

    doc = ir.load_doc(detected)
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, detected)
    typeset.typeset_document(detected, pages=[page_id])

    assert not (ir.load_doc(detected)["pages"][0].get("annotations") or [])
