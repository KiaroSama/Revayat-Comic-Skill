"""Recover from numeric and decoder failures without poisoning the next call."""

import io
import json
import logging
import threading
from fractions import Fraction

import pytest

import providers
import server

LOG = logging.getLogger(__name__)


@pytest.mark.parametrize("confidence", [10**400, 10**5000, Fraction(10**400, 1)],
                         ids=["large-int", "large-repr", "large-fraction"])
def test_outsize_confidence_is_a_failed_result_not_an_exception(monkeypatch, confidence):
    class Reader:
        def read(self, *_args):
            return "Hello", confidence
    monkeypatch.setattr(providers, "_OUTSTANDING", threading.BoundedSemaphore(1))
    result = providers.call(Reader(), "ocr", "unused", "en")
    assert not result.ok and result.status == "error"
    assert "confidence" in result.detail and len(result.detail) < 300
    assert providers.call(providers.FakeOCR(), "ocr", "unused", "en").ok
    LOG.info("Rejected an unusable probability and retained worker capacity")


@pytest.mark.parametrize("confidence", [0, 1, .75, Fraction(1, 2)])
def test_valid_confidence_keeps_its_numeric_contract(confidence):
    class Reader:
        def read(self, *_args):
            return "Hello", confidence
    result = providers.call(Reader(), "ocr", "unused", "en")
    assert result.ok and result.as_provenance()["confidence"] == float(confidence)


def _bad_frame(case):
    if case == "integer":
        return '{"id":1,"method":"ping","params":{"n":' + '9'*5000 + '}}'
    if case == "nesting":
        return '{"id":1,"method":"ping","params":{"n":' + '[' * 200 + '0' + ']' * 200 + '}}'
    if case == "nonfinite":
        return '{"id":1,"method":"ping","params":{"n":NaN}}'
    return '{"id":1,"method":"ping","params":{"n":1e999}}'


@pytest.mark.parametrize("case", ["integer", "nesting", "nonfinite", "exponent"])
def test_bad_json_frame_does_not_end_mcp_session(case):
    raw = _bad_frame(case)
    out = io.StringIO()
    assert server.serve_mcp(io.StringIO(raw + '\n{"id":2,"method":"ping"}\n'), out) == 0
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 2 and responses[1]["result"] == {}


@pytest.mark.parametrize("case", ["integer", "nesting", "nonfinite", "exponent"])
def test_bad_http_json_is_an_answer_and_next_request_still_works(case):
    import http.client
    service, token = server.serve_http(port=0)
    connection = http.client.HTTPConnection("127.0.0.1", service.server_port, timeout=5)
    try:
        headers = {"X-Revayat-Token": token, "Content-Type": "application/json"}
        connection.request("POST", "/tools/qa", body=_bad_frame(case).encode(), headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 400 and not body["ok"]
        assert body["error"] == "invalid JSON"
        connection.request("GET", "/tools", headers=headers)
        response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["tools"]
    finally:
        connection.close()
        service.shutdown()
        service.server_close()


def test_unavailable_stage_does_not_break_tool_discovery(monkeypatch):
    original = server.importlib.import_module
    def load(name):
        if name == "qa":
            raise ImportError("deliberate local fixture")
        return original(name)
    monkeypatch.setattr(server.importlib, "import_module", load)
    response = server.handle({"id":1, "method":"tools/list"})
    entries = response["result"]["tools"]
    assert any(tool["name"] == "revayat_qa" for tool in entries)
    assert not server.run("qa")["ok"]
    assert server.handle({"id":2, "method":"ping"})["result"] == {}


def test_oversized_direct_integer_argument_is_structured():
    assert not server.run("qa", [10**5000])["ok"]


@pytest.mark.parametrize("text", ['"' + "[" * 300 + '"', json.dumps('quotes: " \\ [[]] ژ'),
                                 '{"a":[true,false,null,1,-2,0.5,1e-5]}'])
def test_json_limits_do_not_reject_normal_or_quoted_content(text):
    import wire_json
    assert wire_json.loads(text) == json.loads(text)


def test_json_limits_accept_boundaries_without_changing_interpreter_settings():
    import sys
    import wire_json
    before = sys.getrecursionlimit()
    raw = '[' * wire_json.MAX_DEPTH + '0' + ']' * wire_json.MAX_DEPTH
    assert wire_json.loads(raw) == json.loads(raw)
    assert wire_json.loads('9' * wire_json.MAX_INTEGER_DIGITS) == int('9' * wire_json.MAX_INTEGER_DIGITS)
    assert sys.getrecursionlimit() == before
    with pytest.raises(ValueError):
        wire_json.loads('[' + raw + ']')
