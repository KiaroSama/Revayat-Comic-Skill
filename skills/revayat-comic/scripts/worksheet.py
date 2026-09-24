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
    propose: a name or term this balloon MENTIONS, for the glossary
    drop:    yes — there is no text here; the detector matched artwork

`speaker` and `propose` are separate because they answer different questions.
The glossary used to be fed from `speaker` alone, so the only way to get a name
that is merely talked about — "did you see Anna?" — into the table was to write
it in `speaker`, which then said the wrong person was talking and carried that
wrong voice into every later page's context.

Merging refuses rather than guesses. If the page was re-detected after the
worksheet was written, region ids no longer mean what the worksheet thinks they
mean, and a merge would file every translation against the wrong balloon. The
document's fingerprint is stamped into the worksheet and compared on the way
back in.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import pageir as ir
import stages
from replies import (  # noqa: F401 - re-exported: the protocol and the
    ACTIONS,                          # parser have always been reached
    BOX,                              # through `worksheet`, and the CLI,
    FIELD,                            # the transport and every test do.
    FIELDS,
    HEADER,
    PROPOSALS,
    _add_region,
    _apply,
    _apply_page,
    invalid_fields,
    parse_worksheet,
    reply_digest,
)
from sheet import (  # noqa: F401 - re-exported: `worksheet.page_worksheet`
    STAMP_SCHEME,                          # is the name every caller and
    page_worksheet,                        # every test already uses.
)

FINGERPRINT = re.compile(r"^#\s*fingerprint:\s*(?P<value>[0-9a-f]{64})\s*$", re.M)





# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

#: Marks a reply whose `# fingerprint:` is a page fingerprint under the current
#: algorithm. A reply without it was written by an older build, whose stamp was
#: computed a different way and cannot be compared with this one.
SCHEME_LINE = re.compile(r"^#\s*scheme:\s*(?P<value>\d+)\s*$", re.M)


def _addresses_the_same_regions(blocks: dict[str, Any],
                                page: dict[str, Any]) -> bool:
    """Does this reply still name exactly the regions that are on the page?

    This is a structural prerequisite for explicit page reconciliation. It is
    not geometry evidence and never makes an unrecognized fingerprint fresh.

    An added `+slug` block is allowed: it is asking for a region the page does
    not have yet, which is the one legitimate way the two sets differ.
    """
    addressed = {key for key in blocks if not key.startswith("+")}
    return addressed == {region["id"] for region in page.get("regions", [])}


def _stamp_state(reply: Path, pages: dict[str, dict[str, Any]],
                 document_stamp: str,
                 blocks: dict[str, Any] | None = None) -> str:
    """``fresh`` | ``stale`` | ``legacy`` | ``unstamped``.

    Known page or document fingerprints can prove freshness. An unknown older
    scheme cannot prove geometry; explicit page reconciliation preserves its
    Persian without trusting IDs alone.
    """
    text = ir.read_text(reply)
    stamped = FINGERPRINT.search(text)
    if not stamped:
        return "stale"
    value = stamped.group("value")
    page = pages.get(reply.name.split(".", 1)[0])
    if page is not None and value == ir.page_fingerprint(page):
        return "fresh"
    if value == document_stamp:
        return "fresh"          # the document-wide stamp this build still writes
    if not SCHEME_LINE.search(text):
        # Unrecognized, from an older build or with the scheme line removed.
        if page is None:
            return "stale"
        if blocks is None:
            blocks = parse_worksheet(text)
        # Stable IDs do not identify geometry. An unrecognized old fingerprint
        # needs explicit page reconciliation, even if all IDs still exist.
        return "stale"
    return "stale"


def _is_stale(reply: Path, pages: dict[str, dict[str, Any]],
              document_stamp: str) -> bool:
    return _stamp_state(reply, pages, document_stamp) == "stale"


def _restamp(path: Path, page: dict[str, Any], *, expected: str | None = None) -> None:
    """Point a consumed reply at the page as it is now.

    Any accepted correction that moves a box, reclassifies a region or adds one
    changes that page's fingerprint, so the reply just merged looked stale to
    the very next merge and the reader was told to redo work they had only
    corrected. `reply_digest` reads the parsed blocks, so rewriting this header
    does not change what the reply is recorded as saying.
    """
    text = ir.read_text(path)
    if expected is not None and ir.sha256_bytes(text.encode("utf-8")) != expected:
        raise RuntimeError(f"{path} changed while its merge was being committed; preserve and review it")
    stamp = f"# fingerprint: {ir.page_fingerprint(page)}"
    text = (FINGERPRINT.sub(stamp, text, count=1) if FINGERPRINT.search(text)
            else stamp + "\n" + text)
    if SCHEME_LINE.search(text):
        text = SCHEME_LINE.sub(f"# scheme: {STAMP_SCHEME}", text, count=1)
    else:
        text = text.replace(stamp, f"{stamp}\n# scheme: {STAMP_SCHEME}", 1)
    ir.write_text(path, text)


def _finish_receipt(path: Path, page: dict[str, Any], text: str) -> str:
    """Finish a header write whose accepted text committed with this receipt."""
    receipt = page.get("worksheet_receipt") or {}
    if (isinstance(receipt, dict)
            and receipt.get("path") == str(path.resolve())
            and receipt.get("raw") == ir.sha256_bytes(text.encode("utf-8"))
            and receipt.get("after") == ir.page_fingerprint(page)
            and receipt.get("digest") == page.get("worksheet_digest")
            and receipt.get("digest") == reply_digest(text)):
        stamped = FINGERPRINT.search(text)
        if stamped and stamped.group("value") == receipt.get("accepted", receipt.get("before")):
            _restamp(path, page, expected=receipt["raw"])
            return ir.read_text(path)
    return text


@ir.mutating
def reconcile_document(doc_path: str | Path, *, pages: Sequence[str],
                       worksheets: str | Path | None = None) -> dict[str, Any]:
    """Record the operator's explicit review of named pages without rewriting Persian."""
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    if not pages:
        raise ValueError("reconciliation requires explicit page IDs after reviewing their geometry")
    chosen = {page["id"]: page for page in doc["pages"] if page["id"] in pages}
    if set(pages) != set(chosen):
        raise ValueError("unknown page in reconciliation")
    folder = ir.worksheet_folder(doc_path, doc, worksheets)
    pending = []
    for page_id, page in chosen.items():
        path = folder / f"{page_id}.done.txt"
        text = ir.read_text(path)
        blocks = parse_worksheet(text)
        if (not _addresses_the_same_regions(blocks, page)
                or any(block.get("_seen", 1) != 1 or block.get("_duplicate_fields")
                       or invalid_fields(block)
                       for block in blocks.values())):
            raise ValueError(f"{page_id}: reconcile named regions, duplicate fields and invalid decisions first")
        pending.append((path, page, ir.sha256_bytes(text.encode("utf-8"))))
    for path, page, digest in pending:
        _restamp(path, page, expected=digest)
    return {"ok": True, "reconciled": list(chosen)}

@ir.mutating
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
    folder = ir.worksheet_folder(doc_path, doc, out)
    fingerprint = ir.fingerprint(doc)
    by_id = {page["id"]: page for page in doc["pages"]}

    # Only the pages this build is about. A completed reply for page 7 going
    # stale is a fact about page 7, and it stopped `worksheet build --pages
    # p0002` — a page the reader had never touched — from being written at all.
    existing = sorted(folder.glob("*.done.txt")) if folder.exists() else []
    if pages is not None:
        wanted = set(pages)
        existing = [path for path in existing
                    if path.name.split(".", 1)[0] in wanted]
    stale = [path.name for path in existing
             if _is_stale(path, by_id, fingerprint)]
    if stale and not force:
        return {
            "refused": "stale-worksheets",
            "stale": stale[:20],
            "detail": (
                "These completed worksheets were written against a different "
                "set of regions, so their ids no longer point at the same "
                "balloons. Review each affected page's current crops and map "
                "the existing Persian to its regions, then use `worksheet "
                "reconcile --pages <reviewed-page-ids>` before merging."
            ),
        }

    # Where the replies live, so every later guard looks in the right place.
    # A reader who keeps them elsewhere got an empty answer from all of them:
    # the folder was not there, so nothing was unmerged, so nothing refused.
    if out and pages != []:
        doc.setdefault("meta", {})["worksheets"] = str(folder)
        ir.save_doc(doc, doc_path)

    written: list[str] = []
    empty: list[str] = []
    for page in doc["pages"]:
        if pages is not None and page["id"] not in pages:
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
@ir.mutating
def merge_document(
    doc_path: str | Path,
    worksheets: str | Path | None = None,
    *,
    pages: Sequence[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    folder = ir.worksheet_folder(doc_path, doc, worksheets)
    if worksheets and pages != []:
        doc["meta"]["worksheets"] = str(folder)
    # Kept only so a worksheet stamped by an older build is still recognised;
    # staleness itself is decided per page. See `_is_stale`.
    document_stamp = ir.fingerprint(doc)
    policy = doc["meta"].get("sfx_policy", "keep")
    direction = doc["meta"].get("reading_direction", "rtl")

    if not folder.exists() and pages != []:
        return {"ok": False, "error": f"no worksheets at {folder}"}

    report: dict[str, Any] = {
        "merged": 0,
        "dropped": [],
        "kept": [],
        "reclassified": [],
        "bad_kind": [],
        "invalid_fields": [],
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
        "duplicate_fields": [],
        "legacy_worksheets": [],
        "unchanged": [],
    }

    by_page = {page["id"]: page for page in doc["pages"]
               if pages is None or page["id"] in pages}
    consumed: list[Path] = []
    reply_versions: dict[Path, str] = {}
    #: Which report lists mean "this page's reply did not fully land".
    trouble = ("missing_regions", "unknown_regions", "duplicate_regions",
               "empty_translation", "bad_added_regions",
               "conflicting_actions", "duplicate_fields", "bad_kind", "invalid_fields")
    list_keys = [key for key, value in report.items() if isinstance(value, list)]
    for page_id, page in by_page.items():
        path = folder / f"{page_id}.done.txt"
        if not path.exists():
            report["missing_outputs"].append(page_id)
            continue

        text = _finish_receipt(path, page, ir.read_text(path))
        reply_versions[path] = ir.sha256_bytes(text.encode("utf-8"))
        blocks = parse_worksheet(text)

        # Structure FIRST, and before the shortcut. The shortcut compares a
        # digest, and a reply corrupted by a pasted-in duplicate block or a
        # second `fa:` line holding the same words hashed identically to the
        # reply it corrupted — so a merge that should have refused reported the
        # page as already landed and the reader was told nothing had changed.
        # A reply is read whole and judged whole before any of it is trusted.
        page_report: dict[str, list[str]] = {key: [] for key in list_keys}
        for region_id, block in blocks.items():
            page_report["invalid_fields"] += [
                f"{region_id}: {problem}" for problem in invalid_fields(block)]
            if int(block.get("_seen", 1)) > 1:
                page_report["duplicate_regions"].append(region_id)
            repeated = block.get("_duplicate_fields", "")
            for name in sorted({n for n in repeated.split(",") if n}):
                page_report["duplicate_fields"].append(f"{region_id}: {name}")
        malformed = (page_report["duplicate_regions"]
                     + page_report["duplicate_fields"] + page_report["invalid_fields"])

        state = _stamp_state(path, by_page, document_stamp, blocks)
        if state == "stale" and not force:
            report["stale_worksheets"].append(page_id)
            continue
        if state == "legacy":
            report["legacy_worksheets"].append(page_id)

        digest = reply_digest(text)
        if (not malformed and page.get("worksheet_digest") == digest
                and page.get("worksheet_clean")):
            # This exact reply has already landed whole. Applying it again would
            # overwrite `falint`'s normalised Persian with the raw text the
            # reader typed, which is how a correction to a half-space got
            # undone by a merge that changed nothing else.
            report["unchanged"].append(page_id)
            consumed.append(path)
            continue

        # Validate scalar/header contracts before applying even to a copy.
        # An invalid added orientation must be a reported refusal, not an
        # exception from constructing a region before the refusal is checked.
        if page_report["invalid_fields"]:
            for key, values in page_report.items():
                report[key] += values
            page["worksheet_digest"] = digest
            page["worksheet_clean"] = False
            continue

        known = {region["id"] for region in page.get("regions", [])}
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
        # One outcome, used for all three questions: does this page commit,
        # is it clean, and does the command exit non-zero. They disagreed —
        # a `keep: yes` beside an `erase: yes` refused the page and still
        # reported `ok`, and an invalid `kind:` left the page "clean".
        refused = (page_report["duplicate_regions"]
                   + page_report["unknown_regions"]
                   + page_report["conflicting_actions"]
                   + page_report["duplicate_fields"]
                   + page_report["bad_kind"]
                   + page_report["bad_added_regions"] + page_report["invalid_fields"])
        for key, values in page_report.items():
            report[key] += values
        if refused:
            # The reply was read and did not land. Recording THAT — rather than
            # leaving the page with no record at all — is what lets the context
            # guard answer "this page is not merged". Without it the guard falls
            # back to "does the page hold any Persian yet", which says yes on
            # the strength of an earlier run's text.
            page["worksheet_digest"] = reply_digest(text)
            page["worksheet_clean"] = False
            continue

        # What was consumed, and whether it landed whole. Without this the only
        # way to ask "is this page merged" was "does it hold any Persian yet" —
        # which says yes to a page whose reply was edited afterwards, and yes to
        # one whose reply was only half applied.
        candidate["worksheet_digest"] = digest
        candidate["worksheet_clean"] = not any(
            page_report[key] for key in trouble)
        candidate["worksheet_receipt"] = {
            "path": str(path.resolve()), "raw": reply_versions[path], "digest": digest,
            "before": ir.page_fingerprint(page), "after": ir.page_fingerprint(candidate),
            "accepted": (FINGERPRINT.search(text).group("value")
                         if FINGERPRINT.search(text) else None),
        }
        page.clear()
        page.update(candidate)
        report["merged"] += merged
        consumed.append(path)

    # THE DOCUMENT FIRST, then the replies that describe it. Restamping first
    # made every reply claim a document state that the save had not reached
    # yet: a failure there left the merged Persian unwritten and the replies on
    # disk pointing at it, so the next run read them as fresh and merged
    # nothing. No write may claim another write already succeeded.
    if consumed:
        stages.stamp_stage(doc, "worksheet", {"merged": report["merged"]},
                           pages=[path.name.split(".", 1)[0] for path in consumed])
    ir.save_doc(doc, doc_path)

    # Every consumed reply, not only the ones that added a region. A `kind:`
    # correction moves the page fingerprint just as surely as a new box does,
    # and it merged once and then reported itself stale on the next run.
    for path in consumed:
        page = by_page.get(path.name.split(".", 1)[0])
        if page is not None:
            _restamp(path, page, expected=reply_versions[path])

    blocking = (
        report["missing_outputs"] or report["missing_regions"]
        or report["unknown_regions"] or report["duplicate_regions"]
        or report["stale_worksheets"] or report["empty_translation"]
        or report["bad_kind"] or report["bad_added_regions"]
        or report["conflicting_actions"] or report["duplicate_fields"]
        or report["invalid_fields"]
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
    folder = ir.worksheet_folder(doc_path, doc, worksheets)

    by_id = {page["id"]: page for page in doc["pages"]}
    document_stamp = ir.fingerprint(doc)
    expected = [page["id"] for page in doc["pages"] if page.get("regions")]

    present, merged, stale, legacy, edited = [], [], [], [], []
    for page_id in expected:
        path = folder / f"{page_id}.done.txt"
        if not path.exists():
            continue
        present.append(page_id)
        state = _stamp_state(path, by_id, document_stamp)
        if state == "stale":
            stale.append(page_id)
            continue
        if state == "legacy":
            legacy.append(page_id)
        page = by_id[page_id]
        if not page.get("worksheet_clean"):
            continue
        if page.get("worksheet_digest") == reply_digest(ir.read_text(path)):
            merged.append(page_id)
        else:
            # Answered, merged, and then edited again — which "does it exist"
            # could not tell from "is it in the document".
            edited.append(page_id)

    return {
        "pages_with_text": len(expected),
        # Kept: the number every earlier report and every doc calls this.
        "translated": len(present),
        "present": present,
        "merged": merged,
        "edited_since_merge": edited,
        "stale": stale,
        "legacy_stamp": legacy,
        "remaining": [page_id for page_id in expected
                      if page_id not in set(present)],
    }

@ir.cli
def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic worksheet",
        description="Build translation worksheets, or merge the answers back.",
    )
    parser.add_argument("action", choices=["build", "merge", "status", "reconcile"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--worksheets", default=None)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--force", action="store_true",
                        help="proceed even though the regions changed")
    args = parser.parse_args(argv)

    if args.action == "reconcile":
        if not args.pages:
            parser.error("reconcile requires --pages naming the pages whose geometry you reviewed")
        ir.emit(reconcile_document(args.doc, pages=[p for p in args.pages.split(",") if p],
                                   worksheets=args.worksheets))
        return 0

    if args.action == "build":
        report = build_document(
            args.doc, args.worksheets,
            pages=ir.parse_pages(args.pages),
            force=args.force,
        )
        ir.emit(report)
        return 1 if report.get("refused") else 0

    if args.action == "status":
        ir.emit(status(args.doc, args.worksheets))
        return 0

    report = merge_document(
        args.doc, args.worksheets,
        pages=ir.parse_pages(args.pages),
        force=args.force)
    ir.emit(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
