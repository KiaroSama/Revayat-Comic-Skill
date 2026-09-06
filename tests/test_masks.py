"""Masks — what may be repainted, and what may not.

The mask is the only thing standing between a translation and a damaged page,
so these tests are about what it must *not* cover as much as what it must.
"""

from __future__ import annotations

import numpy as np
import pytest

import masks
import pageir as ir


def test_a_mask_is_written_for_every_region(detected):
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    for _, region in ir.iter_regions(doc):
        assert region["mask"], f"{region['id']} has no mask"
        assert (root / region["mask"]).exists()
        assert region["mask_box"][2] > 0 and region["mask_box"][3] > 0


def test_a_mask_covers_the_lettering(detected):
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    rgb = np.asarray(ir.load_image(root / page["image"]))

    for region in page["regions"]:
        if region["kind"] != "speech":
            continue
        mask = masks.load_mask(root / region["mask"])
        mx, my = region["mask_box"][0], region["mask_box"][1]
        # The lettering is the ink inside the text box *and* inside the balloon.
        # A balloon is an ellipse, so the corners of its text box fall outside
        # it — on a page with screentone behind the balloon that is artwork, and
        # the mask is right to leave it alone.
        interior = masks.balloon_interior(
            rgb, region["balloon"], region.get("polarity", "light"),
            (page["width"], page["height"]), inset=masks.OUTLINE_INSET,
        )
        tx, ty, tw, th = region["bbox"]
        window = rgb[ty:ty + th, tx:tx + tw]
        ink = (window.min(axis=2) < 100) & (interior[ty:ty + th, tx:tx + tw] > 0)
        covered_mask = mask[ty - my:ty - my + th, tx - mx:tx - mx + tw]
        # Nearly all of it has to be inside the mask; the few stragglers are the
        # anti-aliased edge of a glyph.
        covered = (covered_mask[ink] > 0).mean() if ink.any() else 1.0
        assert covered > 0.98, f"{region['id']} leaves {1 - covered:.0%} of its ink"


def test_the_balloon_outline_is_never_inside_a_mask(detected):
    """Clipping to the balloon's bounding box repaints the corners of the box,
    which is outside the balloon, and erases the outline that crosses them."""
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    union = masks.load_mask(root / page["mask"])

    for region in page["regions"]:
        balloon = region.get("balloon")
        if not balloon:
            continue
        x, y, w, h = (int(v) for v in balloon)
        ring = np.zeros(union.shape, bool)
        ring[y:y + h, x:x + w] = True
        inset = max(3, int(0.02 * min(w, h)))
        ring[y + inset:y + h - inset, x + inset:x + w - inset] = False
        assert not (union[ring] > 0).any(), (
            f"{region['id']} would repaint the rim of its own balloon"
        )


def test_the_interior_is_the_balloon_shape_not_its_box(detected):
    """The corners of a box around an ellipse are outside the balloon."""
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    rgb = np.asarray(ir.load_image(root / page["image"]))
    region = next(r for r in page["regions"] if r.get("balloon"))

    interior = masks.balloon_interior(
        rgb, region["balloon"], region.get("polarity", "light"),
        (page["width"], page["height"]),
    )
    x, y, w, h = (int(v) for v in region["balloon"])
    box_area = w * h
    covered = int((interior > 0).sum())
    # An inscribed ellipse is pi/4 of its box; anything near 1.0 means the box
    # was used and the corners went with it.
    assert 0.6 * box_area < covered < 0.92 * box_area


def test_the_union_is_the_union(detected):
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    page = doc["pages"][0]
    union = masks.load_mask(root / page["mask"])

    total = np.zeros_like(union)
    for region in page["regions"]:
        mask = masks.load_mask(root / region["mask"])
        x, y, w, h = region["mask_box"]
        total[y:y + h, x:x + w] = np.maximum(total[y:y + h, x:x + w], mask)
    assert np.array_equal(total, union)


def test_coverage_stays_small_on_an_ordinary_page(detected):
    doc = ir.load_doc(detected)
    for page in doc["pages"]:
        assert page["mask_coverage"] < 0.15, (
            f"{page['id']} would repaint {page['mask_coverage']:.0%} of the artwork"
        )


def test_excessive_coverage_is_reported(detected):
    """A region that matched artwork rather than lettering must be surfaced
    before cleaning, not discovered in the finished file.

    Note what it takes to provoke: growing the mask is not enough, because a
    balloon's mask is clipped to the balloon and cannot spread past it. It takes
    a detection that was wrong about where the text is.
    """
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    page["regions"].append(
        ir.new_region(f"{page['id']}r900", [10, 10, 900, 1400], kind="sfx")
    )
    ir.save_doc(doc, detected)

    report = masks.build_document(detected, grow=0.01)
    assert "p0001" in report["excessive_coverage"]
    assert "28%" in report["warning"]


def test_a_speck_under_the_balloon_centre_does_not_empty_the_interior():
    """The interior is the balloon's paper, and the paper is the *biggest* light
    thing inside a balloon's own box — never whatever the centre pixel happens
    to land on.

    Found on a real page. The centre of one balloon fell on a 113-pixel fleck of
    screentone, `balloon_interior` returned it as the interior, eroding by the
    outline inset wiped it out, the mask came back empty, cleaning had nothing to
    paint and the English stayed on the finished page — with every count
    reporting success. Only `source-text-survived` noticed.

    The old code fell back to the largest component only when the centre landed
    on a *letter*. A speck is light, so it never triggered.
    """
    from PIL import Image, ImageDraw

    width, height = 200, 160
    page = Image.new("RGB", (width, height), "black")
    draw = ImageDraw.Draw(page)
    draw.ellipse([10, 10, width - 10, height - 10], fill="white", outline="black", width=3)
    # A letter across the middle, with one isolated light speck at the exact
    # centre pixel — the shape that used to be mistaken for the whole balloon.
    draw.rectangle([60, 60, 140, 100], fill="black")
    cx, cy = width // 2, height // 2
    draw.rectangle([cx - 1, cy - 1, cx + 1, cy + 1], fill="white")

    interior = masks.balloon_interior(
        np.asarray(page), [0, 0, width, height], "light", (width, height),
        inset=masks.OUTLINE_INSET,
    )
    covered = int((interior > 0).sum())
    assert covered > 0.25 * width * height, (
        f"interior collapsed to {covered} px; the speck was taken for the paper"
    )


def test_free_lettering_can_be_masked_solid_for_a_generative_cleaner(detected):
    """Lettering drawn onto the artwork has no balloon to protect, and clipping a
    reconstruction back to the letter shapes is what makes it look repaired
    rather than redrawn: every seam lands on a glyph edge, which is where the eye
    goes. `--free-lettering solid` hands the whole patch over instead.
    """
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    free = [r for r in page["regions"] if not r.get("balloon")]
    assert free, "fixture has no free lettering to mask"

    rgb = np.asarray(ir.load_image(ir.doc_dir(detected) / page["image"]))
    size = (page["width"], page["height"])
    glyphs, _ = masks.region_mask(rgb, free[0], size)
    solid, box = masks.region_mask(rgb, free[0], size, solid_free=True)

    assert (solid > 0).all()
    assert (solid > 0).sum() > (glyphs > 0).sum()
    assert solid.shape == (box[3], box[2])


def test_a_balloon_is_never_masked_solid(detected):
    """The option is for free lettering only. A solid mask over a balloon would
    take its outline with it, which is the defect the interior clip exists for."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    balloons = [r for r in page["regions"] if r.get("balloon")]
    assert balloons

    rgb = np.asarray(ir.load_image(ir.doc_dir(detected) / page["image"]))
    size = (page["width"], page["height"])
    plain, _ = masks.region_mask(rgb, balloons[0], size)
    asked, _ = masks.region_mask(rgb, balloons[0], size, solid_free=True)
    assert (plain == asked).all()


def test_solid_masks_are_recorded_and_refused_by_the_built_in_cleaners(detected):
    """The one combination that would destroy artwork, blocked at the door: a
    solid patch painted flat or inpainted blanks a rectangle out of the drawing.
    """
    import clean

    masks.build_document(detected, solid_free=True)
    assert ir.load_doc(detected)["meta"]["free_lettering_mask"] == "solid"

    with pytest.raises(ValueError, match="free-lettering solid"):
        clean.clean_document(detected)

    masks.build_document(detected)
    assert ir.load_doc(detected)["meta"]["free_lettering_mask"] == "glyphs"
    clean.clean_document(detected)          # and now it runs


def test_an_added_speech_region_gets_its_balloon_found_for_it(detected):
    """The point of splitting one region into two: each half has to *be* a
    balloon, or the mask is not clipped to an interior and Persian can be set
    over the outline."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    balloon = [r for r in page["regions"] if r.get("balloon")][0]
    bx, by, bw, bh = balloon["bbox"]

    page["regions"].append(dict(
        ir.new_region(f"{page['id']}r900", [bx, by, bw, bh], kind="speech",
                      detector="reader", confidence=1.0),
        balloon=None, polarity=balloon.get("polarity", "light"),
        added_as="split", target_text="سلام",
    ))
    ir.save_doc(doc, detected)

    report = masks.build_document(detected)
    assert report["balloons_derived"] >= 1

    added = [r for _, r in ir.iter_regions(ir.load_doc(detected))
             if r.get("added_as") == "split"][0]
    assert added["balloon"] is not None
    x, y, w, h = added["balloon"]
    assert x <= bx and y <= by and x + w >= bx + bw and y + h >= by + bh


def test_a_panel_sized_component_is_not_accepted_as_a_derived_balloon(detected):
    """The guard that keeps a whole panel out. A box drawn on open artwork has
    no balloon, and inventing one would clip the mask to the wrong shape."""
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    rgb = np.asarray(ir.load_image(ir.doc_dir(detected) / page["image"]))
    size = (page["width"], page["height"])
    whole_page = [0, 0, page["width"], page["height"]]
    assert masks.find_balloon(rgb, whole_page, "light", size) is None
