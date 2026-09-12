"""One box, marked for erasure on every page of a chapter.

**Read `references/watermarks.md` before using this.** Removing a mark from your
own pages, from material you licensed, or from a scan whose group told you to is
ordinary work. Stripping another group's credit or a publisher's mark off
someone else's book, to pass it on, is not — and this project's own README says
the artwork is usually someone else's. The tool cannot tell the two apart; you
can, and the choice is yours to make and to own.

**What this is, technically.** Nothing new. A watermark here is an ordinary
region carrying `erase: True`, which means *remove this and put nothing back* —
the fifth terminal state, beside `translated` and `kept_by_policy`. It is masked
by `mask`, cleaned by `clean` through the same tier ladder every balloon uses,
skipped by `typeset` because there is no Persian to set, and held to the same
`artwork_pixels_changed: 0` proof by `qa`. No pixel outside the box you give
can move, and that is arithmetic rather than a promise.

**When to use this command instead of the worksheet.** Only for a mark that sits
in the *same place on every page* — a corner stamp on all two hundred. Anything
that moves from page to page belongs in the worksheet, where the reading model
that is already looking at the page marks it with `erase: yes`. That path needs
no command at all and is the one this project is built around.

    revayat-comic watermark --doc work/comic.json --box "12 1840 300 44"
    revayat-comic mask  --doc work/comic.json     # the new boxes need masks
    revayat-comic clean --doc work/comic.json

Re-running with a corrected box **moves** the existing one rather than adding a
second: the boxes are identified by `--label`, so a wrong box on two hundred
pages is fixed by running the command again, not by unpicking it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import pageir as ir

#: `x y w h`, in the page's own pixels — the same numbers a reader reads off
#: `overview.png`. Commas are accepted because people type them.
BOX = re.compile(r"^\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)\s*$")

#: Smallest box worth accepting. Below this a typo — a dropped digit — would
#: silently mark a few pixels and look like it worked.
MIN_SIDE = 4

#: Largest share of a page one erase box may cover. A watermark is a mark on a
#: page; a box over most of the page is a mistyped coordinate or an attempt to
#: erase the artwork itself, and the inpainter would invent a whole panel.
MAX_AREA_SHARE = 0.25


def parse_box(text: str) -> list[int]:
    match = BOX.match(text or "")
    if not match:
        raise ValueError(
            f"--box wants four numbers, `x y w h`, in the page's own pixels "
            f"(read them off overview.png). Got: {text!r}"
        )
    box = [int(value) for value in match.groups()]
    if box[2] < MIN_SIDE or box[3] < MIN_SIDE:
        raise ValueError(
            f"--box is {box[2]}x{box[3]}, which is too small to be a mark. "
            f"Check for a dropped digit."
        )
    return box


def mark_document(
    doc_path: str | Path,
    box: list[int],
    *,
    label: str = "watermark",
    kind: str = "sign",
    pages: list[str] | None = None,
) -> dict[str, Any]:
    """Put one erase region at `box` on every page, or on the named ones."""
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    if kind not in ir.REGION_KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of "
                         f"{', '.join(ir.REGION_KINDS)}")

    slug = f"wm-{label}"
    marked: list[dict[str, Any]] = []
    moved: list[str] = []
    refused: list[str] = []

    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        width, height = page["width"], page["height"]
        clamped = ir.clamp_bbox(box, width, height)
        if clamped[2] < MIN_SIDE or clamped[3] < MIN_SIDE:
            # The box is off this page entirely. Pages in one chapter are not
            # always the same size — a double spread, a colour insert — and
            # marking a sliver at the edge of one would be worse than saying so.
            refused.append(f"{page['id']}: the box falls outside "
                           f"{width}x{height}")
            continue
        share = (clamped[2] * clamped[3]) / float(max(1, width * height))
        if share > MAX_AREA_SHARE:
            refused.append(f"{page['id']}: the box covers "
                           f"{share:.0%} of the page")
            continue

        existing = next((r for r in page.get("regions", [])
                         if r.get("added_as") == slug), None)
        if existing is not None:
            if existing["bbox"] != clamped:
                existing["bbox"] = clamped
                existing["balloon"] = None   # `mask` re-derives it from the box
                existing["mask"] = None
                moved.append(existing["id"])
            region = existing
        else:
            region = ir.new_region(
                _next_region_id(page), clamped, kind=kind,
                orientation="horizontal" if clamped[2] >= clamped[3]
                else "vertical",
                # `operator`, not `detect`: this box came from a person naming
                # it, so a later `detect` run must not treat it as its own guess
                # and renumber it away.
                detector="operator", confidence=1.0,
            )
            region["balloon"] = None
            region["added_as"] = slug
            region["polarity"] = "light"
            page.setdefault("regions", []).append(region)

        region["erase"] = True
        region["locked"] = True
        region["source_text"] = ""
        region["target_text"] = ""
        region["typeset"] = {}
        region.pop("keep", None)
        region.pop("dropped", None)
        marked.append({"page": page["id"], "region": region["id"]})

    ir.stamp_stage(doc, "watermark", {"label": label, "box": box,
                                      "pages": len(marked)})
    ir.save_doc(doc, doc_path)

    return {
        "document": str(doc_path),
        "label": label,
        "box": box,
        "marked": marked,
        "moved": moved,
        "refused": refused,
        "next": "Run `mask` so the new boxes get masks, then `clean`. `qa` "
                "still proves nothing outside them moved.",
    }


def _next_region_id(page: dict[str, Any]) -> str:
    """The next free `pNNNNrMMM` on this page."""
    used = 0
    for region in page.get("regions", []):
        _, _, tail = region["id"].partition("r")
        if tail.isdigit():
            used = max(used, int(tail))
    return f"{page['id']}r{used + 1:03d}"


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Mark one box for erasure on every page — for a mark that "
                    "sits in the same place throughout. A mark that moves "
                    "belongs in the worksheet, as `erase: yes`.")
    parser.add_argument("--doc", required=True)
    parser.add_argument("--box", required=True,
                        help="x y w h, in the page's own pixels, read off "
                             "overview.png")
    parser.add_argument("--label", default="watermark",
                        help="names this box, so re-running moves it instead "
                             "of adding a second")
    parser.add_argument("--kind", default="sign",
                        help=f"one of {', '.join(ir.REGION_KINDS)}")
    parser.add_argument("--pages", default="",
                        help="comma-separated page ids; default is every page")
    args = parser.parse_args(argv)

    ir.emit(mark_document(
        args.doc,
        parse_box(args.box),
        label=args.label,
        kind=args.kind,
        pages=[p for p in args.pages.split(",") if p] or None,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
