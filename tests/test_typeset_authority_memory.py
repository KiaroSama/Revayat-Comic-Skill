"""Retained permission storage is bounded, without borrowing neighbor authority."""
import sys

import numpy as np
from PIL import Image

import pageir as ir
import typeset


def test_retained_authority_owns_only_its_small_patch(tmp_path):
    path = tmp_path / "comic.json"
    image = tmp_path / "pages" / "p0001.png"
    image.parent.mkdir()
    Image.new("RGB", (400, 600), "white").save(image)
    page = ir.new_page("p0001", 0, "pages/p0001.png", 400, 600, ir.sha256_file(image))
    region = ir.new_region("p0001r001", [30, 30, 100, 60], kind="sign")
    region.update(target_text="سلام", source_text="HELLO", mask_box=[30, 30, 100, 60])
    page["regions"] = [region]
    observed = []
    previous = sys.getprofile()

    def profile(frame, event, argument):
        if event == "return" and frame.f_code is typeset.typeset_page.__code__:
            for value in frame.f_locals["authority"].values():
                patch = value[2] if isinstance(value, tuple) else value
                observed.append((patch.nbytes, patch.base is None))

    sys.setprofile(profile)
    try:
        report = typeset.typeset_page(path, page, typeset.Shaper(force_fallback=True),
                                     typeset.find_font(), policy="keep", max_size=24,
                                     min_size=13, stylise=False)
    finally:
        sys.setprofile(previous)
    assert observed and sum(size for size, _ in observed) <= 100 * 60
    assert all(owns for _, owns in observed)
    assert report["placed"] == 1
    output = np.asarray(ir.load_image(tmp_path / page["final"]))
    original = np.asarray(ir.load_image(image))
    outside = np.ones((600, 400), bool)
    outside[30:90, 30:130] = False
    assert np.array_equal(output[outside], original[outside])
