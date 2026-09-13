"""Draw a comic page for each case in `cases.json`.

Half the difficult cases are only difficult when you can see the drawing — who
is speaking, who they are speaking to, what the panel shows — so a set of
sentence pairs is not a substitute for pages. These pages are generated, which
makes them rights-clean by construction and also means they are not scans:
no screentone, no noise floor, no letterer's hand. What they can carry is the
*structure* — two speakers, a balloon that continues into the next one, an
effect drawn across a panel — and that is what the taxonomy in `README.md`
mostly turns on.

    python evaluation/build_pages.py --out evaluation/pages

Real pages, when somebody has the right to share them, go in the same folder
under their own names and are listed in `cases.json` with a `page` field.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

WIDTH, HEIGHT = 1000, 1500
INK = (20, 20, 20)
PAPER = (248, 246, 240)


def _panel(draw, box):
    draw.rectangle(box, outline=INK, width=4, fill=(236, 233, 226))


def _balloon(draw, centre, size, *, tail=None):
    cx, cy = centre
    half_w, half_h = size[0] // 2, size[1] // 2
    draw.ellipse([cx - half_w, cy - half_h, cx + half_w, cy + half_h],
                 outline=INK, width=3, fill=(255, 255, 255))
    if tail:
        draw.polygon([(cx, cy + half_h - 4), (cx + 18, cy + half_h - 10),
                      tail], fill=(255, 255, 255), outline=INK)


def _figure(draw, box, *, facing="right"):
    """A person, at the level of detail this needs: a head and shoulders, and
    which way they are turned. Who is speaking to whom is the point."""
    x0, y0, x1, y1 = box
    head = (x1 - x0) // 3
    cx = (x0 + x1) // 2
    draw.ellipse([cx - head, y0, cx + head, y0 + 2 * head],
                 outline=INK, width=3, fill=(255, 255, 255))
    draw.polygon([(x0, y1), (x1, y1), (cx + head, y0 + 2 * head),
                  (cx - head, y0 + 2 * head)], outline=INK, width=3,
                 fill=(255, 255, 255))
    eye = cx + (head // 2 if facing == "right" else -head // 2)
    draw.ellipse([eye - 4, y0 + head - 4, eye + 4, y0 + head + 4], fill=INK)


def draw_case(case: dict):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    _panel(draw, [40, 40, WIDTH - 40, 640])
    _panel(draw, [40, 680, WIDTH - 40, HEIGHT - 40])

    _figure(draw, [140, 300, 340, 620], facing="right")
    _figure(draw, [WIDTH - 360, 320, WIDTH - 160, 620], facing="left")

    width = int(WIDTH * case["balloon"][0])
    height = int(HEIGHT * case["balloon"][1])
    _balloon(draw, (WIDTH // 2, 180), (width, height), tail=(260, 320))

    # A continuation gets the second balloon its sentence runs into, in the
    # panel below — which is the whole shape of that difficulty.
    if case.get("continues_into") or case.get("continues_from"):
        _balloon(draw, (WIDTH // 2, 820), (width, height),
                 tail=(WIDTH - 340, 960))
    return image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(HERE / "pages"))
    parser.add_argument("--cases", default=str(HERE / "cases.json"))
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    for case in cases:
        draw_case(case).save(out / f"{case['id']}.png")
    print(f"{len(cases)} page(s) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
