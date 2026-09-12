"""Stage bookkeeping: what ran, from what, in what order, and what is stale.

Every stage stamped that it had run and nothing ever asked whether the answer
still held. Correct one approved Persian line and the finished page rendered
from the old one stayed on disk, stamped `typeset`, and shipped. Re-run `masks`
with a different polarity and the cleaned artwork underneath was from the
previous masks. Neither left a mark anywhere, which is what this module exists
to change.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pageir as ir

#: What each stage actually reads. Named facets rather than one document hash,
#: because "did anything change" is the wrong question: correcting a Persian
#: line has to invalidate the render and must NOT invalidate the detection that
#: produced the boxes, and a single hash cannot tell those apart.
STAGE_INPUTS: dict[str, tuple[str, ...]] = {
    "detect": ("pages",),
    "crops": ("geometry",),
    "ocr": ("geometry",),
    "worksheet": ("geometry",),
    "translate": ("geometry", "source"),
    "glossary": ("text",),
    "falint": ("text",),
    "masks": ("geometry", "policy"),
    "clean": ("geometry", "policy"),
    "typeset": ("geometry", "text", "policy"),
    "watermark": ("geometry",),
    "export": ("geometry", "text", "policy"),
}

#: Which stage's OUTPUT each stage consumes. A path in `comic.json` does not
#: change when the file behind it is redrawn, so "has clean run since typeset
#: did" is a question about order, not about content — and the order is what
#: the sequence number on each stamp records.
STAGE_NEEDS: dict[str, tuple[str, ...]] = {
    "crops": ("detect",),
    "ocr": ("detect", "crops"),
    "worksheet": ("detect",),
    "translate": ("detect",),
    "masks": ("detect",),
    "clean": ("masks",),
    "typeset": ("clean",),
    "watermark": ("typeset",),
    "export": ("typeset",),
}


def _facet(doc: dict[str, Any], name: str) -> str:
    """A hash of one named part of the document."""
    digest = hashlib.sha256()
    pages = doc.get("pages", [])
    if name == "pages":
        for page in pages:
            digest.update(f"{page['id']}|{page['sha256']}|".encode("utf-8"))
    elif name == "geometry":
        digest.update(ir.fingerprint(doc).encode("utf-8"))
    elif name in ("source", "text"):
        for page in pages:
            for region in page.get("regions", []):
                digest.update(
                    f"{region['id']}|{region.get('source_text') or ''}|"
                    .encode("utf-8"))
                if name == "text":
                    digest.update("|".join([
                        region.get("translation") or "",
                        str(region.get("drop", False)),
                        str(region.get("keep", False)),
                        str(region.get("erase", False)),
                    ]).encode("utf-8"))
    elif name == "policy":
        meta = doc.get("meta", {})
        for key in ("sfx_policy", "free_lettering_mask", "reading_direction",
                    "target_language", "source_language"):
            digest.update(f"{key}={meta.get(key)!r}|".encode("utf-8"))
        for entry in meta.get("glossary") or []:
            digest.update(f"{entry}|".encode("utf-8"))
    else:  # pragma: no cover - a facet named in the table but not built here
        raise KeyError(name)
    return digest.hexdigest()


def stamp_stage(doc: dict[str, Any], stage: str, detail: dict[str, Any]) -> None:
    """Record that a stage ran, with what it ran against and when.

    `seq` is a plain counter, not a clock: two stages that run inside the same
    second still have an order, and a working folder copied between machines
    keeps it.

    It counts CHANGES, not runs. A stage re-run that produces an identical
    record kept its old number and the counter does not move — running a stage
    twice is an ordinary thing to do, and it must leave the document
    byte-identical and must not tell everything downstream it is now stale.
    """
    meta = doc.setdefault("meta", {})
    stages = doc.setdefault("stages", {})
    record = {
        "fingerprint": ir.fingerprint(doc),
        "inputs": {facet: _facet(doc, facet)
                   for facet in STAGE_INPUTS.get(stage, ())},
        **detail,
    }
    before = stages.get(stage) or {}
    unchanged = {key: value for key, value in before.items() if key != "seq"}
    if unchanged == record and before.get("seq") is not None:
        record["seq"] = before["seq"]
    else:
        meta["stage_seq"] = record["seq"] = int(meta.get("stage_seq") or 0) + 1
    stages[stage] = record


def stale_stages(doc: dict[str, Any]) -> dict[str, str]:
    """Stage -> why its recorded result no longer describes this document.

    The gap this closes: every stage stamped that it had run and nothing ever
    asked whether the answer still held. Correct one approved Persian line and
    the finished page rendered from the old one stayed on disk, stamped
    `typeset`, and shipped. Re-run `masks` with a different polarity and the
    cleaned artwork underneath it was from the previous masks. Neither left a
    mark anywhere.
    """
    stages = doc.get("stages") or {}
    reasons: dict[str, str] = {}
    for stage, record in stages.items():
        recorded = record.get("inputs")
        if recorded is None:
            # Stamped by a build that recorded no inputs. Unknown is not
            # stale: refusing to publish over a missing field would make an
            # upgrade look like a defect.
            continue
        changed = sorted(facet for facet, value in recorded.items()
                         if _facet(doc, facet) != value)
        if changed:
            reasons[stage] = f"{', '.join(changed)} changed after it ran"
            continue
        seq = record.get("seq")
        if seq is None:
            continue
        for need in STAGE_NEEDS.get(stage, ()):
            upstream = (stages.get(need) or {}).get("seq")
            if upstream is not None and upstream > seq:
                reasons[stage] = f"{need} has run since"
                break
    return reasons
