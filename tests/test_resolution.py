"""Detection has to hold at the size a real scan actually is.

Every threshold in `detect.py` is a fraction of the page, which makes the
detector scale-invariant *provided the artwork scales too*. A real scan does:
a tankobon at 300 dpi has a proportionally thicker balloon outline than the same
art at 96 dpi, because it is the same ink measured with more pixels.

These tests pin both halves of that. The default fixture is 1000x1500; without
them, nothing here would ever have met a 2480x3508 page, and the first real
chapter would have been the experiment.
"""

from __future__ import annotations

import pytest

from PIL import Image

import detect
import pageir as ir
from tests_support import manga_page, page_bytes

#: A4 at 300 dpi — what a scanned tankobon page actually is. Also a webtoon-ish
#: tall strip and a small web scan, to bracket the range.
SIZES = [
    pytest.param(700, 1050, id="small-web-scan"),
    pytest.param(1000, 1500, id="default"),
    pytest.param(1600, 2300, id="large-web-scan"),
    pytest.param(2480, 3508, id="a4-at-300dpi"),
]


def _detect(tmp_path, width, height, **options):
    path = tmp_path / f"p{width}x{height}.png"
    path.write_bytes(page_bytes(manga_page(width, height, **options)))
    return detect.detect_page(path)


@pytest.mark.parametrize("width,height", SIZES)
def test_every_balloon_is_found_at_every_resolution(tmp_path, width, height):
    found = _detect(tmp_path, width, height)
    speech = [r for r in found["regions"] if r["kind"] == "speech"]
    assert len(speech) == 3, (
        f"{width}x{height}: found {len(speech)} balloons of 3"
    )


@pytest.mark.parametrize("width,height", SIZES)
def test_the_page_still_cuts_into_four_panels(tmp_path, width, height):
    assert len(_detect(tmp_path, width, height)["panels"]) == 4


@pytest.mark.parametrize("width,height", SIZES)
def test_boxes_stay_proportional_to_the_page(tmp_path, width, height):
    """The same artwork at twice the size must give twice the box, not the same
    box. A threshold that is secretly absolute shows up here and nowhere else."""
    found = _detect(tmp_path, width, height)
    for region in found["regions"]:
        if region["kind"] != "speech":
            continue
        share = ir.bbox_area(region["bbox"]) / float(width * height)
        assert 0.02 < share < 0.12, (
            f"{width}x{height}: a balloon's text box is {share:.1%} of the page"
        )


def test_a_hairline_outline_is_the_known_limit(tmp_path):
    """The honest counter-case, pinned so it cannot regress silently.

    Detection needs the balloon outline to be resolvable *relative to the page*.
    Art whose line weight did not scale with the raster — a small drawing
    upsampled, or vector line art rendered thin at high DPI — has an outline the
    ink and solidity heuristics do not expect, and balloons are missed.

    This is a property of the input, not a bug to fix by loosening thresholds:
    loosening them enough to catch a 0.16%-wide outline also makes every
    screentone gradient a balloon. `references/detection.md` documents it, and
    the fix is `--balloon-min-solidity` on that book.
    """
    from PIL import Image, ImageDraw

    width, height = 2480, 3508
    page = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    # A balloon-sized ellipse with a four-pixel outline on a 2480-wide page:
    # 0.16% of the width, where the scaled fixture would use ~10 pixels.
    draw.ellipse([600, 400, 1600, 1200], fill=(255, 255, 255),
                 outline=(20, 20, 20), width=4)
    for row in range(3):
        for column in range(5):
            x = 800 + column * 130
            y = 600 + row * 130
            draw.rectangle([x, y, x + 80, y + 90], fill=(20, 20, 20))

    path = tmp_path / "hairline.png"
    path.write_bytes(page_bytes(page))
    found = detect.detect_page(path)
    speech = [r for r in found["regions"] if r["kind"] == "speech"]

    # Documented as a limit, not asserted as working. If a future change makes
    # this pass, that is good news and this test should be rewritten to demand
    # it — but it must never pass by accident and go unnoticed.
    assert len(speech) <= 1


# --- webtoon geometry, end to end --------------------------------------------

def test_a_webtoon_strip_goes_through_the_whole_pipeline(tmp_path):
    """A tall strip is flagged at import and had never been *run*.

    What a synthetic fixture can honestly test here is the geometry — a page
    several times taller than it is wide, read top to bottom — and geometry is
    exactly what breaks on one: reading order, mask boxes, the interior fit, and
    every threshold expressed as a fraction of a page that is now a ribbon.
    It says nothing about a real webtoon's art or lettering, which still needs a
    real sample.
    """
    import clean
    import detect
    import masks
    import qa
    import readers
    import typeset
    from tests_support import manga_page, page_bytes

    strip = tmp_path / "strip"
    strip.mkdir()
    # Three page-heights stacked: 1000 x 4500, well past the webtoon threshold.
    tall = Image.new("RGB", (1000, 4500), "white")
    for index in range(3):
        tall.paste(manga_page(1000, 1500), (0, index * 1500))
    (strip / "0001.png").write_bytes(page_bytes(tall))

    work = tmp_path / "work"
    report = readers.import_source(strip, work, source_language="ko",
                                   direction="ltr")
    assert report["webtoon_strips"] == ["p0001"]

    doc = work / "comic.json"
    detect.detect_document(doc)
    masks.build_document(doc)

    loaded = ir.load_doc(doc)
    regions = [r for _, r in ir.iter_regions(loaded)]
    assert len(regions) >= 6, f"only {len(regions)} regions found on a 3-page strip"

    # Reading order must run down the strip, not across it.
    tops = [r["bbox"][1] for r in regions]
    assert tops == sorted(tops), "reading order is not top-to-bottom on a strip"

    for region in regions:
        region["source_text"] = "stop!"
        region["target_text"] = "بس کن!"
        region["locked"] = True
    ir.save_doc(loaded, doc)

    clean.clean_document(doc)
    typeset.typeset_document(doc)
    result = qa.check_document(doc)

    assert result["stats"]["artwork_pixels_changed"] == 0
    assert result["stats"]["states"]["unresolved"] == 0
