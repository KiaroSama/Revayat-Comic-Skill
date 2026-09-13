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
from collections import defaultdict
from pathlib import Path
from typing import Any

import falint
import masks as mask_tools
import pageir as ir
import stages
from pageir import IMAGE_SUFFIXES  # noqa: F401 - `package.py` reads it from here
import providers

#: Every finding this module can produce. Keeping the list here rather than
#: scattered through the checks is what lets the skill document each one with an
#: action, and lets a test assert that the documentation covers all of them.
CODES = {
    "source-modified": "error",
    "page-missing": "error",
    "page-size-changed": "error",
    "artwork-modified": "error",
    "untranslated-region": "error",
    "page-not-rendered": "error",
    "source-script-left": "error",
    "not-persian": "error",
    "text-overflow": "error",
    "reading-order-broken": "error",
    "archive-invalid": "error",
    "archive-page-count": "error",
    "archive-page-size": "error",
    "archive-duplicate-page": "error",
    "source-text-survived": "error",
    "stale-stage": "error",
    "clean-refused": "error",
    "region-not-rendered": "error",
    "erase-unfinished": "error",
    "delivery-mismatch": "error",
    "delivery-unverified": "warning",
    "stage-unverified": "warning",
    "policy-conflict": "warning",
    "annotation-unplaced": "warning",
    "compressed-variant": "warning",
    "mask-excessive": "warning",
    "duplicate-translation": "warning",
    "low-confidence-region": "warning",
    "glossary-drift": "warning",
    "typography": "warning",
    "sfx-untranslated": "warning",
    # Everything a model said. `advice` is its own severity and always will be:
    # a model's opinion must not be able to fail a run, and must not be able to
    # clear one either. See `visual_review` below.
    "visual-note": "advice",
}

#: Findings a visual pass may file. Anything else it invents is dropped with a
#: count, because an open vocabulary would let a model define its own codes and
#: a reader could never learn what they mean.
VISUAL_CODES = (
    "speaker-mismatch",      # the balloon tail points at somebody else
    "missed-text",           # visible lettering with no region on it
    "reconstruction-poor",   # the repair inside a mask looks wrong
    "placement-poor",        # it fits geometrically and reads badly
    "sfx-style-poor",        # the effect does not match what was drawn
)

#: How many times a malformed answer is asked for again. Small on purpose: a
#: model that has returned nonsense twice is not one round away from sense, and
#: an open-ended retry loop is how an advisory pass becomes the slowest stage.
VISUAL_RETRIES = 2

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
    # `delta` was already collapsed across the three channels by the
    # `max(axis=2)` above, so it is H x W. Dividing by three again made
    # every reported share three times too large.
    return changed, int(delta.size), int(outside.max())


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

    # Did the cleaner do anything at all? Asked first, because every test
    # below can exit early on a page where nothing happened — which is
    # exactly the page this question is about. A cleaner that left every
    # original letter where it was measured 0.000 and the gate passed it.
    #
    # Inside the mask the question is not "is there ink" — an inpainted
    # region legitimately has some — but "is this byte for byte what was
    # here before", which no real repair ever is.
    covered = mask > 0
    if int(covered.sum()) >= 24:
        was = original[y:y + h, x:x + w].astype(np.int16).mean(axis=2)
        now = cleaned[y:y + h, x:x + w].astype(np.int16).mean(axis=2)
        # The balloon's own colour, read from the ORIGINAL just outside the
        # mask, so this does not depend on the clean having worked.
        around = was[~covered]
        paper_before = float(np.median(around if around.size else was))
        inked = (np.abs(was - paper_before) > 60) & covered
        under = int(inked.sum())
        if under >= 12:
            untouched = int((np.abs(was - now) < 1)[inked].sum())
            if untouched / under > 0.98:
                return 1.0

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

def _normalise(payload: Any, page_id: str) -> tuple[list[dict[str, Any]], int]:
    """Keep the findings that are shaped like findings; count the rest.

    A provider returns whatever it returns. Everything that reaches the report
    has a code from `VISUAL_CODES`, a region or a page, and a note — so the
    output is stable enough for a reader to skim and for a later run to diff.
    """
    if not isinstance(payload, list):
        return [], 1
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in payload:
        if not isinstance(item, dict) or item.get("code") not in VISUAL_CODES:
            dropped += 1
            continue
        kept.append({
            "code": item["code"],
            "page": page_id,
            "region": str(item.get("region") or ""),
            "note": str(item.get("note") or "")[:400],
        })
    return kept, dropped


def visual_review(doc_path: str | Path, *, provider: str,
                  timeout: float = providers.DEFAULT_TIMEOUT) -> dict[str, Any]:
    """An optional second look at what deterministic checks cannot judge.

    **It is advisory and it stays advisory.** Nothing here can fail a run and,
    more importantly, nothing here can pass one: `check_document` is the gate,
    this is a reading list. A model that says the page looks fine does not clear
    an `artwork-modified` error, and a model that says it looks wrong does not
    create one — it creates a note against a region, which a person reads.

    That asymmetry is the whole design. Deterministic checks answer questions
    with right answers (did a pixel change outside the mask); this answers
    questions that do not have them (does this balloon belong to that speaker),
    and a question without a right answer must not gate a pipeline.
    """
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    model = providers.get("visual_qa", provider)

    notes: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    malformed = 0

    for page in doc["pages"]:
        image = root / (page.get("final") or page.get("clean") or page["image"])
        regions = [
            {"id": r["id"], "kind": r["kind"], "bbox": r["bbox"],
             "speaker": r.get("speaker", ""), "fa": r.get("target_text", "")}
            for r in page.get("regions", []) if not r.get("dropped")
        ]
        for attempt in range(VISUAL_RETRIES + 1):
            result = providers.call(model, "visual_qa", str(image), regions,
                                    timeout=timeout, name=provider)
            calls.append({"page": page["id"], **result.as_provenance()})
            if not result.ok:
                break
            kept, bad = _normalise(result.data, page["id"])
            malformed += bad
            if kept or not bad:
                notes.extend(kept)
                break
            if attempt == VISUAL_RETRIES:
                break

    return {
        "document": str(doc_path),
        "provider": provider,
        "advisory": True,
        "notes": notes,
        "note_count": len(notes),
        "malformed": malformed,
        "calls": calls,
        "note": (
            "Advisory only. These are a model's opinions about things a "
            "deterministic check cannot judge; they never pass or fail a run. "
            "Run `qa` for the gate."
        ),
    }


def _certify_delivery(findings: "Findings", root: Path, page: dict[str, Any],
                      final: str) -> None:
    """Are the bytes on disk the ones the render committed?

    `typeset` signs the finished page, the writable mask it drew inside and the
    cleaned page it drew onto. This re-reads all three. It is deliberately a
    question about provenance and not about content: no OCR, no "does this look
    like Persian" — only whether what is about to be packaged is what the
    recorded run produced. A page swapped for its own cleaned copy, a mask
    rebuilt under a finished render, a hand-edited PNG dropped in afterwards:
    every one of them changes a hash and none of them changes a status.
    """
    delivery = page.get("delivery") or {}
    if not delivery:
        # Rendered by a build that did not sign its output. A warning, for the
        # same reason `stage-unverified` is one: a chapter finished by an older
        # build is not evidence of anything wrong, and making people re-render
        # to satisfy new bookkeeping would be a defect of the upgrade.
        findings.add(
            "delivery-unverified", page["id"],
            "this page was rendered before finished pages were signed, so "
            "there is nothing to check the file against. Re-run `typeset` to "
            "certify it")
        return

    if list(delivery.get("size") or ()) != [page["width"], page["height"]]:
        findings.add(
            "delivery-mismatch", page["id"],
            f"the render was committed at "
            f"{'x'.join(str(n) for n in delivery.get('size') or ('?', '?'))} "
            f"and the page is now {page['width']}x{page['height']}")

    for name, relative in (("final", final), ("clean", page.get("clean")),
                           ("writable", page.get("writable"))):
        recorded = delivery.get(name)
        if not recorded:
            continue
        if not relative:
            findings.add(
                "delivery-mismatch", page["id"],
                f"the render committed a {name} page and the document no "
                f"longer names one. Re-run `typeset`")
            continue
        path = root / relative
        if not path.exists():
            findings.add(
                "delivery-mismatch", page["id"],
                f"{relative} was part of the finished render and is gone")
        elif ir.sha256_file(path) != recorded:
            findings.add(
                "delivery-mismatch", page["id"],
                f"{relative} is not the file this page was finished with — "
                f"it was replaced after `typeset` ran. Re-run `typeset`, or "
                f"restore the page it rendered")


def check_document(doc_path: str | Path, *, strict: bool = False,
                   limit: int | None = 60) -> dict[str, Any]:
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
    # Only what the render depends on. A previous session's `export` is not a
    # prerequisite of checking the current pages, and reporting it blocked a
    # corrected chapter from being verified before it was packaged again.
    for stage, reason in stages.stale_stages(doc, needed_for="typeset").items():
        # `typeset` is the one that ships a wrong page: the render on disk was
        # made from Persian somebody has since corrected. The others are
        # reported for the same reason at a lower cost.
        findings.add("stale-stage", stage,
                     f"the `{stage}` result is out of date — {reason}. "
                     f"Re-run `{stage}` before publishing")
    for page in doc["pages"]:
        for region in page.get("regions", []):
            if region.get("dropped") or region.get("keep"):
                continue          # an explicit decision IS an outcome
            if region.get("erase"):
                # "Remove this and put nothing back" is finished when the
                # cleaner has acted. It lived in the region's review notes and
                # in the census, and nothing that gated publication read it.
                if region.get("clean_status") not in ("cleaned",):
                    findings.add(
                        "erase-unfinished", region["id"],
                        "this region is marked for erasure and the cleaner has "
                        "not acted on it. Run `clean` before publishing")
                continue
            if not (region.get("target_text") or "").strip():
                continue          # `untranslated-region` already covers this
            if not ir.translatable(region, policy):
                # The same question `typeset` asks. A sound effect under
                # `--sfx-policy keep` stays in the artwork by decision, and
                # demanding a render for it makes the gate fire on correct
                # work — which is how a gate teaches people to ignore it.
                continue
            if policy in ("bilingual", "annotate") and region["kind"] == "sfx":
                continue          # `annotation-unplaced` covers the gloss
            status = (region.get("typeset") or {}).get("status")
            if status != "ok":
                # A page file existing proves a page was written. It does not
                # prove that THIS region's Persian is on it, and a region whose
                # render overflowed or was never attempted shipped inside a
                # page that looked finished.
                findings.add(
                    "region-not-rendered", region["id"],
                    f"this region has approved Persian and its render is "
                    f"{status or 'missing'}. Run `typeset`, or shorten the "
                    f"line until it fits")

    for _page, region in ir.iter_regions(doc):
        if region.get("clean_status") == "refused":
            # `clean` had no repair for a solid free-lettering patch and left
            # the original lettering on the page. It was recorded in the
            # region's review notes and nowhere a gate looked, so the chapter
            # was approved with the source text still in the artwork.
            findings.add(
                "clean-refused", region["id"],
                "the artwork here was never repaired — `clean` had no repair "
                "for this patch. Give it `--external`, a working `--provider`, "
                "or re-run `mask --free-lettering glyphs` for this page")

    for page in doc["pages"]:
        for gloss in page.get("annotations") or []:
            # `bilingual` and `annotate` promise the original AND the Persian.
            # Nothing here reserves a place for the second one, so it is held
            # rather than printed over the first.
            findings.add(
                "annotation-unplaced", gloss["region"],
                f"a {meta.get('sfx_policy')} gloss was produced and has "
                f"nowhere to go: {gloss['fa'][:40]}. Place it by hand, or use "
                f"`--sfx-policy translate` to replace the effect instead")

    for _page, region in ir.iter_regions(doc):
        full = (region.get("target_full") or "").strip()
        shown = (region.get("target_text") or "").strip()
        if full and full != shown and "compressed-variant" not in (
                region.get("review_ack") or []):
            # Not a judgement about the shortening — only a person can make
            # that one. The pair is surfaced so it is made, instead of the
            # shorter line quietly becoming the translation.
            findings.add(
                "compressed-variant", region["id"],
                f"this line was shortened to fit: {shown[:40]!r} stands for "
                f"{full[:60]!r}. Read both, then `reviewed: compressed-variant`")

    conflict = ir.sfx_conflict(meta)
    if conflict:
        findings.add("policy-conflict", "meta", conflict)
    for stage, reason in stages.unverified_stages(doc).items():
        # A warning, not an error. A chapter finished by an older build is not
        # evidence of anything wrong, and demanding it be translated again to
        # satisfy new bookkeeping would be a defect of the upgrade.
        findings.add("stage-unverified", stage, reason)

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
        # An erase box is ink to remove, not text to read: a watermark has no
        # place in the order a reader takes the balloons in. It carried the
        # constructor's zero, and the contract then failed on every page that
        # had been marked — so the gate fired on correct work, which is how a
        # gate teaches people to ignore it.
        orders = [region.get("reading_order") or 0
                  for region in page.get("regions", [])
                  if not region.get("dropped") and not region.get("erase")]
        if orders and (min(orders) < 1 or len(set(orders)) != len(orders)):
            findings.add(
                "reading-order-broken", page["id"],
                f"reading order is missing or repeated on this page: {sorted(orders)[:12]}",
            )

        # Everything below sat behind `if final:`, so a chapter whose pages
        # had never been rendered skipped every artwork check and answered
        # `ok: true` — under `--strict` as well — while carrying nine
        # translated regions and no output at all. Draft work is legitimate;
        # calling it finished is not.
        wants_render = any(
            (region.get("target_text") or "").strip()
            for region in page.get("regions", [])
            if not region.get("dropped")
        )
        final = page.get("final")
        if wants_render and not (final and (root / final).exists()):
            findings.add(
                "page-not-rendered", page["id"],
                "this page carries Persian that has never been drawn onto "
                "it; run `typeset` before calling the chapter finished",
            )
        if final:
            final_path = root / final
            if not final_path.exists():
                findings.add("page-missing", page["id"], f"{final} is gone")
            else:
                _certify_delivery(findings, root, page, final)
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
                elif region["kind"] == "sfx" and not region.get("keep"):
                    # An explicit `keep: yes` is a decision the reader made
                    # about this one region, not the global policy leaking
                    # through. Warning on it reports a choice as an omission,
                    # and under a `translate` policy that is every kept sign
                    # and logo on the page.
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
            # `…`, `!!!`, `؟` and a numeric-only balloon carry no word in any
            # script, so there is nothing in them to have translated. They
            # were filed as `not-persian`, which sends a translator to fix
            # something already right. Anything with a letter in it is still
            # judged, so an English sentence left in place is still caught.
            lexical = sum(counts.values()) > 0
            if (target_language == "fa" and lexical
                    and not ir.looks_like(target, "fa")):
                findings.add("not-persian", region["id"],
                             f"target text is not Persian: {target[:40]}")

            # A `zwnj-review` the reader has settled — they confirmed the
            # two words really are two words — must not be demanded again
            # on every run. Asking forever leaves two ways out: make the
            # unsafe edit, or stop running the gate.
            for issue in falint.lint_text(
                    target, acknowledged=region.get("review_ack") or ()):
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

    # `limit=None`: the default caps the list for display, and filing from
    # the capped list reported a chapter with 50 drifting regions as having
    # 30. The totals are computed from what is filed.
    drift = glossary_module.check(doc_path, limit=None)
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
        # `limit` caps the list for a human reading it. Every total above is
        # computed from the full collection, and a caller that has to DECIDE
        # something passes `limit=None`: filing from the capped list reported a
        # document with 82 errors as having 60, and published the other 22.
        "findings": (errors + warnings)[:limit] if limit else errors + warnings,
        "truncated": bool(limit) and len(errors) + len(warnings) > limit,
        "strict": strict,
    }



def publication_preflight(doc_path: str | Path) -> dict[str, Any]:
    """May this chapter be published, and if not, why not.

    One answer, so that `qa` and `export` cannot disagree. They did: `export`
    asked its own narrower question — is there a rendered file for every page
    that wants one — and a chapter whose render was stale, whose lines had
    overflowed, or whose erasures had never been cleaned went straight into a
    package without the gate ever running.
    """
    report = check_document(doc_path, limit=None)
    blocking = [item for item in report["findings"]
                if item["severity"] == "error"]
    return {
        "ok": not blocking,
        "blocking": blocking[:20],
        "blocking_count": len(blocking),
        "next": ("run `qa --doc <document>` for the whole list, fix what it "
                 "names, and export again. `--draft` ships what is there now "
                 "and says so." if blocking else None),
    }


def check_package(package: str | Path, doc_path: str | Path) -> dict[str, Any]:
    """Kept here because `qa package` is where every caller looks for it."""
    from package import check_package as _check

    return _check(package, doc_path)


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic qa", description="Gate the work before it ships."
    )
    parser.add_argument("action", choices=["check", "package", "visual"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--file", default=None, help="the exported package")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as blocking")
    parser.add_argument("--provider", default=None,
                        help="visual-QA provider name, for `visual`")
    args = parser.parse_args(argv)

    if args.action == "visual":
        if not args.provider:
            parser.error("visual needs --provider")
        ir.emit(visual_review(args.doc, provider=args.provider))
        # Advisory by definition: it reports, it never gates. `check` is the
        # gate, and a model's opinion must not be able to fail a build.
        return 0
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
