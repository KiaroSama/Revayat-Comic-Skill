"""The page document — the one thing every stage reads and writes.

Detection, OCR, translation, cleaning, typesetting and QA all talk to this
structure and never to each other. That is the whole point: a detector can be
swapped, an OCR engine can disappear and a renderer can be rewritten without
any of the other stages noticing, because none of them ever sees a provider's
own object.

Two invariants are enforced here rather than trusted to callers:

* **The source page is immutable.** Every page records the SHA-256 of the file
  it was extracted from. Nothing in the pipeline writes to that file, and
  ``qa`` re-hashes it. A stage that needs different pixels writes a new file.
* **Region ids never move.** They are allocated once, at detection, and they
  are what the worksheet, the mask filenames, the glossary and every QA finding
  refer to. Renumbering them silently re-points all four.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_VERSION = 1
TOOL_NAME = "revayat-comic"
TOOL_VERSION = "1.0.0"

#: What a text region is. ``sfx`` is separated from dialogue because it is
#: lettering drawn into the artwork, and the policy for it differs — see
#: ``references/sound-effects.md``.
REGION_KINDS = ("speech", "thought", "narration", "sfx", "sign", "unknown")

#: How the source text runs inside the region. Japanese dialogue is usually
#: vertical; the crop for a vertical region is rotated before it is shown to a
#: reader, and Persian never inherits the orientation.
ORIENTATIONS = ("horizontal", "vertical")

#: What was done to the artwork underneath a region.
FILL_MODES = ("none", "flat", "inpaint", "external", "keep")


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #

def use_utf8_stdio() -> None:
    """Make stdout/stderr carry Persian and Japanese on every platform.

    A Windows console defaults to a legacy code page and raises
    ``UnicodeEncodeError`` on the first non-Latin character, which turns a
    working pipeline into a crash at the moment it prints its result.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - detached stream
                pass


def write_text(path: str | os.PathLike[str], text: str) -> Path:
    """Write UTF-8 atomically, with the newlines that were asked for.

    ``newline=""`` matters: without it Python rewrites every ``\\n`` to
    ``\\r\\n`` on Windows, so a file written on one platform stops matching the
    same file written on another and every content hash disagrees.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=str(target.parent),
        prefix=f".{target.name}.", suffix=".tmp",
    )
    try:
        with handle as stream:
            stream.write(text)
        os.replace(handle.name, target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return target


def write_bytes(path: str | os.PathLike[str], payload: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", delete=False, dir=str(target.parent),
        prefix=f".{target.name}.", suffix=".tmp",
    )
    try:
        with handle as stream:
            stream.write(payload)
        os.replace(handle.name, target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return target


def read_text(path: str | os.PathLike[str]) -> str:
    return Path(path).read_text(encoding="utf-8")


def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)


def emit(payload: Any) -> None:
    """Print a stage report. Every stage speaks JSON on stdout, nothing else."""
    print(dumps(payload))


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------- #
# Document construction
# --------------------------------------------------------------------------- #

def new_doc(
    *,
    source_language: str = "auto",
    target_language: str = "fa",
    reading_direction: str = "rtl",
    title: str = "",
    chapter: str = "",
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "meta": {
            "tool": f"{TOOL_NAME} {TOOL_VERSION}",
            "title": title,
            "chapter": chapter,
            "source_language": source_language,
            "target_language": target_language,
            "reading_direction": reading_direction,
            "sfx_policy": "keep",
        },
        "source": {},
        "pages": [],
        "glossary": {},
        "stages": {},
    }


def new_page(
    page_id: str, index: int, image: str, width: int, height: int, sha256: str
) -> dict[str, Any]:
    return {
        "id": page_id,
        "index": index,
        "image": image,
        "sha256": sha256,
        "width": int(width),
        "height": int(height),
        "panels": [],
        "regions": [],
        "notes": [],
    }


def new_region(
    region_id: str,
    bbox: Sequence[float],
    *,
    kind: str = "unknown",
    orientation: str = "horizontal",
    detector: str = "classical",
    confidence: float = 0.0,
) -> dict[str, Any]:
    if kind not in REGION_KINDS:
        raise ValueError(f"unknown region kind {kind!r}")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"unknown orientation {orientation!r}")
    return {
        "id": region_id,
        "bbox": [int(round(value)) for value in bbox],
        "polygon": [],
        "kind": kind,
        "orientation": orientation,
        "reading_order": 0,
        "panel": None,
        "speaker": None,
        "source_text": "",
        "target_text": "",
        "detector": detector,
        "confidence": float(confidence),
        "mask": None,
        "fill": "none",
        "typeset": {},
        "locked": False,
        "review": [],
    }


def page_id_for(index: int) -> str:
    return f"p{index + 1:04d}"


def region_id_for(page: dict[str, Any], ordinal: int) -> str:
    return f"{page['id']}r{ordinal:03d}"


# --------------------------------------------------------------------------- #
# Loading and saving
# --------------------------------------------------------------------------- #

def load_doc(path: str | os.PathLike[str]) -> dict[str, Any]:
    doc = json.loads(read_text(path))
    version = doc.get("version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{path}: document schema {version!r}, this build reads "
            f"{SCHEMA_VERSION}. Re-run `import` to rebuild it."
        )
    return doc


def save_doc(doc: dict[str, Any], path: str | os.PathLike[str]) -> Path:
    return write_text(path, dumps(doc) + "\n")


def doc_dir(path: str | os.PathLike[str]) -> Path:
    """The folder a document's relative asset paths resolve against."""
    return Path(path).resolve().parent


def resolve(doc_path: str | os.PathLike[str], relative: str) -> Path:
    return doc_dir(doc_path) / relative


# --------------------------------------------------------------------------- #
# Traversal
# --------------------------------------------------------------------------- #

def iter_regions(doc: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for page in doc.get("pages", []):
        for region in page.get("regions", []):
            yield page, region


def all_regions(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [region for _, region in iter_regions(doc)]


def find_page(doc: dict[str, Any], page_id: str) -> dict[str, Any] | None:
    for page in doc.get("pages", []):
        if page["id"] == page_id:
            return page
    return None


def find_region(doc: dict[str, Any], region_id: str) -> dict[str, Any] | None:
    for _, region in iter_regions(doc):
        if region["id"] == region_id:
            return region
    return None


def translatable(region: dict[str, Any], sfx_policy: str = "keep") -> bool:
    """Whether this region is expected to end up carrying Persian.

    An SFX under the ``keep`` policy is deliberately left in the artwork, so it
    is not a hole in the translation and QA must not report one.
    """
    if region["kind"] == "sfx":
        return sfx_policy in {"translate", "bilingual", "annotate"}
    return True


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #

def bbox_area(bbox: Sequence[float]) -> float:
    return max(0.0, float(bbox[2])) * max(0.0, float(bbox[3]))


def bbox_corners(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    x, y, w, h = (float(v) for v in bbox)
    return x, y, x + w, y + h


def bbox_intersection(a: Sequence[float], b: Sequence[float]) -> list[float]:
    ax0, ay0, ax1, ay1 = bbox_corners(a)
    bx0, by0, bx1, by1 = bbox_corners(b)
    x0, y0 = max(ax0, bx0), max(ay0, by0)
    x1, y1 = min(ax1, bx1), min(ay1, by1)
    if x1 <= x0 or y1 <= y0:
        return [0.0, 0.0, 0.0, 0.0]
    return [x0, y0, x1 - x0, y1 - y0]


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    overlap = bbox_area(bbox_intersection(a, b))
    union = bbox_area(a) + bbox_area(b) - overlap
    return overlap / union if union > 0 else 0.0


def bbox_contains(outer: Sequence[float], inner: Sequence[float], slack: float = 0.9) -> bool:
    """True when `slack` of `inner`'s area falls inside `outer`."""
    area = bbox_area(inner)
    if area <= 0:
        return False
    return bbox_area(bbox_intersection(outer, inner)) / area >= slack


def clamp_bbox(bbox: Sequence[float], width: int, height: int) -> list[int]:
    x0, y0, x1, y1 = bbox_corners(bbox)
    x0 = max(0, min(int(round(x0)), width))
    y0 = max(0, min(int(round(y0)), height))
    x1 = max(0, min(int(round(x1)), width))
    y1 = max(0, min(int(round(y1)), height))
    return [x0, y0, max(0, x1 - x0), max(0, y1 - y0)]


def expand_bbox(bbox: Sequence[float], margin: float, width: int, height: int) -> list[int]:
    x, y, w, h = (float(v) for v in bbox)
    return clamp_bbox([x - margin, y - margin, w + 2 * margin, h + 2 * margin],
                      width, height)


def bbox_center(bbox: Sequence[float]) -> tuple[float, float]:
    x, y, w, h = (float(v) for v in bbox)
    return x + w / 2.0, y + h / 2.0


# --------------------------------------------------------------------------- #
# Reading order
# --------------------------------------------------------------------------- #

def _row_bands(boxes: Sequence[Sequence[float]], tolerance: float) -> list[list[int]]:
    """Group box indices into bands that overlap vertically.

    Two balloons side by side in one tier of a panel belong to the same band and
    are then ordered horizontally. Without banding, a plain sort by ``y`` puts a
    balloon three pixels higher than its neighbour first, which reads wrong on
    every page that has a pair of them.
    """
    order = sorted(range(len(boxes)), key=lambda i: boxes[i][1])
    bands: list[list[int]] = []
    for index in order:
        y0 = float(boxes[index][1])
        height = float(boxes[index][3])
        placed = False
        for band in bands:
            top = min(float(boxes[i][1]) for i in band)
            bottom = max(float(boxes[i][1]) + float(boxes[i][3]) for i in band)
            # Same band when the new box starts before the band's rows end,
            # allowing for the tolerance that a hand-drawn page always needs.
            if y0 < bottom - tolerance * min(height, bottom - top):
                band.append(index)
                placed = True
                break
        if not placed:
            bands.append([index])
    return bands


def assign_reading_order(
    page: dict[str, Any], direction: str = "rtl", tolerance: float = 0.35
) -> list[dict[str, Any]]:
    """Number the regions the way the page is read, panel by panel.

    Panels come first when they are known: a manga page is read panel by panel,
    and a balloon at the top of the second panel comes after a balloon at the
    bottom of the first even though it sits higher on the paper.
    """
    regions = page.get("regions", [])
    if not regions:
        return regions

    panels = page.get("panels", [])
    groups: dict[str | None, list[dict[str, Any]]] = {}
    if panels:
        panel_boxes = [(panel["id"], panel["bbox"]) for panel in panels]
        panel_bands = _row_bands([box for _, box in panel_boxes], tolerance)
        panel_sequence: list[str] = []
        for band in panel_bands:
            band.sort(
                key=lambda i: bbox_center(panel_boxes[i][1])[0],
                reverse=direction == "rtl",
            )
            panel_sequence.extend(panel_boxes[i][0] for i in band)
        for panel_id in panel_sequence:
            groups[panel_id] = []
        for region in regions:
            key = region.get("panel") if region.get("panel") in groups else None
            groups.setdefault(key, []).append(region)
        # A region belonging to no panel is read last, not first: it is usually
        # a caption in the gutter or an SFX that spills across the page.
        sequence = [pid for pid in panel_sequence if groups.get(pid)]
        if groups.get(None):
            sequence.append(None)
    else:
        groups[None] = list(regions)
        sequence = [None]

    counter = 0
    ordered: list[dict[str, Any]] = []
    for key in sequence:
        members = groups.get(key) or []
        boxes = [member["bbox"] for member in members]
        for band in _row_bands(boxes, tolerance):
            band.sort(
                key=lambda i: bbox_center(boxes[i])[0], reverse=direction == "rtl"
            )
            for index in band:
                counter += 1
                members[index]["reading_order"] = counter
                ordered.append(members[index])

    page["regions"] = sorted(regions, key=lambda r: r.get("reading_order") or 0)
    return page["regions"]


# --------------------------------------------------------------------------- #
# Script detection
# --------------------------------------------------------------------------- #

_SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    # Persian and Arabic share a script; the target-language check below
    # distinguishes them by the letters Persian actually uses.
    "arabic": ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
    "latin": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F)),
    "hiragana": ((0x3040, 0x309F),),
    "katakana": ((0x30A0, 0x30FF), (0x31F0, 0x31FF)),
    "han": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)),
    "hangul": ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)),
    "cyrillic": ((0x0400, 0x04FF),),
}


def script_counts(text: str) -> dict[str, int]:
    counts = {name: 0 for name in _SCRIPT_RANGES}
    for character in text:
        code = ord(character)
        for name, ranges in _SCRIPT_RANGES.items():
            if any(low <= code <= high for low, high in ranges):
                counts[name] += 1
                break
    return counts


def dominant_script(text: str) -> str:
    counts = script_counts(text)
    best = max(counts, key=lambda name: counts[name])
    return best if counts[best] else "none"


def looks_like(text: str, language: str) -> bool:
    """Whether `text` is plausibly written in `language`.

    Used by QA to catch the two failures that matter: a Persian field that is
    still Japanese, and a Persian field that is really Arabic transliteration.
    """
    counts = script_counts(text)
    total = sum(counts.values())
    if not total:
        return False
    share = {name: value / total for name, value in counts.items()}
    if language in {"fa", "ar", "fas", "per"}:
        return share["arabic"] > 0.5
    if language in {"ja", "jpn"}:
        return share["hiragana"] + share["katakana"] + share["han"] > 0.5
    if language in {"ko", "kor"}:
        return share["hangul"] > 0.4
    if language in {"zh", "zho", "cmn"}:
        return share["han"] > 0.5
    if language in {"en", "eng"}:
        return share["latin"] > 0.5
    return True


#: Persian uses these four letters; Arabic writes the first two differently and
#: has no گ/چ/پ/ژ at all. Their presence is the cheapest positive signal that a
#: string is Persian rather than Arabic.
_PERSIAN_ONLY = re.compile(r"[گچپژکی]")


def is_persian(text: str) -> bool:
    return bool(_PERSIAN_ONLY.search(text)) and looks_like(text, "fa")


# --------------------------------------------------------------------------- #
# Staleness
# --------------------------------------------------------------------------- #

def fingerprint(doc: dict[str, Any]) -> str:
    """A hash of everything a worksheet was generated from.

    Re-detecting a page changes region ids and boxes, which silently invalidates
    every worksheet already written against the old ones. ``worksheet merge``
    compares this and refuses rather than merging a reply into the wrong region.
    """
    digest = hashlib.sha256()
    for page in doc.get("pages", []):
        digest.update(f"{page['id']}|{page['sha256']}".encode("utf-8"))
        for region in page.get("regions", []):
            digest.update(
                "|".join([
                    region["id"],
                    ",".join(str(v) for v in region["bbox"]),
                    region["kind"],
                    region["orientation"],
                ]).encode("utf-8")
            )
    return digest.hexdigest()


def stamp_stage(doc: dict[str, Any], stage: str, detail: dict[str, Any]) -> None:
    """Record that a stage ran, with the fingerprint it ran against."""
    doc.setdefault("stages", {})[stage] = {
        "fingerprint": fingerprint(doc),
        **detail,
    }


# --------------------------------------------------------------------------- #
# Optional dependencies
# --------------------------------------------------------------------------- #

class MissingDependency(RuntimeError):
    """Raised with an instruction the user can act on, not a stack trace."""


def require(module: str, package: str, why: str):
    """Import `module`, or explain exactly what to install and why."""
    try:
        return __import__(module)
    except ImportError as error:
        raise MissingDependency(
            f"{why} needs the {package} package. Install it with:\n"
            f"    pip install {package}"
        ) from error


def load_image(path: str | os.PathLike[str]):
    """Open an image as RGB, with the file handle closed before we return.

    Pillow is lazy; leaving the handle open means a later stage cannot replace
    the file on Windows, which fails with a permission error that says nothing
    about the real cause.
    """
    require("PIL", "pillow", "reading comic pages")
    from PIL import Image

    with open(path, "rb") as stream:
        payload = stream.read()
    with Image.open(io.BytesIO(payload)) as image:
        return image.convert("RGB")


def save_image(image, path: str | os.PathLike[str], **options: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    suffix = target.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(buffer, "JPEG", quality=options.pop("quality", 95),
                                  subsampling=0, **options)
    else:
        image.save(buffer, "PNG", **options)
    return write_bytes(target, buffer.getvalue())
