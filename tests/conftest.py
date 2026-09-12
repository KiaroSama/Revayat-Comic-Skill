"""Shared fixtures.

Fixtures are *generated*, never committed as binaries: the suite stays fast, the
repository stays small, and no third-party artwork is vendored into a GPL tree.

## Why the pipeline stages are built once and then copied

Every stage below — import, detect, mask, clean, typeset — is real image
processing, and it used to run again for every test that asked for it. Measured
on this suite: about **3 seconds of `setup` per test**, and `--durations` showed
ten of the twelve slowest entries were setup rather than any test's own work.
That is the same chapter being rebuilt a hundred and fifty times to produce a
hundred and fifty identical copies of it.

So each stage is built **once per session** into a template directory, and a
test that asks for it gets a `copytree` of that template into its own `tmp_path`.
Isolation is unchanged — every test still owns a private, freely mutable
directory, and nothing reaches back into the template — but the cost per test
falls from seconds of OpenCV and Pillow work to milliseconds of file copying.

The layout a test sees is identical to before: `tmp_path` *is* the working
folder, and the fixture returns `tmp_path / "comic.json"`.

Two rules for anyone adding a fixture here:

- **Expensive and read-mostly → session scope plus a copy.** Never a
  session-scoped object that tests mutate; the copy is what keeps them honest.
- **Ask for the latest stage you actually need.** Requesting `finished` when
  `detected` would do pays for `clean` and `typeset` you never look at.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests_support import manga_page, page_bytes, write_cbz  # noqa: E402


def _clone(template: Path, destination: Path) -> Path:
    """A private copy of a prepared working folder, and its document."""
    shutil.copytree(template, destination, dirs_exist_ok=True)
    return destination / "comic.json"


@pytest.fixture(scope="session")
def sample_cbz(tmp_path_factory) -> Path:
    """Three pages: light balloons, dark balloons, light again, each with an SFX."""
    return write_cbz(tmp_path_factory.mktemp("cbz") / "chapter.cbz", pages=3)


@pytest.fixture(scope="session")
def sample_page(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("page") / "p.png"
    path.write_bytes(page_bytes(manga_page()))
    return path


# --------------------------------------------------------------------------- #
# The stage templates. Built once; never handed to a test directly.
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def _stage_imported(sample_cbz, tmp_path_factory) -> Path:
    import readers

    work = tmp_path_factory.mktemp("stage-imported")
    readers.import_source(sample_cbz, work, source_language="ja", direction="rtl")
    return work


@pytest.fixture(scope="session")
def _stage_detected(_stage_imported, tmp_path_factory) -> Path:
    import detect
    import masks

    work = tmp_path_factory.mktemp("stage-detected")
    doc_path = _clone(_stage_imported, work)
    detect.detect_document(doc_path)
    masks.build_document(doc_path)
    return work


@pytest.fixture(scope="session")
def _stage_translated(_stage_detected, tmp_path_factory) -> Path:
    import pageir as ir

    work = tmp_path_factory.mktemp("stage-translated")
    doc_path = _clone(_stage_detected, work)

    doc = ir.load_doc(doc_path)
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
    ir.save_doc(doc, doc_path)
    return work


@pytest.fixture(scope="session")
def _stage_finished(_stage_translated, tmp_path_factory) -> Path:
    import clean
    import typeset

    work = tmp_path_factory.mktemp("stage-finished")
    doc_path = _clone(_stage_translated, work)
    clean.clean_document(doc_path)
    typeset.typeset_document(doc_path)
    return work


# --------------------------------------------------------------------------- #
# What tests ask for: a private copy of one of those stages.
# --------------------------------------------------------------------------- #

@pytest.fixture
def imported(_stage_imported, tmp_path) -> Path:
    """A working folder with `import` already run. Returns the document path."""
    return _clone(_stage_imported, tmp_path)


@pytest.fixture
def detected(_stage_detected, tmp_path) -> Path:
    """…and `detect` and `mask`."""
    return _clone(_stage_detected, tmp_path)


@pytest.fixture
def translated(_stage_translated, tmp_path) -> Path:
    """Every region filled in with plausible Persian, merged into the document."""
    return _clone(_stage_translated, tmp_path)


@pytest.fixture
def finished(_stage_finished, tmp_path) -> Path:
    """A document taken all the way through `clean` and `typeset`.

    Shared because three suites need a page that has actually been rendered —
    the QA gate, the visual-QA pass and the provider tests all assert against
    final pixels, and a local copy in each would drift.
    """
    return _clone(_stage_finished, tmp_path)
