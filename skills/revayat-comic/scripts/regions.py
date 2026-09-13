"""What a region's decisions MEAN.

Four questions, asked by five stages, and every one of them used to be answered
somewhere else as well:

* **may the cleaner change these pixels?** `masks` and `clean` each had their
  own copy and they disagreed under `bilingual` — the masker wrote authority
  over an effect the cleaner then left drawn.
* **is Persian owed here?** the worksheet merge asked a narrower version on the
  added-box path, so a box added purely to erase a watermark was reported as
  untranslated work.
* **what terminal state did this region reach?** the census, which exists so
  that "it quietly disappeared" cannot be one of the answers.
* **what did a STAGE observe about it?** separate from what the reader wrote,
  because a worksheet is a picture of the page in both directions and a merge
  that replaces the reader's notes must not erase the cleaner's record.

Kept apart from `pageir` because `pageir` is the document — reading it, writing
it, walking it, hashing it — and none of the stages asking these questions
cares how a document is saved. `pageir` re-exports every name here, so existing
callers are unaffected.
"""

from __future__ import annotations

from typing import Any


#: Sound-effect policies that leave the effect drawn in the artwork. `keep`
#: says nothing more; `bilingual` and `annotate` add the Persian somewhere else
#: and still leave the original where the artist drew it.
SFX_KEEP_POLICIES = frozenset({"keep", "bilingual", "annotate"})


#: What a page carries because work was done ON its regions. Every one of them
#: is meaningless once the last region is gone.
DERIVED_FROM_REGIONS = ("clean", "cleaning", "final", "writable", "delivery")

#: Most finished first. This is the order `export` resolves a page in, and the
#: scale `required_artifact` is measured against.
ARTIFACT_ORDER = ("final", "clean", "image")


def required_artifact(page: dict[str, Any]) -> str:
    """The LEAST finished file this page's own decisions allow it to ship.

    `export` ships the most finished file that exists, and that fallback is
    silent. A page whose watermark was erased and whose cleaned image then went
    missing shipped the original — the stamp back on it, the reader's approved
    erasure undone — counted as an untouched page and reported as nothing at
    all. The render had a gate for this (`page-not-rendered`); erasure and
    cleaning had none, because the gate was written around Persian.

    Four kinds of page, one scale:

    * carries Persian -> `final`, because a render is what puts it there;
    * the cleaner acted -> `clean`, whether or not anything was written back;
    * kept by policy, dropped, or no regions at all -> `image`, the immutable
      page that was imported.

    `fill` is the proof the cleaner acted, for the same reason `region_state`
    uses it: a reader's intent to erase is not evidence that anything was
    erased.
    """
    live = [region for region in page.get("regions", [])
            if not region.get("dropped")]
    if any((region.get("target_text") or "").strip() for region in live):
        return "final"
    if any(region.get("fill") not in (None, "none", "keep") for region in live):
        return "clean"
    return "image"


def shipped_artifact(root: "Any", page: dict[str, Any]) -> "Any":
    """The most finished version of this page that exists, and which it is.

    `(Path, key)`, or `None` when the page has no image at all. One definition,
    because `export` resolving it one way and the gate assuming another is how
    a fallback becomes invisible.
    """
    for key in ARTIFACT_ORDER:
        relative = page.get(key)
        if relative and (root / relative).exists():
            return root / relative, key
    return None


def restore_blank_page(page: dict[str, Any]) -> list[str]:
    """The terminal state of a page whose last region has been removed.

    A page with no regions has nothing to repair and nothing to draw, so what a
    reader gets is the page that was imported. `clean` and `typeset` simply
    SKIPPED such a page, which left the previous run's repaired image and
    rendered text on disk and still referenced — a page claiming work that its
    own contents say was never needed.

    Nothing is invented here: no text, no placement, no substitute image. The
    references derived from regions are dropped, so `export` ships the
    immutable original, which is the only honest answer.

    Returns what it cleared, so a caller can report a transition rather than a
    silent rewrite. Idempotent: a page already in this state clears nothing.
    """
    cleared = []
    for key in DERIVED_FROM_REGIONS:
        if page.pop(key, None) is not None:
            cleared.append(key)
    if page.get("annotations"):
        page["annotations"] = []
        cleared.append("annotations")
    return cleared


def add_audit(region: dict[str, Any], note: str) -> None:
    """Record something a STAGE observed about this region.

    Separate from `review`, which holds what the READER wrote, and the two were
    one list. That made a worksheet unable to be a faithful picture of the page
    in both directions: writing the reply back replaced the list and erased
    `clean`'s refusal record with it, and not replacing it meant a note the
    reader deleted came back on the next merge.

    The sheet prints these as comments, so a reader sees them and the parser
    never reads one back as an answer.
    """
    notes = region.setdefault("audit", [])
    if note not in notes:
        notes.append(note)


def may_be_edited(region: dict[str, Any], sfx_policy: str = "keep") -> bool:
    """Whether the cleaner may change this region's pixels at all.

    The other half of `translatable`, and a different question: that one asks
    whether Persian is owed here, this one asks who owns the pixels. They
    disagree on an erasure (nothing is owed, the pixels go) and on a sound
    effect under `bilingual` (Persian is owed, and the effect stays drawn).

    It lives here because two modules were answering it separately and drifting:
    the masker wrote authority over effects `clean` would never touch, and when
    that was corrected `clean` stopped recognising them at all. A region the
    cleaner may not edit gets no mask — masking it puts artwork inside the area
    the cleaner may rewrite and inside the denominator the preservation proof
    divides by.
    """
    if region.get("erase"):
        # "Remove this and put nothing back" is a decision to touch the pixels,
        # and it outranks the policy: an SFX policy is about lettering that
        # belongs to the artwork, not about a stamp put on top of it.
        return True
    if region.get("dropped") or region.get("keep"):
        return False
    if region["kind"] == "sfx":
        return sfx_policy not in SFX_KEEP_POLICIES
    return True


def translatable(region: dict[str, Any], sfx_policy: str = "keep") -> bool:
    """Whether this region is expected to end up carrying Persian.

    An SFX under the ``keep`` policy is deliberately left in the artwork, so it
    is not a hole in the translation and QA must not report one.
    """
    if region.get("keep"):
        # The reader looked at it and said: this is real lettering, leave it in
        # the artwork. Distinct from `dropped`, which says there is no text here
        # — using `drop` for this made the census classify real text as a false
        # detection, which is the one thing the census exists to rule out.
        return False
    if region.get("erase"):
        # Marked for removal with nothing put back — a watermark, a site stamp.
        # It is not a hole in the translation, so QA must not report one.
        return False
    if region["kind"] == "sfx":
        return sfx_policy in {"translate", "bilingual", "annotate"}
    return True


#: Where a region is allowed to end up. Every detected region must reach exactly
#: one of these, and **none of them means "it quietly disappeared"** — which is
#: the point. Completeness is otherwise inferred from a scatter of fields
#: (``dropped``, ``target_text``, ``typeset.status``), and a region that falls
#: between them is invisible to every gate: nothing is missing, no count is
#: wrong, and a balloon simply never got translated.
REGION_STATES = (
    "translated",               # carries Persian
    "kept_by_policy",           # deliberately left as drawn — an SFX under `keep`
    "erased",                   # removed on purpose, with nothing put back
    "dropped_false_detection",  # the reader said there is no text here
    "needs_review",             # seen, not resolved: overflow, or a noted doubt
    "unresolved",               # none of the above — always a QA error
)


def region_state(region: dict[str, Any], sfx_policy: str = "keep") -> str:
    """The one terminal state this region reached. Never guesses in favour."""
    if region.get("dropped"):
        return "dropped_false_detection"

    if region.get("erase"):
        # Erasure is only finished when the cleaner actually acted. `fill` is
        # `keep` when it declined — a solid free-lettering mask with no
        # provider, say — and reporting `erased` off the reader's intent alone
        # would claim a watermark is gone while it is still on the page. That
        # is exactly the "quietly disappeared" failure this census exists to
        # rule out, pointed the other way.
        return "erased" if region.get("fill") not in (None, "none", "keep") \
            else "needs_review"

    typeset = region.get("typeset") or {}
    if typeset.get("status") in {"overflow", "unreliable"}:
        # Two different ways of not being placed, and both need a person.
        # `overflow` is "the words do not fit"; `unreliable` is the typesetter
        # declining to match lettering whose geometry it could not read, which
        # leaves the artwork drawn and the region carrying its target text.
        # Without this the region would report as `translated` on the strength
        # of text that was never put on the page.
        return "needs_review"

    if (region.get("target_text") or "").strip():
        return "translated"

    if not translatable(region, sfx_policy):
        return "kept_by_policy"

    # Seen and questioned by a reader, but left without an answer. That is a
    # different thing from never having been looked at, and it is worth the
    # distinction: one is a decision, the other is a hole.
    if region.get("review") or region.get("audit"):
        return "needs_review"

    return "unresolved"
