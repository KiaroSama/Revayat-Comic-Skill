"""A malformed byte frame must not consume the next healthy request."""
from __future__ import annotations

import io
import json
import logging
import os
import sys
from pathlib import Path

import pytest

import server
from process_support import run_process

LOG = logging.getLogger(__name__)


def test_native_bad_bytes_then_good_request(tmp_path):
    cli = Path(server.__file__).with_name("revayat-comic.py")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8:strict",
           "PYTHONDONTWRITEBYTECODE": "1"}
    raw = b'{"id":"\xff","method":"ping"}\n{"id":2,"method":"ping"}\n'
    result = run_process([sys.executable, str(cli), "serve", "mcp"],
                         cwd=tmp_path, env=env, input=raw, text=False,
                         timeout=15, idle=10)
    stdout, stderr = result.stdout, result.stderr
    assert result.returncode == 0, stderr.decode("utf-8")
    responses = [json.loads(line) for line in stdout.decode("utf-8").splitlines()]
    assert responses == [{"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": "invalid JSON"}},
                         {"jsonrpc": "2.0", "id": 2, "result": {}}]
    LOG.info("Native malformed-byte frame refused; healthy next request and EOF survived")


@pytest.mark.parametrize("kind", ["binary", "strict", "surrogateescape", "text"])
@pytest.mark.parametrize("bad", [b'\xff', b'\xc0\xaf', b'\xed\xa0\x80', b'\xe2\x82'])
def test_bad_frame_never_dispatches_or_closes_borrowed_stream(monkeypatch, kind, bad):
    calls = []
    monkeypatch.setattr(server, "run", lambda *args: calls.append(args))
    frame = b'{"id":1,"method":"tools/call","params":{"name":"revayat_qa","arguments":{"args":["' + bad + b'"]}}}\n'
    raw = frame + '{"id":"سلام😀","method":"ping"}\r\n'.encode("utf-8")
    buffer = io.BytesIO(raw)
    stream = (buffer if kind == "binary" else
              io.StringIO(raw.decode("utf-8", errors="surrogateescape")) if kind == "text" else
              io.TextIOWrapper(buffer, encoding="utf-8", errors=kind))
    out = io.StringIO()
    try:
        assert server.serve_mcp(stream, out) == 0
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        assert responses[0] == {"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32700, "message": "invalid JSON"}}
        assert responses[1] == {"jsonrpc": "2.0", "id": "سلام😀", "result": {}}
        assert not calls and not stream.closed and not buffer.closed and not out.closed
    finally:
        stream.close()
        buffer.close()


@pytest.mark.parametrize("ending", [b'\n', b'\r\n', b''])
def test_valid_binary_unicode_and_eof(ending):
    raw = b'\n' + '{"id":"سلام😀","method":"ping"}'.encode("utf-8") + ending
    stream, out = io.BytesIO(raw), io.StringIO()
    assert server.serve_mcp(stream, out) == 0
    assert json.loads(out.getvalue()) == {"jsonrpc": "2.0", "id": "سلام😀", "result": {}}
    assert not stream.closed


@pytest.mark.parametrize("binary", [False, True])
def test_oversize_frame_drains_without_dispatching_its_suffix(monkeypatch, binary):
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 64)
    raw = 'x' * 70 + '{"id":7,"method":"ping"}\n{"id":2,"method":"ping"}\n'
    stream = io.BytesIO(raw.encode("utf-8")) if binary else io.StringIO(raw)
    out = io.StringIO()
    assert server.serve_mcp(stream, out) == 0
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(responses) == 2 and responses[0]["error"]["code"] == -32600
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


@pytest.mark.parametrize("binary", [False, True])
def test_no_newline_discard_is_finitely_bounded(monkeypatch, binary):
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 16)
    raw = 'x' * 1000
    stream = io.BytesIO(raw.encode("utf-8")) if binary else io.StringIO(raw)
    out = io.StringIO()
    assert server.serve_mcp(stream, out) == 1
    assert stream.tell() <= 4 * 16 + 1
    assert json.loads(out.getvalue())["error"]["code"] == -32600
    assert not stream.closed
