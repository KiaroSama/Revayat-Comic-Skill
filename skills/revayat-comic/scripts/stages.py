"""Stage bookkeeping: what each page was made from, and what that makes stale.

Every stage stamped that it had run and nothing ever asked whether the answer
still held. Correct one approved Persian line and the finished page rendered
from the old one stayed on disk, stamped `typeset`, and shipped. Re-run `masks`
with a different polarity and the cleaned artwork underneath was from the
previous masks. Neither left a mark anywhere.

Three things decide the shape of this module:

**Identity is the inputs, not a counter.** The first version numbered the
stamps and compared the numbers, which broke twice over: a re-run that produced
an identical summary kept its old number, so `masks -> clean -> masks -> clean`
left `clean` permanently stale however many times it ran; and a number says
nothing about *what* was consumed. Here a stage records a `revision` — a hash of
the facets it reads, the options it ran with, and the revisions of the upstream
work it consumed. Re-running with identical inputs recomputes an identical
revision, so the document is byte-identical; re-running after a real change
records the new upstream revision, which is what ends the loop.

**Per page.** `mask --pages p0003` is an ordinary thing to do, and a
document-wide hash called the other forty pages freshly masked because one was.

**Named facets, not one document hash.** Correcting a Persian line has to
invalidate the render and must NOT invalidate the detection that produced the
boxes. `geometry` and `render` are separate for the same reason: a worksheet
reply is filed against ids, boxes, kinds and orientations and only those, while
a mask also depends on polarity, the traced balloon, the panel and the reading
order — folding them together would tell a reader their finished translation
was stale because somebody corrected a polarity.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pageir as ir

#: Bumped when a facet's definition changes, so every stamp written by an older
#: build is recognised as unverified rather than silently compared against a
#: hash that now means something else.
SCHEME = "3"

#: Facets each stage reads. `policy` and `constraints` are document-wide; the
#: rest are per page.
STAGE_INPUTS: dict[str, tuple[str, ...]] = {
    "detect": ("page",),
    # Marking precedes masking and cleaning: it reads the artwork and adds
    # regions to it, and consumes no other stage's output.
    "watermark": ("page",),
    "crops": ("geometry",),
    "ocr": ("geometry",),
    # The worksheet header carries the glossary table and the title policy.
    "worksheet": ("geometry", "constraints"),
    # Translation reads the glossary as a hard constraint and the title policy
    # as a standing decision. It depended on neither, so locking a name left
    # every line translated before the lock looking current.
    "translate": ("geometry", "source", "constraints"),
    "glossary": ("source", "text"),
    "falint": ("text",),
    "masks": ("render", "policy"),
    "clean": ("render", "policy", "masked"),
    "typeset": ("render", "text", "policy"),
    "export": ("render", "text", "policy"),
}

#: Which stage's OUTPUT each stage consumes. Acyclic, and `watermark` is absent
#: on purpose: it was recorded as depending on `typeset`, which is backwards —
#: a mark is placed before the page is masked, cleaned or set.
STAGE_NEEDS: dict[str, tuple[str, ...]] = {
    "crops": ("detect",),
    "ocr": ("detect", "crops"),
    "worksheet": ("detect",),
    "translate": ("detect",),
    "masks": ("detect",),
    "clean": ("masks",),
    "typeset": ("clean",),
    "export": ("typeset",),
}


def prerequisites(stage: str) -> set[str]:
    """Every stage whose output `stage` transitively consumes."""
    seen: set[str] = set()
    queue = [stage]
    while queue:
        for need in STAGE_NEEDS.get(queue.pop(), ()):
            if need not in seen:
                seen.add(need)
                queue.append(need)
    return seen


def _stable(value: Any) -> str:
    """A deterministic rendering of a mapping or a nested structure."""
    return json.dumps(value or {}, sort_keys=True, ensure_ascii=False,
                      default=str)


def _region_text(region: dict[str, Any]) -> str:
    """The decisions a render is made from, under the names the document uses.

    These read `target_text` and `dropped`. They read `translation` and `drop`
    for one day — names no region has ever carried — so every region's Persian
    hashed as the same empty string and correcting an approved line changed
    nothing at all. The test meant to catch it invented the same two fields in
    its own fixture and agreed with the bug.
    """
    return "|".join([
        region["id"],
        region.get("target_text") or "",
        region.get("target_full") or "",
        str(bool(region.get("dropped"))),
        str(bool(region.get("keep"))),
        str(bool(region.get("erase"))),
        str(region.get("fill") or "none"),
    ])


def _region_render(region: dict[str, Any]) -> str:
    """What a mask and a set balloon are measured from.

    The ACTIONS are in here as well as in `text`, and they answer a different
    question in each: `text` asks what the page says, this asks what the
    cleaner is allowed to touch. A region the reader kept or dropped gets no
    mask at all, so flipping either one changes the authority — and while they
    lived only in `text`, masking and cleaning were never invalidated by the
    decision that governs them.
    """
    return "|".join([
        region["id"],
        str(bool(region.get("dropped"))),
        str(bool(region.get("keep"))),
        str(bool(region.get("erase"))),
        ",".join(str(value) for value in region["bbox"]),
        region["kind"],
        region["orientation"],
        str(region.get("polarity") or ""),
        # The traced balloon decides the writable interior, so a hand-drawn box
        # that gained one is a different render — not a different worksheet.
        _stable(region.get("balloon")),
        _stable(region.get("polygon") or []),
        str(region.get("reading_order")),
        str(region.get("panel")),
    ])


def _page_facet(page: dict[str, Any], name: str) -> str:
    """A hash of one named part of ONE page."""
    digest = hashlib.sha256()
    digest.update(f"{page['id']}|{page['sha256']}|"
                  f"{page.get('width')}x{page.get('height')}|".encode("utf-8"))
    if name == "page":
        pass                      # the artwork and its dimensions, nothing else
    elif name == "geometry":
        digest.update(ir.page_fingerprint(page).encode("utf-8"))
    elif name == "render":
        for region in page.get("regions", []):
            digest.update((_region_render(region) + "|").encode("utf-8"))
    elif name == "source":
        for region in page.get("regions", []):
            digest.update(
                f"{region['id']}|{region.get('source_text') or ''}|"
                .encode("utf-8"))
    elif name == "text":
        for region in page.get("regions", []):
            digest.update((_region_text(region) + "|").encode("utf-8"))
    elif name == "masked":
        # What `mask` produced and `clean` consumes. `clean` already depends on
        # the masks stage's revision, which covers a rebuild — this covers the
        # page's mask mode, options and assets being changed under it without
        # one, which is the case where the cleaner reaches for the tier a solid
        # patch must never reach.
        digest.update(
            f"{page.get('free_lettering_mask')}|"
            f"{_stable(page.get('mask_options'))}|{page.get('mask')}|"
            f"{page.get('mask_coverage')}|".encode("utf-8"))
        for region in page.get("regions", []):
            digest.update(
                f"{region['id']}|{region.get('mask')}|"
                f"{_stable(region.get('mask_box'))}|".encode("utf-8"))
    else:  # pragma: no cover - a facet named in the table but not built here
        raise KeyError(name)
    return digest.hexdigest()


def _policy_facet(doc: dict[str, Any]) -> str:
    """The standing decisions a RENDER obeys.

    Deliberately narrow. This once held the glossary as well, and the glossary
    is a translation constraint that masking and cleaning know nothing about —
    so running `glossary scan`, which is the stage whose whole job is to fill
    that table in, reported the masks of every page as out of date. A gate that
    fires on the correct order of operations is a gate people learn to ignore.
    """
    meta = doc.get("meta", {})
    digest = hashlib.sha256()
    for key in ("sfx_policy", "free_lettering_mask", "reading_direction"):
        digest.update(f"{key}={meta.get(key)!r}|".encode("utf-8"))
    return digest.hexdigest()


def _constraints_facet(doc: dict[str, Any]) -> str:
    """The standing decisions a TRANSLATION obeys.

    The glossary, the title policy and the two languages. A change here
    invalidates the worksheet that prints the table and the machine translation
    that was constrained by it — and nothing downstream of the words, because
    what a render depends on is the words themselves.
    """
    meta = doc.get("meta", {})
    digest = hashlib.sha256()
    for key in ("target_language", "source_language"):
        digest.update(f"{key}={meta.get(key)!r}|".encode("utf-8"))
    digest.update(f"title={_stable(ir.title_policy(meta))}|".encode("utf-8"))
    # The canonical location, which is `glossary.entries`. `meta.glossary` was
    # hashed instead — a key nothing writes — so locking a name or changing an
    # approved spelling left every translation looking current.
    entries = (doc.get("glossary") or {}).get("entries") or {}
    for term in sorted(entries):
        entry = entries[term] if isinstance(entries[term], dict) else {}
        digest.update(
            f"{term}={entry.get('target') or ''}@{entry.get('version') or 1}"
            f"{'!' if entry.get('locked') else '?'}|".encode("utf-8"))
    return digest.hexdigest()


def page_revision(doc: dict[str, Any], stage: str, page: dict[str, Any], *,
                  options: Any = None,
                  stages: dict[str, Any] | None = None) -> str:
    """The identity this stage's answer for this page would have right now.

    Content-derived, so it survives a copy between machines, and so that a
    stage which re-runs and consumes a *changed* upstream records that even
    when its own summary comes out identical. Counting runs could not express
    that, and `masks -> clean -> masks -> clean` never became fresh.
    """
    known = doc.get("stages") if stages is None else stages
    digest = hashlib.sha256()
    digest.update(f"scheme={SCHEME}|stage={stage}|".encode("utf-8"))
    for facet in STAGE_INPUTS.get(stage, ()):
        if facet == "policy":
            value = _policy_facet(doc)
        elif facet == "constraints":
            value = _constraints_facet(doc)
        else:
            value = _page_facet(page, facet)
        digest.update(f"{facet}={value}|".encode("utf-8"))
    digest.update(f"options={_stable(options)}|".encode("utf-8"))
    for need in sorted(STAGE_NEEDS.get(stage, ())):
        upstream = ((known or {}).get(need) or {}).get("pages") or {}
        digest.update(
            f"{need}={upstream.get(page['id']) or 'unknown'}|".encode("utf-8"))
    return digest.hexdigest()


def stamp_stage(doc: dict[str, Any], stage: str, detail: dict[str, Any], *,
                options: Any = None, pages: Any = None) -> None:
    """Record that a stage ran, and exactly what each page it touched ran on.

    `options` are the effective options of the run — the ones that change its
    output, such as a mask's grow or a typeset font. Two runs differing only in
    an option produced different pixels and must not share an identity.

    `pages` is the subset that actually ran; every other page keeps the
    revision it already had, so `mask --pages p0003` no longer claims the other
    forty were freshly masked.
    """
    recorded = doc.setdefault("stages", {})
    previous = recorded.get(stage) or {}
    selected = None if not pages else set(pages)
    current = {page["id"] for page in doc.get("pages", [])}
    per_page = {pid: rev for pid, rev in (previous.get("pages") or {}).items()
                if pid in current}
    # The options belong to the PAGE that ran with them, not to the stage. One
    # dict for the whole record meant `mask --pages p0001 --grow 3` followed by
    # `mask --pages p0002 --grow 9` left grow=9 on the record, and page 1's
    # revision — computed with grow=3 — never matched again. Masking two pages
    # differently is the ordinary reason this feature exists.
    per_options = {pid: opts
                   for pid, opts in (previous.get("page_options") or {}).items()
                   if pid in current}
    for page in doc.get("pages", []):
        if selected is None or page["id"] in selected:
            per_page[page["id"]] = page_revision(doc, stage, page,
                                                 options=options)
            per_options[page["id"]] = options if options is not None else {}
    recorded[stage] = {
        "scheme": SCHEME,
        "pages": per_page,
        "page_options": per_options,
        # What each page consumed from upstream, so "why is this stale" has an
        # exact answer instead of a guess: an upstream that moved is a
        # different instruction from an input of this page's own that moved.
        "needs": {
            need: {pid: (((recorded.get(need) or {}).get("pages") or {})
                         .get(pid) or "unknown")
                   for pid in per_page}
            for need in STAGE_NEEDS.get(stage, ())
        },
        # The last run's options, for a human reading the document. The value
        # every freshness decision uses is `page_options`.
        "options": options if options is not None else {},
        **detail,
    }
    # The counter the first version kept. Left behind by an upgrade it is
    # bookkeeping nothing reads, and it would make every document compare
    # unequal to a freshly built one.
    doc.get("meta", {}).pop("stage_seq", None)


def _why(stage: str, page_id: str, record: dict[str, Any],
         stages: dict[str, Any]) -> str:
    """The shortest true sentence about why this page's record no longer holds."""
    if page_id not in (record.get("pages") or {}):
        return "it has not run for"
    consumed = record.get("needs") or {}
    for need in sorted(STAGE_NEEDS.get(stage, ())):
        was = (consumed.get(need) or {}).get(page_id)
        now = ((stages.get(need) or {}).get("pages") or {}).get(page_id)
        if was != now:
            return f"`{need}` has run again since, for"
    return "the inputs changed after it ran, for"


def unverified_stages(doc: dict[str, Any]) -> dict[str, str]:
    """Stages stamped by a build whose freshness scheme is not this one.

    Unknown is not stale. A document written before this bookkeeping existed
    carries no revision, and refusing to publish it — or worse, demanding the
    chapter be translated again — would turn an upgrade into a defect. It is
    reported so somebody can re-run the cheap stages once and get a real answer.
    """
    return {
        stage: (f"stamped by an older build (freshness scheme "
                f"{record.get('scheme') or 'none'}, this one is {SCHEME}); "
                f"re-run `{stage}` once to establish it")
        for stage, record in (doc.get("stages") or {}).items()
        if record.get("scheme") != SCHEME or not record.get("pages")
    }


def stale_pages(doc: dict[str, Any], stage: str) -> list[str]:
    """Which pages this stage's recorded answer no longer describes."""
    stages = doc.get("stages") or {}
    record = stages.get(stage) or {}
    if record.get("scheme") != SCHEME or not record.get("pages"):
        return []                 # unverified, not stale
    consumed = record["pages"]
    per_options = record.get("page_options") or {}
    fallback = record.get("options")
    out = []
    for page in doc.get("pages", []):
        was = consumed.get(page["id"])
        # This page's own options. `record["options"]` is only the fallback for
        # a stamp written before they were recorded per page.
        options = per_options.get(page["id"], fallback)
        if was is None or was != page_revision(doc, stage, page,
                                               options=options,
                                               stages=stages):
            out.append(page["id"])
    return out


def stale_stages(doc: dict[str, Any], *,
                 needed_for: str | None = None) -> dict[str, str]:
    """Stage -> why its recorded result no longer describes this document.

    `needed_for` narrows the answer to the stages that operation actually
    depends on. Publication QA asks about the render; an export from a previous
    session is not a prerequisite of checking the current one, and reporting it
    blocked a chapter from being verified before it was packaged again.
    """
    stages = doc.get("stages") or {}
    wanted = None if needed_for is None else prerequisites(needed_for) | {
        needed_for}
    reasons: dict[str, str] = {}
    for stage in stages:
        if wanted is not None and stage not in wanted:
            continue
        pages = stale_pages(doc, stage)
        if not pages:
            continue
        shown = ", ".join(pages[:4]) + (", …" if len(pages) > 4 else "")
        reasons[stage] = (
            f"{_why(stage, pages[0], stages[stage], stages)} "
            f"{len(pages)} page(s): {shown}")
    return reasons
