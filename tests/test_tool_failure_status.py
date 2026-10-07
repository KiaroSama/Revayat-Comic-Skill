"""Business refusal remains a failure through CLI and tool transport."""
import importlib.util

import pytest
from PIL import Image

import readers
import server
import watermark


def test_watermark_refusal_returns_nonzero(tmp_path, capsys):
    source = tmp_path / "source.png"
    Image.new("RGB", (40, 60), "white").save(source)
    readers.import_source(source, tmp_path / "work", source_language="en")
    path = tmp_path / "work" / "comic.json"
    assert watermark.main(["--doc", str(path), "--box", "100 100 10 10"]) != 0
    assert '"refused"' in capsys.readouterr().out


@pytest.mark.parametrize("ready", [False, True])
def test_doctor_status_matches_readiness(monkeypatch, ready):
    original = importlib.util.module_from_spec

    def controlled(spec):
        module = original(spec)
        loader = spec.loader
        execute = loader.exec_module

        def load(target):
            execute(target)
            target.doctor = lambda: {"ready": ready}

        loader.exec_module = load
        return module

    monkeypatch.setattr(importlib.util, "module_from_spec", controlled)
    report = server.run("doctor", [])
    assert report["ok"] is ready
    assert report["exit"] == (0 if ready else 1)
    assert report["report"] == {"ready": ready}
