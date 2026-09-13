"""Whether a chapter may be published, and the transaction that publishes it.

What each format is turned into lives in `writers`; this decides what goes in,
refuses a destination that would destroy what the export is reading, and makes
the package and the document that describes it into one recoverable step.

Page order is the only thing that can be silently wrong in an export, because
every reader sorts an archive's names itself and none of them agree about what
``page10`` means next to ``page9``. The names are zero-padded and already in
reading order, so byte-wise sorting and reading order are the same thing and no
reader has to guess.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import journal
import pageir as ir
import stages
import writers
# Part of this module's surface: the destination claim is what serializes two
# exports, and a caller needs to be able to name it.
from writers import staging_path  # noqa: F401

FORMATS = ("cbz", "pdf", "dir")


def _wants_rendering(page: dict[str, Any]) -> bool:
    """Whether this page has Persian on it that a render has to carry."""
    return any((region.get("target_text") or "").strip()
               for region in page.get("regions", [])
               if not region.get("dropped"))


def _manifest(doc: dict[str, Any], root: Path) -> dict[str, str]:
    """Which file each page will ship, resolved before anything is written."""
    return {page["id"]: writers._resolve(root, page)[1] for page in doc["pages"]}


def _dependencies(doc: dict[str, Any], root: Path, doc_path: Path) -> set[Path]:
    """Every file this chapter is made of, resolved through symlinks.

    An export reads these while it writes, so writing onto one of them destroys
    the chapter mid-flight. Resolved rather than compared as written, because
    `work/pages/../pages/p0001.png` and a symlink alias name the same bytes.
    """
    found = {doc_path.resolve()}
    # The container this chapter was imported from. Not a working file, and
    # that is exactly why it belongs here: everything else under `root` can be
    # rebuilt from it, and it cannot be rebuilt from anything.
    origin = (doc.get("source") or {}).get("path")
    if isinstance(origin, str) and origin:
        candidate = Path(origin)
        if candidate.exists():
            found.add(candidate.resolve())
    for page in doc.get("pages", []):
        named = [page.get(key) for key in
                 ("image", "clean", "final", "mask", "writable")]
        # Region masks were missing, and they are the largest set of files
        # here: `masks/<page>/r0003.png` is what authorised every pixel the
        # cleaner changed, and an export onto one destroys evidence the
        # package cannot be used to rebuild.
        named += [region.get("mask") for region in page.get("regions", [])]
        for relative in named:
            if isinstance(relative, str) and relative:
                candidate = root / relative
                if candidate.exists():
                    found.add(candidate.resolve())
    return found


def _working_folders(doc: dict[str, Any], root: Path,
                     doc_path: Path) -> set[Path]:
    """Directories the chapter is made of, so their contents need no listing.

    A folder holding a file this chapter is made of is a folder this export
    must not write into — which covers every region mask under `masks/<page>/`
    without walking a single one of them.

    `crops` and the worksheets are here explicitly because they are the two the
    DOCUMENT does not name: a reader is looking at those crops and typing into
    those worksheets, and an export over either loses work in progress that
    exists nowhere else.

    The working folder itself is deliberately excluded. `work/out/chapter.cbz`
    is an ordinary place to put a chapter, and refusing the whole tree because
    `comic.json` sits at the top of it would forbid it.
    """
    root = root.resolve()
    folders = {path.parent for path in _dependencies(doc, root, doc_path)}
    folders.add(root / "crops")
    folders.add(ir.worksheet_folder(doc_path, doc).resolve())
    return {folder for folder in folders
            if folder != root and root in folder.parents and folder.is_dir()}


def _refuse_collisions(doc: dict[str, Any], root: Path, doc_path: Path,
                       out: Path, fmt: str) -> None:
    """Refuse an output path that lands on something the chapter is made of.

    Checked for every format and after `--format` has been resolved: guessing
    the format from the suffix is exactly how `--format cbz --out page.png`
    walks past a suffix-based guard.
    """
    owned = _dependencies(doc, root, doc_path)
    target = out.resolve()

    if target in owned:
        raise ValueError(
            f"{out} is a file the chapter is made of. Exporting onto it would "
            "destroy what the export is reading. Pick a different --out."
        )

    for folder in _working_folders(doc, root, doc_path):
        if target == folder or folder in target.parents:
            raise ValueError(
                f"{out} is inside {folder}, which holds files the chapter is "
                "made of. Exporting there would write over the work. Pick a "
                "different --out."
            )

    if fmt == "dir":
        # A folder export writes `0001.png`, `0002.png`… Those are legal page
        # names, so a chapter whose own pages are named that way has its
        # originals overwritten rather than flagged by the stranger check
        # below, which only looks at files the export will NOT replace.
        clashing = sorted(str(path) for path in owned if path.parent == target)
        if clashing:
            raise ValueError(
                f"{out} holds {len(clashing)} file(s) the chapter is made of "
                f"({', '.join(Path(c).name for c in clashing[:4])}…). Exporting "
                "there would write over the originals. Export to an empty folder."
            )
        return


#: How many editions a document remembers. A chapter is published to a handful
#: of places — an archive, a PDF, a folder for a proofreader — and each one is
#: verifiable against its own manifest for as long as it is remembered. Bounded
#: because a document is not an archive of every export ever run.
MAX_REMEMBERED_EDITIONS = 8


def _editions(doc: dict[str, Any], out: Path,
              result: dict[str, Any]) -> dict[str, Any]:
    """Every destination this document remembers publishing to, newest last.

    There was one manifest, belonging to whichever export ran last, and
    `qa package` checked whatever it was handed against it. Export the chapter
    as an archive and then as a PDF and checking the archive compared it with
    the PDF's rows — a package reported wrong page by page because a different
    package had been written since.
    """
    previous = ((doc.get("stages") or {}).get("export") or {})
    editions = dict(previous.get("editions") or {})
    key = str(out.resolve())
    editions.pop(key, None)
    editions[key] = {"format": result["format"],
                     "manifest": result["manifest"]}
    while len(editions) > MAX_REMEMBERED_EDITIONS:
        editions.pop(next(iter(editions)))
    return editions


def reconcile_pending(doc_path: str | Path) -> dict[str, Any] | None:
    """Apply the stamp of an export that published but could not record it.

    Returns the record it applied, or `None` — which means either that there
    was nothing to reconcile, or that what was there could not be trusted.

    It used to stamp whatever the record said. That certified a document which
    had changed since with an older export's manifest: a chapter described by
    one generation and made of the bytes of another, every internal hash
    agreeing. `journal.verifies` is the difference — the document this edition
    was made from, and the bytes it published, both still exactly as recorded.
    """
    doc_path = Path(doc_path)
    record = journal.read(doc_path)
    if record is None:
        return None
    refused = journal.verifies(doc_path, record)
    if refused:
        journal.reject(doc_path, refused)
        return None

    doc = ir.load_doc(doc_path)
    stages.stamp_stage(doc, "export", record["result"],
                       options=record["options"])
    ir.save_doc(doc, doc_path)
    journal.clear(doc_path)
    return record


def export_document(
    doc_path: str | Path, out: str | Path, *, fmt: str | None = None,
    quality: int = 0, draft: bool = False,
) -> dict[str, Any]:
    """Publish the chapter, and record the edition that was published.

    Two locks, in this order everywhere: the workspace first — this run reads
    every asset and writes the document, and a `clean` or `typeset` running
    beside it would change what is being packaged half way through — and then
    the destination, claimed by the writer as its staging path. One order, so
    two exports of two chapters into one folder cannot hold half of each
    other's.
    """
    doc_path = Path(doc_path)
    with ir.workspace_lock(ir.doc_dir(doc_path), what="export"):
        return _publish(doc_path, Path(out).expanduser(), fmt, quality, draft)


def _publish(doc_path: Path, out: Path, fmt: str | None, quality: int,
             draft: bool) -> dict[str, Any]:
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)

    if fmt is None:
        suffix = out.suffix.lower()
        fmt = {".cbz": "cbz", ".zip": "cbz", ".pdf": "pdf"}.get(suffix, "dir")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")
    # An export that could not commit its own stamp last time. Reconciled
    # before this one starts, so the document never describes an edition older
    # than the files beside it.
    if reconcile_pending(doc_path) is not None:
        doc = ir.load_doc(doc_path)
    _refuse_collisions(doc, root, doc_path, out, fmt)

    # Resolved before a byte is written, because the fallback is silent: a
    # page whose render is missing shipped its cleaned version — or the
    # untranslated original — and was still counted under `typeset_pages`.
    sources = _manifest(doc, root)
    unrendered = sorted(
        page["id"] for page in doc["pages"]
        if _wants_rendering(page) and sources[page["id"]] != "final"
    )
    if not draft:
        # The whole gate, not export's own narrower question. Asking only "is
        # there a file for every page that wants one" let a chapter whose
        # render was stale, whose lines had overflowed, or whose erasures had
        # never been cleaned go into a package without `qa` ever running.
        import qa

        state = qa.publication_preflight(doc_path)
        if not state["ok"]:
            named = ", ".join(
                f"{item['code']} ({item['where']})"
                for item in state["blocking"][:4])
            raise ValueError(
                f"this chapter does not pass publication QA: "
                f"{state['blocking_count']} blocking finding(s) — {named}. "
                f"{state['next']}"
            )
    if unrendered and not draft:
        raise ValueError(
            f"{len(unrendered)} page(s) carry Persian that has not been "
            f"rendered: {', '.join(unrendered[:6])}. Run `typeset`, or pass "
            "--draft to ship the cleaned pages instead and have the report "
            "say so page by page."
        )

    options = {"format": fmt, "quality": quality, "draft": draft}
    committed: dict[str, Any] = {}

    def commit(manifest: list[dict[str, Any]],
               published: dict[str, str]) -> None:
        """Record the transaction, between assembling it and publishing it."""
        committed["result"] = {"format": fmt, "path": str(out),
                               # What was shipped, so `qa package` can check
                               # the package against it rather than against a
                               # sort of its own file names.
                               "manifest": manifest}
        journal.write(doc_path, destination=out, published=published,
                      result=committed["result"], options=options)

    write = {"cbz": writers.export_cbz, "pdf": writers.export_pdf,
             "dir": writers.export_dir}[fmt]
    report = write(doc, root, out, quality, draft, commit)

    # Counted from what was actually written, not from what the document says
    # exists. A recorded `final` whose file has been deleted is not a
    # typeset page, and a cleaned page is not an unchanged original.
    report["sources"] = sources
    report["draft"] = draft
    if draft:
        # A draft says so in the report AND in the package. Without the second
        # one, a folder or archive produced with `--draft` is indistinguishable
        # from an approved edition as soon as the report scrolls away.
        report["approved"] = False
        report["note"] = ("DRAFT — this package did NOT pass publication QA "
                          "and must not be shipped as a finished chapter.")
    else:
        report["approved"] = True
    report["typeset_pages"] = sum(1 for key in sources.values() if key == "final")
    report["cleaned_pages"] = sum(1 for key in sources.values() if key == "clean")
    report["original_pages"] = sum(1 for key in sources.values() if key == "image")
    report["untouched_pages"] = report["original_pages"]
    if unrendered:
        report["unrendered_pages"] = unrendered
        report["note"] = (
            f"DRAFT: {len(unrendered)} page(s) carry Persian that was never "
            "rendered and shipped without it. `sources` says which file each "
            "page used."
        )
    elif report["original_pages"]:
        report["note"] = (
            f"{report['original_pages']} page(s) had no translated text and "
            "were exported exactly as they arrived."
        )
    # Exactly what the journal recorded, so the stamp and the record can never
    # describe two different editions.
    result = dict(committed["result"])
    result["editions"] = _editions(doc, out, result)
    stages.stamp_stage(doc, "export", result, options=options)
    ir.save_doc(doc, doc_path)
    journal.clear(doc_path)
    return report


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic export", description="Write the finished chapter out."
    )
    parser.add_argument("--doc", required=True)
    parser.add_argument("--out", required=True,
                        help="chapter-fa.cbz, chapter-fa.pdf, or a folder")
    parser.add_argument("--format", choices=list(FORMATS), default=None,
                        help="inferred from --out when omitted")
    parser.add_argument("--draft", action="store_true",
                        help="ship pages whose Persian was never rendered, "
                             "using their cleaned or original image; the "
                             "report then says which file each page used")
    parser.add_argument("--jpeg-quality", type=int, default=0,
                        help="re-encode pages as JPEG at this quality; 0 keeps "
                             "the original bytes, which is the default. Note "
                             "that JPEG is not automatically smaller: line art "
                             "with flat whites compresses better as PNG, and "
                             "JPEG adds ringing along every ink edge")
    args = parser.parse_args(argv)

    report = export_document(
        args.doc, args.out, fmt=args.format, quality=args.jpeg_quality,
        draft=args.draft,
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
