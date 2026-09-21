"""Small real packages exercise every durable publication boundary."""

import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import export
import journal
import pageir as ir
import readers


def _pixels(path, fmt):
    if fmt == "pdf":
        import pymupdf

        with pymupdf.open(path) as pdf:
            return [ir.sha256_bytes(page.get_pixmap(alpha=False).samples) for page in pdf]
    if fmt == "cbz":
        with zipfile.ZipFile(path) as archive:
            payloads = [archive.read(name) for name in sorted(archive.namelist())
                        if name.endswith(".png")]
    else:
        payloads = [p.read_bytes() for p in sorted(path.glob("*.png"))]
    result = []
    for payload in payloads:
        with Image.open(io.BytesIO(payload)) as image:
            result.append(ir.sha256_bytes(image.convert("RGB").tobytes()))
    return result


def _generations(tmp_path, fmt):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(2):
        Image.new("RGB", (48, 64), (30 + index * 50, 40, 50)).save(source / f"{index}.png")
    root = tmp_path / "work"
    readers.import_source(source, root)
    doc_path = root / "comic.json"
    export.export_document(doc_path, tmp_path / "remembered.cbz", draft=True)
    out = tmp_path / ("edition" if fmt == "dir" else "edition." + fmt)
    export.export_document(doc_path, out, draft=True)
    old = _pixels(out, fmt)
    doc = ir.load_doc(doc_path)
    wanted = []
    for index, page in enumerate(doc["pages"]):
        image = Image.new("RGB", (48, 64), (110 + index * 50, 150, 190))
        relative = f"final/{page['id']}.png"
        ir.save_image(image, root / relative)
        page["final"] = relative
        wanted.append(ir.sha256_bytes(image.tobytes()))
    ir.save_doc(doc, doc_path)
    return doc_path, out, old, wanted


POINTS = [
    (fmt, point, side)
    for fmt in ("cbz", "pdf", "dir")
    for point in ("intent", "metadata", "clear",
                  *(f"{phase}:{index}" for phase in ("backing-up", "backed-up", "promoted")
                    for index in range(3 if fmt == "dir" else 1)),
                  "published", "backup", "promotion")
    for side in ("before", "after")
]


@pytest.mark.parametrize("fmt,point,side", POINTS)
def test_every_publication_boundary_recovers_one_whole_generation(
        tmp_path, monkeypatch, fmt, point, side):
    doc_path, out, old, new = _generations(tmp_path, fmt)
    fired = []
    counts = {}

    def inject(label, operation, *args, **kwargs):
        count = counts.get(label, 0)
        counts[label] = count + 1
        match = point == label or point == f"{label}:{count}"
        if match and not fired and side == "before":
            fired.append(label)
            raise OSError("injected boundary")
        result = operation(*args, **kwargs)
        if match and not fired and side == "after":
            fired.append(label)
            raise OSError("injected boundary")
        return result

    persist, replace, save, clear = journal._persist, Path.replace, ir.save_doc, journal.clear

    def persist_at(path, record):
        phase = record["progress"]["phase"]
        return inject("intent" if phase == "prepared" else phase, persist, path, record)

    def move_at(path, target):
        label = "backup" if Path(target).parent.name.endswith(".revayat-kept") else "promotion"
        return inject(label, replace, path, target)

    monkeypatch.setattr(journal, "_persist", persist_at)
    monkeypatch.setattr(Path, "replace", move_at)
    monkeypatch.setattr(ir, "save_doc", lambda *a, **k: inject("metadata", save, *a, **k))
    monkeypatch.setattr(journal, "clear", lambda *a, **k: inject("clear", clear, *a, **k))
    with pytest.raises(OSError, match="injected boundary"):
        export.export_document(doc_path, out, draft=True)
    assert fired, "the named boundary was never exercised"
    monkeypatch.undo()
    export.reconcile_pending(doc_path)
    assert export.reconcile_pending(doc_path) is None
    assert _pixels(out, fmt) in (old, new), "a mixed generation survived recovery"
    editions = ir.load_doc(doc_path)["stages"]["export"]["editions"]
    assert str((tmp_path / "remembered.cbz").resolve()) in editions
    assert str(out.resolve()) in editions
    assert not journal.path_for(doc_path).exists()


def test_process_death_mid_directory_promotion_recovers_all_pages(tmp_path):
    doc_path, out, old, new = _generations(tmp_path, "dir")
    script = tmp_path / "interrupt.py"
    source = Path(export.__file__).parent
    ir.write_text(script, "\n".join([
        "import os, sys", "from pathlib import Path",
        f"sys.path.insert(0, {str(source)!r})", "import export",
        "original = Path.replace",
        "def interrupt(self, target):",
        "    result = original(self, target)",
        f"    if Path(target) == Path({str(out / '0001.png')!r}):",
        "        os._exit(93)",
        "    return result", "Path.replace = interrupt",
        f"export.export_document({str(doc_path)!r}, {str(out)!r}, draft=True)",
    ]) + "\n")
    child = subprocess.run([sys.executable, str(script)], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert child.returncode == 93, child.stderr
    assert _pixels(out, "dir") not in (old, new)
    with pytest.raises(RuntimeError, match="already writing"):
        export.export_document(doc_path, out, draft=True)
    record = export.reconcile_pending(doc_path, recover_orphans=True)
    assert record is not None
    assert _pixels(out, "dir") == new
    assert export.reconcile_pending(doc_path) is None
    assert len(ir.load_doc(doc_path)["stages"]["export"]["editions"]) == 2


def test_saving_a_stale_snapshot_preserves_the_newer_edit(imported):
    stale, current = ir.load_doc(imported), ir.load_doc(imported)
    current["meta"]["title"] = "Reader's current title"
    ir.save_doc(current, imported)
    stale["meta"]["title"] = "Stale title"
    with pytest.raises(RuntimeError, match="changed"):
        ir.save_doc(stale, imported)
    assert ir.load_doc(imported)["meta"]["title"] == "Reader's current title"


def test_process_death_before_journal_has_an_explicit_orphan_recovery_route(tmp_path):
    doc_path, out, old, _ = _generations(tmp_path, "cbz")
    script = tmp_path / "interrupt-before-journal.py"
    source = Path(export.__file__).parent
    ir.write_text(script, "\n".join([
        "import os, sys", f"sys.path.insert(0, {str(source)!r})",
        "import export, writers", "original = writers._encode",
        "def interrupt(*args, **kwargs):", "    os._exit(94)",
        "writers._encode = interrupt",
        f"export.export_document({str(doc_path)!r}, {str(out)!r}, draft=True)",
    ]) + "\n")
    child = subprocess.run([sys.executable, str(script)], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert child.returncode == 94, child.stderr
    assert not journal.path_for(doc_path).exists()
    report = export.reconcile_pending(doc_path, recover_orphans=True, destination=out)
    assert report and Path(report["orphaned_staging"]).exists()
    assert _pixels(out, "cbz") == old
    export.export_document(doc_path, out, draft=True)


def test_changed_recovery_input_is_preserved_and_quarantined(tmp_path, monkeypatch):
    doc_path, out, _, _ = _generations(tmp_path, "dir")
    save = ir.save_doc
    monkeypatch.setattr(ir, "save_doc", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError):
        export.export_document(doc_path, out, draft=True)
    monkeypatch.setattr(ir, "save_doc", save)
    doc = ir.load_doc(doc_path)
    image = doc_path.parent / doc["pages"][0]["final"]
    image.write_bytes(b"operator changed this input")
    before = doc_path.read_bytes()
    assert export.reconcile_pending(doc_path) is None
    assert doc_path.read_bytes() == before
    assert image.read_bytes() == b"operator changed this input"
    assert list(doc_path.parent.glob("*.export-conflict-*.json"))
