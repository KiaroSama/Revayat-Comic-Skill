"""Assembling each package format, and putting it where it belongs.

Three writers with one shape: encode the whole chapter into a staging path this
run owns, hand the recorded bytes to `commit` — the one moment at which the
recovery record can be written before anything is published — and only then
promote. Nothing here decides whether a chapter MAY be published; `export` does
that before calling in.

Split out of `export` when that file passed the size at which a module is
closed to new code. The division is by question: `export` resolves what to
publish and what must not be written over, this turns it into bytes at a
destination.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pageir as ir
from pageir import IMAGE_SUFFIXES

def _resolve(root: Path, page: dict[str, Any]) -> tuple[Path, str]:
    """The most finished version of this page that exists, and which it is.

    The order lives in `regions` because the gate measures against it: what
    this resolves to has to be the same thing `required_artifact` is compared
    with, or the fallback is invisible again.
    """
    found = ir.shipped_artifact(root, page)
    if found is None:
        raise FileNotFoundError(f"no image for {page['id']}")
    return found


def _page_source(root: Path, page: dict[str, Any]) -> Path:
    return _resolve(root, page)[0]


def staging_path(out: Path) -> Path:
    """Where an export assembles the bytes it is about to publish.

    Deterministic, because this path is also the lock. A random suffix made
    ownership a fact and serialization impossible: two exports of one chapter
    to one destination each wrote their own staging file and both promoted,
    the last writer winning, with neither knowing the other existed.

    The name is ours — `.revayat-part`, not `.part` — so claiming it cannot
    collide with an operator's own working file, which is what the random
    suffix was introduced to avoid.
    """
    return out.with_name(out.name + ".revayat-part")


def _kept_path(out: Path) -> Path:
    """Where a folder export holds the previous edition while it promotes."""
    return out.with_name(out.name + ".revayat-kept")


@contextlib.contextmanager
def _claim(path: Path, *, directory: bool) -> Iterator[Path]:
    """Take exclusive ownership of a scratch path, or refuse.

    Created with `O_EXCL` — or `mkdir` without `exist_ok`, which is the same
    guarantee — so the claim either succeeds or says somebody else is writing
    here. Released on every path, and only ever the path this made.
    """
    try:
        if directory:
            path.mkdir(parents=True, exist_ok=False)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise RuntimeError(
            f"{path} already exists, so another export is writing "
            f"{path.parent} or a previous one was killed there. Wait for it "
            f"to finish, or delete {path} and try again."
        ) from None
    try:
        yield path
    finally:
        if directory:
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
def _pixel_digest(payload: bytes) -> str:
    """A hash of what the page LOOKS like, not of how it was packed.

    A PDF re-wraps every image it is given, so the encoded bytes on the way out
    are not the encoded bytes on the way in and an exact comparison could not
    be made at all — which is why a PDF carried no hash, and why an exported
    chapter replaced by an unrelated image of the same shape passed every
    check it had.
    """
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(payload)) as image:
            return ir.sha256_bytes(image.convert("RGB").tobytes())
    except Exception:      # pragma: no cover - an unreadable page fails earlier
        return ""


def _shipped(page: dict[str, Any], name: str, payload: bytes,
             quality: int) -> dict[str, Any]:
    """One manifest row: what this page was shipped as.

    `sha256` is the hash of the bytes THIS EXPORT WROTE, whatever they are —
    the re-encoded JPEG, not the PNG it came from — so it is always comparable.
    It was gated behind `lossy` on the theory that a re-encoded page "will
    never hash to the bytes on disk", which is true of the source file and not
    of the payload recorded here: the effect was that every JPEG page in a
    package went unverified.

    `lossy` survives as truthful metadata about the encoding, and the flag was
    also inverted — a JPEG, the one lossy thing this writes, was recorded as
    lossless.

    `pixels` is the hash of the decoded image, which survives a container
    re-wrapping the bytes. It is what a PDF can be checked against — as long as
    the sheet is provably nothing but that image.

    `appearance` is for when it is not. A hash answers "are these the bytes";
    it cannot answer "is this what a reader sees", because a correct image can
    be rotated, cropped, faded or covered and still hash correctly. The
    appearance is a coarse reduction of the page that survives being rendered
    at another scale, so a sheet that is not a plain full-page image can still
    be compared with what was exported instead of being waved through on its
    dimensions.
    """
    import pdfpage

    return {
        "page": page["id"],
        "name": name,
        "sha256": ir.sha256_bytes(payload),
        "pixels": _pixel_digest(payload),
        "appearance": pdfpage.appearance(payload),
        "width": page["width"],
        "height": page["height"],
        "lossy": name.lower().endswith((".jpg", ".jpeg")),
    }


def export_cbz(doc: dict[str, Any], root: Path, out: Path, quality: int,
                draft: bool, commit: Any) -> dict[str, Any]:
    written = 0
    manifest: list[dict[str, Any]] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    # Written to a temporary name and moved into place, so an interrupted export
    # cannot leave a half-written archive that opens and is missing chapters.
    # The claim releases it on every path, so an encoding failure half way
    # through leaves the previous package untouched and no debris beside it.
    with _claim(staging_path(out), directory=False) as staging:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            for page in doc["pages"]:
                source = _page_source(root, page)
                name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
                payload, name = _encode(source, name, quality)
                archive.writestr(name, payload)
                manifest.append(_shipped(page, name, payload, quality))
                written += 1
            archive.writestr(
                "ComicInfo.xml", _comic_info(doc, draft).encode("utf-8")
            )
        # The archive is complete and nothing is published. This is the one
        # moment at which the recovery record can be written before the bytes
        # it describes exist at the destination.
        commit(manifest, {out.name: ir.sha256_file(staging)})
        staging.replace(out)
    return {"format": "cbz", "path": str(out), "pages": written,
            "manifest": manifest}


def _encode(source: Path, name: str, quality: int) -> tuple[bytes, str]:
    """Bytes for the archive: as-is, or re-encoded to JPEG when asked."""
    if quality <= 0 or source.suffix.lower() in {".jpg", ".jpeg"}:
        return source.read_bytes(), name
    import io

    image = ir.load_image(source)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, subsampling=0, optimize=True)
    return buffer.getvalue(), str(Path(name).with_suffix(".jpg"))


def _comic_info(doc: dict[str, Any], draft: bool = False) -> str:
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
        # Inside the package, so a draft cannot pass for an approved
        # edition once the report has scrolled away.
        *([("Notes", "DRAFT - did not pass publication QA")]
          if draft else []),
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


def export_pdf(doc: dict[str, Any], root: Path, out: Path, quality: int,
                draft: bool, commit: Any) -> dict[str, Any]:
    import pdfpage

    pymupdf = ir.require("pymupdf", "pymupdf", "writing a PDF")
    out.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        manifest: list[dict[str, Any]] = []
        for index, page in enumerate(doc["pages"]):
            source = _page_source(root, page)
            payload, _ = _encode(source, source.name, quality)
            rect = pymupdf.Rect(0, 0, page["width"], page["height"])
            new_page = document.new_page(width=page["width"], height=page["height"])
            new_page.insert_image(rect, stream=payload)
            manifest.append({"page": page["id"], "name": f"{index + 1:04d}",
                             "width": page["width"], "height": page["height"],
                             # What the page looks like. The encoded bytes are
                             # the PDF's to choose; the pixels are not.
                             "pixels": _pixel_digest(payload),
                             # And what it looks like at a glance, for a sheet
                             # whose structure cannot prove the embedded image
                             # is what a reader sees. Without it such a sheet
                             # can only be reported as unverifiable.
                             "appearance": pdfpage.appearance(payload),
                             "lossy": True})
        title = doc["meta"].get("title", "")
        document.set_metadata({
            # DRAFT in the package itself, not only in the report. A PDF
            # produced with `--draft` was indistinguishable from an approved
            # edition the moment the terminal scrolled away, and a PDF is the
            # format people forward.
            "title": f"[DRAFT] {title}".strip() if draft else title,
            "subject": ("DRAFT — this package did not pass publication QA"
                        if draft else ""),
            "keywords": "revayat-comic draft" if draft else "revayat-comic",
            "producer": doc["meta"].get("tool", ""),
        })
        # Saved beside the destination and moved into place, so a write that
        # fails part way cannot replace a good package with a truncated one.
        # The claim is taken and released inside this `try`, so a save that
        # raises removes its own scratch and touches nothing else.
        with _claim(staging_path(out), directory=False) as staging:
            document.save(str(staging), garbage=3, deflate=True)
            commit(manifest, {out.name: ir.sha256_file(staging)})
            staging.replace(out)
    finally:
        document.close()
    return {"format": "pdf", "path": str(out), "pages": len(doc["pages"]),
            "draft": draft, "manifest": manifest}
def _restore(out: Path, replaced: Path, promoted: list[str],
             backed_up: list[str]) -> bool:
    """Put the previous edition back. Returns whether it is safe to discard it.

    Every file this run promoted is removed and every file it moved aside is
    put back — the two lists differ, because a file can be backed up and then
    fail to be replaced.

    A restore that itself fails leaves the backup where it is: it is then the
    only copy of the operator's previous edition, and deleting it to tidy up
    after a failed rollback would turn a recoverable failure into a loss. A
    recovery note beside it says what the files are.
    """
    intact = True
    for name in reversed(promoted):
        try:
            (out / name).unlink(missing_ok=True)
        except OSError:
            intact = False
    for name in reversed(backed_up):
        kept = replaced / name
        if not kept.exists():
            continue
        try:
            kept.replace(out / name)
        except OSError:
            intact = False
    if not intact:
        try:
            ir.write_text(replaced / "RECOVERY.txt",
                          "This folder holds the previous edition of files an "
                          "export moved aside. The export failed AND putting "
                          "them back failed, so they were kept here rather "
                          "than deleted. Move them back by hand.\n")
        except OSError:
            pass
    return intact


def export_dir(doc: dict[str, Any], root: Path, out: Path, quality: int,
                draft: bool, commit: Any) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []

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
    with _claim(staging_path(out), directory=True) as staging:
        _assemble(doc, root, staging, quality, draft, manifest)
        # Every file is assembled and none of it is published. This is the one
        # moment at which the recovery record can be written before the bytes
        # it describes exist at the destination.
        commit(manifest, {child.name: ir.sha256_file(child)
                          for child in sorted(staging.iterdir())})
        _promote(out, staging)
    return {"format": "dir", "path": str(out), "pages": len(doc["pages"]),
            "manifest": manifest}


def _assemble(doc: dict[str, Any], root: Path, staging: Path, quality: int,
              draft: bool, manifest: list[dict[str, Any]]) -> None:
    """Encode the whole chapter into the staging folder."""
    for page in doc["pages"]:
        source = _page_source(root, page)
        name = f"{page['index'] + 1:04d}{source.suffix.lower()}"
        payload, name = _encode(source, name, quality)
        ir.write_bytes(staging / name, payload)
        manifest.append(_shipped(page, name, payload, quality))
    ir.write_text(staging / "ComicInfo.xml", _comic_info(doc, draft))


def _promote(out: Path, staging: Path) -> None:
    """Move the assembled edition in, with the previous one held aside.

    Promoting file by file and hoping was enough for the first failure: a
    `replace` that raised half way through left some pages from this chapter
    and the rest from the last one, in a folder that looked finished.
    """
    replaced = _kept_path(out)
    # Set before the try, because the cleanup below reads it on every path —
    # including a failure that happens before a single file has been promoted.
    rolled_back = True
    replaced.mkdir(parents=True, exist_ok=False)
    promoted: list[str] = []
    backed_up: list[str] = []
    try:
        for child in sorted(staging.iterdir()):
            target = out / child.name
            if target.exists():
                target.replace(replaced / child.name)
                # Journalled HERE, before the promotion that may fail.
                # Recording it afterwards meant the one file whose promotion
                # raised had its previous edition moved aside, left out of the
                # rollback list, and then deleted by the `finally` below — the
                # operator's current file destroyed by a failure that changed
                # nothing else.
                backed_up.append(child.name)
            child.replace(target)
            promoted.append(child.name)
    except BaseException:
        rolled_back = _restore(out, replaced, promoted, backed_up)
        raise
    finally:
        if rolled_back:
            shutil.rmtree(replaced, ignore_errors=True)
