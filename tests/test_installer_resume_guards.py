"""Recovery/path invariants checked during the resumed round-thirteen review."""
import importlib.util
import json
import logging
from pathlib import Path
import shutil

import pytest

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup(tmp_path):
    spec = importlib.util.spec_from_file_location('installer_guard', ROOT / 'install/safe_install.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    base = tmp_path / 'project'
    base.mkdir()
    LOG.info('Prepared a private installer workspace')
    return core, base


def test_subset_upgrade_retains_both_installed_pointer_targets(setup):
    core, base = setup
    for name in ('opencode', 'antigravity'):
        core.install(ROOT, agent=name, scope='project', project=base, force=True)
    core.install(ROOT, agent='opencode', scope='project', project=base, force=True)
    text = (base / 'AGENTS.md').read_text(encoding="utf-8")
    assert str(base / '.opencode/skills/revayat-comic').replace('\\', '/') in text
    assert str(base / '.agents/skills/revayat-comic').replace('\\', '/') in text
    assert text.count(core.BEGIN.decode("utf-8")) == text.count(core.END.decode("utf-8")) == 1


def link_folder(target, outside):
    import os
    from process_support import run_process
    if os.name == 'nt':
        result = run_process(['cmd', '/c', 'mklink', '/J', str(target), str(outside)], timeout=10, idle=5)
        assert result.returncode == 0
    else:
        target.symlink_to(outside, target_is_directory=True)


@pytest.mark.parametrize('storage', ['staging', 'backups'])
def test_recovery_does_not_follow_linked_storage_parents(setup, tmp_path, storage):
    core, base = setup
    control = base / '.revayat-comic-installer'
    control.mkdir()
    outside = tmp_path / 'other-owner'
    outside.mkdir()
    (outside / 'sentinel').write_bytes(b'preserve')
    link_folder(control / storage, outside)
    target = base / '.codex/skills/revayat-comic'
    token = 'a' * 32
    stage, backup = core.artifact_paths(control, target, token)
    record = {'version': 1, 'token': token, 'phase': 'prepared', 'items': [
        {'target': str(target), 'stage': str(stage), 'backup': str(backup), 'old': None, 'new': '0'*64}]}
    pending = control / 'pending.json'
    pending.write_text(json.dumps(record), encoding="utf-8")
    raw = pending.read_bytes()
    with pytest.raises(ValueError, match='linked'):
        core.install(ROOT, agent='codex', scope='project', project=base, recover=True)
    assert pending.read_bytes() == raw
    assert (outside / 'sentinel').read_bytes() == b'preserve'
    assert not (control / 'lock.json').exists()


def test_linked_pending_record_does_not_leave_an_owned_lock(setup, tmp_path):
    core, base = setup
    control = base / '.revayat-comic-installer'
    control.mkdir()
    outside = tmp_path / 'outside-record'
    outside.mkdir()
    # A directory symlink/junction is sufficient to exercise the path check
    # without requiring Windows symlink privileges.
    link_folder(control / 'pending.json', outside)
    with pytest.raises(ValueError, match='linked'):
        core.install(ROOT, agent='codex', scope='project', project=base, force=True)
    assert not (control / 'lock.json').exists()
    assert list(outside.iterdir()) == []


def test_committed_recovery_does_not_certify_missing_backups(setup, monkeypatch):
    core, base = setup
    target = base / '.codex/skills/revayat-comic'
    target.mkdir(parents=True)
    (target / 'operator.txt').write_bytes(b'original')
    with monkeypatch.context() as changed:
        changed.setattr(core, 'finish', lambda *_args: (_ for _ in ()).throw(OSError('history failure')))
        with pytest.raises(OSError):
            core.install(ROOT, agent='codex', scope='project', project=base, force=True)
    pending = base / '.revayat-comic-installer/pending.json'
    record = json.loads(pending.read_text(encoding="utf-8"))
    backup = Path(record['items'][0]['backup'])
    shutil.rmtree(backup)
    raw = pending.read_bytes()
    with pytest.raises(RuntimeError, match='preserve recovery'):
        core.install(ROOT, agent='codex', scope='project', project=base, recover=True)
    assert pending.read_bytes() == raw
    assert (target / 'SKILL.md').is_file()


def test_post_promotion_edit_is_preserved_without_reporting_success(setup, monkeypatch):
    core, base = setup
    target = base / '.codex/skills/revayat-comic'
    rename = Path.rename
    def concurrent(path, new):
        result = rename(path, new)
        if Path(new) == target:
            (target / 'operator.txt').write_text('new work', encoding="utf-8")
        return result
    with monkeypatch.context() as changed:
        changed.setattr(Path, 'rename', concurrent)
        with pytest.raises(RuntimeError, match='ownership changed'):
            core.install(ROOT, agent='codex', scope='project', project=base, force=True)
    assert (target / 'operator.txt').read_text(encoding="utf-8") == 'new work'
    assert (base / '.revayat-comic-installer/pending.json').is_file()
