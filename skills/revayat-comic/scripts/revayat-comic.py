"""Revayat Comic — one entry point for every stage.

    python revayat-comic.py doctor
    python revayat-comic.py import    chapter.cbz --out work/
    python revayat-comic.py detect    --doc work/comic.json
    python revayat-comic.py mask      --doc work/comic.json
    python revayat-comic.py crops     --doc work/comic.json
    python revayat-comic.py worksheet build --doc work/comic.json
    python revayat-comic.py worksheet merge --doc work/comic.json
    python revayat-comic.py glossary  scan --doc work/comic.json
    python revayat-comic.py falint    fix --doc work/comic.json
    python revayat-comic.py clean     --doc work/comic.json
    python revayat-comic.py typeset   --doc work/comic.json
    python revayat-comic.py qa        check --doc work/comic.json
    python revayat-comic.py export    --doc work/comic.json --out chapter-fa.cbz

``doctor`` is the first thing to run. Two of the things it reports decide
whether Persian will come out correct rather than merely present: whether
Pillow can shape Arabic-script text itself, and whether the machine has a font
that can draw it.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pageir as ir  # noqa: E402  (must follow the sys.path bootstrap)

STAGES = {
    "import": "readers",
    "detect": "detect",
    "mask": "masks",
    "crops": "crops",
    "worksheet": "worksheet",
    # Optional and off by default: the reading model is the transcriber. See
    # references/ocr.md before turning it on.
    "ocr": "ocr",
    "context": "context",
    "translate": "translate",
    "glossary": "glossary",
    "falint": "falint",
    "clean": "clean",
    "typeset": "typeset",
    "qa": "qa",
    "export": "export",
}

REQUIRED = {
    "PIL": ("pillow", "reading pages, and drawing Persian into them"),
    "numpy": ("numpy", "every pixel measurement in the pipeline"),
    "cv2": ("opencv-python-headless", "detecting balloons, building masks, inpainting"),
}

OPTIONAL = {
    "pymupdf": ("pymupdf", "reading a comic from a PDF and exporting to one"),
    "rarfile": ("rarfile", "reading CBR archives (also needs an unrar binary)"),
    "arabic_reshaper": ("arabic-reshaper",
                        "Persian shaping when Pillow has no RAQM"),
    "bidi": ("python-bidi", "Persian direction when Pillow has no RAQM"),
    "manga_ocr": ("manga-ocr",
                  "a second opinion on Japanese text; the reader's own eyes are "
                  "the first"),
}


def _version(module_name: str, package: str) -> str:
    module = importlib.import_module(module_name)
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    try:
        from importlib.metadata import version as package_version

        return str(package_version(package))
    except Exception:
        return "installed"


def doctor() -> dict[str, object]:
    required: dict[str, str] = {}
    missing: list[str] = []
    for module_name, (package, why) in REQUIRED.items():
        try:
            required[module_name] = _version(module_name, package)
        except ImportError:
            required[module_name] = f"MISSING — needed for {why}"
            missing.append(package)

    optional: dict[str, str] = {}
    for module_name, (package, why) in OPTIONAL.items():
        try:
            optional[module_name] = _version(module_name, package)
        except ImportError:
            optional[module_name] = f"not installed — {why}"

    persian: dict[str, object] = {}
    if "PIL" not in missing and not required["PIL"].startswith("MISSING"):
        import typeset

        raqm = typeset.raqm_available()
        persian["shaping"] = "raqm" if raqm else "reshaper fallback"
        persian["raqm"] = raqm
        if not raqm:
            have_fallback = all(
                not optional[name].startswith("not installed")
                for name in ("arabic_reshaper", "bidi")
            )
            persian["shaping_note"] = (
                "Pillow has no RAQM here, so Persian is shaped by "
                "arabic-reshaper and reordered by python-bidi. Pages come out "
                "correct to read. Pillow's wheels DO carry libraqm on Windows and macOS as well as Linux; what is missing here is FriBiDi, which libraqm loads at run time. On Windows, put a `fribidi.dll` (or `fribidi-0.dll` / `libfribidi-0.dll`) on PATH and RAQM turns on — beside python.exe is not enough, it has to be a directory in the DLL search order. Measured: with one on PATH this machine reports raqm true."
            )
            persian["fallback_installed"] = have_fallback
            if not have_fallback:
                persian["shaping_error"] = (
                    "No RAQM *and* no fallback. Persian cannot be drawn at "
                    "all. Run: pip install arabic-reshaper python-bidi"
                )
        try:
            font = typeset.find_font()
            persian["font"] = str(font)
            persian["font_draws_persian"] = typeset._supports_persian(font)
            # Persian in this project is set in Vazir. A fallback face still
            # produces readable pages, which is exactly why it has to be said
            # out loud — otherwise a whole volume ships in Tahoma and nobody
            # notices until it is printed.
            persian["vazir"] = typeset.is_vazir(font)
            if not persian["vazir"]:
                persian["font_note"] = (
                    f"Persian here is set in Vazir; this machine only has "
                    f"{font.name}. Pages will be readable but not in the house "
                    f"face. Install Vazirmatn from "
                    f"https://github.com/rastikerdar/vazirmatn/releases, or "
                    f"pass --font to name it explicitly."
                )
        except ir.MissingDependency as error:
            persian["font"] = None
            persian["font_error"] = str(error)

    # Not ready without *some* way to shape Persian: no RAQM and no fallback
    # means the typesetter would draw disconnected letters in the wrong order,
    # which is worse than refusing, because it looks like output.
    can_shape = persian.get("raqm") or persian.get("fallback_installed")
    ready = not missing and bool(persian.get("font")) and bool(can_shape)
    return {
        "python": sys.version.split()[0],
        "required": required,
        "optional": optional,
        "persian": persian,
        "ready": ready,
        "install": (
            "pip install -r requirements.txt" if missing else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(__doc__.strip())
        print("\nstages: " + ", ".join(sorted(STAGES)) + ", doctor")
        return 0

    stage, rest = argv[0], argv[1:]

    if stage == "doctor":
        report = doctor()
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report["ready"] else 1

    if stage not in STAGES:
        print(f"unknown stage {stage!r}; expected one of "
              f"{', '.join(sorted(STAGES))}, doctor", file=sys.stderr)
        return 2

    module = importlib.import_module(STAGES[stage])
    try:
        return int(module.main(rest) or 0)
    except ir.MissingDependency as error:
        # A missing package is a thing the user can fix in one command. Saying
        # so beats a traceback that buries the instruction under a stack.
        print(str(error), file=sys.stderr)
        return 3
    except (FileNotFoundError, ValueError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
