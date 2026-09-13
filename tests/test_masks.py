"""Masks — what may be repainted, and what may not.

The mask is the only thing standing between a translation and a damaged page,
so these tests are about what it must *not* cover as much as what it must.
"""

from __future__ import annotations

import numpy as np
import pytest

import masks
import typefont
import stages
import pageir as ir


def test_a_mask_is_written_for_every_region_the_cleaner_may_edit(detected):
    """The contract is not "every region gets a mask". A region the reader
    dropped or kept, and a sound effect the POLICY keeps, are artwork — and
    masking artwork puts it inside the area the cleaner may rewrite and inside
    the denominator the preservation proof divides by.
    """
    doc = ir.load_doc(detected)
    root = ir.doc_dir(detected)
    policy = doc["meta"].get("sfx_policy", "keep")
    editable = kept = 0
    for _, region in ir.iter_regions(doc):
        if ir.may_be_edited(region, policy):
            editable += 1
            assert region["mask"], f"{region['id']} has no mask"
            assert (root / region["mask"]).exists()
            assert region["mask_box"][2] > 0 and region["mask_box"][3] > 0
        else:
            kept += 1
            assert region["mask"] is None, (
                f"{region['id']} is kept by policy and was masked anyway")
    assert editable, "the fixture has nothing the cleaner may edit"
    assert kept, "the fixture no longer exercises a policy-kept region"


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
    policy = doc["meta"].get("sfx_policy", "keep")
    for region in page["regions"]:
        # Only the regions that HAVE a mask: the union is the union of the
        # authority, and a region the policy keeps has none.
        if not ir.may_be_edited(region, policy):
            continue
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
    # `speech`, not `sfx`: the default policy keeps sound effects, and a kept
    # effect is no longer masked at all — so an `sfx` region would contribute
    # nothing to coverage and this test would measure the wrong thing.
    huge = ir.new_region(f"{page['id']}r900", [10, 10, 900, 1400],
                         kind="speech")
    huge["target_text"] = "بس کن"
    page["regions"].append(huge)
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


# --- C01: provenance is page-local and content-bound -------------------------

def test_two_pages_masked_with_different_options_both_stay_current(translated):
    """One options dict for the whole record meant `mask --pages p0001 --grow 3`
    followed by `mask --pages p0002 --grow 9` left grow=9 on the record, and
    page 1's revision — computed with grow=3 — never matched again. Masking two
    pages differently is the ordinary reason the page selector exists."""
    doc = ir.load_doc(translated)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]

    masks.build_document(translated, pages=[first], grow=0.03)
    masks.build_document(translated, pages=[second], grow=0.09)

    assert stages.stale_pages(ir.load_doc(translated), "masks") == []


def test_changing_one_pages_options_stales_only_that_page(translated):
    masks.build_document(translated)
    doc = ir.load_doc(translated)
    first, second = doc["pages"][0]["id"], doc["pages"][1]["id"]

    masks.build_document(translated, pages=[first], grow=0.09)

    # Both are current: each page's recorded revision is the one it ran with.
    assert stages.stale_pages(ir.load_doc(translated), "masks") == []
    record = ir.load_doc(translated)["stages"]["masks"]
    assert record["page_options"][first] != record["page_options"][second]


@pytest.mark.parametrize("field", ["keep", "dropped", "erase"])
def test_a_region_action_invalidates_the_masking_that_depends_on_it(translated,
                                                                    field):
    """Keep, drop and erase decide whether the cleaner may touch a region at
    all. They lived only in the `text` facet, so masking and cleaning were
    never invalidated by the decision that governs them."""
    masks.build_document(translated)
    assert stages.stale_pages(ir.load_doc(translated), "masks") == []

    doc = ir.load_doc(translated)
    doc["pages"][0]["regions"][0][field] = True
    ir.save_doc(doc, translated)

    stale = stages.stale_pages(ir.load_doc(translated), "masks")
    assert stale == [doc["pages"][0]["id"]], stale


def test_a_page_mask_mode_changed_underneath_stales_the_cleaning(finished):
    """`clean` depends on the masks stage's revision, which covers a rebuild.
    This covers the page's own mask mode being changed WITHOUT one — the case
    where the cleaner reaches for the tier a solid patch must never reach."""
    assert stages.stale_pages(ir.load_doc(finished), "clean") == []

    doc = ir.load_doc(finished)
    doc["pages"][0]["free_lettering_mask"] = "solid"
    ir.save_doc(doc, finished)

    assert doc["pages"][0]["id"] in stages.stale_pages(
        ir.load_doc(finished), "clean")


def test_removing_every_region_leaves_no_edit_authority(translated):
    """A rebuild that leaves the previous run's files behind leaves authority
    behind with them: the union mask still said the cleaner could rewrite most
    of the page."""
    masks.build_document(translated)
    root = ir.doc_dir(translated)
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    folder = root / "masks" / page["id"]
    assert list(folder.glob("*.png")), "the fixture wrote no masks"

    page["regions"] = []
    ir.save_doc(doc, translated)
    report = masks.build_document(translated, pages=[page["id"]])

    assert report["retired"] > 0, report
    assert [child.name for child in sorted(folder.iterdir())] == ["union.png"]

    union = np.asarray(ir.load_image(root / "masks" / page["id"] / "union.png"))
    assert int((union > 0).sum()) == 0, "the union still authorises pixels"
    assert ir.load_doc(translated)["pages"][0]["mask_coverage"] == 0


def test_a_retired_regions_mask_file_is_swept(translated):
    masks.build_document(translated)
    root = ir.doc_dir(translated)
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    orphan = root / "masks" / page["id"] / "r999.png"
    orphan.write_bytes((root / page["regions"][0]["mask"]).read_bytes())

    masks.build_document(translated, pages=[page["id"]])

    assert not orphan.exists(), "a mask for a region that is gone survived"


def test_lettering_the_policy_keeps_is_not_given_cleaning_authority(translated):
    """A sound effect under `--sfx-policy keep` stays in the artwork by
    decision, and masking it put artwork inside the area the cleaner may
    rewrite and inside the preservation denominator."""
    doc = ir.load_doc(translated)
    doc["meta"]["sfx_policy"] = "keep"
    page = doc["pages"][0]
    page["regions"][0]["kind"] = "sfx"
    ir.save_doc(doc, translated)

    masks.build_document(translated, pages=[page["id"]])

    region = ir.load_doc(translated)["pages"][0]["regions"][0]
    assert region["mask"] is None and region["mask_box"] is None


def test_an_erase_region_is_masked_even_though_it_takes_no_persian(translated):
    """"Remove this and put nothing back" is a decision to touch the pixels."""
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    page["regions"][0].update({"kind": "sfx", "erase": True, "target_text": ""})
    doc["meta"]["sfx_policy"] = "keep"
    ir.save_doc(doc, translated)

    masks.build_document(translated, pages=[page["id"]])

    assert ir.load_doc(translated)["pages"][0]["regions"][0]["mask"]


def test_an_identical_rerun_keeps_identical_revisions_and_pixels(translated):
    masks.build_document(translated)
    doc = ir.load_doc(translated)
    root = ir.doc_dir(translated)
    before = ir.dumps(doc["stages"]["masks"])
    pixels = {path.name: path.read_bytes()
              for path in sorted((root / "masks" / doc["pages"][0]["id"]).iterdir())}

    masks.build_document(translated)

    after = ir.load_doc(translated)
    assert ir.dumps(after["stages"]["masks"]) == before
    assert {path.name: path.read_bytes()
            for path in sorted((root / "masks" / after["pages"][0]["id"]).iterdir())
            } == pixels


def test_a_font_with_the_same_name_but_different_bytes_is_a_different_render(
        tmp_path):
    """Two faces are routinely installed under one basename, and they set a
    balloon differently. Recording `font_path.name` gave both the same render
    identity."""
    first, second = tmp_path / "a" / "F.ttf", tmp_path / "b" / "F.ttf"
    for path, payload in ((first, b"one"), (second, b"two")):
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)

    assert typefont.font_identity(first) != typefont.font_identity(second)
    assert typefont.font_identity(first) == typefont.font_identity(first)
    assert typefont.font_identity(first).startswith("F.ttf:")
