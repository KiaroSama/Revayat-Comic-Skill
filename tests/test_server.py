"""The two transports, and the one thing that makes them safe to have.

`server.py` is a transport, not a layer: every tool is a stage's own `main`,
called with the arguments the CLI takes. So what these tests check is not what
the stages do — the rest of the suite does that — but that the wrapping cannot
lose, corrupt or invent an answer, and cannot be reached by something that
should not reach it.

The load-bearing test is `test_a_stage_printing_its_report_cannot_corrupt_the
_stream`. Every stage speaks JSON on stdout, and on the stdio transport stdout
is also the JSON-RPC channel; without the capture, the first real stage call
would derail the conversation.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import pageir as ir
import server


def _talk(*messages) -> list[dict]:
    """Drive the stdio transport with a list of messages, get the replies."""
    import io

    out = io.StringIO()
    server.serve_mcp(io.StringIO("\n".join(json.dumps(m) for m in messages)),
                     out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def _ask(request_id, method, **params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method,
            "params": params}


# --- the tool surface --------------------------------------------------------

def test_the_stage_list_matches_the_cli():
    """The drift guard. `revayat-comic.py` has a hyphen and cannot be imported,
    so its stage table is read as text — which means the two lists can disagree
    silently and a stage becomes unreachable over MCP without anything failing.

    `serve` is the one difference and it is deliberate: a transport does not
    expose itself as a tool.
    """
    cli = Path(server.__file__).resolve().parent / "revayat-comic.py"
    text = cli.read_text(encoding="utf-8")
    block = text[text.index("STAGES = {"):text.index("REQUIRED = {")]
    named = {line.split('"')[1] for line in block.splitlines()
             if line.strip().startswith('"')}
    assert named - {"serve"} == set(server.STAGES)


def test_every_stage_is_a_tool_and_describes_itself():
    listed = server.tools()
    names = {tool["name"] for tool in listed}
    assert names == {f"revayat_{s}" for s in (server.DOCTOR, *server.STAGES)}
    for tool in listed:
        # Descriptions come from each stage module's own docstring, so an empty
        # one means a module lost its first line rather than that the text here
        # was forgotten.
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"


def test_the_handshake_answers_with_a_protocol_and_a_name():
    (reply,) = _talk(_ask(1, "initialize"))
    result = reply["result"]
    assert result["protocolVersion"] == server.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == server.SERVER_NAME
    assert "tools" in result["capabilities"]


def test_a_notification_is_never_answered():
    """A notification has no `id` and the protocol forbids a reply. Answering
    one is the usual reason a client hangs waiting for a handshake that already
    finished."""
    replies = _talk({"jsonrpc": "2.0", "method": "notifications/initialized"},
                    _ask(2, "ping"))
    assert [r["id"] for r in replies] == [2]


# --- calling a stage ---------------------------------------------------------

def test_a_tool_call_runs_the_stage_and_returns_its_report(detected):
    replies = _talk(_ask(1, "tools/call", name="revayat_qa",
                         arguments={"args": ["check", "--doc", str(detected)]}))
    result = replies[0]["result"]
    body = json.loads(result["content"][0]["text"])
    assert body["stage"] == "qa"
    # `qa` on a detected-but-untranslated document reports findings and exits
    # non-zero. That is the stage working, and the transport passing it through.
    assert body["report"]["findings"]
    assert result["isError"] is (not body["ok"])


def test_a_stage_printing_its_report_cannot_corrupt_the_stream(detected):
    """THE ONE THAT MATTERS. Every stage prints JSON to stdout, and on this
    transport stdout is the wire. Without the capture in `run`, the first stage
    call writes its report into the middle of the conversation and every reply
    after it is unparseable.

    Proved by running a stage that genuinely prints, then requiring every line
    that came back to be one whole JSON-RPC message.
    """
    import io

    out = io.StringIO()
    server.serve_mcp(io.StringIO("\n".join(json.dumps(m) for m in [
        _ask(1, "tools/call", name="revayat_detect",
             arguments={"args": ["--doc", str(detected)]}),
        _ask(2, "ping"),
    ])), out)

    lines = out.getvalue().splitlines()
    assert len(lines) == 2, "a stage's own output reached the wire"
    for line in lines:
        json.loads(line)  # raises if the framing broke
    assert json.loads(lines[1])["result"] == {}


def test_a_failing_stage_is_a_result_not_a_crash():
    replies = _talk(_ask(1, "tools/call", name="revayat_detect",
                         arguments={"args": ["--doc", "nowhere.json"]}))
    result = replies[0]["result"]
    assert result["isError"] is True
    body = json.loads(result["content"][0]["text"])
    assert body["ok"] is False and "FileNotFoundError" in body["error"]


def test_a_bad_flag_does_not_take_the_server_down():
    """argparse calls `sys.exit` on an unknown option. Over a transport that is
    an answer, not a reason to stop serving."""
    replies = _talk(_ask(1, "tools/call", name="revayat_detect",
                         arguments={"args": ["--not-a-flag"]}),
                    _ask(2, "ping"))
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["isError"] is True


def test_an_unknown_tool_says_what_there_is():
    replies = _talk(_ask(1, "tools/call", name="revayat_nonsense",
                         arguments={}))
    body = json.loads(replies[0]["result"]["content"][0]["text"])
    assert body["ok"] is False
    assert server.DOCTOR in body["expected"]


def test_a_stage_that_exits_with_a_message_is_an_answer_not_a_crash(detected):
    """`context` refuses to build over an unmerged page by raising
    `SystemExit(<message>)`, which is the shape `sys.exit` documents and a
    first-party path this project takes. `int(exit_code.code)` then raised
    `ValueError` *inside* the `except SystemExit` handler, so it escaped `run`
    and took the loop down with it. The plain CLI handles the same input."""
    worksheets = Path(detected).parent / "worksheets"
    worksheets.mkdir(exist_ok=True)
    (worksheets / "p0001.done.txt").write_text("a reply nobody merged\n",
                                               encoding="utf-8")
    second = ir.load_doc(detected)["pages"][1]["id"]

    replies = _talk(_ask(1, "tools/call", name="revayat_context",
                         arguments={"args": ["--doc", str(detected),
                                             "--page", second]}),
                    _ask(2, "ping"))
    assert [r["id"] for r in replies] == [1, 2], "the loop did not survive it"
    body = json.loads(replies[0]["result"]["content"][0]["text"])
    assert body["ok"] is False and body["exit"] != 0
    assert "not merged" in body["error"], "the reason was thrown away"


def test_a_bad_flag_comes_back_with_the_reason_argparse_gave(capsys):
    """argparse explains itself on *stderr*, which `run` never captured — so
    the client was told a stage exited 2 and nothing else, while the sentence
    that would have told it which flag was wrong went to the terminal."""
    outcome = server.run("revayat_detect", ["--doc", "nowhere.json",
                                            "--not-a-flag"])
    assert outcome["ok"] is False and outcome["exit"] == 2
    assert "--not-a-flag" in outcome["error"]
    assert capsys.readouterr().err == "", "argparse's complaint reached stderr"


# --- shapes that are not what they claim to be -------------------------------
# Each of these came in over a real transport and either killed the loop or
# dropped the connection, because the shape was used before it was checked.

def test_a_message_that_is_not_an_object_cannot_end_the_conversation():
    """A top-level array or string is valid JSON and not a JSON-RPC message.
    `message.get` on a list is an `AttributeError` out of `serve_mcp`."""
    import io

    out = io.StringIO()
    server.serve_mcp(io.StringIO('[1, 2, 3]\n"hello"\n'
                                 + json.dumps(_ask(3, "ping")) + "\n"), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r["error"]["code"] for r in replies[:2]] == [-32600, -32600]
    assert replies[2]["result"] == {}


@pytest.mark.parametrize("params", [[], ["--doc", "x"], "arguments", 7])
def test_params_that_are_not_an_object_are_refused(params):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": params})
    assert reply["error"]["code"] == -32602


def test_arguments_that_are_not_an_object_are_refused():
    reply = server.handle(_ask(1, "tools/call", name="revayat_detect",
                               arguments=["--doc", "work/comic.json"]))
    assert reply["error"]["code"] == -32602


def test_args_given_as_a_string_are_refused_rather_than_spelled_out():
    """`[str(a) for a in args]` turns `"--doc x"` into fourteen arguments of
    one letter each, and the stage is handed nonsense it cannot explain."""
    outcome = server.run("revayat_detect", "--doc work/comic.json")
    assert outcome["ok"] is False
    assert "list" in outcome["error"] and "--doc" not in outcome.get("report", "")
    assert "exit" not in outcome, "the stage ran on a spelled-out string"


def test_an_unknown_method_and_a_broken_line_are_both_survivable():
    import io

    out = io.StringIO()
    server.serve_mcp(io.StringIO(
        "{not json\n" + json.dumps(_ask(2, "nonsense")) + "\n"
        + json.dumps(_ask(3, "ping")) + "\n"), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["error"]["code"] == -32601
    assert replies[2]["result"] == {}


# --- the HTTP transport ------------------------------------------------------

@pytest.fixture
def http_server():
    httpd, token = server.serve_http(port=0)
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", token
    finally:
        httpd.shutdown()
        httpd.server_close()


def _http(base: str, path: str, body=None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Revayat-Token"] = token
    request = urllib.request.Request(
        base + path, headers=headers,
        data=json.dumps(body).encode("utf-8") if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_http_lists_the_same_tools(http_server):
    base, token = http_server
    status, body = _http(base, "/tools", token=token)
    assert status == 200
    assert ([t["name"] for t in body["tools"]]
            == [t["name"] for t in server.tools()])


def test_http_runs_a_stage(http_server, detected):
    base, token = http_server
    status, body = _http(base, "/tools/revayat_qa",
                         {"args": ["check", "--doc", str(detected)]},
                         token=token)
    assert body["stage"] == "qa" and body["report"]["findings"]
    assert status == (200 if body["ok"] else 400)


def test_two_stages_called_at_once_each_get_their_own_report(http_server,
                                                            detected):
    """`redirect_stdout` swaps a process-global and this transport is a thread
    per request, so without a lock around the capture one caller is handed the
    other's report — well-formed, plausible, and about a stage it never asked
    for. The assertion is on the report's *shape* for that reason: a `qa`
    answer carrying `constraints` is the corruption itself, and nothing raises
    when it happens.
    """
    base, token = http_server
    page = ir.load_doc(detected)["pages"][0]["id"]
    # Two stages that both print their report through the capture, with no key
    # in common. `doctor` would not do: it returns before the redirect and so
    # cannot be corrupted, which would make this test unable to fail.
    calls = [("revayat_qa", ["check", "--doc", str(detected)]),
             ("revayat_context", ["--doc", str(detected), "--page", page])] * 4

    def ask(call):
        name, args = call
        return name, _http(base, f"/tools/{name}", {"args": args}, token=token)[1]

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        answers = list(pool.map(ask, calls))

    for name, body in answers:
        stage = name[len("revayat_"):]
        assert body["stage"] == stage
        report = body["report"]
        assert isinstance(report, dict), f"{stage} came back with {report!r}"
        mine, theirs = (("findings", "constraints") if stage == "qa"
                        else ("constraints", "findings"))
        assert mine in report and theirs not in report,             f"a {stage} call answered with {sorted(report)}"


def test_http_refuses_a_caller_without_the_token(http_server):
    """A page in a browser can POST to localhost. It cannot read a token
    printed in the terminal that started this."""
    base, token = http_server
    assert _http(base, "/tools")[0] == 401
    assert _http(base, "/tools", token="x" * 32)[0] == 401
    assert _http(base, "/tools", token=token)[0] == 200


def test_http_says_what_the_two_routes_are(http_server):
    base, token = http_server
    assert _http(base, "/nope", token=token)[0] == 404
    assert _http(base, "/tools/x", {"args": []}, token=token)[0] == 400


def test_http_refuses_to_bind_off_loopback():
    """This answers requests by running stages that write files. Reachable off
    the machine, that is a remote file-writing service with a header for a
    password."""
    with pytest.raises(ValueError, match="loopback"):
        server.serve_http(port=0, host="0.0.0.0")


def test_an_http_body_that_is_not_an_object_is_a_bounded_error(http_server):
    """`body.get("args")` on a list raises inside the handler thread, which
    drops the connection with no answer at all."""
    base, token = http_server
    assert _http(base, "/tools/revayat_detect", ["--doc", "x"],
                 token=token)[0] == 400
    assert _http(base, "/tools/revayat_detect", "a string", token=token)[0] == 400
    assert _http(base, "/tools/revayat_detect", 7, token=token)[0] == 400
    assert _http(base, "/tools", token=token)[0] == 200, "the server stopped"


# --- what a caller may send, and for how long --------------------------------

def _raw_post(port: int, token: str, declared: int, body: bytes = b"",
              read_timeout: float = 3.0) -> str:
    """A POST written by hand, so the declared length and the bytes actually
    sent can disagree — which is the whole point of the two tests below."""
    head = (f"POST /tools/revayat_nope HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"X-Revayat-Token: {token}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {declared}\r\n\r\n").encode("ascii")
    connection = socket.create_connection(("127.0.0.1", port),
                                          timeout=read_timeout)
    try:
        connection.sendall(head + body)
        return connection.recv(4096).decode("utf-8", "replace")
    finally:
        connection.close()


def test_an_oversized_body_is_refused_before_it_is_read(http_server):
    """A stage's arguments are a few hundred bytes. 64 MiB of them was read in
    full, into memory, and took 28 seconds to say no to."""
    base, token = http_server
    port = int(base.rsplit(":", 1)[1])
    answer = _raw_post(port, token, declared=100 * 1024 * 1024,
                       body=b'{"args":[]}')
    assert "413" in answer.splitlines()[0], answer.splitlines()[:1]


def test_a_body_that_never_arrives_does_not_hold_a_handler(monkeypatch):
    """A declared length and no bytes behind it blocked a handler thread on a
    read with no deadline, for as long as the caller cared to hold it open."""
    monkeypatch.setattr(server, "READ_TIMEOUT", 0.5)
    httpd, token = server.serve_http(port=0)
    try:
        port = httpd.server_address[1]
        started = time.monotonic()
        answer = _raw_post(port, token, declared=64, body=b"", read_timeout=5.0)
        elapsed = time.monotonic() - started
        assert elapsed < 3.0, f"the handler waited {elapsed:.1f}s for a body"
        assert "200" not in answer.splitlines()[:1]
        assert _http(f"http://127.0.0.1:{port}", "/tools", token=token)[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_host_flag_exists_and_still_refuses_off_loopback():
    """`references/serving.md` tells a reader to use `--host`; argparse had
    never heard of it, so the documented flag was an error."""
    with pytest.raises(ValueError, match="loopback"):
        server.main(["http", "--host", "0.0.0.0", "--port", "0"])


def test_the_ipv6_loopback_address_actually_binds():
    """`::1` sat in the allow-list while the server was `AF_INET`, so the one
    caller who took that list at its word got `gaierror` instead of a server."""
    probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    with probe:
        try:
            probe.bind(("::1", 0))
        except OSError as error:
            pytest.skip(f"no IPv6 loopback on this machine: {error}")

    said: dict[str, str] = {}
    httpd, token = server.serve_http(port=0, host="::1", announce=said.update)
    try:
        port = httpd.server_address[1]
        assert said["url"] == f"http://[::1]:{port}", "an unbracketed IPv6 URL"
        status, body = _http(f"http://[::1]:{port}", "/tools", token=token)
        assert status == 200 and body["tools"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_document_is_untouched_by_being_reachable(detected):
    """A transport must not be a second way to change state. Running a
    read-only stage through it leaves the document byte-identical."""
    before = Path(detected).read_bytes()
    _talk(_ask(1, "tools/call", name="revayat_qa",
               arguments={"args": ["check", "--doc", str(detected)]}))
    assert Path(detected).read_bytes() == before
    assert ir.load_doc(detected)["pages"]


# --- a real client, over a real process ---------------------------------------
# Everything above drives `serve_mcp` in-process with StringIO. That proves the
# protocol and proves nothing about the transport: pipe buffering, the child's
# stdout encoding, whether the process exits when the pipe closes. A client
# talking to a subprocess is the shape every MCP host actually uses.

class _StdioClient:
    """The smallest MCP client that is really a client: a subprocess, two
    pipes, newline-delimited JSON-RPC, and no shared memory with the server."""

    def __init__(self, argv):
        import subprocess

        self.process = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self._id = 0

    def request(self, method, **params):
        self._id += 1
        self.process.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method,
             "params": params}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        assert line, "the server closed the pipe without answering"
        return json.loads(line)

    def notify(self, method, **params):
        self.process.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.process.stdin.flush()

    def close(self, timeout=20):
        self.process.stdin.close()
        return self.process.wait(timeout=timeout)


@pytest.fixture
def stdio_client():
    import sys

    cli = Path(server.__file__).resolve().parent / "revayat-comic.py"
    client = _StdioClient([sys.executable, str(cli), "serve", "mcp"])
    try:
        yield client
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait(timeout=10)


def test_a_real_client_completes_the_handshake_and_calls_a_tool(stdio_client,
                                                                detected):
    """The full conversation an MCP host has, across a process boundary:
    initialize, the notification that gets no answer, tools/list, tools/call."""
    hello = stdio_client.request("initialize", protocolVersion="2025-03-26",
                                 capabilities={}, clientInfo={"name": "probe"})
    assert hello["result"]["serverInfo"]["name"] == server.SERVER_NAME

    # A notification must not be answered. If the server replies to it, the
    # next `readline` returns that reply instead and every id after is off by
    # one — which is exactly how this fails in the wild.
    stdio_client.notify("notifications/initialized")

    listed = stdio_client.request("tools/list")
    assert listed["id"] == 2, "the notification was answered"
    assert len(listed["result"]["tools"]) == len(server.tools())

    called = stdio_client.request(
        "tools/call", name="revayat_qa",
        arguments={"args": ["check", "--doc", str(detected)]})
    assert called["id"] == 3
    body = json.loads(called["result"]["content"][0]["text"])
    assert body["stage"] == "qa" and body["report"]["findings"]


def test_the_server_exits_when_the_client_closes_the_pipe(stdio_client):
    """A host that goes away must not leave a python process behind."""
    stdio_client.request("ping")
    assert stdio_client.close() == 0


def test_persian_and_japanese_survive_the_pipe(stdio_client, detected):
    """The wire is UTF-8 on every platform. A Windows console defaults to a
    legacy code page, and a stage report full of Persian is the first thing to
    hit it — which is why every entry point calls `ir.use_utf8_stdio`."""
    stdio_client.request("initialize")
    called = stdio_client.request(
        "tools/call", name="revayat_worksheet",
        arguments={"args": ["build", "--doc", str(detected)]})
    text = called["result"]["content"][0]["text"]
    assert json.loads(text)["stage"] == "worksheet"

    sheet = next((ir.doc_dir(detected) / "worksheets").glob("*.txt"))
    assert sheet.read_text(encoding="utf-8").strip()


# --- R12: a stage that fails is an answer, not the end of the conversation ---

def test_a_corrupt_archive_does_not_end_the_mcp_conversation(stdio_client,
                                                             tmp_path):
    """Only `FileNotFoundError` and `ValueError` were contained, so a corrupt
    archive (`zipfile.BadZipFile`) ended the loop and the client waited for a
    reply that was never coming. Driven through the real subprocess: containing
    it in-process proves nothing about the transport."""
    broken = tmp_path / "broken.cbz"
    broken.write_bytes(b"PK\x03\x04 this is not an archive at all")

    stdio_client.request("initialize", protocolVersion="2025-03-26",
                         capabilities={}, clientInfo={"name": "probe"})
    reply = stdio_client.request(
        "tools/call", name="import",
        arguments={"args": ["--source", str(broken),
                            "--out", str(tmp_path / "work")]})
    outcome = json.loads(reply["result"]["content"][0]["text"])
    assert outcome["ok"] is False and outcome["error"]

    # And the loop is still there.
    assert stdio_client.request("ping")["result"] == {}


def test_a_directory_where_a_file_belongs_does_not_end_it_either(stdio_client,
                                                                 tmp_path):
    """The same door, a different exception: a directory where a document
    belongs raises `IsADirectoryError` or `PermissionError` depending on the
    platform, and neither was contained."""
    folder = tmp_path / "a-folder.json"
    folder.mkdir()

    stdio_client.request("initialize", protocolVersion="2025-03-26",
                         capabilities={}, clientInfo={"name": "probe"})
    reply = stdio_client.request("tools/call", name="detect",
                                 arguments={"args": ["--doc", str(folder)]})
    assert json.loads(reply["result"]["content"][0]["text"])["ok"] is False
    assert stdio_client.request("ping")["result"] == {}


@pytest.mark.parametrize("message,expect", [
    ({"jsonrpc": "1.0", "id": 1, "method": "ping"}, "JSON-RPC 2.0"),
    ({"jsonrpc": "2.0", "id": {}, "method": "ping"}, "id is a string"),
    ({"jsonrpc": "2.0", "id": None, "method": "ping"}, "needs an id"),
    ({"jsonrpc": "2.0", "id": 1, "method": 7}, "method must be a string"),
    ({"jsonrpc": "2.0", "id": 1}, "method must be a string"),
])
def test_a_malformed_envelope_is_answered_not_dropped(message, expect):
    """A NULL id is a malformed request, not a notification — and treating the
    two the same left a client waiting for a reply that was never coming."""
    reply = server.handle(message)
    assert reply is not None, "the client would wait for ever"
    assert expect in reply["error"]["message"], reply


def test_a_notification_is_still_unanswered():
    assert server.handle({"jsonrpc": "2.0", "method": "ping"}) is None


def test_an_oversized_stdio_line_is_refused_without_being_parsed():
    """A stage's arguments are a few hundred bytes; a client that sends a
    megabyte on one line is malfunctioning or hostile."""
    import io as _io

    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping",
                       "params": {"pad": "x" * (server.MAX_BODY_BYTES + 10)}})
    out = _io.StringIO()
    server.serve_mcp(_io.StringIO(line + "\n"), out)
    reply = json.loads(out.getvalue().strip())
    assert "at most" in reply["error"]["message"]


def test_a_rejected_post_closes_rather_than_leaving_its_body_behind(http_server):
    """The body is still in the socket. On a keep-alive connection the next
    read starts in the middle of it, and those bytes are parsed as the next
    request — so a rejected call could be followed by a nonsense one the client
    never sent."""
    import http.client
    import urllib.parse

    base, _token = http_server
    parts = urllib.parse.urlsplit(base)
    connection = http.client.HTTPConnection(parts.hostname, parts.port,
                                            timeout=30)
    try:
        connection.request("POST", "/tools/detect",
                           body=json.dumps({"args": ["--doc", "x"]}),
                           headers={"X-Revayat-Token": "wrong",
                                    "Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 401
        response.read()
        assert response.getheader("Connection", "").lower() == "close"
    finally:
        connection.close()
