"""Public-boundary regressions: no remote services, generated tiny fixtures."""

from __future__ import annotations

import io
import json
import threading

import pytest
from PIL import Image

import clean
import ocr
import pageir as ir
import providers
import server


@pytest.fixture
def tiny_doc(tmp_path):
    image = tmp_path / "page.png"
    Image.new("RGB", (64, 64), "white").save(image)
    doc = ir.new_doc(source_language="en")
    page = ir.new_page("p0001", 0, "page.png", 64, 64, ir.sha256_file(image))
    region = ir.new_region("p0001r001", [4, 4, 40, 20], kind="speech")
    region.update(source_text="Hello", reading_order=1, confidence=1.0)
    page["regions"] = [region]
    doc["pages"] = [page]
    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    return path


class Reader:
    name = "round6-reader"

    def __init__(self, confidence=0.7):
        self.confidence = confidence
        self.calls = 0

    def read(self, *_args, **_kwargs):
        self.calls += 1
        return "Hello", self.confidence


@pytest.mark.parametrize("timeout", [True, -1, 0, float("nan"), float("inf"), "1", None])
def test_invalid_deadline_never_starts_provider(timeout):
    engine = Reader()
    result = providers.call(engine, "ocr", "unused.png", "en", timeout=timeout)
    assert not result.ok
    assert "timeout" in result.detail.lower()
    assert engine.calls == 0


def test_thread_start_failure_releases_capacity(monkeypatch):
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(providers, "_OUTSTANDING", capacity)
    start = threading.Thread.start
    with monkeypatch.context() as failed:
        failed.setattr(threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("startup")))
        result = providers.call(Reader(), "ocr", "unused.png", "en")
        assert not result.ok
    assert threading.Thread.start is start
    assert providers.call(Reader(), "ocr", "unused.png", "en").ok


def test_positional_only_parameter_is_not_offered_as_keyword():
    class Positional:
        def read(self, crop, language, orientation, /):
            return "Hello"
    assert not providers.wants(Positional(), "ocr", "orientation")


def test_positional_only_parameter_stays_positional_with_var_keywords():
    class PositionalAndExtras:
        def read(self, crop, language, orientation, /, **kwargs):
            return "Hello"

    assert not providers.wants(PositionalAndExtras(), "ocr", "orientation")


@pytest.mark.parametrize("payload", [17, {}, [], b"hello", "", "   "])
def test_text_provider_payload_must_be_nonempty_text(payload):
    class Invalid:
        def read(self, *_args):
            return payload
    result = providers.call(Invalid(), "ocr", "unused.png", "en")
    assert not result.ok


@pytest.mark.parametrize("threshold", [True, -1, 1.01, float("nan"), float("inf"), "0.5"])
def test_bad_ocr_threshold_changes_no_document_or_crop(tiny_doc, monkeypatch, threshold):
    before = tiny_doc.read_bytes()
    engine = Reader()
    monkeypatch.setitem(providers._REGISTRY["ocr"], "round6", lambda: engine)
    with pytest.raises(ValueError, match="confidence"):
        ocr.read_document(tiny_doc, provider="round6", min_confidence=threshold)
    assert tiny_doc.read_bytes() == before
    assert not (tiny_doc.parent / "ocr").exists()
    assert engine.calls == 0


def test_stricter_ocr_threshold_cannot_resume_lower_confidence(tiny_doc, monkeypatch):
    engine = Reader(0.7)
    monkeypatch.setitem(providers._REGISTRY["ocr"], "round6", lambda: engine)
    ocr.read_document(tiny_doc, provider="round6", min_confidence=0.6)
    calls = engine.calls
    report = ocr.read_document(tiny_doc, provider="round6", min_confidence=0.95)
    assert engine.calls > calls
    assert report["totals"]["needs_review"] == 1
    region = ir.load_doc(tiny_doc)["pages"][0]["regions"][0]
    assert region["source_text"] == "Hello"
    assert region["provenance"][-1]["outcome"] == "low_confidence"


@pytest.mark.parametrize("stage,role", [("ocr", "ocr"), ("translate", "translation")])
def test_provider_failure_is_not_transport_success(tiny_doc, monkeypatch, stage, role):
    def fail(*_args, **_kwargs):
        raise RuntimeError("deliberate local failure")
    engine = Reader()
    setattr(engine, "read" if role == "ocr" else "translate", fail)
    monkeypatch.setitem(providers._REGISTRY[role], "round6", lambda: engine)
    result = server.run(stage, ["--doc", str(tiny_doc), "--provider", "round6"])
    assert result["report"]["totals"]["failed"] == 1
    assert not result["ok"] and result["exit"] != 0


def test_clean_refusal_is_not_transport_success(tiny_doc, monkeypatch):
    monkeypatch.setattr(clean, "clean_document", lambda *a, **kw: {"refused_pages": ["p0001"]})
    result = server.run("clean", ["--doc", str(tiny_doc)])
    assert not result["ok"] and result["exit"] != 0


def test_module_load_failure_is_a_structured_mcp_result(monkeypatch):
    original = server.importlib.import_module
    with monkeypatch.context() as failed:
        def load(name):
            if name == "qa":
                raise ImportError("deliberate fixture")
            return original(name)
        failed.setattr(server.importlib, "import_module", load)
        result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "revayat_qa", "arguments": {"args": []}}})
        assert result["result"]["isError"]
    assert server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}


def test_doctor_load_failure_is_a_structured_result(monkeypatch):
    monkeypatch.setattr(server, "_doctor", lambda: (_ for _ in ()).throw(ImportError("fixture")))
    assert not server.run("doctor")["ok"]


def test_large_integer_argument_does_not_escape_boundary():
    report = server.run("qa", [10 ** 400])
    assert not report["ok"]


class BoundedInput(io.StringIO):
    def readline(self, size=-1):
        assert 0 < size <= server.MAX_BODY_BYTES + 1, "an unbounded read happened"
        return super().readline(size)


def test_mcp_enforces_raw_byte_limit_before_strip_and_preserves_next_request(monkeypatch):
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 128)
    stream = BoundedInput(" " * 200 + '\n' + json.dumps({"id": 2, "method": "ping"}) + "\n")
    output = io.StringIO()
    assert server.serve_mcp(stream, output) == 0
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32600
    assert replies[1]["id"] == 2 and replies[1]["result"] == {}


def test_mcp_limit_means_utf8_bytes_not_codepoints(monkeypatch):
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 128)
    body = json.dumps({"id": 1, "method": "ping", "params": {"s": "ژ" * 60}}, ensure_ascii=False)
    assert len(body) < 128 < len(body.encode("utf-8"))
    output = io.StringIO()
    server.serve_mcp(io.StringIO(body + "\n"), output)
    assert json.loads(output.getvalue())["error"]["code"] == -32600


def test_all_four_log_levels_keep_timestamps_and_exclude_arguments(tiny_doc, monkeypatch):
    import runlog
    monkeypatch.setenv("REVAYAT_LOG_LEVEL", "DEBUG")
    @ir.cli
    def command(argv):
        for level in ("INFO", "WARNING", "ERROR", "DEBUG"):
            runlog.event(level, "fixed diagnostic", component="test")
        return 0
    assert command(["--doc", str(tiny_doc), "--token", "never-record-this"]) == 0
    content = "\n".join(path.read_text() for path in (tiny_doc.parent / "logs").glob("*.log"))
    for level in ("INFO", "WARNING", "ERROR", "DEBUG"):
        assert f"[{level}]" in content
    assert "UTC]" in content and "never-record-this" not in content
