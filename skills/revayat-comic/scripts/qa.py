"""The gate. Everything here is measured, and nothing here is an opinion.

The check that matters most is ``artwork-modified``. Every other automated
comic translator asks whether the text was replaced; none of them asks what else
changed while it was being replaced. So this one re-opens the original page, the
finished page and the mask that authorised the edit, and proves that every pixel
outside that mask is the same byte it was before.

That single check catches a class of failure nothing else sees: an inpainter
that smeared past its region, a renderer that drew a descender over a face, a
resize that resampled the whole page, and — for anyone who wires a generative
model into ``clean --external`` — a model that quietly redrew an eye two panels
away. None of those are missing content, so a completeness check passes them
all.

Findings are error or warning. Errors block; warnings are reported and can be
made blocking with ``--strict`` for publication work.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import falint
import masks as mask_tools
import pageir as ir

#: Every finding this module can produce. Keeping the list here rather than
#: scattered through the checks is what lets the skill document each one with an
#: action, and lets a test assert that the documentation covers all of them.
CODES = {
    "source-modified": "error",
    "page-missing": "error",
    "page-size-changed": "error",
    "artwork-modified": "error",
    "untranslated-region": "error",
    "source-script-left": "error",
    "not-persian": "error",
    "text-overflow": "error",
    "reading-order-broken": "error",
    "archive-invalid": "error",
    "archive-page-count": "error",
    "source-text-survived": "error",
    "mask-excessive": "warning",
    "duplicate-translation": "warning",
    "low-confidence-region": "warning",
    "glossary-drift": "warning",
    "typography": "warning",
    "sfx-untranslated": "warning",
}

#: How much of a region's original ink may still be sitting outside the mask
#: after cleaning. A stroke that leaned out of the detector's box leaves a rim
#: of the source script on the page; below this it is anti-aliasing.
MAX_SURVIVING_INK = 0.06

#: Below this the detector was guessing, and a region it invented should have
#: been dropped in the worksheet rather than translated.
LOW_CONFIDENCE = 0.5

#: How much of a page may legitimately be repainted before it stops being a
#: clean-up and starts being a repaint of the artwork.
MAX_MASK_COVERAGE = 0.28


class Findings:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, code: str, where: str, detail: str, **extra: Any) -> None:
        if code not in CODES:  # pragma: no cover - guards a typo in a new check
            raise KeyError(f"undeclared QA code {code!r}")
        self.items.append({
            "code": code,
            "severity": CODES[code],
            "where": where,
            "detail": detail,
            **extra,
        })

    def by_code(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
        return counts


# --------------------------------------------------------------------------- #
# Pixel preservation
# --------------------------------------------------------------------------- #

def compare_outside_mask(original_path: Path, final_path: Path, mask_path: Path | None):
    """``(changed_pixels, total_pixels, worst_delta)`` outside the authorised area."""
    np = ir.require("numpy", "numpy", "comparing pages")

    before = np.asarray(ir.load_image(original_path)).astype(np.int16)
    after = np.asarray(ir.load_image(final_path)).astype(np.int16)
    if before.shape != after.shape:
        return None, None, None

    if mask_path is not None and mask_path.exists():
        allowed = mask_tools.load_mask(mask_path) > 0
    else:
        allowed = np.zeros(before.shape[:2], bool)

    delta = np.abs(before - after).max(axis=2)
    outside = delta.copy()
    outside[allowed] = 0
    changed = int((outside > 0).sum())
    return changed, int(delta.size // 3), int(outside.max())


def surviving_ink(original, cleaned, region: dict[str, Any],
                  mask, page_size: tuple[int, int], np) -> float:
    """Share of a balloon's lettering still on the page after cleaning.

    The mirror of ``artwork-modified``, and the hole it leaves. That check
    proves nothing changed that should not have; **nothing proved that what
    should have gone, went.** A mask that misses the tail of a stroke leaves a
    rim of the source script inside the balloon, every count stays correct, and
    the page ships with Japanese on it.

    **Balloons only, and the restriction is the whole reason it works.** Inside
    a balloon the paper is flat, so ink left there after cleaning is a missed
    stroke and nothing else. Measured over the padded box instead, it reads the
    balloon's own outline as un-removed text and returns 100% on a perfect run —
    measured, which is how this ended up scoped. For lettering drawn straight
    onto artwork there is no such separation: leftover ink is indistinguishable
    from the drawing it sits on, so those regions are not judged here.
    """
    balloon = region.get("balloon")
    if not balloon:
        return 0.0

    interior = mask_tools.balloon_interior(
        cleaned, balloon, region.get("polarity", "light"), page_size,
        inset=mask_tools.OUTLINE_INSET,
    )
    x, y, w, h = region["mask_box"]
    if w <= 0 or h <= 0:
        return 0.0

    # Where a letter could have been and the mask did not reach.
    consider = (interior[y:y + h, x:x + w] > 0) & (mask == 0)
    if consider.sum() < 24:
        return 0.0

    before = original[y:y + h, x:x + w].astype(np.int16).mean(axis=2)
    after = cleaned[y:y + h, x:x + w].astype(np.int16).mean(axis=2)
    # The balloon's own colour, read from the cleaned page where it is flat.
    paper = float(np.median(after[consider]))

    was_ink = (np.abs(before - paper) > 60) & consider
    total = int(was_ink.sum())
    if total < 12:
        return 0.0
    still = (np.abs(after - paper) > 60) & was_ink
    return float(int(still.sum()) / total)


# --------------------------------------------------------------------------- #
# Document checks
# --------------------------------------------------------------------------- #

def check_document(doc_path: str | Path, *, strict: bool = False) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    meta = doc["meta"]
    policy = meta.get("sfx_policy", "keep")
    target_language = meta.get("target_language", "fa")
    findings = Findings()

    stats = {
        "pages": len(doc["pages"]),
        "regions": 0,
        "translated": 0,
        "dropped": 0,
        "typeset": 0,
        "artwork_pixels_changed": 0,
        # Every detected region lands in exactly one of these. Reported, not
        # gated: `unresolved` is a strict subset of what `untranslated-region`
        # already blocks on, and two codes firing on identical rows is noise.
        # The census earns its place by answering a question no single code
        # does — what happened to all of them.
        "states": ir.state_census(doc),
    }
    seen_translations: dict[str, list[str]] = defaultdict(list)

    for page in doc["pages"]:
        original = root / page["image"]
        if not original.exists():
            findings.add("page-missing", page["id"], f"{page['image']} is gone")
            continue
        if ir.sha256_file(original) != page["sha256"]:
            findings.add(
                "source-modified", page["id"],
                "the original page file changed after it was imported; every "
                "box and mask was measured against the old pixels",
            )

        if page.get("mask_coverage", 0) > MAX_MASK_COVERAGE:
            findings.add(
                "mask-excessive", page["id"],
                f"{page['mask_coverage']:.0%} of the page is inside an edit mask",
            )

        # Reading order has to be a real order: every surviving region numbered,
        # and no two sharing a number. It does **not** have to be 1..N. Dropping
        # a false detection is the correction the worksheet asks for by name, and
        # it leaves a gap every time — requiring contiguity here made this fire on
        # all ten pages of the first real chapter, which is how a gate teaches
        # people to ignore it.
        orders = [region.get("reading_order") or 0
                  for region in page.get("regions", [])
                  if not region.get("dropped")]
        if orders and (min(orders) < 1 or len(set(orders)) != len(orders)):
            findings.add(
                "reading-order-broken", page["id"],
                f"reading order is missing or repeated on this page: {sorted(orders)[:12]}",
            )

        final = page.get("final")
        if final:
            final_path = root / final
            if not final_path.exists():
                findings.add("page-missing", page["id"], f"{final} is gone")
            else:
                mask_name = page.get("writable") or page.get("mask")
                changed, total, worst = compare_outside_mask(
                    original, final_path, root / mask_name if mask_name else None
                )
                if changed is None:
                    findings.add(
                        "page-size-changed", page["id"],
                        "the finished page is a different size from the original",
                    )
                elif changed:
                    stats["artwork_pixels_changed"] += changed
                    findings.add(
                        "artwork-modified", page["id"],
                        f"{changed} pixel(s) outside the authorised mask differ "
                        f"from the original (worst channel delta {worst})",
                        pixels=changed, share=round(changed / max(1, total), 6),
                    )

        # Did the source lettering actually go? `artwork-modified` above proves
        # nothing changed that should not have. This proves the opposite
        # direction, which nothing else asks.
        cleaned_name = page.get("clean")
        if cleaned_name and (root / cleaned_name).exists():
            import numpy as np

            before = np.asarray(ir.load_image(original))
            after = np.asarray(ir.load_image(root / cleaned_name))
            if before.shape == after.shape:
                for region in page.get("regions", []):
                    # A dropped region is the reader saying there is no text
                    # here, so its "surviving ink" is artwork and measuring it
                    # means nothing. It has to be checked explicitly: a region
                    # dropped *after* an earlier clean still carries that run's
                    # `fill`, and on the first real chapter that stale value let
                    # a hand-split balloon pair be reported at 100% survived.
                    if region.get("dropped"):
                        continue
                    if region.get("fill") in {"none", "keep"} or not region.get("mask"):
                        continue
                    survived = surviving_ink(
                        before, after, region,
                        mask_tools.load_mask(root / region["mask"]),
                        (page["width"], page["height"]), np,
                    )
                    if survived > MAX_SURVIVING_INK:
                        findings.add(
                            "source-text-survived", region["id"],
                            f"{survived:.0%} of this region's original ink is "
                            "still on the cleaned page, outside the mask — the "
                            "mask did not cover the whole of the lettering",
                            share=round(survived, 3),
                        )

        for region in page.get("regions", []):
            stats["regions"] += 1

            if region.get("dropped"):
                stats["dropped"] += 1
                continue

            confidence = region.get("confidence", 1.0)
            if confidence < LOW_CONFIDENCE and not region.get("locked"):
                findings.add(
                    "low-confidence-region", region["id"],
                    f"detector confidence {confidence:.2f} and never reviewed",
                )

            target = (region.get("target_text") or "").strip()
            expected = ir.translatable(region, policy)
            if not target:
                if expected:
                    findings.add("untranslated-region", region["id"],
                                 f"{region['kind']} region has no Persian")
                elif region["kind"] == "sfx":
                    findings.add("sfx-untranslated", region["id"],
                                 f"sound effect left in the artwork "
                                 f"(policy: {policy})")
                continue

            stats["translated"] += 1
            counts = ir.script_counts(target)
            leftover = (counts["hiragana"] + counts["katakana"]
                        + counts["han"] + counts["hangul"])
            if leftover:
                findings.add(
                    "source-script-left", region["id"],
                    f"{leftover} character(s) of the source script are still in "
                    f"the Persian: {target[:40]}",
                )
            if target_language == "fa" and not ir.looks_like(target, "fa"):
                findings.add("not-persian", region["id"],
                             f"target text is not Persian: {target[:40]}")

            for issue in falint.lint_text(target):
                if issue["code"] in {"untranslated", "source-script-left"}:
                    continue  # already reported above, with better detail
                findings.add("typography", region["id"],
                             f"{issue['code']}: {issue['detail']}")

            if region.get("source_text"):
                seen_translations[target].append(region["id"])

            typeset = region.get("typeset") or {}
            if typeset.get("status") == "ok":
                stats["typeset"] += 1
            elif typeset.get("status") == "overflow":
                findings.add(
                    "text-overflow", region["id"],
                    "the Persian does not fit the balloon at the minimum font "
                    "size; shorten it rather than shrinking the type",
                )

    for target, regions in seen_translations.items():
        if len(regions) > 1:
            sources = {
                (ir.find_region(doc, region_id) or {}).get("source_text", "")
                for region_id in regions
            }
            # Two balloons that say the same thing should translate the same
            # way. Two that say different things and came out identical is a
            # worksheet reply pasted twice.
            if len(sources) > 1:
                findings.add(
                    "duplicate-translation", ", ".join(regions[:4]),
                    f"different source text, identical Persian: {target[:50]}",
                )

    import glossary as glossary_module

    drift = glossary_module.check(doc_path)
    for item in drift.get("drift", []):
        findings.add("glossary-drift", item["region"],
                     f"{item['term']} should be {item['expected']}")

    errors = [item for item in findings.items if item["severity"] == "error"]
    warnings = [item for item in findings.items if item["severity"] == "warning"]
    return {
        "ok": not errors and (not warnings or not strict),
        "errors": len(errors),
        "warnings": len(warnings),
        "by_code": findings.by_code(),
        "stats": stats,
        "findings": (errors + warnings)[:60],
        "strict": strict,
    }


# --------------------------------------------------------------------------- #
# Package checks
# --------------------------------------------------------------------------- #

def check_package(package: str | Path, doc_path: str | Path) -> dict[str, Any]:
    package = Path(package)
    doc = ir.load_doc(Path(doc_path))
    findings = Findings()
    expected = len(doc["pages"])

    if not package.exists():
        findings.add("archive-invalid", package.name, "the file does not exist")
        return _package_report(findings, package, expected, 0)

    found = 0
    if package.suffix.lower() in {".cbz", ".zip"}:
        if not zipfile.is_zipfile(package):
            findings.add("archive-invalid", package.name, "not a valid ZIP archive")
        else:
            with zipfile.ZipFile(package) as archive:
                bad = archive.testzip()
                if bad:
                    findings.add("archive-invalid", package.name,
                                 f"corrupt member: {bad}")
                names = [
                    name for name in archive.namelist()
                    if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                ]
                found = len(names)
                # Order is the whole point of a comic archive, and a reader that
                # sorts by name gets it wrong unless the names sort correctly.
                if names != sorted(names):
                    findings.add("archive-invalid", package.name,
                                 "page names do not sort into reading order")
    elif package.suffix.lower() == ".pdf":
        pymupdf = ir.require("pymupdf", "pymupdf", "verifying a PDF")
        try:
            with pymupdf.open(str(package)) as document:
                found = document.page_count
        except Exception as error:
            findings.add("archive-invalid", package.name, f"cannot open: {error}")
    else:
        found = len([
            child for child in package.iterdir()
            if child.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]) if package.is_dir() else 0

    if found != expected:
        findings.add("archive-page-count", package.name,
                     f"{found} page(s) in the package, {expected} in the document")
    return _package_report(findings, package, expected, found)


def _package_report(findings: Findings, package: Path, expected: int,
                    found: int) -> dict[str, Any]:
    errors = [item for item in findings.items if item["severity"] == "error"]
    return {
        "ok": not errors,
        "package": str(package),
        "pages_expected": expected,
        "pages_found": found,
        "findings": findings.items,
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic qa", description="Gate the work before it ships."
    )
    parser.add_argument("action", choices=["check", "package"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--file", default=None, help="the exported package")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as blocking")
    args = parser.parse_args(argv)

    if args.action == "check":
        report = check_document(args.doc, strict=args.strict)
    else:
        if not args.file:
            parser.error("package needs --file")
        report = check_package(args.file, args.doc)
    ir.emit(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
