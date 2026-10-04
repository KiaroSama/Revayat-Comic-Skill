"""Fault injection and real child-process recovery for the shared installer."""
from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger(__name__)


@pytest.fixture
def core():
    spec = importlib.util.spec_from_file_location("revayat_safe_install", ROOT / "install/safe_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def layout(tmp_path):
    repo, base = tmp_path / "repo", tmp_path / "base"
    shutil.copytree(ROOT / "install", repo / "install")
    shutil.copytree(ROOT / "skills", repo / "skills", ignore=shutil.ignore_patterns("__pycache__", "logs"))
    base.mkdir()
    for agent in (".codex", ".opencode"):
        old = base / agent / "skills/revayat-comic"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_text("old skill for " + agent)
        (old / "note.txt").write_text("operator work")
    (base / "AGENTS.md").write_bytes(b"USER RULES\r\nNo changes here.\r\n")
    return repo, base


def call(core, layout, **kwargs):
    repo, base = layout
    return core.install(repo, agent="all", scope="project", project=base, force=True, **kwargs)


def originals(base):
    return {str(path.relative_to(base)): path.read_bytes() for path in base.rglob("*")
            if path.is_file() and ".revayat-comic-installer" not in path.parts}


@pytest.mark.parametrize("at", [1, 2, 20, 61, 62])
def test_copy_failures_preserve_all_old_destinations(core, layout, monkeypatch, at):
    before = originals(layout[1])
    original = core.shutil.copy2
    count = 0
    def copy(*args, **kwargs):
        nonlocal count
        count += 1
        if count == at:
            raise OSError("injected copy failure")
        return original(*args, **kwargs)
    with monkeypatch.context() as changed:
        changed.setattr(core.shutil, "copy2", copy)
        with pytest.raises(OSError):
            call(core, layout)
    assert originals(layout[1]) == before
    assert not (layout[1] / ".revayat-comic-installer/pending.json").exists()
    assert call(core, layout)


@pytest.mark.parametrize("at", [1, 2, 3, 4, 5, 6])
def test_promotion_failure_rolls_back_entire_batch(core, layout, monkeypatch, at):
    before = originals(layout[1])
    rename = Path.rename
    count = 0
    def faulty(path, target):
        nonlocal count
        count += 1
        if count == at:
            raise OSError("injected promotion failure")
        return rename(path, target)
    with monkeypatch.context() as changed:
        changed.setattr(Path, "rename", faulty)
        with pytest.raises(OSError):
            call(core, layout)
    assert originals(layout[1]) == before
    assert call(core, layout)


@pytest.mark.parametrize("boundary", ["first-backup", "first-promote", "pointer-backup", "pointer-promote", "committed"])
def test_killed_process_recovers_then_reinstalls(layout, boundary):
    repo, base = layout
    before = originals(base)
    code = r'''
import importlib.util, os, pathlib, sys
root, base, boundary = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location('installer', root / 'install/safe_install.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rename = pathlib.Path.rename
count = 0
def changed(path, target):
    global count
    result = rename(path, target)
    count += 1
    if count == {'first-backup':1, 'first-promote':2, 'pointer-backup':5, 'pointer-promote':6, 'committed':7}[boundary]:
        os._exit(73)
    return result
pathlib.Path.rename = changed
m.install(root, agent='all', scope='project', project=base, force=True)
'''
    result = subprocess.run([sys.executable, "-c", code, str(repo), str(base), boundary],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stderr
    spec = importlib.util.spec_from_file_location("recover_install", repo / "install/safe_install.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if boundary != "committed":
        pending = base / ".revayat-comic-installer/pending.json"
        recorded = pending.read_bytes()
        # Ordinary reruns refuse the existing journal; they do not recover implicitly.
        with pytest.raises((RuntimeError, FileExistsError)):
            call(m, layout)
        assert pending.read_bytes() == recorded
    call(m, layout, recover=True)
    if boundary != "committed":
        assert originals(base) == before
    else:
        assert (base / ".codex/skills/revayat-comic/scripts/revayat-comic.py").exists()
    call(m, layout)
    assert not (base / ".revayat-comic-installer/pending.json").exists()
    assert not (base / ".revayat-comic-installer/lock.json").exists()


def test_intervening_edit_is_not_overwritten_by_rollback(core, layout, monkeypatch):
    repo, base = layout
    original = Path.rename
    calls = 0
    def rename(path, target):
        nonlocal calls
        result = original(path, target)
        calls += 1
        if calls == 2:
            (base / ".codex/skills/revayat-comic/new-operator-work.txt").write_text("keep me")
        return result
    # Codex was changed by another writer after promotion; a later error must preserve it.
    atomic = core.atomic
    def write(path, data):
        if json.loads(data).get("phase") == "committed":
            raise OSError("metadata failure")
        return atomic(path, data)
    with monkeypatch.context() as changed:
        changed.setattr(Path, "rename", rename)
        changed.setattr(core, "atomic", write)
        with pytest.raises(RuntimeError, match="ownership changed"):
            call(core, layout)
    assert (base / ".codex/skills/revayat-comic/new-operator-work.txt").read_text() == "keep me"
    pending = base / ".revayat-comic-installer/pending.json"
    assert pending.is_file()
    with pytest.raises(RuntimeError, match="ownership changed"):
        call(core, layout, recover=True)
    assert pending.is_file()


def test_agreeing_digest_cannot_hide_pointer_edited_during_staging(core, layout, monkeypatch):
    repo, base = layout
    original = core.shutil.copy2
    changed_once = False
    def copy(*args, **kwargs):
        nonlocal changed_once
        result = original(*args, **kwargs)
        if not changed_once:
            (base / "AGENTS.md").write_text("new owner rules")
            changed_once = True
        return result
    with monkeypatch.context() as changed:
        changed.setattr(core.shutil, "copy2", copy)
        with pytest.raises(RuntimeError):
            call(core, layout)
    assert (base / "AGENTS.md").read_text() == "new owner rules"


def test_live_owner_is_not_displaced(core, layout):
    repo, base = layout
    control = base / ".revayat-comic-installer"
    control.mkdir()
    lock = control / "lock.json"
    raw = json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "token": "a" * 32}).encode()
    lock.write_bytes(raw)
    with pytest.raises(RuntimeError, match="live or unknown"):
        call(core, layout, recover=True)
    assert lock.read_bytes() == raw


@pytest.mark.parametrize("foreign", ["source", "destination", "pointer"])
def test_linked_files_are_refused_without_writing_through(core, layout, tmp_path, foreign):
    repo, base = layout
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "rules.md"
    sentinel.write_text("private")
    if os.name == "nt":
        if foreign == "pointer":
            # A hard-linked file requires no symlink privilege. Atomic pointer
            # promotion must detach that name without rewriting the other link.
            target = base / "AGENTS.md"
            target.unlink()
            os.link(sentinel, target)
            call(core, layout)
            assert sentinel.read_text() == "private"
            assert target.read_text().startswith("private")
            return
        # Junctions need no symlink privilege on Windows CI.
        target = (repo / "skills/revayat-comic/scripts" if foreign == "source"
                  else base / ".codex")
        shutil.rmtree(target)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(outside)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    elif foreign == "source":
        target = repo / "skills/revayat-comic/SKILL.md"
        target.unlink()
        target.symlink_to(sentinel)
    elif foreign == "pointer":
        target = base / "AGENTS.md"
        target.unlink()
        target.symlink_to(sentinel)
    else:
        target = base / ".codex"
        shutil.rmtree(target)
        target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="linked"):
        call(core, layout)
    assert sentinel.read_text() == "private"


def test_backups_are_outside_skill_discovery_directories(core, layout):
    call(core, layout)
    for agent in (".codex", ".opencode"):
        assert len(list((layout[1] / agent / "skills").rglob("SKILL.md"))) == 1


def test_bom_and_balanced_marker_preserve_all_outside_content(core):
    raw = b"\xef\xbb\xbf" + core.BEGIN + b"\r\nold\r\n" + core.END + b"\r\ntrailing"
    output = core.pointer(raw, [Path("/example/skill")])
    assert output.startswith(b"\xef\xbb\xbf" + core.BEGIN)
    assert output.endswith(b"trailing")
    assert core.pointer(output, [Path("/example/skill")]) == output


@pytest.mark.parametrize("when", ["prepared", "committed"])
def test_journal_write_failure_restores_old_state(core, layout, monkeypatch, when):
    before = originals(layout[1])
    original = core.atomic
    def atomic(path, data):
        if json.loads(data)["phase"] == when:
            raise OSError("injected record write failure")
        return original(path, data)
    with monkeypatch.context() as changed:
        changed.setattr(core, "atomic", atomic)
        with pytest.raises(OSError):
            call(core, layout)
    assert originals(layout[1]) == before
    assert call(core, layout)


def test_rollback_can_be_resumed_after_its_own_interruption(core, layout, monkeypatch):
    before = originals(layout[1])
    atomic, remove = core.atomic, core.remove_owned
    failed = False
    def fail_commit(path, data):
        if json.loads(data)["phase"] == "committed":
            raise OSError("commit failure")
        return atomic(path, data)
    def stop_rollback(path, expected):
        nonlocal failed
        remove(path, expected)
        if not failed:
            failed = True
            raise OSError("interrupted rollback after restoring a destination")
    with monkeypatch.context() as changed:
        changed.setattr(core, "atomic", fail_commit)
        changed.setattr(core, "remove_owned", stop_rollback)
        with pytest.raises(OSError):
            call(core, layout)
    assert (layout[1] / ".revayat-comic-installer/pending.json").exists()
    call(core, layout, recover=True)
    assert originals(layout[1]) == before
    assert call(core, layout)


def test_source_edit_during_staging_does_not_publish_a_mixed_bundle(core, layout, monkeypatch):
    before = originals(layout[1])
    original = core.shutil.copy2
    touched = False
    def copy(src, dst):
        nonlocal touched
        result = original(src, dst)
        if not touched:
            Path(src).write_bytes(Path(src).read_bytes() + b"\nchanged")
            touched = True
        return result
    with monkeypatch.context() as changed:
        changed.setattr(core.shutil, "copy2", copy)
        with pytest.raises(RuntimeError, match="source"):
            call(core, layout)
    assert originals(layout[1]) == before


@pytest.mark.parametrize("record", [[], {"version": 1, "token": None},
    {"version": 1, "token": "a" * 32, "phase": "prepared", "items": [None]}])
def test_unknown_recovery_record_is_preserved(core, layout, record):
    control = layout[1] / ".revayat-comic-installer"
    control.mkdir()
    pending = control / "pending.json"
    raw = json.dumps(record).encode()
    pending.write_bytes(raw)
    before = originals(layout[1])
    with pytest.raises(ValueError):
        call(core, layout, recover=True)
    assert pending.read_bytes() == raw and originals(layout[1]) == before
