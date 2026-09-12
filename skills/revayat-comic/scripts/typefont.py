"""The face and the shaping engine: a Persian string, turned into glyphs.

Everything here answers one question — *what will these characters look like*
— and nothing here knows where they end up. `typeset.py` owns that, and the
two were one file until it ran past the size a file is readable at.

The rule that shapes this module: **no string reversal, ever.** Persian is
written right to left, but the characters are stored in logical order and the
*renderer* is what puts them on the page. Reversing the string produces
something that looks correct in one viewer and is broken everywhere else, and
it is unsearchable and uncopyable even where it looks right. Direction comes
from HarfBuzz and FriBidi through Pillow's RAQM layout engine; when RAQM is
missing, `shape_fallback` runs and says so loudly, because pre-shaped text has
the same defects in miniature.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

import pageir as ir

ZWNJ = "\u200c"

#: Fonts that carry a full Persian glyph set, best first. Vazirmatn and Sahel
#: are the modern open Persian faces; the Noto and system entries are the
#: fallbacks that exist on a machine with nothing installed for Persian.
#: Note what is *not* here: DejaVu Sans. It is the fallback every Linux box has
#: and it contains no Arabic script at all, so it would be chosen and then draw
#: nothing. `_supports_persian` catches that, but not listing it is cheaper.
#: The house face. **Persian in this project is set in Vazir** \u2014 Vazirmatn is
#: the current release of that family and the one to install; the older `Vazir-*`
#: files are the same design under its first name. Everything after this tuple is
#: a fallback that keeps a page readable on a machine that has no Vazir, and
#: `doctor` says so out loud rather than letting one pass unnoticed.
VAZIR_FONTS = (
    "Vazirmatn-Medium.ttf", "Vazirmatn-Regular.ttf", "Vazirmatn-SemiBold.ttf",
    "Vazirmatn-Bold.ttf", "Vazirmatn-Light.ttf", "Vazirmatn-ExtraBold.ttf",
    "Vazirmatn-Black.ttf", "Vazirmatn-ExtraLight.ttf", "Vazirmatn-Thin.ttf",
    "Vazirmatn.ttf", "Vazirmatn[wght].ttf",
    "Vazirmatn-VariableFont_wght.ttf",
    "Vazir-Medium.ttf", "Vazir-Regular.ttf", "Vazir-Bold.ttf",
    "Vazir-Light.ttf", "Vazir-Thin.ttf", "Vazir.ttf",
    "Vazir-Medium-FD.ttf", "Vazir-FD.ttf",
)

PERSIAN_FONTS = VAZIR_FONTS + (
    "Sahel.ttf", "Shabnam.ttf", "IRANSansWeb.ttf", "IRANSans.ttf",
    "NotoNaskhArabic-Regular.ttf", "NotoSansArabic-Regular.ttf",
    "NotoNaskhArabic.ttf", "NotoSansArabic.ttf",
    "NotoSansArabic-VariableFont_wdth,wght.ttf",
    # macOS ships these two and nothing else with Persian coverage.
    "GeezaPro.ttc", "Geeza Pro.ttc",
    # Windows ships Tahoma, which has a complete Persian set.
    "Tahoma.ttf", "tahoma.ttf",
    "Arial.ttf", "arial.ttf", "ArialUni.ttf",
    "Nazli.ttf", "Titr.ttf", "Mitra.ttf",
)


def is_vazir(font_path: Path | str) -> bool:
    """Whether this is the house face rather than a fallback.

    Matched on the family name, not the exact filename: Vazirmatn ships a dozen
    weights and a variable build, and a user who installed `Vazirmatn-Bold` has
    the right font.
    """
    return Path(font_path).name.lower().startswith("vazir")

FONT_DIRS = {
    "Windows": (r"C:\Windows\Fonts",),
    "Darwin": ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
               "/Library/Fonts", "~/Library/Fonts"),
    "Linux": ("/usr/share/fonts", "/usr/local/share/fonts",
              "~/.fonts", "~/.local/share/fonts"),
}

def _pil():
    ir.require("PIL", "pillow", "typesetting Persian")
    from PIL import Image, ImageDraw, ImageFont

    return Image, ImageDraw, ImageFont


def _numpy():
    ir.require("numpy", "numpy", "measuring balloons")
    import numpy

    return numpy


# --------------------------------------------------------------------------- #
# Shaping
# --------------------------------------------------------------------------- #

def raqm_available() -> bool:
    """Whether Pillow can shape and reorder Persian itself."""
    try:
        from PIL import features

        return bool(features.check("raqm"))
    except Exception:  # pragma: no cover - very old Pillow
        return False


_RESHAPER = None


def _reshaper():
    """A reshaper configured for Persian rather than for its own defaults.

    ``delete_harakat`` defaults to **True** in arabic-reshaper, and that is not
    a cosmetic setting for Persian: it deletes U+0654, the hamza that carries
    the ezafe. ``خانهٔ ما`` (*our house*) silently becomes ``خانه ما``, which is a
    different construction. Measured, then fixed here rather than discovered in
    a finished chapter.
    """
    global _RESHAPER
    if _RESHAPER is None:
        module = ir.require("arabic_reshaper", "arabic-reshaper",
                            "Persian shaping without RAQM")
        _RESHAPER = module.ArabicReshaper(configuration={
            "delete_harakat": False,
            "support_zwj": True,
            "support_ligatures": False,
        })
    return _RESHAPER


def shape_fallback(text: str) -> str:
    """Pre-shape and reorder by hand, when RAQM is unavailable.

    This produces presentation forms in visual order. It renders correctly, but
    the result is a picture of Persian rather than Persian: the same string
    copied out of the image would not be searchable, and a line broken after
    shaping would break in the wrong place. Line breaking therefore happens on
    the logical text, before this is ever called.

    Not a rare path, and not the platform limit it was long documented as.
    Pillow's wheels carry libraqm everywhere; libraqm loads **FriBiDi** at run
    time, and Linux images normally have one while Windows and macOS normally do
    not. Put a `fribidi` DLL on PATH — `fribidi.dll`, `fribidi-0.dll` or
    `libfribidi-0.dll` — and `features.check("raqm")` turns true on Windows.
    Measured on this project's own machine, where the claim had been repeated in
    five files.
    """
    ir.require("bidi", "python-bidi", "Persian direction without RAQM")
    from bidi.algorithm import get_display

    return get_display(_reshaper().reshape(text))


class Shaper:
    """One place that decides how a Persian string becomes glyphs."""

    def __init__(self, force_fallback: bool = False) -> None:
        self.raqm = raqm_available() and not force_fallback
        _, _, ImageFont = _pil()
        self.layout = (
            ImageFont.Layout.RAQM if self.raqm else ImageFont.Layout.BASIC
        )

    @property
    def mode(self) -> str:
        return "raqm" if self.raqm else "reshaper"

    def prepare(self, text: str) -> str:
        return text if self.raqm else shape_fallback(text)

    def draw_kwargs(self) -> dict[str, Any]:
        # `direction` and `language` are RAQM-only; passing them without it
        # raises rather than degrading, so they are omitted in fallback mode.
        return {"direction": "rtl", "language": "fa"} if self.raqm else {}


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #

def _candidate_paths() -> list[Path]:
    roots = FONT_DIRS.get(platform.system(), FONT_DIRS["Linux"])
    found: list[Path] = []
    for root in roots:
        base = Path(os.path.expanduser(root))
        if not base.is_dir():
            continue
        try:
            found.extend(
                path for path in base.rglob("*")
                if path.suffix.lower() in {".ttf", ".otf", ".ttc"}
            )
        except OSError:  # pragma: no cover - unreadable font directory
            continue
    return found


def find_font(preferred: str | None = None) -> Path:
    """Locate a font that can actually draw Persian."""
    _, _, ImageFont = _pil()

    if preferred:
        direct = Path(os.path.expanduser(preferred))
        if direct.is_file():
            return direct
        try:
            loaded = ImageFont.truetype(preferred, 20)
            return Path(getattr(loaded, "path", preferred))
        except OSError:
            pass  # fall through to the search, but remember what was asked for

    for name in PERSIAN_FONTS:
        try:
            loaded = ImageFont.truetype(name, 20)
            return Path(getattr(loaded, "path", name))
        except OSError:
            continue

    wanted = {name.lower() for name in PERSIAN_FONTS}
    for path in _candidate_paths():
        if path.name.lower() in wanted:
            return path

    raise ir.MissingDependency(
        "No Persian-capable font was found on this machine.\n"
        "Install one and try again — Vazirmatn is the usual choice:\n"
        "    https://github.com/rastikerdar/vazirmatn/releases\n"
        "Then pass it explicitly:  --font /path/to/Vazirmatn-Medium.ttf\n"
        "Tahoma or Noto Naskh Arabic also work if either is already installed."
    )


#: Five codepoints in the Private Use Area. No text font assigns glyphs here,
#: so whatever a face draws for these IS its "I do not have this character"
#: mark — its `.notdef` box, or nothing at all.
_DEFINITELY_MISSING = "\ue000\ue001\ue002\ue003\ue004"


def _supports_persian(font_path: Path) -> bool:
    """Whether this face really has Persian letters, or boxes where they go.

    Decided by COVERAGE, not by ink. The old test counted dark pixels and
    accepted anything between a floor and a ceiling — which a Latin-only face
    passes easily, because five `.notdef` boxes put down MORE ink than the word
    does. Measured: a Latin-only face drew 680 px for `چگونه` where Vazirmatn
    draws 540, so the font that cannot write Persian scored higher than the one
    that can, and `doctor` called the machine ready.

    What separates them is that a face without the letters draws the SAME mark
    for every character it lacks. Render the word, render five private-use
    codepoints, compare: identical means tofu.
    """
    Image, ImageDraw, ImageFont = _pil()
    try:
        font = ImageFont.truetype(str(font_path), 32)
    except OSError:
        return False

    def drawn(text: str) -> bytes | None:
        canvas = Image.new("L", (240, 60), 255)
        draw = ImageDraw.Draw(canvas)
        try:
            draw.text((4, 4), text, font=font, fill=0)
        except Exception:
            return None
        return canvas.tobytes()

    persian = drawn("چگونه")
    blank = drawn("")
    if persian is None or blank is None or persian == blank:
        return False
    missing = drawn(_DEFINITELY_MISSING)
    return missing is None or persian != missing
