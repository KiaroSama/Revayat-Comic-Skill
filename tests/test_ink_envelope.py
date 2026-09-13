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


# --------------------------------------------------------------------------- #
# Two renderers, two envelopes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("size", [16, 24, 36, 48, 64])
def test_a_flat_outline_is_not_charged_for_a_styled_effect(size):
    """One boolean decided this, and it was the wrong one: both callers pass
    "does this text have an outline colour" and the fitter read it as "is this
    a styled sound effect". A dialogue balloon on a dark page reserved three
    times what its outline draws, and was set small — or refused — for want of
    room it was never going to use."""
    outlined = typefit.envelope_for(size, outline=True)
    styled = typefit.envelope_for(size, styled=True, outline=True)

    assert outlined == typefit.stroke_for(size)
    assert outlined < styled


@pytest.mark.parametrize("size", [16, 36, 64])
def test_a_styled_effect_reserves_its_shadow_even_with_no_outline(size):
    """The shadow is drawn whether or not there is an outline colour, so an
    un-outlined effect reserved nothing and was drawn with its shadow hanging
    over the edge of its own strip."""
    reserved = typefit.envelope_for(size, styled=True)

    assert reserved == typefit.shadow_for(size, styled=True) > 0


@pytest.mark.parametrize("size", [16, 24, 36, 48, 64])
def test_the_styled_worst_case_covers_the_heaviest_thing_it_draws(size):
    """Recomputed from the renderer's own constants, including the modulated
    pass — which the reserve did not account for, so it covered about two
    thirds of what got painted."""
    reserved = typefit.envelope_for(size, styled=True, outline=True)
    widest = max(2, int(round(size * lettering.MAX_STROKE)))
    heaviest = max(widest + 1,
                   int(round(widest * (1 + lettering.MAX_MODULATION / 2))))
    drawn = heaviest + max(1, int(round(size * lettering.SHADOW_OFFSET)))

    assert reserved >= drawn, (size, reserved, drawn)


@pytest.mark.parametrize("size", [24, 48])
def test_a_delicate_effect_is_not_charged_for_a_heavy_one(size):
    """The other half of the same defect. The fitter was given the widest
    outline any effect could ask for, so a delicate one was refused room it was
    never going to use."""
    delicate = lettering.strip_envelope({"stroke": 0.04, "modulation": 0.0},
                                        size, True)
    heavy = lettering.strip_envelope({"stroke": 0.9, "modulation": 0.8},
                                     size, True)

    assert delicate < heavy <= typefit.envelope_for(size, styled=True,
                                                    outline=True)


@pytest.mark.parametrize("size", [24, 48])
def test_the_strip_envelope_always_holds_the_shadow(size):
    bare = lettering.strip_envelope({}, size, False)

    assert bare == max(1, round(size * lettering.SHADOW_OFFSET)) > 0


def test_a_dark_balloon_sets_larger_than_a_styled_effect_would():
    """What the over-reservation cost, measured: the same words in the same
    space, fitted as flat outlined text and as a styled effect."""
    from PIL import Image, ImageDraw

    text = "بس کن! این‌جا چه خبر است؟"
    mask = np.full((120, 300), 255, np.uint8)
    draw = ImageDraw.Draw(Image.new("RGB", (300, 120), (255, 255, 255)))
    font = typeset.find_font()
    shaper = typefit.Shaper()

    flat = typefit.fit_region(draw, text, mask, np, shaper, font,
                              max_size=64, min_size=13, outline=True)
    styled = typefit.fit_region(draw, text, mask, np, shaper, font,
                                max_size=64, min_size=13, styled=True,
                                outline=True)

    assert flat and styled and flat["size"] > styled["size"]


# --------------------------------------------------------------------------- #
# A render that runs off the sheet
# --------------------------------------------------------------------------- #

def test_text_drawn_past_the_page_edge_is_not_a_finished_render(translated,
                                                                monkeypatch):
    """The painted box was clamped to the page before anything looked at it, so
    ink past an edge was in no comparison at all: a line whose second half ran
    off the sheet was reported `ok` on the strength of the half that stayed."""
    import clean
    import typeset as typeset_module

    clean.clean_document(translated)
    real = typeset_module.fit_region

    def shoved(*args, **kwargs):
        fitted = real(*args, **kwargs)
        if fitted:
            for line in fitted.get("lines", []):
                line["x"] = int(line["x"]) - 4000
        return fitted

    monkeypatch.setattr(typeset_module, "fit_region", shoved)
    root = ir.doc_dir(translated)
    before = {page["id"]: ir.sha256_file(root / page["clean"])
              for page in ir.load_doc(translated)["pages"]}

    typeset_module.typeset_document(translated)

    doc = ir.load_doc(translated)
    states = [(region.get("typeset") or {}) for _p, region in ir.iter_regions(doc)]
    assert any(state.get("clipped_by_page") for state in states), states[:3]
    assert all(state.get("status") != "ok" for state in states)
    # And the page underneath is exactly as it was found.
    for page in doc["pages"]:
        assert ir.sha256_file(root / page["clean"]) == before[page["id"]]


def test_a_refusal_does_not_erase_the_neighbour_that_already_drew(translated):
    """Rolling back to the page as it was before ANY region drew undid the
    neighbours too: one balloon that did not fit erased the finished
    translation of every balloon whose ink shared a rectangle with it, and
    reported only its own overflow."""
    import clean
    import typeset as typeset_module

    clean.clean_document(translated)
    typeset_module.typeset_document(translated)
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    placed = [region["id"] for region in page["regions"]
              if (region.get("typeset") or {}).get("status") == "ok"]
    assert len(placed) >= 2, "the fixture placed too little to test this"

    # Make the LAST region impossible, leaving the others exactly as they were.
    page["regions"][-1]["target_text"] = "بس " * 300
    ir.save_doc(doc, translated)
    typeset_module.typeset_document(translated, pages=[page["id"]])

    after = ir.load_doc(translated)["pages"][0]
    states = {region["id"]: (region.get("typeset") or {}).get("status")
              for region in after["regions"]}
    assert states[after["regions"][-1]["id"]] in {"overflow", "unreliable"}
    survived = [rid for rid in placed if states.get(rid) == "ok"]
    assert len(survived) >= len(placed) - 1, states


# --------------------------------------------------------------------------- #
# A measurement belongs to the mask it was taken from
# --------------------------------------------------------------------------- #

def test_a_measurement_from_a_mask_that_has_been_rebuilt_is_not_reused(
        translated):
    """`typeset` reuses what `clean` measured rather than measuring again, and
    nothing said WHICH mask it had measured. Re-mask after cleaning and the
    Persian was bent to the slant of lettering measured inside a different
    outline."""
    import clean
    import typeset as typeset_module

    clean.clean_document(translated)
    doc = ir.load_doc(translated)
    page, region = next(
        (p, r) for p, r in ir.iter_regions(doc) if r.get("mask"))
    region["kind"] = "sfx"
    region["lettering"] = {"verdict": "unreliable", "reason": "invented",
                           "mask_sha": "not the mask on disk"}
    ir.save_doc(doc, translated)

    typeset_module.typeset_document(translated, pages=[page["id"]])

    after = ir.find_region(ir.load_doc(translated), region["id"])
    assert (after.get("typeset") or {}).get("reason") != "invented"


def test_a_measurement_that_still_matches_its_mask_is_reused(translated):
    """The other direction: `clean` measured this before it erased anything,
    and a second measurement of the same region could disagree with the one
    that decided whether to erase."""
    import clean
    import typeset as typeset_module

    # `clean` measures the lettering only where it is going to erase it, so
    # the policy has to be the one that replaces a sound effect — and the masks
    # have to be rebuilt under it, because a kept effect is given no mask at
    # all and there is then nothing to measure.
    import masks

    doc = ir.load_doc(translated)
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, translated)
    masks.build_document(translated)
    clean.clean_document(translated)

    doc = ir.load_doc(translated)
    found = [(p, r) for p, r in ir.iter_regions(doc) if r.get("lettering")]
    assert found, "the fixture measured no lettering at all"
    page, region = found[0]
    stamped = dict(region["lettering"])
    assert stamped.get("mask_sha")

    typeset_module.typeset_document(translated, pages=[page["id"]])

    assert ir.find_region(ir.load_doc(translated),
                          region["id"])["lettering"] == stamped


# --------------------------------------------------------------------------- #
# A face either has the letters or it has boxes where they go
# --------------------------------------------------------------------------- #

def test_the_shipped_face_covers_every_group():
    import typefont

    assert typefont._supports_persian(typeset.find_font())


def test_a_face_missing_one_group_is_refused():
    """One sample word passed a face that could not write half the alphabet:
    the old sample happens to contain two of the four Persian-only letters, so
    a face holding exactly those two and no more looked complete."""
    import typefont

    tofu = b"tofu"

    def drawn(text):
        if text == "":
            return b"blank"
        if text == typefont._DEFINITELY_MISSING:
            return tofu
        # Every group real except the one holding the Persian-only letters.
        return tofu if "پ" in text else text.encode("utf-8")

    assert not typefont.covers(drawn)
    assert typefont.covers(lambda text: (text or "blank").encode("utf-8"))
