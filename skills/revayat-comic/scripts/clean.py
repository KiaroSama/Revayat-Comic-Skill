"""Remove the source lettering without touching anything else.

Cleaning escalates. Most balloons are flat paper with black letters on them, and
for those the correct repair is to read the balloon's own colour and paint it
back — no model, no guessing, no texture invented where there was none. Only
when the region sits on real artwork does it go to an inpainter.

    flat      the region's background is uniform  ->  fill with that colour
    inpaint   there is line art or texture under it  ->  OpenCV Telea
    external  a cleaned page supplied from elsewhere  ->  composited in
    keep      left alone on purpose (an SFX under a policy that keeps it)
    refused   the repair this region needs was not available  ->  nothing is
              touched and the region says what would make it possible

The last step is the one that makes the whole thing safe. Whatever produced the
repaired pixels, they are composited back through the mask:

    out = original * (1 - alpha) + repaired * alpha        alpha <= mask

Since ``alpha`` is zero everywhere the mask is zero, every pixel outside the
authorised area is the original byte, by construction rather than by good
behaviour. That holds even for an external image produced by a generative model
that redrew half the page: only the masked pixels of it are ever used.
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
from pageir import IMAGE_SUFFIXES
import providers

#: Standard deviation, in 8-bit levels, below which a background counts as flat.
#: Screentone is not flat and must not be filled; measured dot patterns sit well
#: above this, plain paper well below.
FLAT_STD = 9.0

#: How wide the blend ramp is, in pixels. It lives entirely inside the mask.
FEATHER = 2

#: Telea's radius. Larger reconstructs more context and smears more.
INPAINT_RADIUS = 4

#: What an image model is told it is doing. Kept here rather than in each
#: adapter so every provider gets the same brief, and so the brief is reviewable.
PROVIDER_INSTRUCTIONS = (
    "Reconstruct the artwork underneath the white areas of the mask. Keep every "
    "line, screentone and gradient outside those areas exactly as it is. Do not "
    "add text, signatures, watermarks or new elements. Return the whole page at "
    "its original pixel size."
)

#: A hosted image model on a full page is slow; a stalled one must not hold a
#: chapter. Past this the classical cleaners run instead.
PROVIDER_TIMEOUT = 180.0

#: The sound-effect policies that leave the drawing where it is. `translate` is
#: the only one that takes it away: `bilingual` keeps the original and adds a
#: Persian gloss beside it, `annotate` keeps it and records the meaning off the
#: page. Erasing the artwork for either would delete the very thing they promise
#: to show, and there would be nothing left for the gloss to sit beside.
KEEP_POLICIES = frozenset({"keep", "bilingual", "annotate"})

#: Said to the reader when the generative repair a solid patch needs is missing
#: at the point the region is actually repaired — and written into the region,
#: not only the run's output, because the run's output scrolls away.
SOLID_REFUSAL = (
    "free lettering masked as one solid patch, and the repair it needs did not "
    "arrive: put this page in the --external folder, use a working --provider, "
    "or rebuild this page's masks with `mask --free-lettering glyphs`"
)


def _cv2():
    ir.require("cv2", "opencv-python-headless", "cleaning artwork")
    import cv2

    return cv2


def _numpy():
    ir.require("numpy", "numpy", "cleaning artwork")
    import numpy

    return numpy


def _background_sample(window, mask, np, allowed=None):
    """Pixels in the crop that are *not* being repainted — the paper itself.

    ``allowed`` restricts the sample to the balloon's interior. Without it the
    sample picks up the balloon outline and whatever artwork sits in the corners
    of the crop, and a plain white balloon on a screentone background measures
    as textured. Every balloon then goes to the inpainter instead of taking the
    exact flat fill that is right for it — measured: nine balloons out of nine.
    """
    keep = mask == 0
    if allowed is not None:
        keep &= allowed > 0
    if keep.sum() < 24:
        return None
    return window[keep]


def choose_strategy(window, mask, np, allowed=None) -> tuple[str, tuple[int, int, int] | None]:
    sample = _background_sample(window, mask, np, allowed)
    if sample is None:
        return "inpaint", None
    spread = float(sample.reshape(-1, sample.shape[-1]).std(axis=0).max())
    if spread <= FLAT_STD:
        colour = tuple(int(round(value)) for value in sample.reshape(-1, 3).mean(axis=0))
        return "flat", colour
    return "inpaint", None


def _repair(window, mask, strategy: str, colour, np):
    cv2 = _cv2()
    if strategy == "flat":
        painted = np.empty_like(window)
        painted[:, :] = np.array(colour, dtype=window.dtype)
        return painted
    # Telea propagates the surrounding structure inwards. It is not a generative
    # model and will not invent a face; on a screentone gradient it produces a
    # smooth patch, which is the honest failure and is visible in review.
    return cv2.inpaint(window, (mask > 0).astype(np.uint8), INPAINT_RADIUS, cv2.INPAINT_TELEA)


def _composite(base, repaired, mask, np):
    """Blend, with the ramp strictly inside the authorised mask."""
    cv2 = _cv2()
    blurred = cv2.GaussianBlur(mask, (2 * FEATHER + 1, 2 * FEATHER + 1), 0)
    # Clamping to the hard mask is what keeps the guarantee: a Gaussian spreads
    # outward, and without this the ramp would leak a few pixels past the area
    # QA has authorised, failing the pixel-preservation check it exists to pass.
    alpha = np.minimum(blurred, mask).astype(np.float32) / 255.0
    alpha = alpha[..., None]
    return (base.astype(np.float32) * (1.0 - alpha)
            + repaired.astype(np.float32) * alpha).round().astype(np.uint8)


def _from_provider(provider, base, page, root, np, report) -> Any:
    """Ask an image model to redraw the page, and hand back only an array.

    What comes back is a *candidate*, never a page. It is returned into exactly
    the same variable an `--external` folder fills, so it goes through the same
    per-region hard-mask composite below and cannot reach a pixel the mask does
    not authorise. That is not a policy the provider is asked to respect; it is
    arithmetic it does not participate in.

    Any failure at all — timeout, exception, refusal, a page that came back the
    wrong size — returns ``None``, and the stage carries on with the classical
    cleaners it would have used with no provider configured. A generative
    cleaner that is having a bad day must not be able to stall a chapter.
    """
    from PIL import Image

    page_png = mask_tools._encode_png(Image.fromarray(base))
    mask_png = (root / page["mask"]).read_bytes() if page.get("mask") else b""
    result = providers.call(
        provider, "image_edit", page_png, mask_png, PROVIDER_INSTRUCTIONS,
        timeout=PROVIDER_TIMEOUT,
    )
    record = result.as_provenance()
    if not result.ok:
        report.append({"page": page["id"], **record, "outcome": "fell_back"})
        return None

    try:
        import io

        candidate = np.asarray(
            Image.open(io.BytesIO(result.data)).convert("RGB"))
    except Exception as error:  # noqa: BLE001 - a provider may return anything
        report.append({"page": page["id"], **record, "outcome": "unreadable",
                       "detail": f"{type(error).__name__}: {error}"})
        return None

    if candidate.shape != base.shape:
        report.append({"page": page["id"], **record, "outcome": "wrong_size",
                       "detail": f"{candidate.shape[1]}x{candidate.shape[0]} "
                                 f"against {base.shape[1]}x{base.shape[0]}"})
        return None

    report.append({"page": page["id"], **record, "outcome": "composited"})
    return candidate


def mask_mode(page: dict[str, Any], document_mode: str) -> str:
    """Which free-lettering mask **this page** was built with.

    `mask` recorded one flag for the whole document, so masking a second page
    with a different `--free-lettering` setting overwrote the first page's
    answer and the flag then described neither of them. The builder writes the
    value onto each page as it builds that page's masks, which is the only
    moment it is known; a page that has never been masked by a build that did
    that falls back to the document-wide flag.

    `clean` does NOT write this. It used to, and a flag left by an earlier
    clean then contradicted masks that had since been rebuilt — the page said
    `glyphs` because that is how it was cleaned last time, while the masks on
    disk were solid.
    """
    return page.get("free_lettering_mask") or document_mode


def clean_page(
    doc_path: Path,
    page: dict[str, Any],
    *,
    policy: str,
    external: Path | None = None,
    provider: Any = None,
    report: list[dict[str, Any]] | None = None,
    document_mode: str = "glyphs",
) -> dict[str, Any]:
    np = _numpy()
    root = ir.doc_dir(doc_path)
    report = report if report is not None else []
    solid_free = mask_mode(page, document_mode) == "solid"
    base = np.asarray(ir.load_image(root / page["image"])).copy()

    supplied = None
    if external is not None:
        candidate = next(
            (external / f"{page['id']}{suffix}"
             for suffix in sorted(IMAGE_SUFFIXES)
             if (external / f"{page['id']}{suffix}").exists()),
            None,
        )
        if candidate is not None:
            supplied = np.asarray(ir.load_image(candidate))
            if supplied.shape != base.shape:
                raise ValueError(
                    f"{candidate.name} is {supplied.shape[1]}x{supplied.shape[0]}, "
                    f"but {page['id']} is {base.shape[1]}x{base.shape[0]}. A "
                    "cleaned page has to be the same size as the original."
                )

    # The provider is NOT called here. A page whose every region is a flat
    # balloon needs no reconstruction at all, and paying a hosted image model to
    # redraw it is money and minutes for pixels that get thrown away. It is
    # fetched below, once, the first time a region actually needs it.
    provider_page = None
    provider_tried = False

    counts = {"flat": 0, "inpaint": 0, "external": 0, "keep": 0, "skipped": 0,
              "refused": 0}
    for region in page.get("regions", []):
        if region.get("dropped") or not region.get("mask"):
            counts["skipped"] += 1
            continue
        # `erase: yes` first, and deliberately so. It is a reader looking at
        # this one region and saying *remove this, put nothing back* — a
        # watermark, a site stamp. The SFX policy is a decision about lettering
        # that belongs to the artwork, and it has nothing to say about a mark
        # stamped on top of it; letting the policy win here left the stamp on
        # the page and the document claiming it had been dealt with.
        if not region.get("erase") and (region.get("keep") or (
                region["kind"] == "sfx" and policy in KEEP_POLICIES)):
            # The artwork *is* the sound effect. Erasing it to write the same
            # thing in Persian is a loss, so these policies leave it drawn.
            region["fill"] = "keep"
            counts["keep"] += 1
            continue

        mask = mask_tools.load_mask(root / region["mask"])
        x, y, w, h = region["mask_box"]
        if w <= 0 or h <= 0 or not mask.any():
            counts["skipped"] += 1
            continue

        # Can the typesetter match how this effect was drawn? The question has
        # to be asked HERE, before anything is erased. Asked later — after the
        # ink is gone — "leave it as drawn" is a promise about pixels that no
        # longer exist, and the page ends up with a blank patch where the
        # lettering was. The mask is the same evidence either way, so nothing
        # is lost by asking early.
        # Not asked of an erasure. The question is whether Persian can be set
        # the way the original was drawn, and an erasure is not putting anything
        # back — so an unreadable geometry was refusing to remove a watermark on
        # the grounds that it could not tell which way the watermark leaned.
        if (region["kind"] == "sfx" and policy not in KEEP_POLICIES
                and not region.get("erase")):
            drawn = lettering.measure(
                mask, np, origin=region.get("mask_box", (0, 0))[:2])
            if drawn is not None:
                # The whole measurement, not a summary: `typeset` renders from
                # it, and a second measurement of the same region could disagree
                # with the one that decided whether to erase.
                region["lettering"] = dict(drawn)
                if drawn["verdict"] == "unreliable":
                    region["fill"] = "keep"
                    region.setdefault("review", []).append(
                        f"sound effect left as drawn: {drawn['reason']}")
                    counts["keep"] += 1
                    continue

        window = base[y:y + h, x:x + w]

        allowed = None
        if region.get("balloon"):
            interior = mask_tools.balloon_interior(
                base, region["balloon"], region.get("polarity", "light"),
                (page["width"], page["height"]),
                inset=mask_tools.OUTLINE_INSET,
            )
            allowed = interior[y:y + h, x:x + w]
        strategy, colour = choose_strategy(window, mask, np, allowed)

        # Two different things that both produce replacement pixels, and they
        # are deliberately NOT treated the same.
        #
        # `--external` is a page a person handed over, having already decided
        # this whole page should be replaced. Second-guessing that per region
        # would silently ignore most of what they supplied — which is what an
        # earlier version of this code did.
        #
        # A native provider is the pipeline choosing to spend a model call, so
        # it escalates: a flat balloon is repaired exactly by reading its own
        # colour and painting it back, better than any model and instant, and
        # the provider takes over only where the deterministic tiers stop being
        # enough — a region needing inpainting, or a solid free-lettering patch.
        solid_patch = solid_free and not region.get("balloon")
        repaired = None
        if supplied is not None:
            repaired, strategy, colour = supplied[y:y + h, x:x + w], "external", None
        elif provider is not None and (strategy == "inpaint" or solid_patch):
            if not provider_tried:
                provider_tried = True
                provider_page = _from_provider(provider, base, page, root, np,
                                               report)
            if provider_page is not None:
                repaired = provider_page[y:y + h, x:x + w]
                strategy, colour = "external", None

        if repaired is None:
            # THE SAME SAFETY QUESTION, ASKED WHERE IT IS ANSWERED. The refusal
            # in `clean_document` is decided on a promise: a folder was named,
            # or a provider was configured. Both can break after it — the folder
            # may not contain this page, and a provider can fail, time out, or
            # answer at the wrong size — and the fallback is the one tier a
            # solid patch must never reach. It has no unmasked pixel to read
            # from, so it repairs nothing at all and `inpaint` goes into the
            # document for it: the source lettering ships under the Persian on a
            # page every gate now believes was cleaned.
            if solid_patch:
                region["fill"] = "keep"
                # A barrier, not a note. `fill: keep` alone reads as "the
                # reader wanted this left in the artwork", which is a decision
                # somebody made — and the region then took a translated overlay
                # and shipped, with the source lettering underneath it. This
                # says what actually happened, and `typeset` and `qa` both
                # refuse to treat it as cleaned.
                region["clean_status"] = "refused"
                if SOLID_REFUSAL not in region.setdefault("review", []):
                    region["review"].append(SOLID_REFUSAL)
                counts["refused"] += 1
                continue
            repaired = _repair(window, mask, strategy, colour, np)

        base[y:y + h, x:x + w] = _composite(window, repaired, mask, np)
        region["fill"] = strategy
        region["clean_status"] = "cleaned"
        if colour is not None:
            region["fill_colour"] = list(colour)
        counts[strategy] += 1

    from PIL import Image

    relative = f"clean/{page['id']}.png"
    ir.save_image(Image.fromarray(base), root / relative)
    page["clean"] = relative
    # Deliberately NOT writing `free_lettering_mask` here. `mask` owns it: it
    # is a fact about the masks on disk, and a value left behind by an earlier
    # clean contradicted masks that had since been rebuilt.
    return counts


def clean_document(
    doc_path: str | Path,
    *,
    external: str | Path | None = None,
    pages: Sequence[str] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    policy = doc["meta"].get("sfx_policy", "keep")
    external_dir = Path(external).expanduser() if external else None
    if external_dir is not None and not external_dir.is_dir():
        raise FileNotFoundError(f"--external is not a folder: {external_dir}")
    edit_provider = providers.get("image_edit", provider)

    document_mode = doc["meta"].get("free_lettering_mask", "glyphs")
    scope = [page for page in doc["pages"]
             if page.get("regions") and (not pages or page["id"] in pages)]
    # Per page, because the document's flag is whatever the *last* `mask` run
    # wrote. One page masked solid is enough to refuse, and naming it is what
    # lets a reader fix that page rather than re-mask the chapter.
    solid_pages = [page["id"] for page in scope
                   if mask_mode(page, document_mode) == "solid"]
    if solid_pages and external_dir is None and edit_provider is None:
        where = ", ".join(solid_pages[:5])
        if len(solid_pages) > 5:
            where += f" and {len(solid_pages) - 5} more"
        raise ValueError(
            f"the masks for {where} were built with "
            "`mask --free-lettering solid`, which covers each piece of free "
            "lettering as a whole patch rather than as letter shapes. That is "
            "for a generative cleaner: painting it flat or inpainting it would "
            "blank a rectangle out of the artwork. Either pass --provider "
            "with an image-edit provider, or --external with "
            "your reconstructed pages, or rebuild the masks with "
            "`mask --free-lettering glyphs`."
        )

    provider_report: list[dict[str, Any]] = []
    totals = {"flat": 0, "inpaint": 0, "external": 0, "keep": 0, "skipped": 0,
              "refused": 0}
    per_page: list[dict[str, Any]] = []
    for page in scope:
        counts = clean_page(
            doc_path, page, policy=policy, external=external_dir,
            provider=edit_provider, report=provider_report,
            document_mode=document_mode,
        )
        for key, value in counts.items():
            totals[key] += value
        per_page.append({"page": page["id"], **counts})

    stamp = {"totals": totals}
    if provider_report:
        # Persisted, not just reported: the CLI output is gone as soon as the
        # terminal scrolls, and "what did the model actually touch" has to be
        # answerable from the document months later.
        stamp["provider"] = provider
        stamp["provider_calls"] = provider_report
    stages.stamp_stage(doc, "clean", stamp,
                       options={"external": bool(external_dir),
                                "provider": provider}, pages=pages)
    ir.save_doc(doc, doc_path)

    heavy = [entry["page"] for entry in per_page if entry["inpaint"] > entry["flat"]]
    refused = [entry["page"] for entry in per_page if entry["refused"]]
    return {
        "document": str(doc_path),
        "totals": totals,
        "pages": per_page,
        "provider": provider,
        "provider_calls": provider_report,
        "refused_pages": refused,
        "refused_note": SOLID_REFUSAL if refused else None,
        "inpaint_heavy_pages": heavy,
        "note": (
            "On these pages most regions needed inpainting rather than a flat "
            "fill, which means the lettering sits on artwork. Look at them "
            "before exporting; Telea smooths, it does not redraw."
        ) if heavy else None,
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic clean",
        description="Remove source lettering through the authorised masks.",
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--pages", default="")
    parser.add_argument("--provider", default=None,
                        help="name of an image-edit provider to redraw pages "
                             "with; its output is composited under the same "
                             "mask as everything else, and any failure falls "
                             "back to the classical cleaners")
    parser.add_argument("--external", default=None,
                        help="folder of externally cleaned pages named "
                             "<page id>.png; only their masked pixels are used")
    args = parser.parse_args(argv)

    report = clean_document(
        args.doc,
        external=args.external,
        pages=[p for p in args.pages.split(",") if p] or None,
        provider=args.provider,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
