"""Regression tests for Feature 015 visual, balloon, outline, overlap, and dimension fixes."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import clean  # noqa: E402
import masks as mask_tools  # noqa: E402
import pageir as ir  # noqa: E402
import qachecks  # noqa: E402
import typefont  # noqa: E402
import typeset  # noqa: E402
import worksheet  # noqa: E402


def _make_oval_balloon_page(size=(400, 400), *, hair_on_left=False):
    img = Image.new("RGB", size, (180, 180, 180))  # grey screentone background
    draw = ImageDraw.Draw(img)
    # Draw crisp oval speech balloon
    draw.ellipse((80, 80, 320, 260), fill=(255, 255, 255), outline=(0, 0, 0), width=4)
    if hair_on_left:
        # Dark character hair encroaching from left border right up to balloon
        draw.polygon([(0, 120), (115, 145), (105, 240), (0, 280)], fill=(10, 10, 10))
    # Draw two groups of fake dark English glyphs inside balloon
    for x in range(125, 200, 14):
        draw.rectangle((x, 145, x + 8, 175), fill=(15, 15, 15))
    for x in range(215, 280, 14):
        draw.rectangle((x, 145, x + 8, 175), fill=(15, 15, 15))
    return np.asarray(img)


def test_region_mask_without_balloon_never_erases_perimeter_hair_or_outline() -> None:
    """Defect class 1 (Images 1, 2, 4, 7): balloon=None must not mask hair/border."""
    rgb = _make_oval_balloon_page(hair_on_left=True)
    # Region box slightly clips into the black hair on the left (x=95..210)
    region = {
        "id": "p0001r001",
        "kind": "speech",
        "bbox": [95, 135, 115, 55],
        "balloon": None,
        "polarity": "light",
    }
    mask, box = mask_tools.region_mask(rgb, region, (400, 400))
    x, y, w, h = box
    # Left border pixels that belong to hair must NOT be masked white!
    hair_region_in_mask = mask[:, :8]
    assert int((hair_region_in_mask > 0).sum()) == 0


def test_full_balloon_cleaning_and_surviving_ink_catch_half_cleaned_balloon() -> None:
    """Defect class 2 (Image 5): leftover English outside narrow bbox must be cleaned & caught."""
    orig = _make_oval_balloon_page()
    balloon = [76, 76, 248, 188]
    # Narrow bbox only covers left half of the letters (x=120..205), missing x=215..280
    region = {
        "id": "p0001r001",
        "kind": "speech",
        "bbox": [120, 140, 85, 42],
        "balloon": balloon,
        "polarity": "light",
    }
    # 1. Single-region full-balloon mask must cover BOTH left and right lettering groups!
    mask, box = mask_tools.region_mask(orig, region, (400, 400), full_balloon=True)
    bx, by, bw, bh = box
    right_glyph_x = 230 - bx
    right_glyph_y = 160 - by
    assert 0 <= right_glyph_x < bw and 0 <= right_glyph_y < bh
    assert mask[right_glyph_y, right_glyph_x] > 0

    # 2. If cleaning only erased the narrow left box, full_balloon_surviving_ink MUST flag it!
    cleaned = orig.copy()
    cleaned[140:182, 120:205] = 255
    region["mask_box"] = [120, 140, 85, 42]
    survived = qachecks.full_balloon_surviving_ink(
        orig, cleaned, region, [region], np.full((42, 85), 255, np.uint8), (400, 400), np
    )
    assert survived > 0.30


def test_rendered_text_overlaps_detects_colliding_regions() -> None:
    """Defect class 3 (Image 4): colliding rendered Persian texts fail QA."""
    cleaned = np.full((300, 300, 3), 255, np.uint8)
    final = cleaned.copy()
    # Paint dark text in overlapping region [100..160, 100..140]
    final[110:130, 115:145] = 20
    page = {
        "width": 300,
        "height": 300,
        "regions": [
            {"id": "p0001r001", "typeset": {"status": "ok", "ink_box": [80, 100, 70, 40]}},
            {"id": "p0001r002", "typeset": {"status": "ok", "ink_box": [120, 105, 70, 40]}},
        ],
    }
    overlaps = qachecks.rendered_text_overlaps(page, cleaned, final, np)
    assert len(overlaps) == 1
    assert overlaps[0][0] == "p0001r001"
    assert overlaps[0][1] == "p0001r002"
    assert overlaps[0][2] > 0


def test_text_crosses_outline_detects_spill_onto_screentone_and_border() -> None:
    """Defect class 4 (Images 6, 7, 8): Persian ink spilling outside balloon border fails QA."""
    orig = _make_oval_balloon_page()
    cleaned = orig.copy()
    cleaned[135:185, 115:290] = 255
    final = cleaned.copy()
    # Paint Persian ink spilling across the right balloon outline onto grey screentone
    final[150:175, 290:355] = 15
    page = {
        "width": 400,
        "height": 400,
        "regions": [
            {
                "id": "p0001r001",
                "bbox": [120, 140, 160, 40],
                "balloon": [76, 76, 248, 188],
                "polarity": "light",
                "typeset": {"status": "ok", "ink_box": [130, 145, 230, 35]},
            }
        ],
    }
    offenders = qachecks.text_crosses_outline(page, orig, cleaned, final, np)
    assert len(offenders) == 1
    assert offenders[0][0] == "p0001r001"
    assert offenders[0][1] > 100


def test_dimension_preservation_and_reconciliation(tmp_path: Path) -> None:
    """Item 7: exact W x H dimension enforcement & aspect-safe external edit reconciliation."""
    orig_path = tmp_path / "orig.png"
    clean_bad = tmp_path / "clean_bad.png"
    final_ok = tmp_path / "final_ok.png"

    Image.new("RGB", (1050, 1500), (255, 255, 255)).save(orig_path)
    Image.new("RGB", (1024, 1536), (255, 255, 255)).save(clean_bad)
    Image.new("RGB", (1050, 1500), (255, 255, 255)).save(final_ok)

    mismatches = qachecks.check_page_dimensions(orig_path, clean_bad, final_ok)
    assert len(mismatches) == 1
    assert mismatches[0][0] == "clean"

    # Reconciling 1024x1536 -> 1050x1500 (aspect drift ~4.8% < 8%) succeeds cleanly.
    reconciled = qachecks.reconcile_image_dimensions(Image.open(clean_bad), (1050, 1500))
    assert (reconciled.width, reconciled.height) == (1050, 1500)

    # Reconciling wildly mismatched square 1024x1024 -> 1050x1500 (drift ~42%) refuses!
    square = Image.new("RGB", (1024, 1024), (255, 255, 255))
    with pytest.raises(ValueError, match="aspect ratio"):
        qachecks.reconcile_image_dimensions(square, (1050, 1500))


def test_bundled_vazir_is_default_with_sibling_weights():
    fonts = SCRIPTS.parent / "assets" / "fonts"
    assert typefont.find_font() == fonts / "Vazir-Regular.ttf"
    assert typefont.find_font_variant(typefont.find_font(), bold=True) == fonts / "Vazir-Bold.ttf"
    assert typefont.find_font_variant(typefont.find_font(), weight="medium") == fonts / "Vazir-Medium.ttf"


def test_styles_round_trip_in_worksheet(translated):
    doc = ir.load_doc(translated)
    page = doc["pages"][0]
    region = page["regions"][0]
    region["style"] = "bold-italic, outline"
    sheet = worksheet.page_worksheet(doc, page, ir.page_fingerprint(page))
    parsed = worksheet.parse_worksheet(sheet)
    assert parsed[region["id"]]["style"] == "bold-italic, outline"
    typed = worksheet.parse_worksheet(f"@@ {region['id']}\nstyle: BOLD, italic , SHADOW\n")
    assert typed[region["id"]]["style"] == "bold-italic, shadow"
    assert worksheet.invalid_fields({"style": "loud"})


def test_outline_qa_checks_balloon_without_a_detected_box():
    cleaned = _make_oval_balloon_page().copy()
    cleaned[135:185, 115:290] = 255
    final = cleaned.copy()
    final[160:170, 290:335] = 15
    region = {"id": "oval", "kind": "speech", "bbox": [120, 140, 160, 40],
              "balloon": None, "typeset": {"status": "ok", "ink_box": [290, 160, 45, 10]}}
    page = {"width": 400, "height": 400, "regions": [region]}
    offenders = qachecks.text_crosses_outline(page, cleaned, cleaned, final, np)
    assert offenders and offenders[0][0] == "oval"
    unbounded = np.full_like(cleaned, 255)
    assert not qachecks.text_crosses_outline(page, unbounded, unbounded, final, np)


def test_styled_balloon_without_box_centers_ink_on_enclosure(tmp_path):
    page = {"id": "p0001", "width": 400, "height": 400, "image": "page.png", "regions": []}
    rgb = _make_oval_balloon_page().copy()
    rgb[135:185, 115:290] = 255
    Image.fromarray(rgb).save(tmp_path / page["image"])
    region = {"id": "oval", "kind": "speech", "bbox": [100, 140, 100, 54],
              "balloon": None, "mask_box": [100, 140, 100, 54],
              "target_text": "سلام", "style": "bold-italic, outline, shadow"}
    page["regions"].append(region)
    typeset.typeset_page(tmp_path / "comic.json", page, typefont.Shaper(),
                         typefont.find_font(), policy="translate", max_size=40, min_size=13)
    record = region["typeset"]
    assert record["status"] == "ok"
    assert record["font"] == "Vazir-Bold.ttf"
    x, _, w, _ = record["ink_box"]
    assert abs(x + w / 2 - 200) <= 4
    result = np.asarray(Image.open(tmp_path / page["final"]))
    safe = qachecks.local_white_enclosure(rgb, region["bbox"], "light", (400, 400))
    assert not np.any(np.any(result != rgb, axis=2) & (safe == 0))


def test_short_shout_uses_page_size_cap(tmp_path):
    page = {"id": "p0001", "width": 600, "height": 400, "image": "page.png", "regions": []}
    Image.new("RGB", (600, 400), "white").save(tmp_path / page["image"])
    for i, (box, text) in enumerate([
        ([10, 10, 140, 50], "بریم سر کار خودمون"),
        ([180, 10, 140, 50], "امروز خیلی کار داریم"),
        ([170, 180, 240, 135], "برو!")
    ]):
        page["regions"].append({"id": str(i), "kind": "speech", "bbox": box,
                                "mask_box": box, "target_text": text})
    typeset.typeset_page(tmp_path / "comic.json", page, typefont.Shaper(),
                         typefont.find_font(), policy="translate", max_size=60, min_size=13)
    a, b, shout = [r["typeset"] for r in page["regions"]]
    assert all(r["status"] == "ok" for r in (a, b, shout))
    assert shout["size"] <= round((a["size"] + b["size"]) / 2 * 1.32)


def test_external_flat_patch_matches_tint_and_feathers_inside_mask(tmp_path):
    original = np.full((100, 120, 3), [90, 45, 125], np.uint8)
    patch = np.full_like(original, [106, 70, 151])
    patch[20:80, 20:100] += 24
    patch[37:63, 44:66] = [20, 30, 40]
    Image.fromarray(original).save(tmp_path / "source.png")
    Image.new("L", (80, 60), 255).save(tmp_path / "mask.png")
    external = tmp_path / "external"
    external.mkdir()
    Image.fromarray(patch).save(external / "p0001.png")
    region = {"id": "caption", "kind": "other", "bbox": [20, 20, 80, 60],
              "mask": "mask.png", "mask_box": [20, 20, 80, 60], "target_text": "سلام"}
    page = {"id": "p0001", "width": 120, "height": 100, "image": "source.png", "regions": [region]}
    clean.clean_page(tmp_path / "comic.json", page, policy="translate", external=external)
    result = np.asarray(Image.open(tmp_path / page["clean"]))
    outside = np.ones(original.shape[:2], bool)
    outside[20:80, 20:100] = False
    assert np.array_equal(result[outside], original[outside])
    assert np.array_equal(result[45, 20], original[45, 20])
    assert tuple(result[45, 31]) == (114, 69, 149)
    assert tuple(result[45, 52]) == (4, 5, 14)


def test_connected_double_balloon_preserves_lobe_order_without_swapping(tmp_path):
    """A small upper lobe joined to a wider lower lobe must never swap text."""
    page_img = Image.new("RGB", (400, 460), (20, 20, 20))
    draw = ImageDraw.Draw(page_img)
    # Figure-8 connected double balloon: narrow upper lobe joined to wide lower lobe.
    draw.ellipse([195, 50, 315, 190], fill="white", outline="black", width=4)
    draw.ellipse([90, 175, 290, 395], fill="white", outline="black", width=4)
    # Open the connecting neck between the two lobes.
    draw.ellipse([198, 150, 268, 225], fill="white")
    page_img.save(tmp_path / "page.png")

    upper = {
        "id": "r1", "kind": "speech",
        "bbox": [215, 85, 80, 65], "mask_box": [215, 85, 80, 65],
        "target_text": "وگرنه…",
    }
    lower = {
        "id": "r2", "kind": "speech",
        "bbox": [125, 225, 130, 115], "mask_box": [125, 225, 130, 115],
        "target_text": "…همه‌مون قبل از شروع نبرد می‌میریم.",
    }
    page = {"id": "p0001", "width": 400, "height": 460, "image": "page.png",
            "regions": [upper, lower]}
    typeset.typeset_page(tmp_path / "comic.json", page, typefont.Shaper(),
                         typefont.find_font(), policy="translate", max_size=36, min_size=12)
    u_rec, l_rec = upper["typeset"], lower["typeset"]
    assert u_rec["status"] == "ok" and l_rec["status"] == "ok"
    _, uy, _, uh = u_rec["ink_box"]
    _, ly, _, lh = l_rec["ink_box"]
    # Upper lobe stays strictly above lower lobe (no lobe swap, no overlap).
    assert uy + uh < ly
    assert uy < 190
    assert ly >= 175


def test_full_balloon_clean_keeps_thin_gray_outline(tmp_path):
    image = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((45, 40, 194, 139), outline=(228,) * 3, width=2)
    draw.ellipse((46, 41, 193, 138), outline=(180,) * 3)
    outline = np.asarray(image).copy()[:, :, 0] < 255
    draw.rectangle((65, 82, 87, 96), fill=(48,) * 3)
    source = np.asarray(image)
    image.save(tmp_path / "page.png")
    region = ir.new_region("r1", [65, 82, 23, 15], kind="speech")
    region.update(balloon=[40, 35, 160, 110], target_text="سلام")
    page = ir.new_page("p0001", 0, "page.png", *image.size, ir.sha256_file(tmp_path / "page.png"))
    page["regions"] = [region]
    doc = ir.new_doc()
    doc["pages"] = [page]
    doc_path = tmp_path / "comic.json"
    ir.save_doc(doc, doc_path)

    mask_tools.build_document(doc_path, grow=0.12)
    page = ir.load_doc(doc_path)["pages"][0]
    mask = mask_tools.load_mask(tmp_path / page["mask"])
    clean.clean_page(doc_path, page, policy="translate")
    cleaned = np.asarray(Image.open(tmp_path / page["clean"]))
    assert not mask[outline].any()
    assert np.array_equal(cleaned[outline], source[outline])
    assert np.all(cleaned[84:95, 67:86] >= 250)


@pytest.mark.parametrize("top", [55, -5])
def test_panel_clipped_balloon_recovers_curved_paper(tmp_path, top):
    image = Image.new("RGB", (400, 290), (160,) * 3)
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, top, 435, 165), outline=(185,) * 3, fill="white", width=2)
    rgb = np.asarray(image)
    image.save(tmp_path / "page.png")
    region = {"id": "r1", "kind": "speech", "panel": "panel", "bbox": [227, 70, 84, 53],
              "mask_box": [227, 70, 84, 53], "target_text": "بیا بریم!"}
    panel = [20, 20, 300, 250]
    page = {"id": "p0001", "width": 400, "height": 290, "image": "page.png", "regions": [region],
            "panels": [{"id": "panel", "bbox": panel}]}
    safe = qachecks.balloon_text_interior(rgb, region, image.size, panel=panel)
    assert safe is not None
    assert safe[:, 319].any() and not safe[:, 320:].any()
    if top < 0:
        assert safe[20, :].any() and not safe[:20, :].any()
    assert not safe[rgb[:, :, 0] != 255].any()
    typeset.typeset_page(tmp_path / "comic.json", page, typefont.Shaper(),
                         typefont.find_font(), policy="translate", max_size=40, min_size=13)
    result = np.asarray(Image.open(tmp_path / page["final"]))
    changed = (result != rgb).any(axis=2)
    assert region["typeset"]["status"] == "ok" and changed.any()
    assert not changed[safe == 0].any()


@pytest.mark.parametrize("obstacle", ["hair", "balloon", "transformed_hair"])
def test_free_light_lettering_does_not_touch_neighbor(tmp_path, monkeypatch, obstacle):
    rgb = np.full((140, 240, 3), 255, np.uint8)
    region = {"id": "r1", "kind": "sign", "bbox": [30, 31, 180, 74],
              "mask_box": [30, 31, 180, 74], "target_text": "چه دوره!"}
    page = {"id": "p0001", "width": 240, "height": 140, "image": "page.png", "regions": [region]}
    if obstacle in {"hair", "transformed_hair"}:
        rgb[:, 111:127] = 40
        left, right = 108, 130
    else:
        page["regions"].append({"id": "r2", "kind": "speech",
                                "bbox": [112, 110, 12, 10], "balloon": [97, 25, 43, 100]})
        left, right = 94, 143
    if obstacle == "transformed_hair":
        region["lettering"] = {"verdict": "rotated"}

        def displaced(canvas, *_args, **_kwargs):
            canvas.putpixel((120, 65), (10, 10, 10))
            return {"box": [120, 65, 121, 66], "style": "rotated"}

        monkeypatch.setattr(typeset.lettering, "render", displaced)
    Image.fromarray(rgb).save(tmp_path / "page.png")
    typeset.typeset_page(tmp_path / "comic.json", page, typefont.Shaper(),
                         typefont.find_font(), policy="translate", max_size=40, min_size=13)
    result = np.asarray(Image.open(tmp_path / page["final"]))
    changed = (result != rgb).any(axis=2)
    assert region["typeset"]["status"] == "ok" and changed.any()
    assert not changed[:, left:right].any()


def test_unicode_paragraph_separators_render_like_newlines(tmp_path):
    shaper = typefont.Shaper()
    rendered = []
    for name, text in [("unicode", "سلام\u2029بیا\u0085بریم\u2028حالا"),
                       ("lf", "سلام\nبیا\nبریم\nحالا")]:
        box = [20, 20, 260, 180]
        region = {"id": "r1", "kind": "speech", "bbox": box, "mask_box": box, "target_text": text}
        page_id = f"p_{name}"
        page = {"id": page_id, "width": 300, "height": 220, "image": f"{name}.png", "regions": [region]}
        Image.new("RGB", (300, 220), "white").save(tmp_path / page["image"])
        typeset.typeset_page(tmp_path / "comic.json", page, shaper,
                             typefont.find_font(), policy="translate", max_size=36, min_size=13)
        assert region["typeset"]["status"] == "ok"
        assert region["typeset"]["lines"] == 4
        rendered.append(np.asarray(Image.open(tmp_path / page["final"])))
    assert np.array_equal(*rendered)

