"""The worksheet protocol — how the reader's answers get back into the document.

One worksheet per page, plain text, one block per region:

    @@ p0001r003 speech vertical
    src: やめろ！
    fa: بس کن!

Plain text rather than JSON for the reason the sibling novel skill found the
hard way: models corrupt JSON and fight Persian quoting, while a missing ``@@``
line is caught deterministically at merge. A field continues onto the next line
until another field or another ``@@`` starts, so multi-line dialogue needs no
escaping at all.

Three optional fields let the reader correct what the detector guessed, because
the reader can see the page and the detector cannot:

    kind:    reclassify — the detector called it speech, it is a sign
    speaker: who is talking, for the glossary and for voice consistency
    drop:    yes — there is no text here; the detector matched artwork

Merging refuses rather than guesses. If the page was re-detected after the
worksheet was written, region ids no longer mean what the worksheet thinks they
mean, and a merge would file every translation against the wrong balloon. The
document's fingerprint is stamped into the worksheet and compared on the way
back in.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import pageir as ir

HEADER = re.compile(r"^@@\s+(?P<id>\+?[A-Za-z0-9_#-]+)(?:\s+(?P<rest>.*))?$")
FIELD = re.compile(
    r"^(?P<name>src|fa|kind|speaker|note|drop|keep|erase|box|polarity)"
    r"\s*:\s?(?P<value>.*)$")

#: `box: x y w h`, in the page's own pixels — the same pixels `overview.png`
#: is drawn at, so a reader can take the numbers straight off it.
BOX = re.compile(r"^\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*$")
FINGERPRINT = re.compile(r"^#\s*fingerprint:\s*(?P<value>[0-9a-f]{64})\s*$", re.M)

FIELDS = ("src", "fa", "kind", "speaker", "note", "drop", "keep", "erase", "box",
          "polarity")

_DIRECTION_WORDS = {
    "rtl": "right to left (Japanese order: the rightmost balloon is first)",
    "ltr": "left to right",
}


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

def _rows(pairs: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """One line per entry, wide enough for the longest of them.

    Nothing is clipped. The columns used to be a fixed 21 characters, so a
    long name was printed as most of itself — a binding spelling that was
    not the spelling, which is worse than no table at all.
    """
    source_width = max(len(source) for source, _ in pairs)
    target_width = max(len(entry.get("target", "")) for _, entry in pairs)
    lines = [
        f"#   {'source':<{source_width}}  {'Persian':<{target_width}}  role",
        f"#   {'-' * source_width}  {'-' * target_width}  {'-' * 18}",
    ]
    for source, entry in pairs:
        lines.append(
            f"#   {source:<{source_width}}  "
            f"{entry.get('target', ''):<{target_width}}  "
            f"{entry.get('role', '')}"
        )
    return lines


def _glossary_table(doc: dict[str, Any], limit: int = 40) -> list[str]:
    """The names table, with the binding rows separated from the guesses.

    Everything with a `target` used to be printed under a heading saying it
    was binding, including the entries the scan proposed and nobody had
    approved. A translator told a guess is binding spells the rest of the
    chapter to match it. And the whole thing stopped at 40 rows with
    nothing said, so enough guesses pushed the one approved term off the
    end — which is why the cap now falls on the guesses only.
    """
    entries = doc.get("glossary", {}).get("entries", {})
    with_target = [(source, entry) for source, entry in entries.items()
                   if entry.get("target")]
    binding = [pair for pair in with_target if pair[1].get("locked")]
    suggested = [pair for pair in with_target if not pair[1].get("locked")]
    if not with_target:
        return []

    lines: list[str] = []
    if binding:
        lines += [
            "# Names and terms — these are binding. Use exactly the "
            "Persian given.",
            "#",
        ]
        lines += _rows(binding)
        lines.append("#")

    room = max(0, limit - len(binding))
    shown = suggested[:room]
    if shown:
        lines += [
            "# Proposed by the scan and not binding — nobody has approved "
            "these.",
            "# Use one if it is right; if it is wrong, just translate "
            "normally.",
            "#",
        ]
        lines += _rows(shown)
        lines.append("#")
    hidden = len(suggested) - len(shown)
    if hidden:
        lines.append(f"#   … and {hidden} more suggestion(s) not shown.")
        lines.append("#")
    return lines


def page_worksheet(doc: dict[str, Any], page: dict[str, Any], fingerprint: str) -> str:
    meta = doc["meta"]
    direction = meta.get("reading_direction", "rtl")
    regions = page.get("regions", [])

    lines = [
        f"# {meta.get('title') or 'comic'} — page {page['id']} "
        f"({page['index'] + 1} of {len(doc['pages'])})",
        # This PAGE's fingerprint. A document-wide one made a correction on
        # any page declare every other page's finished reply stale.
        f"# fingerprint: {fingerprint}",
        "#",
        "# Look at these before writing anything:",
        f"#   {page.get('overview', '(run crops first)')}",
    ]
    for sheet in page.get("sheets", []):
        lines.append(f"#   {sheet}")
    lines += [
        "#",
        f"# Source language: {meta.get('source_language')}   "
        f"target: {meta.get('target_language')}",
        f"# Reading order: {_DIRECTION_WORDS.get(direction, direction)}",
        f"# Sound effects: {meta.get('sfx_policy', 'keep')}",
        "#",
        "# Fill in `src:` with what the balloon actually says, and `fa:` with the",
        "# Persian. Keep every `@@` line exactly as it is. A field continues on",
        "# the following lines until the next field or the next `@@`.",
        "#",
        "# Optional corrections — use them when the crop shows the detector was",
        "# wrong. You can see the page; it could not.",
        "#   kind:    speech | thought | narration | sfx | sign | unknown",
        "#   speaker: a short stable name, the same one every time",
        "#   drop:    yes   — there is no text here at all",
        "#   keep:    yes   — there IS text, leave it in the artwork",
        "#   erase:   yes   — remove this and put nothing back (a watermark,",
        "#                    a site stamp, a scan credit). Only for marks you",
        "#                    have the right to remove.",
        "#",
        "# Something the detector missed entirely? Add it. Free lettering is",
        "# the weak case, adjacent balloons sometimes come back as one region,",
        "# and a whole panel is occasionally taken for a balloon — so a page can",
        "# be missing text that is plainly there in overview.png.",
        "#",
        "#   @@ +bump sfx horizontal",
        "#   box: 742 436 58 24        <- x y w h, in the page's own pixels,",
        "#                                read straight off overview.png",
        "#   src: BUMP",
        "#   fa: تلپ",
        "#",
        "# Add `polarity: dark` when the lettering is white on black. After a",
        "# merge that added regions, run `mask` again before `clean`.",
        "#",
    ]
    lines += _glossary_table(doc)

    for region in regions:
        lines.append("")
        lines.append(f"@@ {region['id']} {region['kind']} {region['orientation']}")
        if region.get("panel"):
            lines.append(f"# panel {region['panel']}, "
                         f"reading order {region.get('reading_order')}")
        if region.get("confidence", 1.0) < 0.5:
            lines.append("# low-confidence detection — check the crop; "
                         "`drop: yes` if there is no text")
        lines.append(f"src: {region.get('source_text', '')}")
        lines.append(f"fa: {region.get('target_text', '')}")
        if region.get("speaker"):
            lines.append(f"speaker: {region['speaker']}")
        # Decisions already taken are written back out. An ABSENT field resets
        # them at the next merge, so a rebuilt worksheet silently undid every
        # `drop`, `keep` and `erase` a reader had reviewed — and the notes with
        # them. A worksheet has to be a faithful picture of the page.
        if region.get("dropped"):
            lines.append("drop: yes")
        if region.get("keep"):
            lines.append("keep: yes")
        if region.get("erase"):
            lines.append("erase: yes")
        for note in region.get("review", []):
            lines.append(f"note: {note}")
    return "\n".join(lines) + "\n"


def _is_stale(reply: Path, pages: dict[str, dict[str, Any]],
              document_stamp: str) -> bool:
    """Whether a finished worksheet was written against different regions.

    Compared against the page it belongs to. A stamp equal to the document-wide
    hash is accepted as well: worksheets already on disk carry that, and telling
    a reader their finished work is stale because the scheme changed underneath
    them would be the same defect wearing a different hat.
    """
    stamped = FINGERPRINT.search(ir.read_text(reply))
    if not stamped:
        return False
    value = stamped.group("value")
    if value == document_stamp:
        return False
    page = pages.get(reply.name.split(".", 1)[0])
    return page is None or value != ir.page_fingerprint(page)


def build_document(
    doc_path: str | Path,
    out: str | Path | None = None,
    *,
    pages: Sequence[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    folder = Path(out) if out else root / "worksheets"
    fingerprint = ir.fingerprint(doc)
    by_id = {page["id"]: page for page in doc["pages"]}

    existing = sorted(folder.glob("*.done.txt")) if folder.exists() else []
    stale = [path.name for path in existing
             if _is_stale(path, by_id, fingerprint)]
    if stale and not force:
        return {
            "refused": "stale-worksheets",
            "stale": stale[:20],
            "detail": (
                "These completed worksheets were written against a different "
                "set of regions, so their ids no longer point at the same "
                "balloons. Re-translate them, or pass --force if you are "
                "certain the regions did not move."
            ),
        }

    written: list[str] = []
    empty: list[str] = []
    for page in doc["pages"]:
        if pages and page["id"] not in pages:
            continue
        if not page.get("regions"):
            # Written anyway. `@@ +slug` is the one way to recover text the
            # detector missed entirely, and skipping the sheet made it
            # unreachable on exactly the page that needed it most. Still
            # reported under `pages_without_text` so the count stays honest.
            empty.append(page["id"])
        target = folder / f"{page['id']}.txt"
        ir.write_text(target, page_worksheet(doc, page,
                                             ir.page_fingerprint(page)))
        written.append(str(target.relative_to(root)) if target.is_relative_to(root)
                       else str(target))

    return {
        "worksheets": written,
        "count": len(written),
        "pages_without_text": empty,
        "page_fingerprints": {page["id"]: ir.page_fingerprint(page)
                              for page in doc["pages"]},
        "fingerprint": fingerprint,
        "next": "Translate each one to <page>.done.txt, then run `worksheet merge`.",
    }


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

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
        if raw.lstrip().startswith("#"):
            continue
        match = FIELD.match(raw)
        if match:
            field = match.group("name")
            current[field] = match.group("value").strip()
            continue
        if field is not None:
            # A continuation line. Keep the newline: a balloon that breaks its
            # own line does so for a reason, and the typesetter may honour it.
            current[field] = (current[field] + "\n" + raw.strip()).strip()
    return blocks


def _apply(region: dict[str, Any], block: dict[str, str],
           report: dict[str, list[str]]) -> bool:
    if block.get("drop", "").strip().lower() in {"yes", "true", "1"}:
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
    kept = block.get("keep", "").strip().lower() in {"yes", "true", "1"}
    if kept:
        region["keep"] = True
    else:
        region.pop("keep", None)

    # Ink the reader wants gone with nothing put in its place — a watermark, a
    # site stamp, a scan credit. The three existing answers all say something
    # else: `drop` claims there is no ink there, `keep` leaves it drawn, and a
    # `fa:` line puts Persian over it. None of them is "remove this".
    erased = block.get("erase", "").strip().lower() in {"yes", "true", "1"}
    if erased and kept:
        report["conflicting_actions"].append(
            f"{region['id']}: both `keep: yes` and `erase: yes`")
        erased = False
    if erased:
        region["erase"] = True
    else:
        region.pop("erase", None)

    source = block.get("src", "").strip()
    target = block.get("fa", "").strip()
    kind = block.get("kind", "").strip().lower()
    speaker = block.get("speaker", "").strip()
    note = block.get("note", "").strip()

    if kind:
        if kind not in ir.REGION_KINDS:
            report["bad_kind"].append(f"{region['id']}: {kind}")
        elif kind != region["kind"]:
            region["kind"] = kind
            report["reclassified"].append(f"{region['id']} -> {kind}")
    if speaker:
        region["speaker"] = speaker
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
    existing = next((r for r in page.get("regions", [])
                     if r.get("added_as") == slug), None)
    if existing is not None:
        if existing["bbox"] != bbox:
            existing["bbox"] = bbox
            existing["balloon"] = None      # re-derived by `mask` from the new box
        existing["kind"] = kind
        _apply(existing, block, report)
        return bool((existing.get("target_text") or "").strip())

    region = ir.new_region(
        _next_region_id(page), bbox, kind=kind,
        orientation=block.get("_orientation")
        or ("vertical" if bbox[3] > 1.6 * bbox[2] else "horizontal"),
        # Named `reader` on purpose: this box came from someone looking at the
        # page, so `detect` must not treat it as one of its own guesses.
        detector="reader", confidence=1.0,
    )
    region["balloon"] = None
    region["added_as"] = slug
    region["polarity"] = "dark" if block.get("polarity", "").strip().lower() == "dark" else "light"
    region["locked"] = True
    page.setdefault("regions", []).append(region)
    _apply(region, block, report)
    report["added"].append(f"{region['id']} ({slug})")
    return bool((region.get("target_text") or "").strip())


def reply_digest(text: str) -> str:
    """A stable name for one finished worksheet's contents."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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


def merge_document(
    doc_path: str | Path,
    worksheets: str | Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    folder = Path(worksheets) if worksheets else root / "worksheets"
    # Kept only so a worksheet stamped by an older build is still recognised;
    # staleness itself is decided per page. See `_is_stale`.
    document_stamp = ir.fingerprint(doc)
    policy = doc["meta"].get("sfx_policy", "keep")
    direction = doc["meta"].get("reading_direction", "rtl")

    if not folder.exists():
        return {"ok": False, "error": f"no worksheets at {folder}"}

    report: dict[str, Any] = {
        "merged": 0,
        "dropped": [],
        "kept": [],
        "reclassified": [],
        "bad_kind": [],
        "missing_outputs": [],
        "missing_regions": [],
        "unknown_regions": [],
        "duplicate_regions": [],
        "empty_translation": [],
        "stale_worksheets": [],
        "added": [],
        "bad_added_regions": [],
        "erased": [],
        "conflicting_actions": [],
    }

    by_page = {page["id"]: page for page in doc["pages"]}
    consumed: list[Path] = []
    #: Which report lists mean "this page's reply did not fully land".
    trouble = ("missing_regions", "unknown_regions", "duplicate_regions",
               "empty_translation", "bad_added_regions",
               "conflicting_actions")
    list_keys = [key for key, value in report.items() if isinstance(value, list)]
    for page_id, page in by_page.items():
        path = folder / f"{page_id}.done.txt"
        if not path.exists():
            report["missing_outputs"].append(page_id)
            continue

        text = ir.read_text(path)
        if _is_stale(path, by_page, document_stamp) and not force:
            report["stale_worksheets"].append(page_id)
            continue

        blocks = parse_worksheet(text)
        known = {region["id"] for region in page.get("regions", [])}
        page_report: dict[str, list[str]] = {key: [] for key in list_keys}
        for region_id, block in blocks.items():
            if int(block.get("_seen", 1)) > 1:
                page_report["duplicate_regions"].append(region_id)
        additions = sorted(key for key in blocks if key.startswith("+"))
        page_report["unknown_regions"] += sorted(set(blocks) - known - set(additions))

        # Regions the reader added are addressed by their `+slug` block, not by
        # an `@@ <id>` block of their own, so they are not missing from the sheet.
        slugs = {slug[1:] for slug in additions}
        covered = {region["id"] for region in page.get("regions", [])
                   if region.get("added_as") in slugs}

        # Applied to a COPY first. A reply is one answer about one page, and
        # applying the sound part of a malformed one left the page in a state
        # nobody wrote: some regions carrying the new reply, the rest carrying
        # the old, while the report mentioned only the block that was wrong.
        candidate = copy.deepcopy(page)
        merged = _apply_page(candidate, blocks, page_report, policy, direction,
                             additions, covered)

        # What makes a reply un-appliable, as opposed to merely incomplete: it
        # answers about a region twice, about a region that is not on the page,
        # or it asks for two opposite things. `missing_regions` and
        # `empty_translation` are NOT here — translating part of a page and
        # coming back to it is the ordinary way this work gets done.
        refused = (page_report["duplicate_regions"]
                   + page_report["unknown_regions"]
                   + page_report["conflicting_actions"])
        for key, values in page_report.items():
            report[key] += values
        if refused:
            continue

        # What was consumed, and whether it landed whole. Without this the only
        # way to ask "is this page merged" was "does it hold any Persian yet" —
        # which says yes to a page whose reply was edited afterwards, and yes to
        # one whose reply was only half applied.
        candidate["worksheet_digest"] = reply_digest(text)
        candidate["worksheet_clean"] = not any(
            page_report[key] for key in trouble)
        page.clear()
        page.update(candidate)
        report["merged"] += merged
        consumed.append(path)

    if report["added"]:
        # Adding a region changes THAT page's fingerprint, which would make the
        # worksheet just merged look stale to the *next* merge — the reader
        # would be told to re-translate work they had only added to. Re-stamp
        # what was consumed, so the loop stays closed. A page nobody added to
        # keeps the stamp it already had.
        for path in consumed:
            page = by_page.get(path.name.split(".", 1)[0])
            if page is None:
                continue
            text = ir.read_text(path)
            if FINGERPRINT.search(text):
                ir.write_text(path, FINGERPRINT.sub(
                    f"# fingerprint: {ir.page_fingerprint(page)}", text, count=1))

    ir.stamp_stage(doc, "worksheet", {"merged": report["merged"]})
    ir.save_doc(doc, doc_path)

    blocking = (
        report["missing_outputs"] or report["missing_regions"]
        or report["unknown_regions"] or report["duplicate_regions"]
        or report["stale_worksheets"] or report["empty_translation"]
        or report["bad_kind"] or report["bad_added_regions"]
    )
    report["ok"] = not blocking
    if report["added"]:
        report["next"] = ("regions were added, so they have no mask yet — "
                          "run `mask` again before `clean`")
    for key in ("missing_regions", "unknown_regions", "empty_translation"):
        report[key] = report[key][:25]
    return report


def status(doc_path: str | Path, worksheets: str | Path | None = None) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    folder = Path(worksheets) if worksheets else root / "worksheets"

    expected = [page["id"] for page in doc["pages"] if page.get("regions")]
    done = [page_id for page_id in expected if (folder / f"{page_id}.done.txt").exists()]
    return {
        "pages_with_text": len(expected),
        "translated": len(done),
        "remaining": [page_id for page_id in expected if page_id not in set(done)],
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic worksheet",
        description="Build translation worksheets, or merge the answers back.",
    )
    parser.add_argument("action", choices=["build", "merge", "status"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--worksheets", default=None)
    parser.add_argument("--pages", default="")
    parser.add_argument("--force", action="store_true",
                        help="proceed even though the regions changed")
    args = parser.parse_args(argv)

    if args.action == "build":
        report = build_document(
            args.doc, args.worksheets,
            pages=[p for p in args.pages.split(",") if p] or None,
            force=args.force,
        )
        ir.emit(report)
        return 1 if report.get("refused") else 0

    if args.action == "status":
        ir.emit(status(args.doc, args.worksheets))
        return 0

    report = merge_document(args.doc, args.worksheets, force=args.force)
    ir.emit(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
