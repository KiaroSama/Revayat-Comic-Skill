"""Persistent installer diagnostics through the actual CLI boundary."""
import importlib.util
import logging
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def core(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("logging_install", ROOT / "install/safe_install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    launcher = tmp_path / "launcher with spaces" / "safe_install.py"
    launcher.parent.mkdir()
    monkeypatch.setattr(module, "__file__", str(launcher))
    monkeypatch.setenv("REVAYAT_LOG_LEVEL", "DEBUG")
    monkeypatch.chdir(tmp_path)
    return module, launcher.parent


def test_logs_are_unique_utc_utf8_closed_and_exclude_error_payloads(core, monkeypatch, capsys):
    module, folder = core
    baseline = list(module.LOG.handlers)
    def install(*args, **kwargs):
        module.LOG.warning("controlled warning")
        module.LOG.debug("UTF-8 round trip: فارسی")
        raise OSError("synthetic-secret-do-not-log")
    monkeypatch.setattr(module, "install", install)
    for _ in range(2):
        assert module.main(["--agent", "codex", "--scope", "project"]) == 1
    files = list((folder / "logs").glob("safe_install_*.log"))
    assert len(files) == 2
    assert module.LOG.handlers == baseline
    for path in files:
        assert re.fullmatch(r"safe_install_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_UTC(?:_[a-f0-9]+)?\.log", path.name)
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        assert text.encode("utf-8") == raw
        assert "فارسی" in text and "controlled warning" in text
        assert "stack=" in text and "exit=1" in text and "UTC] [ERROR] [installer]" in text
        assert "synthetic-secret-do-not-log" not in text
        path.rename(path.with_suffix(".closed"))
    assert "synthetic-secret-do-not-log" not in capsys.readouterr().err


@pytest.mark.parametrize("message, guidance", [
    ("installer owner is live or unknown; preserve its lock", "wait for the original local installer"),
    ("AGENTS.md has an unmatched Revayat begin marker; preserve and repair it", "repair the balanced Revayat block"),
    ("installation ownership changed; backups retained: synthetic-private-path", "reconcile the operator's intervening changes"),
])
def test_refusals_report_safe_actionable_categories(core, monkeypatch, capsys, message, guidance):
    module, _ = core
    def refuse(*args, **kwargs):
        raise RuntimeError(message)
    monkeypatch.setattr(module, "install", refuse)
    assert module.main(["--recover"]) == 1
    output = capsys.readouterr().err
    assert guidance in output and "synthetic-private-path" not in output


def test_logging_initialization_failure_keeps_safe_console_diagnostics(core, monkeypatch, capsys):
    module, folder = core
    handler = logging.FileHandler
    def fail(*args, **kwargs):
        raise PermissionError("synthetic-secret-do-not-log")
    monkeypatch.setattr(module.logging, "FileHandler", fail)
    monkeypatch.setattr(module, "install", lambda *args, **kwargs: [])
    assert module.main(["--agent", "codex"]) == 0
    output = capsys.readouterr().err
    assert "file logging unavailable" in output and "exit=0" in output
    assert "synthetic-secret-do-not-log" not in output
    monkeypatch.setattr(module.logging, "FileHandler", handler)
