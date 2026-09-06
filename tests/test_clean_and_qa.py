"""Cleaning, and the gate that proves the artwork survived it.

The pixel-preservation check is the point of this project. These tests both
prove it holds on a real run and prove it *fails* when something breaks it —
a gate that cannot fail is not a gate.
"""

from __future__ import annotations

import numpy as np
import pytest

import clean
import falint
import masks
import pageir as ir
import qa
import typeset


@pytest.fixture
def finished(translated):
    clean.clean_document(translated)
    typeset.typeset_document(translated)
    return translated


# --- Strategy ---------------------------------------------------------------

def test_a_flat_balloon_is_filled_not_inpainted(finished):
    """Reading the balloon's own colour and painting it back is exact. Sending
    it to an inpainter is slower and only approximates what was already known."""
    doc = ir.load_doc(finished)
    filled = [r for _, r in ir.iter_regions(doc) if r["fill"] == "flat"]
    assert len(filled) >= 6


def test_the_background_is_sampled_inside_the_balloon_only():
    """Sampling the whole crop picks up the outline and the artwork behind the
    balloon, and a plain white balloon then measures as textured — nine out of
    nine went to the inpainter before this was fixed."""
    window = np.full((60, 60, 3), 250, np.uint8)
    window[0, :] = 0          # the balloon outline along one edge
    window[:, 0] = 0
    mask = np.zeros((60, 60), np.uint8)
    mask[20:40, 20:40] = 255  # the lettering

    allowed = np.zeros((60, 60), np.uint8)
    allowed[5:55, 5:55] = 255

    assert clean.choose_strategy(window, mask, np)[0] == "inpaint"
    assert clean.choose_strategy(window, mask, np, allowed)[0] == "flat"


def test_texture_goes_to_the_inpainter():
    window = np.zeros((60, 60, 3), np.uint8)
    window[::3] = 255                       # stripes: not a flat background
    mask = np.zeros((60, 60), np.uint8)
    mask[20:40, 20:40] = 255
    assert clean.choose_strategy(window, mask, np)[0] == "inpaint"


def test_a_sound_effect_is_kept_under_the_keep_policy(translated):
    doc = ir.load_doc(translated)
    doc["meta"]["sfx_policy"] = "keep"
    ir.save_doc(doc, translated)
    report = clean.clean_document(translated)
    assert report["totals"]["keep"] > 0


def test_a_sound_effect_is_removed_under_the_translate_policy(translated):
    doc = ir.load_doc(translated)
    doc["meta"]["sfx_policy"] = "translate"
    ir.save_doc(doc, translated)
    report = clean.clean_document(translated)
    assert report["totals"]["keep"] == 0


# --- Compositing ------------------------------------------------------------

def test_the_blend_ramp_never_leaves_the_mask():
    """A Gaussian spreads outward. Without clamping it back to the hard mask,
    the ramp leaks past the authorised area and fails the very check it is
    there to pass."""
    base = np.zeros((40, 40, 3), np.uint8)
    repaired = np.full((40, 40, 3), 255, np.uint8)
    mask = np.zeros((40, 40), np.uint8)
    mask[15:25, 15:25] = 255

    out = clean._composite(base, repaired, mask, np)
    outside = out.copy()
    outside[mask > 0] = 0
    assert outside.max() == 0


def test_cleaning_changes_nothing_outside_the_mask(translated):
    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    before = {p["id"]: np.asarray(ir.load_image(root / p["image"])).copy()
              for p in doc["pages"]}

    clean.clean_document(translated)
    doc = ir.load_doc(translated)
    for page in doc["pages"]:
        after = np.asarray(ir.load_image(root / page["clean"]))
        allowed = masks.load_mask(root / page["mask"]) > 0
        delta = np.abs(before[page["id"]].astype(int) - after.astype(int)).max(axis=2)
        delta[allowed] = 0
        assert delta.max() == 0, f"{page['id']} was modified outside its mask"


def test_an_external_page_only_contributes_its_masked_pixels(translated, tmp_path):
    """This is what makes a generative cleaner safe to plug in: even if it
    redraws the whole page, only the masked pixels of it are ever used."""
    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    external = tmp_path / "external"
    external.mkdir()
    from PIL import Image

    for page in doc["pages"]:
        # A completely different image, the right size.
        Image.new("RGB", (page["width"], page["height"]), (255, 0, 0)).save(
            external / f"{page['id']}.png"
        )

    clean.clean_document(translated, external=external)
    doc = ir.load_doc(translated)
    for page in doc["pages"]:
        original = np.asarray(ir.load_image(root / page["image"]))
        after = np.asarray(ir.load_image(root / page["clean"]))
        allowed = masks.load_mask(root / page["mask"]) > 0
        delta = np.abs(original.astype(int) - after.astype(int)).max(axis=2)
        delta[allowed] = 0
        assert delta.max() == 0


def test_an_external_page_of_the_wrong_size_is_refused(translated, tmp_path):
    from PIL import Image

    external = tmp_path / "external"
    external.mkdir()
    Image.new("RGB", (100, 100), "white").save(external / "p0001.png")
    with pytest.raises(ValueError, match="same size"):
        clean.clean_document(translated, external=external)


# --- The gate ---------------------------------------------------------------

def test_a_finished_chapter_passes(finished):
    falint.fix_document(finished)
    report = qa.check_document(finished)
    assert report["ok"], report["findings"]
    assert report["stats"]["artwork_pixels_changed"] == 0


def test_the_gate_catches_artwork_that_was_modified(finished):
    """Paint over a face far from any balloon. Nothing is missing, every count
    is right, and only this check notices."""
    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    page = doc["pages"][0]
    from PIL import Image

    image = ir.load_image(root / page["final"])
    pixels = np.asarray(image).copy()
    pixels[900:960, 60:120] = (255, 0, 0)
    ir.save_image(Image.fromarray(pixels), root / page["final"])

    report = qa.check_document(finished)
    assert not report["ok"]
    assert report["by_code"]["artwork-modified"] == 1


def test_the_gate_catches_an_edited_original(finished):
    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    page = doc["pages"][0]
    from PIL import Image

    pixels = np.asarray(ir.load_image(root / page["image"])).copy()
    pixels[10:20, 10:20] = (0, 255, 0)
    ir.save_image(Image.fromarray(pixels), root / page["image"])

    report = qa.check_document(finished)
    assert "source-modified" in report["by_code"]


def test_the_gate_catches_an_untranslated_region(finished):
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = ""
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert report["by_code"]["untranslated-region"] >= 1


def test_the_gate_catches_source_script_left_in_the_persian(finished):
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = "بس کن やめろ"
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert report["by_code"]["source-script-left"] >= 1


def test_the_gate_catches_text_that_is_not_persian(finished):
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = "Stop right there"
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert report["by_code"]["not-persian"] >= 1


def test_the_gate_catches_a_reply_pasted_twice(finished):
    doc = ir.load_doc(finished)
    regions = [region for _, region in ir.iter_regions(doc)][:2]
    regions[0]["source_text"] = "やめろ"
    regions[1]["source_text"] = "誰も知らない"
    regions[0]["target_text"] = regions[1]["target_text"] = "همان جملهٔ تکراری"
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert report["by_code"]["duplicate-translation"] >= 1


def test_the_same_source_translated_the_same_way_is_not_a_defect(finished):
    doc = ir.load_doc(finished)
    regions = [region for _, region in ir.iter_regions(doc)][:2]
    regions[0]["source_text"] = regions[1]["source_text"] = "やめろ"
    regions[0]["target_text"] = regions[1]["target_text"] = "بس کن"
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert "duplicate-translation" not in report["by_code"]


def test_strict_makes_warnings_blocking(finished):
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = "كتاب"          # an Arabic kaf: a typography warning
    ir.save_doc(doc, finished)

    assert qa.check_document(finished)["ok"]
    assert not qa.check_document(finished, strict=True)["ok"]


def test_a_glossary_drift_is_reported(finished):
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["source_text"] = "ハルカ"
    region["target_text"] = "هاروکو برگشت"      # a different name entirely
    doc["glossary"] = {"entries": {"ハルカ": {"target": "هاروکا", "locked": True}}}
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert report["by_code"]["glossary-drift"] >= 1


def test_an_inflected_form_of_a_locked_name_is_not_drift(finished):
    """`هاروکا` with an ezafe is `هاروکای`, and that is correct Persian. Matching
    on the substring accepts the inflection and still rejects a different name."""
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["source_text"] = "ハルカ"
    region["target_text"] = "کتابِ هاروکای کوچک"
    doc["glossary"] = {"entries": {"ハルカ": {"target": "هاروکا", "locked": True}}}
    ir.save_doc(doc, finished)
    report = qa.check_document(finished)
    assert "glossary-drift" not in report["by_code"]


def test_every_finding_code_is_declared():
    """A check that emits an undeclared code would produce a finding the skill
    has no documented action for."""
    with pytest.raises(KeyError):
        qa.Findings().add("invented-code", "here", "detail")


def test_the_skill_documents_every_code():
    from pathlib import Path

    skill = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    missing = [code for code in qa.CODES if f"`{code}`" not in text]
    assert not missing, f"SKILL.md has no action for: {missing}"


# --- Terminal states ---------------------------------------------------------
# Completeness used to be inferred from a scatter of fields. A region that fell
# between them was invisible: nothing missing, no count wrong, and a balloon
# simply never translated. The census makes "what happened to all of them" a
# question with one answer per region.

def test_every_region_reaches_exactly_one_terminal_state(finished):
    doc = ir.load_doc(finished)
    census = ir.state_census(doc)
    assert sum(census.values()) == len(ir.all_regions(doc))
    assert set(census) == set(ir.REGION_STATES)


def test_a_finished_chapter_leaves_nothing_unresolved(finished):
    assert ir.state_census(ir.load_doc(finished))["unresolved"] == 0


@pytest.mark.parametrize("setup, expected", [
    (lambda r: r.update(target_text="سلام"), "translated"),
    (lambda r: r.update(dropped=True), "dropped_false_detection"),
    (lambda r: r.update(target_text="سلام", typeset={"status": "overflow"}),
     "needs_review"),
    (lambda r: r.update(review=["cannot read this crop"]), "needs_review"),
    (lambda r: None, "unresolved"),
])
def test_each_terminal_state_is_reachable(setup, expected):
    region = ir.new_region("r1", [0, 0, 10, 10], kind="speech")
    setup(region)
    assert ir.region_state(region, "keep") == expected


def test_a_kept_sound_effect_is_a_decision_not_a_hole():
    sfx = ir.new_region("r1", [0, 0, 10, 10], kind="sfx")
    assert ir.region_state(sfx, "keep") == "kept_by_policy"
    # Under `translate` the same empty region IS a hole.
    assert ir.region_state(sfx, "translate") == "unresolved"


def test_an_unresolved_region_is_counted_and_still_blocks(finished):
    """The census is reported, not gated: `unresolved` is a strict subset of
    what `untranslated-region` already blocks on, so a second code firing on the
    same rows would be noise. The count still has to be visible."""
    doc = ir.load_doc(finished)
    _, region = next(iter(ir.iter_regions(doc)))
    region["target_text"] = ""
    region["typeset"] = {}
    region["review"] = []
    region["dropped"] = False
    ir.save_doc(doc, finished)

    report = qa.check_document(finished)
    assert report["stats"]["states"]["unresolved"] >= 1
    assert report["by_code"]["untranslated-region"] >= 1
    assert not report["ok"]


def test_unresolved_never_escapes_the_blocking_code(finished):
    """Why the census is safe to leave ungated, asserted rather than assumed:
    nothing can be `unresolved` without also being untranslated."""
    doc = ir.load_doc(finished)
    policy = doc["meta"].get("sfx_policy", "keep")
    for _, region in ir.iter_regions(doc):
        if ir.region_state(region, policy) == "unresolved":
            assert ir.translatable(region, policy)
            assert not (region.get("target_text") or "").strip()


# --- Did the lettering actually go? ------------------------------------------

def test_a_clean_run_leaves_no_surviving_lettering(finished):
    assert "source-text-survived" not in qa.check_document(finished)["by_code"]


def test_the_gate_catches_a_mask_that_missed_half_the_lettering(finished):
    """`artwork-modified` proves nothing changed that should not have. This
    proves the other direction, which nothing else asks."""
    from PIL import Image

    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    victim = next(r for _, r in ir.iter_regions(doc) if r.get("balloon"))
    mask = masks.load_mask(root / victim["mask"]).copy()
    mask[: mask.shape[0] // 2, :] = 0
    Image.fromarray(mask, mode="L").save(root / victim["mask"])

    clean.clean_document(finished)
    report = qa.check_document(finished)
    assert report["by_code"]["source-text-survived"] >= 1
    assert not report["ok"]


def test_the_balloon_outline_is_not_mistaken_for_leftover_text(finished):
    """The first implementation measured over the padded box and read every
    balloon's own outline as un-removed lettering — 100% survived on a perfect
    run. Scoping it to the interior is what makes the number mean anything."""
    doc = ir.load_doc(finished)
    root = ir.doc_dir(finished)
    page = doc["pages"][0]
    before = np.asarray(ir.load_image(root / page["image"]))
    after = np.asarray(ir.load_image(root / page["clean"]))
    size = (page["width"], page["height"])

    for region in page["regions"]:
        if not region.get("balloon") or region.get("fill") in {"none", "keep"}:
            continue
        share = qa.surviving_ink(
            before, after, region, masks.load_mask(root / region["mask"]),
            size, np,
        )
        assert share <= qa.MAX_SURVIVING_INK, f"{region['id']} reads {share:.0%}"


def test_free_lettering_is_not_judged_for_survival():
    """On artwork there is no flat paper to measure against: leftover ink is
    indistinguishable from the drawing it sits on, so the check declines."""
    region = ir.new_region("r1", [0, 0, 40, 40], kind="sfx")
    region["mask_box"] = [0, 0, 40, 40]
    assert qa.surviving_ink(
        np.zeros((40, 40, 3), np.uint8), np.zeros((40, 40, 3), np.uint8),
        region, np.zeros((40, 40), np.uint8), (40, 40), np,
    ) == 0.0


def test_dropping_a_false_detection_is_not_a_broken_reading_order(finished):
    """`drop: yes` is the correction the worksheet asks for by name, and it
    leaves a gap in the numbering every single time.

    The check used to require the surviving regions to be numbered 1..N, so it
    fired on all ten pages of the first real chapter — every one of them
    correctly translated. A gate that goes off on the documented workflow is how
    people learn to skip reading the gate.
    """
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    live = [r for r in page["regions"] if not r.get("dropped")]
    assert len(live) >= 2, "fixture needs at least two regions to drop one"
    live[0]["dropped"] = True
    ir.save_doc(doc, finished)

    report = qa.check_document(finished)
    assert "reading-order-broken" not in report["by_code"]


def test_two_regions_sharing_a_reading_order_is_still_caught(finished):
    """Loosening the check must not turn it off: a repeated number is a real
    ordering fault and still fails."""
    doc = ir.load_doc(finished)
    page = doc["pages"][0]
    live = [r for r in page["regions"] if not r.get("dropped")]
    assert len(live) >= 2
    live[1]["reading_order"] = live[0]["reading_order"]
    ir.save_doc(doc, finished)

    report = qa.check_document(finished)
    assert report["by_code"].get("reading-order-broken") == 1
