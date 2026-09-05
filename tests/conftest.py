"""Shared fixtures.

Fixtures are *generated*, never committed as binaries: the suite stays fast, the
repository stays small, and no third-party artwork is vendored into a GPL tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests_support import manga_page, page_bytes, write_cbz  # noqa: E402


@pytest.fixture(scope="session")
def sample_cbz(tmp_path_factory) -> Path:
    """Three pages: light balloons, dark balloons, light again, each with an SFX."""
    return write_cbz(tmp_path_factory.mktemp("cbz") / "chapter.cbz", pages=3)


@pytest.fixture(scope="session")
def sample_page(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("page") / "p.png"
    path.write_bytes(page_bytes(manga_page()))
    return path


@pytest.fixture
def imported(sample_cbz, tmp_path) -> Path:
    """A working folder with `import` already run. Returns the document path."""
    import readers

    readers.import_source(sample_cbz, tmp_path, source_language="ja", direction="rtl")
    return tmp_path / "comic.json"


@pytest.fixture
def detected(imported) -> Path:
    import detect
    import masks

    detect.detect_document(imported)
    masks.build_document(imported)
    return imported


@pytest.fixture
def translated(detected) -> Path:
    """Every region filled in with plausible Persian, merged into the document."""
    import pageir as ir

    doc = ir.load_doc(detected)
    lines = [
        "بس کن! این‌جا چه خبر است؟",
        "هیچ‌کس نمی‌داند او کجا رفته.",
        "دوباره برگشتی؟",
    ]
    sources = ["やめろ！", "誰も知らない。", "また来たのか"]
    for index, (_, region) in enumerate(ir.iter_regions(doc)):
        region["source_text"] = sources[index % len(sources)]
        region["target_text"] = lines[index % len(lines)]
        region["speaker"] = "هاروکا" if index % 2 == 0 else "کنجی"
        region["locked"] = True
    ir.save_doc(doc, detected)
    return detected
