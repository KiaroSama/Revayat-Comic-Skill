"""Exact rendering/state parity with the historical full-page authority strategy."""
from __future__ import annotations

import ast
import copy
import inspect
import sys
import textwrap

import numpy as np
import pytest
from PIL import Image, ImageDraw

import pageir as ir
import typeset


@pytest.fixture(scope="module")
def fullpage_renderer():
    # These two blocks are the exact pre-P018 strategy in 6d1a49d. Keep the
    # remaining function identical, so no copied renderer/fixture can drift.
    tree = ast.parse(inspect.getsource(typeset.typeset_page))
    function = tree.body[0]
    storage = next(node for node in function.body if isinstance(node, ast.For)
                   and any(isinstance(part, ast.Delete) for part in node.body))
    start = next(i for i, node in enumerate(storage.body)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "writable" for t in node.targets))
    assert isinstance(storage.body[-1], ast.Delete)
    storage.body[start:] = ast.parse(textwrap.dedent('''
        authority[region["id"]] = own
        writable = np.maximum(writable, own)
    ''')).body
    comparison = next(node for node in ast.walk(function) if isinstance(node, ast.If)
                      and any(isinstance(part, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == "entry"
                                      for t in part.targets) for part in node.body))
    start = next(i for i, node in enumerate(comparison.body)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "allowed" for t in node.targets))
    assert isinstance(comparison.body[-1], ast.Assign)
    assert comparison.body[-1].targets[0].id == "stray"
    comparison.body[start:] = ast.parse(textwrap.dedent('''
        allowed = authority.get(region["id"])
        if allowed is None:
            allowed = writable
        stray = int((changed & (allowed[y0:y1, x0:x1] == 0)).sum())
    ''')).body
    ast.fix_missing_locations(tree)
    namespace = dict(typeset.__dict__)
    exec(compile(tree, "<6d1a49d-fullpage-authority>", "exec"), namespace)
    return namespace["typeset_page"]


def chapter(root, scenario):
    root.mkdir()
    width, height = 360, 240
    image = Image.new("RGB", (width, height), (225, 225, 225))
    draw = ImageDraw.Draw(image)
    boxes = [[20, 20, 110, 70], [200, 20, 110, 70]]
    if scenario == "overlap":
        boxes[1] = [75, 45, 110, 70]
    if scenario == "many":
        boxes = [[15 + x * 115, 10 + y * 55, 100, 45]
                 for y in range(4) for x in range(3)]
    page = ir.new_page("p0001", 0, "page.png", width, height, "")
    for index, box in enumerate(boxes):
        x, y, w, h = box
        curved = scenario in {"ellipse", "dark", "corner"}
        dark = scenario == "dark"
        shape = [x, y, x + w - 1, y + h - 1]
        if curved:
            draw.ellipse(shape, fill="black" if dark else "white",
                         outline="white" if dark else "black", width=2)
        else:
            draw.rectangle(shape, fill="white")
        region = ir.new_region(f"p0001r{index + 1:03d}", box,
                               kind="speech" if curved else "sign")
        region.update(source_text="HELLO", target_text="سلام" if index == 0 else "نه",
                      mask_box=None if scenario == "empty" else box,
                      balloon=box if curved else None, polarity="dark" if dark else "light")
        page["regions"].append(region)
    ir.save_image(image, root / "page.png")
    page["sha256"] = ir.sha256_file(root / "page.png")
    union = Image.new("L", (width, height), 0)
    ImageDraw.Draw(union).rectangle([2, 2, 4, 4], fill=255)
    ir.save_image(union, root / "union.png")
    page["mask"] = "union.png"
    return page


def render(renderer, root, page, shaper, font, monkeypatch, scenario):
    observed = []
    original_fit = typeset.fit_region
    calls = 0

    def displaced(*args, **kwargs):
        nonlocal calls
        fitted = original_fit(*args, **kwargs)
        calls += 1
        if fitted and calls == 2 and scenario in {"neighbor", "offpage", "corner"}:
            for line in fitted["lines"]:
                line["x"], line["y"] = {"neighbor": (75, 55), "offpage": (-4, 55),
                                        "corner": (210, 28)}[scenario]
        return fitted

    def observe(frame, event, argument):
        if event == "return" and frame.f_code is renderer.__code__:
            for value in frame.f_locals["authority"].values():
                patch = value[2] if isinstance(value, tuple) else value
                observed.append((patch.nbytes, patch.base is None))

    previous = sys.getprofile()
    with monkeypatch.context() as context:
        context.setitem(renderer.__globals__, "fit_region", displaced)
        sys.setprofile(observe)
        try:
            report = renderer(root / "comic.json", page, shaper, font, policy="keep",
                              max_size=20, min_size=13, stylise=False)
        finally:
            sys.setprofile(previous)
    final = np.array(ir.load_image(root / page["final"]))
    writable = (root / page["writable"]).read_bytes()
    return report, final, writable, observed


@pytest.mark.parametrize("scenario", ["multi", "overlap", "ellipse", "dark", "empty",
                                      "neighbor", "offpage", "corner", "many"])
def test_tight_authority_preserves_fullpage_pixels_state_and_union(
        tmp_path, monkeypatch, fullpage_renderer, scenario):
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_page = chapter(old_root, scenario)
    new_page = chapter(new_root, scenario)
    assert old_page == new_page
    original = copy.deepcopy(new_page)
    shaper, font = typeset.Shaper(force_fallback=True), typeset.find_font()
    old = render(fullpage_renderer, old_root, old_page, shaper, font, monkeypatch, scenario)
    new = render(typeset.typeset_page, new_root, new_page, shaper, font, monkeypatch, scenario)
    assert old[0] == new[0]
    assert old_page == new_page
    assert np.array_equal(old[1], new[1])
    assert old[2] == new[2]
    source = np.asarray(ir.load_image(new_root / "page.png"))
    with Image.open(new_root / new_page["writable"]) as mask:
        writable = np.array(mask) > 0
    assert np.array_equal(new[1][~writable], source[~writable])
    assert ir.sha256_file(new_root / "page.png") == original["sha256"]
    assert new[3] and all(owned for _, owned in new[3])
    assert sum(size for size, _ in new[3]) < sum(size for size, _ in old[3])
    if scenario in {"multi", "overlap", "ellipse", "dark", "many"}:
        assert new[0]["placed"] == len(new_page["regions"])
    if scenario in {"neighbor", "corner", "empty"}:
        assert new[0]["overflow"]
        assert any(r["typeset"].get("outside_authorised", 0) > 0 for r in new_page["regions"])
    if scenario == "offpage":
        assert new_page["regions"][1]["typeset"].get("clipped_by_page") is True
    if scenario in {"neighbor", "offpage", "corner"}:
        assert new_page["regions"][0]["typeset"]["status"] == "ok"
        assert new_page["regions"][1]["typeset"]["status"] == "overflow"
    if scenario == "many":
        assert len(new[3]) == 12
        assert sum(size for size, _ in new[3]) == 12 * 100 * 45
        assert sum(size for size, _ in old[3]) == 12 * 360 * 240
