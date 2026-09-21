"""The public Word companion preserves an editable translation snapshot."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import pytest

import pageir as ir
import workspace


CLI = Path(ir.__file__).resolve().parent / "revayat-comic.py"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _cli(doc_path, out, *, script=CLI, python_flags=(), cwd=None, env=None):
    return subprocess.run(
        [sys.executable, *python_flags, str(script), "review-docx", "--doc", str(doc_path),
         "--out", str(out)],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_review_docx_cli_preserves_text_identity_and_empty_pages(imported):
    doc = ir.load_doc(imported)
    doc["meta"].update(title="Editable review", source_language="fr")
    translated = ir.new_region("p0001r001", [20, 20, 160, 90], kind="speech")
    translated.update(
        reading_order=1, speaker="لیلا", locked=True,
        source_text="Notre maison & l'API <42>.\n\nOn reste ?",
        target_text="خانهٔ ما و API <42>.\n\nمی‌مانیم؟",
        target_full="خانهٔ ما و رابط API <42>.\n\nاینجا می‌مانیم؟",
        review=["Check the hesitant delivery."],
    )
    unresolved = ir.new_region("p0001r002", [200, 20, 160, 90], kind="speech")
    unresolved.update(reading_order=2, source_text="Et ensuite ?")
    kept = ir.new_region("p0003r001", [20, 20, 100, 60], kind="sfx")
    kept.update(reading_order=1, source_text="KNOCK", keep=True)
    doc["pages"][0]["regions"] = [translated, unresolved]
    doc["pages"][1]["regions"] = []
    doc["pages"][1]["notes"] = ["This source page has no lettering."]
    doc["pages"][2]["regions"] = [kept]
    ir.save_doc(doc, imported)

    originals = [imported, Path(doc["source"]["path"])]
    originals.extend(imported.parent / page["image"] for page in doc["pages"])
    before = {path: path.read_bytes() for path in originals}
    out = imported.parent / "review outputs" / "chapter review.docx"
    out.parent.mkdir()
    result = subprocess.run(
        [sys.executable, str(CLI), "review-docx", "--doc", str(imported),
         "--out", str(out)],
        cwd=imported.parent, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert Path(report["path"]) == out
    assert report["pages"] == 3 and report["regions"] == 3
    assert report["review_only"] is True
    assert report["snapshot_sha256"] == hashlib.sha256(before[imported]).hexdigest()
    assert report["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()

    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(archive.namelist())
        document = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = []
    for paragraph in document.iter(W + "p"):
        pieces = []
        for node in paragraph.iter():
            if node.tag == W + "t":
                pieces.append(node.text or "")
            elif node.tag in {W + "br", W + "cr"}:
                pieces.append("\n")
            elif node.tag == W + "tab":
                pieces.append("\t")
        paragraphs.append("".join(pieces))
    text = "\n".join(paragraphs)
    for expected in (
        "Notre maison & l'API <42>.\n\nOn reste ?",
        "خانهٔ ما و API <42>.\n\nمی‌مانیم؟",
        "خانهٔ ما و رابط API <42>.\n\nاینجا می‌مانیم؟",
        "لیلا", "Check the hesitant delivery.", "Et ensuite ?", "KNOCK",
        "unresolved", "kept_by_policy", "This source page has no lettering.",
    ):
        assert expected in text, expected
    identities = ("p0001r001", "p0001r002", "p0002", "p0003r001")
    assert [text.index(identity) for identity in identities] == sorted(
        text.index(identity) for identity in identities)
    assert "no regions" in text.lower(), "the empty page needs an explicit state"
    assert any(paragraph.find(W + "pPr/" + W + "bidi") is not None
               for paragraph in document.iter(W + "p"))
    # MS-OE376 2.3.1.13: Word interprets left/right relative to paragraph bidi.
    # In a bidi paragraph, left places text at the physical right edge.
    for paragraph in document.iter(W + "p"):
        if paragraph.find(W + "pPr/" + W + "bidi") is not None:
            assert paragraph.find(W + "pPr/" + W + "jc").get(W + "val") == "left"
    assert {path: path.read_bytes() for path in originals} == before


def test_companion_honors_declared_reading_order_without_renumbering(imported):
    doc = ir.load_doc(imported)
    first = ir.new_region("p0001r001", [20, 20, 160, 90], kind="speech")
    second = ir.new_region("p0001r002", [200, 20, 160, 90], kind="speech")
    first.update(reading_order=2, source_text="Read this second.")
    second.update(reading_order=1, source_text="Read this first.")
    doc["pages"][0]["regions"] = [first, second]
    ir.save_doc(doc, imported)
    before = imported.read_bytes()
    out = imported.parent / "ordered.docx"
    result = _cli(imported, out)
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(out) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    text = "\n".join(node.text or "" for node in document.iter(W + "t"))
    assert text.index("p0001r002") < text.index("p0001r001")
    assert text.index("Read this first.") < text.index("Read this second.")
    assert imported.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("source_text", "bad\x0bsource"), ("target_text", "بد\x00"),
    ("kind", {}), ("kind", []), ("reading_order", "first"), ("typeset", []),
    ("typeset", {"status": []}), ("target_text", {}), ("keep", "yes"),
    ("fill", {}),
])
def test_invalid_region_data_is_refused_as_json_without_publication(imported, field, value):
    doc = ir.load_doc(imported)
    region = ir.new_region("p0001r001", [20, 20, 160, 90], kind="speech")
    region[field] = value
    doc["pages"][0]["regions"] = [region]
    ir.save_doc(doc, imported)
    before = imported.read_bytes()
    out = imported.parent / "refused.docx"
    result = _cli(imported, out)
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["ok"] is False and report["error"]
    assert not out.exists()
    assert imported.read_bytes() == before


def test_malformed_crop_paths_are_a_structured_refusal(imported):
    doc = ir.load_doc(imported)
    doc["pages"][0]["sheets"] = 7
    ir.save_doc(doc, imported)
    before = imported.read_bytes()
    out = imported.parent / "bad-paths.docx"
    result = _cli(imported, out)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not out.exists()
    assert imported.read_bytes() == before


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_existing_destination_is_preserved(imported, directory):
    out = imported.parent / "operator.docx"
    if directory:
        out.mkdir()
        preserved = out / "operator.txt"
    else:
        preserved = out
    preserved.write_bytes(b"operator-owned content")
    before = imported.read_bytes()
    result = _cli(imported, out)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert preserved.read_bytes() == b"operator-owned content"
    assert imported.read_bytes() == before


@pytest.mark.parametrize("problem", ["suffix", "parent-is-file"])
def test_invalid_output_path_is_refused_without_changing_inputs(imported, problem):
    before = imported.read_bytes()
    if problem == "suffix":
        out = imported.parent / "not-a-word-file.pdf"
    else:
        blocked = imported.parent / "operator-file"
        blocked.write_bytes(b"keep")
        out = blocked / "review.docx"
    result = _cli(imported, out)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not out.exists()
    assert imported.read_bytes() == before
    if problem == "parent-is-file":
        assert blocked.read_bytes() == b"keep"


@pytest.mark.parametrize("dangling", [False, True], ids=["existing-target", "absent-target"])
def test_destination_directory_links_are_never_followed(imported, dangling):
    target = imported.parent / "operator target.docx"
    if not dangling:
        target.mkdir()
        (target / "operator.txt").write_bytes(b"keep")
    out = imported.parent / "linked.docx"
    if os.name == "nt":
        # Junctions exercise Windows reparse paths without symlink privileges.
        made = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(out), str(target)],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert made.returncode == 0, made.stdout + made.stderr
    else:
        out.symlink_to(target, target_is_directory=True)
    result = _cli(imported, out)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert os.path.lexists(out)
    if dangling:
        assert not target.exists()
    else:
        assert (target / "operator.txt").read_bytes() == b"keep"


@pytest.mark.parametrize("folder_kind", ["original", "worksheet"])
def test_new_companion_cannot_be_written_inside_input_directories(
        tmp_path, sample_page, folder_kind):
    import readers
    import worksheet

    original = tmp_path / "original"
    original.mkdir()
    source = original / "page.png"
    source.write_bytes(sample_page.read_bytes())
    work = tmp_path / "work"
    readers.import_source(original, work)
    doc_path = work / "comic.json"
    sheets = tmp_path / "external worksheets"
    worksheet.build_document(doc_path, sheets)
    out = (original if folder_kind == "original" else sheets) / "new.docx"
    before = {path: path.read_bytes() for folder in (original, sheets)
              for path in folder.iterdir() if path.is_file()}
    before[doc_path] = doc_path.read_bytes()
    result = _cli(doc_path, out)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not out.exists()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("scope", ["workspace", "destination"])
def test_another_writers_claim_is_respected(imported, scope):
    out = imported.parent / "busy.docx"
    claim = (ir.workspace_lock(imported.parent, what="another writer")
             if scope == "workspace" else workspace.destination_claim(out, imported))
    before = imported.read_bytes()
    with claim:
        record = claim.path.read_bytes()
        result = _cli(imported, out)
        assert result.returncode != 0
        assert json.loads(result.stdout)["ok"] is False
        assert claim.path.read_bytes() == record
    assert not out.exists()
    assert imported.read_bytes() == before


def test_input_limit_precedes_json_parsing_and_publication(imported):
    doc = ir.load_doc(imported)
    doc["meta"]["oversized_note"] = "x" * (16 * 1024 * 1024)
    ir.save_doc(doc, imported)
    before = hashlib.sha256(imported.read_bytes()).hexdigest()
    out = imported.parent / "too-large.docx"
    result = _cli(imported, out)
    assert result.returncode != 0
    assert "input document exceeds" in json.loads(result.stdout)["error"]
    assert not out.exists()
    assert hashlib.sha256(imported.read_bytes()).hexdigest() == before


def test_publication_failure_does_not_leave_a_partial_companion(imported):
    out = imported.parent / "publication-failed.docx"
    before = imported.read_bytes()
    injection = (
        "import os, runpy, sys\n"
        "def refuse(*args, **kwargs):\n"
        "    raise OSError('injected filesystem publication failure')\n"
        "os.rename = refuse\nos.link = refuse\n"
        "sys.argv = sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", injection, str(CLI), "review-docx", "--doc", str(imported),
         "--out", str(out)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode != 0
    assert "publication failure" in json.loads(result.stdout)["error"]
    assert not out.exists()
    assert not list(imported.parent.glob(".revayat-review-*.tmp"))
    assert not list(imported.parent.glob("*.revayat-claim"))
    assert imported.read_bytes() == before


def test_real_mcp_transport_exposes_the_same_word_companion(stdio_client, imported):
    listed = stdio_client.request("tools/list")
    assert "revayat_review-docx" in {tool["name"] for tool in listed["result"]["tools"]}
    out = imported.parent / "transport.docx"
    response = stdio_client.request(
        "tools/call", name="revayat_review-docx",
        arguments={"args": ["--doc", str(imported), "--out", str(out)]},
    )
    report = json.loads(response["result"]["content"][0]["text"])
    assert report["ok"] and report["report"]["review_only"]
    with zipfile.ZipFile(out) as archive:
        ET.fromstring(archive.read("word/document.xml"))
    assert stdio_client.request("ping").get("result") == {}


def test_real_installer_provides_the_native_command_without_site_packages(imported):
    project = imported.parent / "separate project"
    project.mkdir()
    root = CLI.parents[3]
    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        assert shell, "the Windows installer requires PowerShell"
        command = [shell, "-NoProfile", "-NonInteractive", "-File", str(root / "install/install.ps1"),
                   "-Agent", "codex", "-Scope", "project", "-Path", str(project), "-Force"]
    else:
        command = ["bash", str(root / "install/install.sh"), "--agent", "codex",
                   "--scope", "project", "--path", str(project), "--force"]
    installed = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    skill = project / ".codex/skills/revayat-comic"
    assert (skill / "references/native-documents.md").is_file()
    assert "references/native-documents.md" in (skill / "SKILL.md").read_text(encoding="utf-8")
    out = project / "installed-review.docx"
    result = _cli(imported, out, script=skill / "scripts/revayat-comic.py", python_flags=("-S",),
                  cwd=project, env={**os.environ, "PYTHONPATH": ""})
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["review_only"]
    with zipfile.ZipFile(out) as archive:
        ET.fromstring(archive.read("word/document.xml"))
