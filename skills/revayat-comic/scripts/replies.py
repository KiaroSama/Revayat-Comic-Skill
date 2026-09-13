"""Reading a finished worksheet back: the protocol, the parser, the merge of
one page.

`sheet.py` prints the question and this reads the answer. The rule that shapes
every function here is that a reply lands whole or not at all — applying the
sound part of a malformed one left the page in a state nobody wrote, with some
regions carrying the new answer and the rest carrying the old.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pageir as ir

HEADER = re.compile(r"^@@\s+(?P<id>\+?[A-Za-z0-9_#-]+)(?:\s+(?P<rest>.*))?$")
FIELD = re.compile(
    r"^(?P<name>src|fa_full|fa|kind|speaker|propose|note|drop|keep|erase|box"
    r"|polarity|reviewed)"
    r"\s*:\s?(?P<value>.*)$")

#: `box: x y w h`, in the PAGE's own pixels. `overview.png` is drawn at most
#: is drawn at, so a reader can take the numbers straight off it.
BOX = re.compile(r"^\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*$")

FIELDS = ("src", "fa", "fa_full", "kind", "speaker", "propose", "note",
          "drop", "keep", "erase", "box", "polarity", "reviewed")

#: `propose: Anna, the Iron Gate` — a comma in either script separates them.
PROPOSALS = re.compile(r"[,\u060c]")


def _is_comment(raw: str) -> bool:
    """Whether this line is a note to the reader or something a balloon says.

    A leading `#` used to mean comment wherever it appeared, so a balloon
    reading `#1`, or a line continued as `#2 هم هست`, was deleted with no
    word about it anywhere. Restricting comments to the top of a block
    instead was worse: the sheet writes `# panel …` after the fields a
    reader inserts, and those notes were swallowed into whatever field came
    before them, which broke `kind:`, `drop:` and `note:` at once.

    The rule: `#` at column 0 followed by a space or nothing. Every note
    this tool writes looks like that and `#1` does not. A line that really
    must begin with `# ` inside a balloon is written '\\#' — see
    `_unescape`.
    """
    return raw.startswith("#") and (len(raw) == 1 or raw[1] in " \t")


def _unescape(line: str) -> str:
    """A leading '\\#' is a literal `#`, so a balloon can start with one."""
    return line[1:] if line.startswith("\\#") else line


def parse_worksheet(text: str) -> dict[str, dict[str, str]]:
    """``{region id: {field: value}}``. Unknown lines continue the last field."""
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    field: str | None = None

    for raw in text.splitlines():
        header = HEADER.match(raw)
        if header:
            region_id = header.group("id")
            current = blocks.setdefault(region_id, {"_seen": 0})
            current["_seen"] = int(current.get("_seen", 0)) + 1
            # `@@ <id> <kind> <orientation>`. For an existing region these are
            # echoed back from the document and ignored; for an added one they
            # are the only place the kind is written, so they are kept.
            words = (header.group("rest") or "").split()
            if words and words[0] in ir.REGION_KINDS:
                current["_kind"] = words[0]
            if len(words) > 1 and words[1] in ir.ORIENTATIONS:
                current["_orientation"] = words[1]
            field = None
            continue
        if current is None:
            continue
        if _is_comment(raw):
            continue
        match = FIELD.match(raw)
        if match:
            field = match.group("name")
            if field in current:
                # Two `fa:` lines in one block silently kept the last one, so a
                # reader who pasted a correction under the original shipped the
                # original and never saw it happen.
                current.setdefault("_duplicate_fields", "")
                current["_duplicate_fields"] += f"{field},"
            current[field] = _unescape(match.group("value").strip())
            continue
        if field is not None:
            # A continuation line. Keep the newline: a balloon that breaks its
            # own line does so for a reason, and the typesetter honours it.
            current[field] = (current[field] + "\n"
                              + _unescape(raw.strip())).strip()
    return blocks


#: The three answers that are not a translation. Exactly one may be given.
ACTIONS = ("drop", "keep", "erase")


def _asked(block: dict[str, str], name: str) -> bool:
    return block.get(name, "").strip().lower() in {"yes", "true", "1"}


def _set_or_clear(region: dict[str, Any], block: dict[str, str],
                  field: str, key: str) -> None:
    """A field the reader wrote applies; a field they emptied clears.

    Absent and present-but-empty were the same thing, so `speaker:` with
    nothing after it could not take back a name typed on the wrong balloon —
    the only way out was to edit `comic.json` by hand.
    """
    if field not in block:
        return
    value = block[field].strip()
    if value:
        region[key] = value
    else:
        region.pop(key, None)


def _apply(region: dict[str, Any], block: dict[str, str],
           report: dict[str, list[str]]) -> bool:
    # Checked together, before any of them is acted on. `drop` returned
    # immediately, so `drop: yes` beside `keep: yes` or `erase: yes` never
    # reached the conflict check at all and the page merged as if the reader
    # had asked for one thing.
    asked = [name for name in ACTIONS if _asked(block, name)]
    if len(asked) > 1:
        report["conflicting_actions"].append(
            f"{region['id']}: " + " and ".join(f"`{name}: yes`" for name in asked))
        return False

    if "drop" in asked:
        region["dropped"] = True
        region["target_text"] = ""
        region["source_text"] = ""
        # Forget what an earlier run did to it. A region dropped after it had
        # already been cleaned and typeset kept that run's `fill` and `typeset`
        # records, and those stale values then spoke for a region nobody was
        # cleaning any more.
        region["fill"] = "none"
        region["typeset"] = {}
        report["dropped"].append(region["id"])
        return True

    # Real lettering the reader wants left in the artwork — a shop sign, a
    # logo, an effect the policy would otherwise translate. `drop` would have
    # said "there is no text here", which is a different claim and made
    # `stats.states` count real text as a false detection. It still runs
    # through the shared metadata below: a kept region can be reclassified,
    # given a speaker and annotated like any other, and returning early here
    # silently threw all three away.
    kept = "keep" in asked
    if kept:
        region["keep"] = True
    else:
        region.pop("keep", None)

    # Ink the reader wants gone with nothing put in its place — a watermark, a
    # site stamp, a scan credit. The three existing answers all say something
    # else: `drop` claims there is no ink there, `keep` leaves it drawn, and a
    # `fa:` line puts Persian over it. None of them is "remove this".
    erased = "erase" in asked
    if erased:
        region["erase"] = True
    else:
        region.pop("erase", None)

    source = block.get("src", "").strip()
    target = block.get("fa", "").strip()
    kind = block.get("kind", "").strip().lower()
    note = block.get("note", "").strip()

    if kind:
        if kind not in ir.REGION_KINDS:
            report["bad_kind"].append(f"{region['id']}: {kind}")
        elif kind != region["kind"]:
            region["kind"] = kind
            report["reclassified"].append(f"{region['id']} -> {kind}")
    _set_or_clear(region, block, "speaker", "speaker")
    if "reviewed" in block:
        # Lint codes the reader has looked at and settled, so the gate stops
        # asking. `reviewed: zwnj-review` on a line where `می` really is wine.
        codes = [code.strip() for code
                 in PROPOSALS.split(block["reviewed"]) if code.strip()]
        if codes:
            region["review_ack"] = codes
        else:
            region.pop("review_ack", None)
    if "propose" in block:
        # Replaces rather than accumulates, like every other field here: a
        # worksheet is a picture of the page, and a merge run twice must not
        # leave the same name in the list twice. An empty `propose:` clears it.
        proposed = [name.strip() for name
                    in PROPOSALS.split(block["propose"]) if name.strip()]
        if proposed:
            region["proposed"] = proposed
        else:
            region.pop("proposed", None)
    if note:
        # Only once. Merging the same reply twice is an ordinary thing to do —
        # and it appended the note again each time, so a page re-merged three
        # times carried the same sentence three times.
        notes = region.setdefault("review", [])
        if note not in notes:
            notes.append(note)

    region["source_text"] = source
    region["dropped"] = False

    if kept:
        region["target_text"] = ""
        region["fill"] = "none"
        region["typeset"] = {}
        # A keep IS a review — the reader looked at the region and decided.
        # Without this the decision reads as "never reviewed": `qa` warns
        # `low-confidence-region` on it and a later `detect` run is free to
        # renumber it away.
        region["locked"] = True
        report["kept"].append(region["id"])
        return True

    if erased:
        region["target_text"] = ""
        region["typeset"] = {}
        # Deliberately NOT `fill = "none"`. That is what `keep` sets to tell the
        # cleaner to leave the pixels alone, and it is the opposite of what this
        # asks for: an erase region goes through the ordinary tier ladder —
        # flat fill, classical inpaint, then a provider — like any other masked
        # region. Leaving `fill` unset is what lets `clean` pick.
        region["locked"] = True
        report["erased"].append(region["id"])
        return True

    region["target_text"] = target
    # The meaning the line in `fa:` was shortened FROM. Naturalisation and
    # compression are different jobs: a balloon that would not fit is a layout
    # problem first, and when it does become a wording problem the full version
    # has to survive somewhere a reviewer can see it. A compression nobody can
    # compare is a compression nobody can check.
    _set_or_clear(region, block, "fa_full", "target_full")
    # Locking stops a later `detect` run from renumbering a region a human or a
    # reading model has already committed a translation to.
    region["locked"] = bool(source or target)
    return bool(target)


def _next_region_id(page: dict[str, Any]) -> str:
    """The next free `pNNNNrMMM` on this page."""
    used = 0
    for region in page.get("regions", []):
        _, _, tail = region["id"].partition("r")
        if tail.isdigit():
            used = max(used, int(tail))
    return f"{page['id']}r{used + 1:03d}"


def _add_region(page: dict[str, Any], slug: str, block: dict[str, str],
                report: dict[str, Any]) -> bool:  # noqa: C901 - one flow, read top to bottom
    """Create a region the detector never found, from a `box:` the reader read.

    The counterpart to `drop`, and the page needs both. Detection returns the
    balloons it is sure of; free lettering it is not sure of at all, adjacent
    balloons sometimes come back welded into one region, and a panel is
    occasionally taken for a balloon and swallows everything drawn inside it.
    Each of those loses text that is plainly there on the page, and until this
    existed the reader could see it and had no way to say so.
    """
    label = f"{page['id']}:{slug}"
    match = BOX.match(block.get("box", ""))
    if not match:
        report["bad_added_regions"].append(f"{label}: needs `box: x y w h`")
        return False

    x, y, w, h = (int(value) for value in match.groups())
    width, height = page.get("width") or 0, page.get("height") or 0
    if w < 2 or h < 2:
        report["bad_added_regions"].append(f"{label}: box is {w}x{h}")
        return False
    bbox = ir.clamp_bbox([x, y, w, h], width, height) if width and height else [x, y, w, h]
    if bbox[2] < 2 or bbox[3] < 2:
        report["bad_added_regions"].append(f"{label}: box falls outside the page")
        return False

    kind = (block.get("kind") or block.get("_kind") or "sfx").strip().lower()
    if kind not in ir.REGION_KINDS:
        report["bad_kind"].append(f"{label}: {kind}")
        return False

    # A worksheet is merged more than once — after a correction, after a
    # shortened translation. The `+slug` is the reader's name for the box, so it
    # identifies the region on every later merge; without that, each merge made
    # another copy and reported the previous ones as regions the worksheet had
    # forgotten.
    orientation = (block.get("_orientation")
                   or ("vertical" if bbox[3] > 1.6 * bbox[2] else "horizontal"))
    polarity = ("dark" if block.get("polarity", "").strip().lower() == "dark"
                else "light")

    existing = next((r for r in page.get("regions", [])
                     if r.get("added_as") == slug), None)
    if existing is not None:
        # Everything the box decides, not only the box. Correcting a `+slug`'s
        # polarity or orientation changed neither, and a corrected box left the
        # mask, the cleaned pixels and the lettering that were derived from the
        # OLD one still on disk and still referenced.
        moved = (existing["bbox"] != bbox
                 or existing.get("polarity") != polarity
                 or existing["orientation"] != orientation
                 or existing["kind"] != kind)
        existing["bbox"] = bbox
        existing["kind"] = kind
        existing["orientation"] = orientation
        existing["polarity"] = polarity
        if moved:
            for derived in ("balloon", "mask", "mask_box"):
                existing[derived] = None
            existing["fill"] = "none"
            existing["typeset"] = {}
        _apply(existing, block, report)
        filled = bool((existing.get("target_text") or "").strip())
        if not filled and not existing.get("dropped") and not existing.get("keep"):
            report["empty_translation"].append(existing["id"])
        return filled

    region = ir.new_region(
        _next_region_id(page), bbox, kind=kind, orientation=orientation,
        # Named `reader` on purpose: this box came from someone looking at the
        # page, so `detect` must not treat it as one of its own guesses.
        detector="reader", confidence=1.0,
    )
    region["balloon"] = None
    region["added_as"] = slug
    region["polarity"] = polarity
    region["locked"] = True
    page.setdefault("regions", []).append(region)
    _apply(region, block, report)
    report["added"].append(f"{region['id']} ({slug})")
    filled = bool((region.get("target_text") or "").strip())
    if not filled and not region.get("dropped") and not region.get("keep"):
        # A box the reader added with no Persian in it is exactly as unfinished
        # as a detected balloon with no Persian in it, and reported as clean.
        report["empty_translation"].append(region["id"])
    return filled


#: Bumped when the digest below starts covering something new.
DIGEST_SCHEME = "2"


def reply_digest(text: str) -> str:
    """A stable name for what one finished worksheet SAYS.

    Over the parsed blocks, not the raw bytes. The bookkeeping header is
    rewritten in place after a merge that moved a box, so hashing the file made
    a reply that had just been consumed look like a different reply — and the
    page it had been merged into then read as never merged.
    """
    blocks = parse_worksheet(text)
    payload = {
        region_id: {name: value for name, value in sorted(block.items())
                    if not name.startswith("_")}
        for region_id, block in sorted(blocks.items())
    }
    return hashlib.sha256(
        (DIGEST_SCHEME + json.dumps(payload, sort_keys=True, ensure_ascii=False))
        .encode("utf-8")).hexdigest()[:16]


def _apply_page(page: dict[str, Any], blocks: dict[str, dict[str, str]],
                report: dict[str, list[str]], policy: str, direction: str,
                additions: list[str], covered: set[str]) -> int:
    """One page's reply, applied to `page`. Returns how many regions it filled.

    Separate from `merge_document` so the same work can be done against a copy
    and thrown away if the reply turns out not to be about this page.
    """
    merged = 0
    for region in page.get("regions", []):
        if region["id"] in covered:
            continue
        block = blocks.get(region["id"])
        if block is None:
            report["missing_regions"].append(region["id"])
            continue
        if _apply(region, block, report):
            merged += 1
        elif not region.get("dropped") and ir.translatable(region, policy):
            report["empty_translation"].append(region["id"])

    for slug in additions:
        if _add_region(page, slug[1:] or "added", blocks[slug], report):
            merged += 1
    if additions:
        # A new box changes what comes before what, and it has no mask yet.
        ir.assign_reading_order(page, direction)
    return merged
