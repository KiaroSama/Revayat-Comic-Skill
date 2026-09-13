"""Set Persian into the balloons — shaped, wrapped to the balloon's real shape.

Three things here are non-negotiable, and each of them is a way this goes wrong
in almost every automated translation people publish:

**No string reversal, ever.** Persian is written right to left, but the
characters are stored in logical order and the *renderer* is what puts them on
the page. Reversing the string produces something that looks correct in one
viewer and is broken everywhere else, and it is unsearchable and uncopyable
even where it looks right. Direction comes from HarfBuzz and FriBidi through
Pillow's RAQM layout engine. If RAQM is missing, the reshaper fallback runs and
says so loudly, because pre-shaped text has the same defects in miniature.

**The balloon is not a rectangle.** A round balloon is narrow at the top, wide
in the middle and narrow again at the bottom, so a paragraph set to a constant
width either overflows the curve or wastes half the balloon. Every line is
measured against the width actually available in its own vertical band, which is
what a letterer does by hand.

**Text never silently shrinks to nothing.** Persian runs longer than Japanese;
when a translation will not fit, the size floor holds and the region is reported
as overflowing, so the answer is a shorter sentence rather than six-point type
nobody can read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import lettering
import masks as mask_tools
import pageir as ir
import stages
from typefit import (  # noqa: F401 - re-exported: every caller and every
    BALLOON_PADDING,                   # test reaches these through
    BODY_WIDTH,                        # `typeset`, which is where they
    DEFAULT_MAX_SIZE,                  # have always lived.
    DEFAULT_MIN_SIZE,
    LINE_SPACING,
    _band_span,
    _body,
    _measure,
    _row_widths,
    _tokens,
    _wrap,
    fit_region,
    interior_mask,
    stroke_for,
)
from typefont import (  # noqa: F401 - re-exported: `typeset.find_font`
    FONT_DIRS,                                # and friends are the names
    PERSIAN_FONTS,                            # the CLI, `doctor` and the
    VAZIR_FONTS,                              # tests have always used.
    ZWNJ,
    Shaper,
    font_identity,
    _numpy,
    _pil,
    _supports_persian,
    find_font,
    is_vazir,
    raqm_available,
    shape_fallback,
)

#: Keep this much of the balloon clear at its edge, as a share of its size.


# --------------------------------------------------------------------------- #
# Balloon interior
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def refused_clean(region: dict[str, Any]) -> bool:
    """Whether the artwork under this region was never actually repaired.

    `clean` refuses a solid free-lettering patch it has no repair for, and the
    original lettering is still there. Drawing Persian over it ships two
    layers of text in one balloon on a page every gate believed was cleaned.
    """
    return region.get("clean_status") == "refused"


def _text_colour(region: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int] | None]:
    """``(fill, stroke)``. A dark balloon needs light letters, and lettering on
    bare artwork needs an outline or it disappears into the drawing."""
    if region.get("polarity") == "dark":
        return (245, 245, 245), (12, 12, 12)
    if not region.get("balloon"):
        return (18, 18, 18), (250, 250, 250)
    return (18, 18, 18), None


def _restore(canvas, region: dict[str, Any], root: Path, np) -> None:
    """Put a region's original pixels back, bounded by its own mask.

    The mirror of `clean._composite` and bounded the same way: only pixels the
    mask authorises are written, so restoring can no more damage neighbouring
    artwork than cleaning could. Needed because the decision to leave an effect
    drawn can only be *finally* made once the Persian has been fitted, and by
    then `clean` has already erased it.
    """
    Image, _, _ = _pil()
    original = np.asarray(ir.load_image(root / region["_page_image"]))
    x, y, w, h = region["mask_box"]
    mask = mask_tools.load_mask(root / region["mask"])
    # `np.asarray(canvas)` is a read-only view of Pillow's own buffer; crop to a
    # real array, choose per pixel, and paste the result back.
    patch = np.array(canvas.crop((x, y, x + w, y + h)))
    keep = mask[..., None] > 0
    patch = np.where(keep, original[y:y + h, x:x + w], patch).astype(patch.dtype)
    canvas.paste(Image.fromarray(patch), (x, y))


def typeset_page(
    doc_path: Path,
    page: dict[str, Any],
    shaper: Shaper,
    font_path: Path,
    *,
    policy: str,
    max_size: int,
    min_size: int,
    stylise: bool = True,
) -> dict[str, Any]:
    Image, ImageDraw, ImageFont = _pil()
    np = _numpy()
    root = ir.doc_dir(doc_path)

    source = page.get("clean") or page["image"]
    canvas = ir.load_image(root / source).copy()
    for region in page.get("regions", []):
        # `_restore` needs the untouched page, not the cleaned one.
        region["_page_image"] = page["image"]
    clean_rgb = np.asarray(canvas)
    # An explicit copy, kept as the reference for "did this line land where
    # it was allowed to". `canvas` is drawn on in place below.
    before_draw = np.array(canvas)
    draw = ImageDraw.Draw(canvas)
    size = (page["width"], page["height"])

    # What this page is ALLOWED to have changed. It is built here, from the
    # geometry a person or the detector approved, and it is never widened
    # afterwards.
    #
    # It used to start as the lettering mask and then absorb the bounding box
    # of every line that was actually drawn. That made the preservation proof
    # circular: whatever the typesetter painted became, by definition, the
    # area it had been allowed to paint, so an overflow could not fail the
    # gate. Measured on a page whose text was shoved 260 px off its balloon,
    # the authorised area grew from 60,051 px to 531,746 — about a third of
    # the page — and `qa` reported no error at all.
    #
    # The balloon interior is the right authority rather than the lettering
    # mask: Persian set into a repainted balloon legitimately covers paper
    # the source glyphs never touched, and that paper is inside the balloon.
    #: One entry per region: where THAT region's ink is allowed to land. The
    #: old answer was a single page-wide union of every region's area, so ink
    #: from one balloon landing inside the next balloon was authorised — by the
    #: neighbour's authority, which is not this region's to spend. Two balloons
    #: side by side is the ordinary case, not a corner one.
    authority: dict[str, Any] = {}
    writable = np.zeros((page["height"], page["width"]), np.uint8)
    union = page.get("mask")
    if union:
        writable = np.maximum(writable, mask_tools.load_mask(root / union))
    for region in page.get("regions", []):
        if region.get("dropped") or not (region.get("target_text") or "").strip():
            continue
        own = np.zeros((page["height"], page["width"]), np.uint8)
        if region.get("mask") :
            try:
                own = np.maximum(own, mask_tools.load_mask(root / region["mask"]))
            except Exception:  # pragma: no cover - a mask file that went away
                pass
        if region.get("balloon"):
            # `inset=0` deliberately, unlike `clean`. The inset is a CLEANING
            # conservatism — do not repaint the balloon's own outline — not a
            # statement about where text may go. Measured on a real Japanese
            # page: six pixels of one glyph's anti-aliased edge landed on the
            # outline it was set against, every one of them within two pixels
            # of the inset interior. The balloon is still the boundary; text
            # shoved off it entirely is still caught.
            interior = mask_tools.balloon_interior(
                before_draw, region["balloon"],
                region.get("polarity", "light"), size, inset=0.0,
            )
            own = np.maximum(own, np.asarray(interior, np.uint8))
        elif region.get("mask_box"):
            # Free lettering has no balloon, so the authorised area is the
            # box the region was masked at — approved geometry either way.
            bx, by, bw, bh = region["mask_box"]
            own[by:by + bh, bx:bx + bw] = 255
        authority[region["id"]] = own
        writable = np.maximum(writable, own)

    placed = 0
    overflow: list[str] = []
    unreliable: list[str] = []
    refused: list[str] = []
    glossed: list[str] = []
    skipped = 0
    for region in page.get("regions", []):
        text = (region.get("target_text") or "").strip()
        if region.get("dropped") or not text:
            skipped += 1
            continue
        if region.get("keep") or (
                region["kind"] == "sfx" and policy == "keep"):
            skipped += 1
            continue
        if policy in ("bilingual", "annotate") and region["kind"] == "sfx":
            # `bilingual` and `annotate` both promise to SHOW the original and
            # add Persian beside it. `clean` keeps the original, so the only
            # place left for the Persian is the box the original occupies —
            # and drawing it there prints one on top of the other, which is
            # neither of the two things the policy promised.
            #
            # No placement is invented. The gloss is recorded against the page
            # so a letterer, a sidecar or a later feature can place it, and
            # `qa` says it has nowhere to go.
            page.setdefault("annotations", []).append({
                "region": region["id"], "kind": region["kind"],
                "source": (region.get("source_text") or "").strip(),
                "fa": text, "reason": "no reserved place for a gloss",
            })
            glossed.append(region["id"])
            skipped += 1
            continue
        if refused_clean(region):
            # The artwork under this region was never repaired — `clean` had
            # no repair for a solid free-lettering patch and said so. Drawing
            # Persian over it ships two layers of text in one balloon, on a
            # page every gate then believed was cleaned.
            refused.append(region["id"])
            skipped += 1
            continue

        fill, stroke = _text_colour(region)
        painted: list[list[int]] = []
        record: dict[str, Any] | None = None
        # The page as it is NOW, with every region already committed on it.
        # Rolling back to `before_draw` — the page as it was before any region
        # drew — undid the neighbours too: one balloon that did not fit erased
        # the finished translation of every balloon whose ink shared a
        # rectangle with it, and reported only its own overflow.
        before_region = np.asarray(canvas).copy()

        # Lettering that was drawn rather than typed: slant, arc and recession
        # measured from the mask `clean` erased, and matched only where the
        # measurement holds up. A balloon, a straight effect, or a region with
        # no mask of its own all take the flat path below.
        # `clean` measured this already, before it erased anything — reuse its
        # answer rather than measuring a second time. Two measurements of one
        # region can disagree, and only one of them decided whether the original
        # ink is still on the page.
        drawn = region.get("lettering")
        if drawn is None and stylise and region["kind"] == "sfx" \
                and region.get("mask"):
            drawn = lettering.measure(
                mask_tools.load_mask(root / region["mask"]), np,
                origin=region.get("mask_box", (0, 0))[:2],
            )
        if not stylise:
            drawn = None

        if drawn is not None and drawn["verdict"] == "unreliable":
            # `clean` saw this coming and did not erase it, so the lettering is
            # still on the page and "left as drawn" is true about actual pixels.
            # Stamping type that is confidently wrong about its own angle over
            # hand lettering is worse than leaving the original.
            #
            # This is the code declining to replace, never overriding a reader:
            # an explicit `keep: yes` was already honoured further up the loop.
            # `clean` already left this drawn and recorded `keep`; do not
            # overwrite that with "none", which claims nothing was decided.
            region["fill"] = "keep"
            region["typeset"] = {"status": "unreliable",
                                 "style": "unreliable",
                                 "reason": drawn.get("reason", "")}
            note = f"sound effect left as drawn: {drawn.get('reason', '')}"
            if note not in region.get("review", []):
                region.setdefault("review", []).append(note)
            unreliable.append(region["id"])
            skipped += 1
            continue

        if drawn is not None and drawn["verdict"] != "flat":
            done = lettering.render(
                canvas, text, drawn, shaper, font_path, fill, stroke, np,
                fit_region, _pil(), max_size=max_size, min_size=min_size)
            if done is not None:
                painted.append(done.pop("box"))
                record = {"status": "ok", **done}
            elif drawn["verdict"] in {"curved", "warped"}:
                # A strongly stylised effect that will not fit its own shape.
                # Setting it flat would replace an arc of hand lettering with a
                # horizontal line of type — the "visibly worse" case
                # `sound-effects.md` exists to avoid. `clean` already erased it,
                # so the honest answer is to put the original ink back under its
                # own mask and ask for a person.
                _restore(canvas, region, root, np)
                # The original ink is back on the page, so that is what `fill`
                # has to say — whatever `clean` did has been undone.
                region["fill"] = "keep"
                region["typeset"] = {"status": "unreliable", "style": drawn["verdict"],
                                     "reason": "the Persian does not fit the "
                                               "shape the lettering was drawn in"}
                region.setdefault("review", []).append(
                    f"sound effect restored as drawn: the Persian does not fit "
                    f"the {drawn['verdict']} shape it was lettered in")
                unreliable.append(region["id"])
                skipped += 1
                continue

        if record is None:
            area = interior_mask(clean_rgb, region, size)
            fitted = fit_region(
                draw, text, area, np, shaper, font_path,
                max_size=max_size, min_size=min_size, stroke=bool(stroke),
            )
            if fitted is None:
                overflow.append(region["id"])
                region["typeset"] = {"status": "overflow"}
                continue

            font = ImageFont.truetype(str(font_path), fitted["size"],
                                      layout_engine=shaper.layout)
            for line in fitted["lines"]:
                shaped = shaper.prepare(line["text"])
                options: dict[str, Any] = {
                    "font": font, "fill": fill, "anchor": "mm",
                    **shaper.draw_kwargs(),
                }
                if stroke:
                    options["stroke_width"] = stroke_for(fitted["size"])
                    options["stroke_fill"] = stroke
                draw.text((line["x"], line["y"]), shaped, **options)
                box = draw.textbbox((line["x"], line["y"]), shaped, **{
                    k: v for k, v in options.items()
                    if k != "fill" and k != "stroke_fill"
                })
                painted.append([int(box[0]), int(box[1]),
                                int(box[2]), int(box[3])])
            record = {
                "status": "ok",
                "style": "flat",
                "size": fitted["size"],
                "lines": fitted["line_count"],
                "font": fitted["font"],
                "shaping": shaper.mode,
            }

        # The check that replaces the old widening. Compare the pixels that
        # actually changed against the area this region was authorised for,
        # and say so when ink landed outside it. A bounding box would be too
        # crude: the corners of a box around a line of Persian sit outside
        # the balloon on a curve, while the ink itself does not.
        if painted:
            x0 = max(0, min(box[0] for box in painted))
            y0 = max(0, min(box[1] for box in painted))
            x1 = min(page["width"], max(box[2] for box in painted))
            y1 = min(page["height"], max(box[3] for box in painted))
            if x1 > x0 and y1 > y0:
                after = np.asarray(canvas)[y0:y1, x0:x1]
                changed = (before_region[y0:y1, x0:x1] != after).any(axis=2)
                # This region's own authority, not the page-wide union. Ink
                # that lands in the NEXT balloon is outside this region's
                # permission however legitimately that balloon belongs to
                # somebody else's.
                allowed = authority.get(region["id"])
                if allowed is None:
                    allowed = writable
                stray = int((changed & (allowed[y0:y1, x0:x1] == 0)).sum())
                if stray:
                    # Painted, checked, and taken back off again. Noticing the
                    # overflow after the ink is down is not enough — the ink is
                    # down, and the gate is right to count it. Restoring the
                    # rectangle leaves the cleaned page exactly as it was and
                    # the region honestly marked `overflow`, which is what "the
                    # words do not fit this balloon" has always meant here: the
                    # Persian is shortened and merged again, not shipped over
                    # the artwork.
                    Image = _pil()[0]
                    canvas.paste(
                        Image.fromarray(before_region[y0:y1, x0:x1]), (x0, y0))
                    painted.clear()
                    record["status"] = "overflow"
                    record["outside_authorised"] = stray
                    if region["id"] not in overflow:
                        overflow.append(region["id"])

        region["typeset"] = record
        placed += 1

    for region in page.get("regions", []):
        region.pop("_page_image", None)

    relative = f"final/{page['id']}.png"
    ir.save_image(canvas, root / relative)
    page["final"] = relative

    writable_path = f"masks/{page['id']}/writable.png"
    ir.write_bytes(root / writable_path,
                   mask_tools._encode_png(Image.fromarray(writable, mode="L")))
    page["writable"] = writable_path

    # What was actually delivered, signed by the run that delivered it.
    #
    # A filename and `typeset.status: ok` say a page was written; they say
    # nothing about WHICH pixels are in the file now. Copying the cleaned,
    # textless page over `final/` left every count correct, every status `ok`,
    # the size identical and every pixel inside the authorised mask — so the
    # preservation proof passed it and the chapter shipped with no Persian on
    # it. Nothing in the document could tell the difference, because nothing in
    # the document had ever looked at the bytes.
    page["delivery"] = {
        "final": ir.sha256_file(root / relative),
        "writable": ir.sha256_file(root / writable_path),
        "clean": (ir.sha256_file(root / page["clean"])
                  if page.get("clean") and (root / page["clean"]).exists()
                  else None),
        "size": [page["width"], page["height"]],
        "placed": placed,
    }

    return {"placed": placed, "overflow": overflow, "skipped": skipped,
            "unreliable": unreliable, "refused_clean": refused,
            "unplaced_gloss": glossed}


def typeset_document(
    doc_path: str | Path,
    *,
    font: str | None = None,
    max_size: int = DEFAULT_MAX_SIZE,
    min_size: int = DEFAULT_MIN_SIZE,
    force_fallback: bool = False,
    pages: Sequence[str] | None = None,
    stylise: bool = True,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    policy = doc["meta"].get("sfx_policy", "keep")

    font_path = find_font(font)
    if not _supports_persian(font_path):
        raise ir.MissingDependency(
            f"{font_path.name} does not draw Persian — the test word came out "
            "blank or as tofu boxes.\nInstall Vazirmatn and pass it with "
            "--font, or name another Persian face you have."
        )
    shaper = Shaper(force_fallback=force_fallback)

    placed = 0
    overflow: list[str] = []
    unreliable: list[str] = []
    refused_pages: list[str] = []
    unplaced: list[str] = []
    per_page: list[dict[str, Any]] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        if not page.get("regions"):
            continue
        result = typeset_page(
            doc_path, page, shaper, font_path,
            policy=policy, max_size=max_size, min_size=min_size,
            stylise=stylise,
        )
        placed += result["placed"]
        overflow += result["overflow"]
        unreliable += result["unreliable"]
        refused_pages += result["refused_clean"]
        unplaced += result["unplaced_gloss"]
        per_page.append({"page": page["id"], **result})

    stages.stamp_stage(
        doc, "typeset",
        {"placed": placed, "font": font_path.name, "shaping": shaper.mode,
         "vazir": is_vazir(font_path)},
        # The face and the shaper are options, not results: the same text set
        # in Tahoma instead of Vazir is a different page, and a fallback shaper
        # breaks lines somewhere else.
        options={"font": font_identity(font_path), "shaping": shaper.mode,
                 "max_size": max_size, "min_size": min_size,
                 "stylise": stylise},
        pages=pages)
    ir.save_doc(doc, doc_path)

    note = None
    if not is_vazir(font_path):
        note = (
            f"Persian in this project is set in Vazir; this run used "
            f"{font_path.name}. The pages are readable and the type is not the "
            f"house face. Install Vazirmatn "
            f"(https://github.com/rastikerdar/vazirmatn/releases) or pass "
            f"--font /path/to/Vazirmatn-Medium.ttf."
        )

    return {
        "document": str(doc_path),
        "font": str(font_path),
        "vazir": is_vazir(font_path),
        "font_note": note,
        "shaping": shaper.mode,
        "placed": placed,
        "overflow": overflow[:30],
        "overflow_count": len(overflow),
        "unreliable": unreliable[:30],
        "unreliable_count": len(unreliable),
        "refused_clean": refused_pages[:30],
        "refused_clean_count": len(refused_pages),
        "unplaced_gloss": unplaced[:30],
        "unplaced_gloss_count": len(unplaced),
        "pages": per_page,
        "warning": None if shaper.raqm else (
            "Pillow has no RAQM here, so Persian was shaped and reordered by "
            "arabic-reshaper and python-bidi instead of HarfBuzz and FriBidi. "
            "The pages are correct to read, so this is a note, not a fault. "
            "Pillow's wheels DO carry libraqm on Windows and macOS as well as Linux; what is missing here is FriBiDi, which libraqm loads at run time. On Windows, put a `fribidi.dll` (or `fribidi-0.dll` / `libfribidi-0.dll`) on PATH and RAQM turns on — beside python.exe is not enough, it has to be a directory in the DLL search order. Measured: with one on PATH this machine reports raqm true. See references/persian-typesetting.md for what differs."
        ),
        "next": (
            f"{len(overflow)} region(s) did not fit at the minimum size. Shorten "
            "those translations in the worksheet and re-run merge and typeset."
        ) if overflow else "Run `qa check`.",
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic typeset",
        description="Set the Persian translations into the cleaned pages.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--font", default=None,
                        help="a Persian font file or family name")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE)
    parser.add_argument("--min-size", type=int, default=DEFAULT_MIN_SIZE,
                        help="never set smaller than this; report overflow instead")
    parser.add_argument("--no-raqm", action="store_true",
                        help="force the reshaper fallback (for testing it)")
    parser.add_argument("--flat-sfx", action="store_true",
                        help="set every sound effect horizontally, even where "
                             "the mask shows the original was on a slant")
    args = parser.parse_args(argv)

    report = typeset_document(
        args.doc,
        font=args.font,
        max_size=args.max_size,
        min_size=args.min_size,
        force_fallback=args.no_raqm,
        pages=[p for p in args.pages.split(",") if p] or None,
        stylise=not args.flat_sfx,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
