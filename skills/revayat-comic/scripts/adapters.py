"""Real providers, for the models this project can actually reach.

`providers.py` defines the boundary and ships fakes for the suite. This is where
adapters for *real* models live — and there is deliberately very little here,
because the default is still that the agent running the skill does the work.

**Nothing in this file is imported by the pipeline.** Each adapter registers
itself only when you ask for it, and each one's dependency is optional. Import
this module (or pass `--adapters`) to make its providers selectable by name:

```bash
pip install manga-ocr
revayat-comic ocr --doc work/comic.json --provider manga-ocr
```

**What is here and what is not.** `manga-ocr` runs locally, needs no account and
no key, so it is the one real model this project can ship an adapter for and
have anybody be able to run it. Hosted models — an image editor, a translator,
a vision model — need a key that belongs to whoever is running the skill, and an
adapter for one is a dozen lines against their SDK. The shape is at the bottom
of this file; the boundary is what makes it safe, not the adapter.
"""

from __future__ import annotations

from typing import Any

import providers

#: How confident to call a `manga-ocr` reading. The model returns text and no
#: score of its own, so this is a judgement about the model rather than about
#: any particular crop: it is a specialist trained on exactly this material and
#: is right far more often than not, but it is reading one rectangle without the
#: page around it. High enough to fill an empty region, low enough that raising
#: `--min-confidence` past it turns the stage into a suggest-only pass.
MANGA_OCR_CONFIDENCE = 0.80


class MangaOcr:
    """`manga-ocr` — a specialist Japanese manga recogniser, run locally.

    Genuinely better than a generalist at vertical Japanese with furigana, which
    is the one job this pipeline's reader is weakest at. It costs about 400 MB of
    model on first use and pulls in torch, which is why it is not a dependency.

    The model is loaded on first read, not on construction, so registering the
    adapter costs nothing and a run that never reaches a region never pays.
    """

    name = "manga-ocr"

    def __init__(self) -> None:
        self._model: Any = None

    def read(self, crop_path: str, language: str):
        if language not in {"ja", "jpn", "japanese", ""}:
            # Say so rather than returning confident nonsense: it is a Japanese
            # model and `providers.call` turns None into a clean `refused`.
            return None
        if self._model is None:
            from manga_ocr import MangaOcr as _MangaOcr

            self._model = _MangaOcr()

        from PIL import Image

        text = self._model(Image.open(crop_path))
        text = (text or "").strip()
        if not text:
            return None
        return text, MANGA_OCR_CONFIDENCE


def register_all() -> dict[str, list[str]]:
    """Make every adapter in this module selectable, and say what is usable.

    Registration is unconditional and cheap — nothing is constructed and no
    optional dependency is imported. Whether the package is actually installed
    is reported, so `doctor` can tell "not registered" from "registered but you
    still need to `pip install` it".
    """
    providers.register("ocr", MangaOcr.name, MangaOcr)

    usable: list[str] = []
    missing: list[str] = []
    try:
        import manga_ocr  # noqa: F401
    except ImportError:
        missing.append(MangaOcr.name)
    else:
        usable.append(MangaOcr.name)
    return {"registered": [MangaOcr.name], "installed": usable,
            "needs_install": missing}


# --------------------------------------------------------------------------- #
# Writing your own
# --------------------------------------------------------------------------- #
# An adapter is the smallest object with the right method. Nothing needs to
# subclass anything, and nothing here needs to change.
#
#     class MyImageEditor:
#         name = "my-editor"
#         def repair(self, page_png: bytes, mask_png: bytes,
#                    instructions: str) -> bytes | None:
#             ...                       # your SDK call
#             return new_page_png       # or None to decline
#
#     providers.register("image_edit", "my-editor", MyImageEditor)
#
# A method may also name an optional argument the stage knows about and will
# pass only if you ask for it — an OCR `read` that names `orientation` is told
# whether the line runs vertically. Nothing breaks if you leave it out; see
# `providers.wants`.
#
# Three things the boundary guarantees, so your adapter does not have to:
#
#   * whatever it returns is composited under the authoritative mask, so it
#     cannot touch a pixel outside the region it was asked about;
#   * it is called lazily, only for regions the deterministic cleaners cannot
#     handle, at most once per page;
#   * a timeout, an exception, a refusal or a wrong-sized page all become a
#     recorded status and the classical cleaners run instead.
#
# Read the credential from the environment. Never take one as an argument and
# never write one into `comic.json` — the document is meant to be shareable.
