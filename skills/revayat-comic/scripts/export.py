"""Write the finished pages out as CBZ, PDF or a plain folder.

Page order is the only thing that can be silently wrong in an export, because
every reader sorts an archive's names itself and none of them agree about what
``page10`` means next to ``page9``. The names written here are zero-padded and
already in reading order, so byte-wise sorting and reading order are the same
thing and no reader has to guess.

Nothing is re-encoded unless it has to be. A page that was never touched is
copied through byte for byte.
"""

from __future__ import annotations

import argparse
import sys
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pageir as ir
from pageir import IMAGE_SUFFIXES

FORMATS = ("cbz", "pdf", "dir")


def _resolve(root: Path, page: dict[str, Any]) -> tuple[Path, str]:
    """The most finished version of this page that exists, and which it is."""
    for key in ("final", "clean", "image"):
        relative = page.get(key)
        if relative and (root / relative).exists():
            return root / relative, key
    raise FileNotFoundError(f"no image for {page['id']}")


def _page_source(root: Path, page: dict[str, Any]) -> Path:
    return _resolve(root, page)[0]


def _wants_rendering(page: dict[str, Any]) -> bool:
    """Whether this page has Persian on it that a render has to carry."""
    return any((region.get("target_text") or "").strip()
               for region in page.get("regions", [])
               if not region.get("dropped"))


def _manifest(doc: dict[str, Any], root: Path) -> dict[str, str]:
    """Which file each page will ship, resolved before anything is written."""
    return {page["id"]: _resolve(root, page)[1] for page in doc["pages"]}


def _dependencies(doc: dict[str, Any], root: Path, doc_path: Path) -> set[Path]:
    """Every file this chapter is made of, resolved through symlinks.

    An export reads these while it writes, so writing onto one of them destroys
    the chapter mid-flight. Resolved rather than compared as written, because
    `work/pages/../pages/p0001.png` and a symlink alias name the same bytes.
    """
    found = {doc_path.resolve()}
    for page in doc.get("pages", []):
        for key in ("image", "clean", "final", "mask", "writable"):
            relative = page.get(key)
            if isinstance(relative, str) and relative:
                candidate = root / relative
                if candidate.exists():
                    found.add(candidate.resolve())
    return found


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


def _export_cbz(doc: dict[str, Any], root: Path, out: Path,
                quality: int) -> dict[str, Any]:
    written = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written to a temporary name and moved into place, so an interrupted export
    # cannot leave a half-written archive that opens and is missing chapters.
    staging = out.with_suffix(out.suffix + ".part")
    with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
        for page in doc["pages"]:
            source = _page_source(root, page)
            name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
            payload, name = _encode(source, name, quality)
            archive.writestr(name, payload)
            written += 1
        archive.writestr(
            "ComicInfo.xml", _comic_info(doc).encode("utf-8")
        )
    staging.replace(out)
    return {"format": "cbz", "path": str(out), "pages": written}


def _encode(source: Path, name: str, quality: int) -> tuple[bytes, str]:
    """Bytes for the archive: as-is, or re-encoded to JPEG when asked."""
    if quality <= 0 or source.suffix.lower() in {".jpg", ".jpeg"}:
        return source.read_bytes(), name
    import io

    image = ir.load_image(source)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, subsampling=0, optimize=True)
    return buffer.getvalue(), str(Path(name).with_suffix(".jpg"))


def _comic_info(doc: dict[str, Any]) -> str:
    """The metadata sidecar every comic reader looks for."""
    meta = doc["meta"]

    def escape(value: str) -> str:
        return (str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    fields = [
        ("Title", meta.get("title", "")),
        ("Number", meta.get("chapter", "")),
        ("LanguageISO", meta.get("target_language", "fa")),
        ("PageCount", str(len(doc["pages"]))),
        ("Translator", meta.get("tool", "")),
        # Persian is read right to left, so a two-page spread has to be paired
        # the other way round. `Manga` carries that: the ComicInfo
        # documentation says the field "defines the reading direction as
        # right-to-left when set to YesAndRightToLeft". Plain `Yes` only says
        # the book is a manga and leaves direction unstated, so every spread
        # in the book was still shown back to front.
        ("Manga", "YesAndRightToLeft"
         if meta.get("reading_direction") == "rtl" else "No"),
    ]
    body = "".join(
        f"  <{name}>{escape(value)}</{name}>\n" for name, value in fields if value
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        f"{body}</ComicInfo>\n"
    )


def _export_pdf(doc: dict[str, Any], root: Path, out: Path,
                quality: int) -> dict[str, Any]:
    pymupdf = ir.require("pymupdf", "pymupdf", "writing a PDF")
    out.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        for page in doc["pages"]:
            source = _page_source(root, page)
            payload, _ = _encode(source, source.name, quality)
            rect = pymupdf.Rect(0, 0, page["width"], page["height"])
            new_page = document.new_page(width=page["width"], height=page["height"])
            new_page.insert_image(rect, stream=payload)
        document.set_metadata({
            "title": doc["meta"].get("title", ""),
            "producer": doc["meta"].get("tool", ""),
        })
        # Saved beside the destination and moved into place, so a write that
        # fails part way cannot replace a good package with a truncated one.
        staging = out.with_suffix(out.suffix + ".part")
        document.save(str(staging), garbage=3, deflate=True)
    finally:
        document.close()
    staging.replace(out)
    return {"format": "pdf", "path": str(out), "pages": len(doc["pages"])}


def _export_dir(doc: dict[str, Any], root: Path, out: Path,
                quality: int) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)

    planned = set()
    for page in doc["pages"]:
        source = _page_source(root, page)
        name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
        planned.add(_encode(source, name, quality)[1])

    # Exporting into a folder that already holds other images would mix them
    # into the chapter — pointing --out at the working folder's own `pages/`
    # silently ships the untranslated originals alongside the finished ones.
    strangers = sorted(
        child.name for child in out.iterdir()
        if child.is_file()
        and child.suffix.lower() in IMAGE_SUFFIXES
        and child.name not in planned
    )
    if strangers:
        raise ValueError(
            f"{out} already contains {len(strangers)} image(s) that this export "
            f"will not replace ({', '.join(strangers[:4])}…). They would be "
            "shipped as part of the chapter. Export to an empty folder."
        )

    # Written to a staging folder and moved in, so a chapter that fails half
    # way — an unreadable page, a full disk — leaves the previous export whole
    # instead of a mixture of two. Moved file by file rather than swapping the
    # folder, because anything else the operator keeps in there is not ours.
    staging = out.with_name(out.name + ".part")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for page in doc["pages"]:
            source = _page_source(root, page)
            name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
            payload, name = _encode(source, name, quality)
            ir.write_bytes(staging / name, payload)
        ir.write_text(staging / "ComicInfo.xml", _comic_info(doc))
        for child in sorted(staging.iterdir()):
            child.replace(out / child.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"format": "dir", "path": str(out), "pages": len(doc["pages"])}


def export_document(
    doc_path: str | Path, out: str | Path, *, fmt: str | None = None,
    quality: int = 0, draft: bool = False,
) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    root = ir.doc_dir(doc_path)
    out = Path(out).expanduser()

    if fmt is None:
        suffix = out.suffix.lower()
        fmt = {".cbz": "cbz", ".zip": "cbz", ".pdf": "pdf"}.get(suffix, "dir")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")
    _refuse_collisions(doc, root, doc_path, out, fmt)

    # Resolved before a byte is written, because the fallback is silent: a
    # page whose render is missing shipped its cleaned version — or the
    # untranslated original — and was still counted under `typeset_pages`.
    sources = _manifest(doc, root)
    unrendered = sorted(
        page["id"] for page in doc["pages"]
        if _wants_rendering(page) and sources[page["id"]] != "final"
    )
    if unrendered and not draft:
        raise ValueError(
            f"{len(unrendered)} page(s) carry Persian that has not been "
            f"rendered: {', '.join(unrendered[:6])}. Run `typeset`, or pass "
            "--draft to ship the cleaned pages instead and have the report "
            "say so page by page."
        )

    writers = {"cbz": _export_cbz, "pdf": _export_pdf, "dir": _export_dir}
    report = writers[fmt](doc, root, out, quality)

    # Counted from what was actually written, not from what the document says
    # exists. A recorded `final` whose file has been deleted is not a
    # typeset page, and a cleaned page is not an unchanged original.
    report["sources"] = sources
    report["draft"] = draft
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
    ir.stamp_stage(doc, "export", {"format": fmt, "path": str(out)})
    ir.save_doc(doc, doc_path)
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
