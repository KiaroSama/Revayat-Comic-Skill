"""A region without an assigned lobe cannot reuse the complete balloon."""

import numpy as np
import pytest
from PIL import Image, ImageDraw

import typefit
import typefont
import typeset


@pytest.mark.parametrize("patches", [False, True])
def test_coincident_regions_do_not_keep_overlapping_authority(patches):
    mask = np.full((20, 20), 255, dtype=np.uint8)
    authority = {rid: (0, 0, mask.copy()) if patches else mask.copy() for rid in ("a", "b")}
    regions = [{"id": rid, "bbox": [4, 4, 12, 12]} for rid in ("a", "b")]

    typefit.partition_shared_interiors(authority, {"a", "b"}, regions, (20, 20), np)

    first = authority["a"][2] if patches else authority["a"]
    second = authority["b"][2] if patches else authority["b"]
    assert np.count_nonzero(first) == 400
    assert np.count_nonzero(second) == 0


def test_region_without_a_partition_is_refused_instead_of_repositioned(tmp_path):
    image = Image.new("RGB", (400, 400), (50, 50, 50))
    ImageDraw.Draw(image).ellipse((60, 40, 340, 360), fill="white", outline="black", width=4)
    image.save(tmp_path / "page.png")
    regions = [
        {
            "id": rid, "kind": "speech", "bbox": [140, 140, 120, 80],
            "mask_box": [140, 140, 120, 80], "balloon": [60, 40, 281, 321],
            "target_text": text,
        }
        for rid, text in (("a", "سلام"), ("b", "خوبی؟"))
    ]
    page = {"id": "p0001", "width": 400, "height": 400, "image": "page.png", "regions": regions}

    result = typeset.typeset_page(
        tmp_path / "comic.json", page, typefont.Shaper(), typefont.find_font(),
        policy="translate", max_size=36, min_size=12,
    )

    assert result["placed"] == 1
    assert result["overflow"] == ["b"]
    assert regions[0]["typeset"]["status"] == "ok"
    assert regions[1]["typeset"]["status"] == "overflow"
