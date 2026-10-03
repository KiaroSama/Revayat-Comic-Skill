"""Decoded request strings must remain representable on strict UTF-8 transports."""

import http.client
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

import server
import wire_json

LOG = logging.getLogger(__name__)


def test_surrogate_request_does_not_break_strict_output():
    raw = '{"id":"\\ud800","method":"ping"}\n{"id":2,"method":"ping"}\n'
    data = io.BytesIO()
    out = io.TextIOWrapper(data, encoding="utf-8", errors="strict")
    try:
        assert server.serve_mcp(io.StringIO(raw), out) == 0
        out.flush()
        responses = [json.loads(line) for line in data.getvalue().decode("utf-8").splitlines()]
        assert responses[0]["id"] is None and responses[0]["error"]["code"] == -32700
        assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}
    finally:
        out.close()


@pytest.mark.parametrize("escape", [r"\ud800", r"\udfff"])
@pytest.mark.parametrize("frame", ['"%s"', '{"%s":1}', '{"outer":[{"key":"%s"}]}'])
def test_all_decoded_strings_and_keys_reject_lone_surrogates(escape, frame):
    with pytest.raises(ValueError, match="Unicode") as error:
        wire_json.loads(frame % escape)
    assert escape not in str(error.value) and len(str(error.value)) < 100


@pytest.mark.parametrize("raw,expected", [(r'"\ud83d\ude00"', "😀"),
                                          ('"سلام‌دنیا"', "سلام‌دنیا"),
                                          (r'"\\ud800"', r"\ud800"),
                                          ('{"😀":["سلام","\\u2028"]}', {"😀": ["سلام", "\u2028"]})])
def test_valid_unicode_is_not_repaired_or_discarded(raw, expected):
    assert wire_json.loads(raw) == expected


def test_bad_argument_is_refused_before_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "run", lambda *args: calls.append(args))
    frame = r'{"id":1,"method":"tools/call","params":{"name":"revayat_qa","arguments":{"args":["\udfff"]}}}'
    out = io.StringIO()
    server.serve_mcp(io.StringIO(frame + '\n{"id":2,"method":"ping"}\n'), out)
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert not calls and responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 2 and responses[1]["result"] == {}


def test_real_stdio_keeps_session_usable(tmp_path):
    cli = Path(server.__file__).with_name("revayat-comic.py")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8:strict",
           "PYTHONDONTWRITEBYTECODE": "1"}
    raw = b'{"id":"\\ud800","method":"ping"}\n{"id":2,"method":"ping"}\n'
    process = subprocess.Popen([sys.executable, str(cli), "serve", "mcp"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=tmp_path, env=env)
    try:
        stdout, stderr = process.communicate(raw, timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert process.returncode == 0, stderr.decode("utf-8")
    responses = [json.loads(line) for line in stdout.decode("utf-8").splitlines()]
    assert responses[0]["error"]["code"] == -32700 and responses[0]["id"] is None
    assert responses[1]["id"] == 2 and responses[1]["result"] == {}
    LOG.info("Real stdio refused malformed Unicode and exited cleanly")


@pytest.mark.parametrize("raw", [r'{"args":["\ud800"]}', r'{"\udfff":[]}',
                                  r'{"args":[{"nested":"\ud800"}]}'])
def test_real_http_rejects_before_stage_and_accepts_next(monkeypatch, raw):
    calls = []
    monkeypatch.setattr(server, "run", lambda *args: calls.append(args))
    service, token = server.serve_http(port=0)
    connection = http.client.HTTPConnection("127.0.0.1", service.server_port, timeout=3)
    try:
        headers = {"X-Revayat-Token": token, "Content-Type": "application/json"}
        connection.request("POST", "/tools/qa", raw.encode("utf-8"), headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 400 and body == {"ok": False, "error": "invalid JSON"}
        assert not calls
        connection.request("GET", "/tools", headers=headers)
        response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["tools"]
    finally:
        connection.close()
        service.shutdown()
        service.server_close()
