"""Real entry-point regressions for safe installation and pointer preservation."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger(__name__)
BEGIN = b"<!-- BEGIN revayat-comic -->"
END = b"<!-- END revayat-comic -->"


@pytest.fixture
def fixture(tmp_path):
    repo = tmp_path / "repository with spaces"
    shutil.copytree(ROOT / "install", repo / "install")
    shutil.copytree(ROOT / "skills", repo / "skills", ignore=shutil.ignore_patterns("__pycache__", "logs"))
    project = tmp_path / "project with spaces"
    project.mkdir()
    return repo, project


def run_installer(repo, project, agent="codex", *, force=True, recover=False, automatic=False):
    env = os.environ.copy()
    if automatic:
        env.pop("REVAYAT_PYTHON", None)
    else:
        env["REVAYAT_PYTHON"] = sys.executable
    if os.name == "nt":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        assert shell, "Windows installer testing requires PowerShell"
        command = [shell, "-NoProfile", "-NonInteractive", "-File", str(repo / "install/install.ps1"),
                   "-Agent", agent, "-Scope", "project", "-Path", str(project)]
        if force:
            command.append("-Force")
        if recover:
            command.append("-Recover")
    else:
        command = ["bash", str(repo / "install/install.sh"), "--agent", agent,
                   "--scope", "project", "--path", str(project)]
        if force:
            command.append("--force")
        if recover:
            command.append("--recover")
    result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30,
                            start_new_session=os.name != "nt")
    LOG.info("Installer exit=%s for isolated %s", result.returncode, agent)
    return result


def old_install(project, agent="codex"):
    target = project / (".opencode" if agent == "opencode" else ".codex") / "skills/revayat-comic"
    target.mkdir(parents=True)
    (target / "operator-note.md").write_text("private local work", encoding="utf-8")
    (target / "SKILL.md").write_text("previous skill", encoding="utf-8")
    return target


def test_headless_install_never_assumes_replacement_consent(fixture):
    repo, project = fixture
    target = old_install(project)
    result = run_installer(repo, project, force=False)
    assert result.returncode != 0
    assert (target / "operator-note.md").read_text() == "private local work"
    assert (target / "SKILL.md").read_text() == "previous skill"


@pytest.mark.parametrize("markers", [BEGIN, END, BEGIN + b"\n" + BEGIN + b"\n" + END,
                                     BEGIN + b"\n" + END + b"\n" + BEGIN + b"\n" + END])
def test_malformed_pointer_refuses_without_losing_rules_or_installation(fixture, markers):
    repo, project = fixture
    target = old_install(project, "opencode")
    raw = b"owner prefix\n" + markers + b"\nOWNER RULES AFTER MARKER\n"
    pointer = project / "AGENTS.md"
    pointer.write_bytes(raw)
    result = run_installer(repo, project, "opencode")
    assert result.returncode != 0
    assert pointer.read_bytes() == raw
    assert (target / "operator-note.md").read_text() == "private local work"


@pytest.mark.parametrize("missing", ["SKILL.md", "requirements.txt", "scripts/revayat-comic.py",
                                     "scripts/regions.py", "references/translation-policy.md"])
def test_incomplete_source_cannot_replace_working_installation(fixture, missing):
    repo, project = fixture
    target = old_install(project)
    (repo / "skills/revayat-comic" / missing).unlink()
    result = run_installer(repo, project)
    assert result.returncode != 0
    assert (target / "operator-note.md").read_text() == "private local work"


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_pointer_preserves_outside_bytes_and_unowned_scratch(fixture, ending):
    repo, project = fixture
    prefix = b"# Owner rules" + ending + "نام کاربر".encode() + ending
    suffix = b"USER SUFFIX WITHOUT FINAL NEWLINE"
    pointer = project / "AGENTS.md"
    pointer.write_bytes(prefix + BEGIN + ending + b"old section" + ending + END + ending + suffix)
    scratch = project / "AGENTS.md.revayat-comic.tmp"
    scratch.write_bytes(b"unowned scratch")
    assert run_installer(repo, project, "opencode").returncode == 0
    once = pointer.read_bytes()
    assert once.startswith(prefix) and once.endswith(suffix)
    assert once.count(BEGIN) == once.count(END) == 1
    assert scratch.read_bytes() == b"unowned scratch"
    assert run_installer(repo, project, "opencode").returncode == 0
    assert pointer.read_bytes() == once


def test_successful_upgrade_keeps_previous_operator_files_in_backup(fixture):
    repo, project = fixture
    target = old_install(project)
    result = run_installer(repo, project)
    assert result.returncode == 0, result.stderr
    assert (target / "scripts/revayat-comic.py").is_file()
    backups = list((project / ".revayat-comic-installer/backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "operator-note.md").read_text() == "private local work"


def test_only_manifest_files_ship_not_runtime_caches_or_local_outputs(fixture):
    repo, project = fixture
    source = repo / "skills/revayat-comic"
    for folder in ("logs", "venv", "__pycache__", "private-reading-copies"):
        (source / folder).mkdir(exist_ok=True)
        (source / folder / "private.txt").write_text("not for installation")
    assert run_installer(repo, project).returncode == 0
    target = project / ".codex/skills/revayat-comic"
    for folder in ("logs", "venv", "__pycache__", "private-reading-copies"):
        assert not (target / folder).exists()


def test_manifest_covers_all_tracked_skill_files():
    manifest = ROOT / "install/skill-files.txt"
    assert manifest.is_file()
    names = manifest.read_text().splitlines()
    tracked = subprocess.run(["git", "ls-files", "skills/revayat-comic"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.splitlines()
    assert set(names) == {name.removeprefix("skills/revayat-comic/") for name in tracked}
    assert len(names) == len(set(names))


def test_native_entry_discovers_python_without_an_override(fixture):
    repo, project = fixture
    result = run_installer(repo, project, automatic=True)
    assert result.returncode == 0, result.stderr
    assert (project / ".codex/skills/revayat-comic/scripts/revayat-comic.py").is_file()
