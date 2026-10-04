"""Real entry-point regressions for safe installation and pointer preservation."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from process_support import run_process
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
    result = run_process(command, env=env, timeout=30, idle=20)
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
    assert (target / "operator-note.md").read_text(encoding="utf-8") == "private local work"
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "previous skill"


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
    assert (target / "operator-note.md").read_text(encoding="utf-8") == "private local work"


@pytest.mark.parametrize("missing", ["SKILL.md", "requirements.txt", "scripts/revayat-comic.py",
                                     "scripts/regions.py", "references/translation-policy.md"])
def test_incomplete_source_cannot_replace_working_installation(fixture, missing):
    repo, project = fixture
    target = old_install(project)
    (repo / "skills/revayat-comic" / missing).unlink()
    result = run_installer(repo, project)
    assert result.returncode != 0
    assert (target / "operator-note.md").read_text(encoding="utf-8") == "private local work"


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
def test_pointer_preserves_outside_bytes_and_unowned_scratch(fixture, ending):
    repo, project = fixture
    prefix = b"# Owner rules" + ending + "نام کاربر".encode("utf-8") + ending
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
    assert (backups[0] / "operator-note.md").read_text(encoding="utf-8") == "private local work"


def test_only_manifest_files_ship_not_runtime_caches_or_local_outputs(fixture):
    repo, project = fixture
    source = repo / "skills/revayat-comic"
    for folder in ("logs", "venv", "__pycache__", "private-reading-copies"):
        (source / folder).mkdir(exist_ok=True)
        (source / folder / "private.txt").write_text("not for installation", encoding="utf-8")
    assert run_installer(repo, project).returncode == 0
    target = project / ".codex/skills/revayat-comic"
    for folder in ("logs", "venv", "__pycache__", "private-reading-copies"):
        assert not (target / folder).exists()


def test_manifest_covers_all_tracked_skill_files():
    manifest = ROOT / "install/skill-files.txt"
    assert manifest.is_file()
    names = manifest.read_text(encoding="utf-8").splitlines()
    tracked = run_process(["git", "ls-files", "skills/revayat-comic"], cwd=ROOT,
                          timeout=10, idle=5, check=True).stdout.splitlines()
    assert set(names) == {name.removeprefix("skills/revayat-comic/") for name in tracked}
    assert len(names) == len(set(names))


@pytest.mark.parametrize("override", [False, True])
def test_bash_probes_next_supported_candidate_but_honors_override(fixture, override):
    repo, project = fixture
    env = os.environ.copy()
    env["REAL_PY"] = sys.executable.replace("\\", "/")
    env.pop("REVAYAT_PYTHON", None)
    env["OVERRIDE_PROBE"] = "1" if override else "0"
    tools = project / "probe-tools"
    tools.mkdir()
    for name, body in (("python3", "exit 1"), ("python", 'exec "$REAL_PY" "$@"')):
        path = tools / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="")
        path.chmod(0o755)
    script = 'tools="$1"; if command -v cygpath >/dev/null 2>&1; then tools="$(cygpath -u "$tools")"; fi; export PATH="$tools:$PATH"; if [ "$OVERRIDE_PROBE" = 1 ]; then export REVAYAT_PYTHON="$tools/python3"; fi; shift; exec bash "$@"'
    result = run_process([shutil.which("bash"), "-c", script, "candidate-test", str(tools).replace("\\", "/"),
                          str(repo / "install/install.sh").replace("\\", "/"), "--agent", "codex",
                          "--scope", "project", "--path", str(project)], env=env)
    target = project / ".codex/skills/revayat-comic/SKILL.md"
    assert (result.returncode != 0) if override else result.returncode == 0, result.stderr
    assert target.exists() is not override


def test_native_entry_discovers_python_without_an_override(fixture):
    repo, project = fixture
    result = run_installer(repo, project, automatic=True)
    assert result.returncode == 0, result.stderr
    assert (project / ".codex/skills/revayat-comic/scripts/revayat-comic.py").is_file()
