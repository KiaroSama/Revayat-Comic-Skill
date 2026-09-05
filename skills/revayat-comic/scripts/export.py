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
import zipfile
from pathlib import Path
from typing import Any

import pageir as ir

FORMATS = ("cbz", "pdf", "dir")


def _page_source(root: Path, page: dict[str, Any]) -> Path:
    """The most finished version of this page that exists."""
    for key in ("final", "clean", "image"):
        relative = page.get(key)
        if relative and (root / relative).exists():
            return root / relative
    raise FileNotFoundError(f"no image for {page['id']}")


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
        # the other way round. Readers honour this tag; without it every spread
        # in the book is shown back to front.
        ("Manga", "Yes" if meta.get("reading_direction") == "rtl" else "No"),
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
        document.save(str(out), garbage=3, deflate=True)
    finally:
        document.close()
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
        and child.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        and child.name not in planned
    )
    if strangers:
        raise ValueError(
            f"{out} already contains {len(strangers)} image(s) that this export "
            f"will not replace ({', '.join(strangers[:4])}…). They would be "
            "shipped as part of the chapter. Export to an empty folder."
        )

    for page in doc["pages"]:
        source = _page_source(root, page)
        name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
        payload, name = _encode(source, name, quality)
        ir.write_bytes(out / name, payload)
    ir.write_text(out / "ComicInfo.xml", _comic_info(doc))
    return {"format": "dir", "path": str(out), "pages": len(doc["pages"])}


def export_document(
    doc_path: str | Path, out: str | Path, *, fmt: str | None = None,
    quality: int = 0,
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

    writers = {"cbz": _export_cbz, "pdf": _export_pdf, "dir": _export_dir}
    report = writers[fmt](doc, root, out, quality)

    finished = sum(1 for page in doc["pages"] if page.get("final"))
    report["typeset_pages"] = finished
    report["untouched_pages"] = len(doc["pages"]) - finished
    if report["untouched_pages"]:
        report["note"] = (
            f"{report['untouched_pages']} page(s) had no translated text and "
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
    parser.add_argument("--jpeg-quality", type=int, default=0,
                        help="re-encode pages as JPEG at this quality; 0 keeps "
                             "the original bytes, which is the default. Note "
                             "that JPEG is not automatically smaller: line art "
                             "with flat whites compresses better as PNG, and "
                             "JPEG adds ringing along every ink edge")
    args = parser.parse_args(argv)

    report = export_document(
        args.doc, args.out, fmt=args.format, quality=args.jpeg_quality
    )
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
