"""The same stages, reachable over MCP and over HTTP.

**Why this exists at all.** The skill's own answer to "how does an agent drive
this" has always been: run the CLI. That is still the recommended path, and
nothing here changes it. But not every host can run a subprocess — a hosted
agent, a sandboxed one, a service on another machine — and for those the CLI is
not a smaller interface, it is no interface. Four of the audit documents asked
for MCP and REST; this is that, at the size it deserves.

**What it is not.** It is not a second implementation. Every tool here is one
stage's `main(argv)`, called with the arguments the CLI would take, with stdout
captured and parsed back into JSON. There is no path through this file that can
do something the CLI cannot, and no stage that had to change to be reachable.
That is the whole design: a transport, not a layer.

    revayat-comic serve mcp                  # JSON-RPC over stdio
    revayat-comic serve http --port 8765     # loopback, token in a header

**The translation stage is still yours.** Exposing the stages does not make the
pipeline autonomous: step 5 is the reading model looking at the crop sheets, and
that is the model driving this server, not something the server can call. What
these tools give it is the other fifteen stages without a shell.

**Security, plainly.** Both transports run pipeline stages with this process's
file access, and arguments reach `argparse` directly — never a shell, so there
is nothing to inject into. The HTTP transport binds loopback only and requires a
token printed at startup, because a page in a browser can POST to `localhost`
and a server that writes files should not answer it.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pageir as ir  # noqa: E402  (must follow the sys.path bootstrap)

#: Advertised to a client at `initialize`. This is the revision this server was
#: written against; a client asking for another is answered anyway, because the
#: three methods used here have not changed across revisions.
PROTOCOL_VERSION = "2025-03-26"

SERVER_NAME = "revayat-comic"

#: Every stage, under the name the CLI uses. Kept as a tuple rather than read
#: back out of `revayat-comic.py` because that file is a script with a hyphen in
#: its name and cannot be imported; the drift is caught by a test that compares
#: the two lists.
STAGES = (
    "import", "detect", "mask", "crops", "worksheet", "ocr", "context",
    "translate", "glossary", "falint", "clean", "typeset", "qa", "export",
    # Not a step in the chain: it marks one box for erasure on every page,
    # before `mask` and `clean`. Listed here because a host with no shell needs
    # it as much as one with a shell — and the drift test says so.
    "watermark",
)

#: `doctor` lives in the CLI script rather than in a stage module, so it is
#: described here and dispatched separately below. It is the first call a client
#: should make: it says whether Persian will come out shaped and in the right
#: font, which is the difference between output that is correct and output that
#: merely exists.
DOCTOR = "doctor"

#: Held across the stdout capture in `run()`. `contextlib.redirect_stdout`
#: replaces the process-global `sys.stdout`, and the HTTP transport is a
#: `ThreadingHTTPServer` — a thread per request. Two stages capturing at once
#: each restore the other's stdout, so a caller receives someone else's report
#: and nothing raises. A wrong answer that parses is the worst shape a
#: transport can fail in, so stage runs are serialised here.
_STDOUT_LOCK = threading.Lock()


def _describe(stage: str) -> str:
    """One line about a stage, taken from the module that implements it.

    Read from the docstring rather than written out here, so a tool description
    cannot drift from what the stage actually does — the failure this project
    has hit three times in documentation and now tests for.
    """
    module = importlib.import_module(stage_module(stage))
    doc = (module.__doc__ or "").strip().splitlines()
    return doc[0].strip() if doc else f"the {stage} stage"


def stage_module(stage: str) -> str:
    """The module implementing a stage. `import` is a keyword; the rest match."""
    return {"import": "readers", "mask": "masks"}.get(stage, stage)


def tools() -> list[dict[str, Any]]:
    """Every stage as an MCP tool descriptor.

    One tool per stage rather than one `run` tool with a stage argument: a
    client's tool list is how a model learns what exists, and a single opaque
    tool teaches it nothing. The arguments stay a pass-through list, because the
    CLI's own `--help` is the authority on them and a hand-copied JSON schema
    for every stage would be wrong within a month.
    """
    listed = [{
        "name": f"revayat_{DOCTOR}",
        "description": "Check that Pillow, NumPy and OpenCV are present and "
                       "that this machine can shape and draw Persian. Run it "
                       "first; nothing else is worth running until it is ready.",
        "inputSchema": {"type": "object", "properties": {}},
    }]
    for stage in STAGES:
        listed.append({
            "name": f"revayat_{stage}",
            "description": _describe(stage),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command-line arguments for this stage, "
                                       "exactly as the CLI takes them, e.g. "
                                       "[\"--doc\", \"work/comic.json\"].",
                    },
                },
            },
        })
    return listed


def run(name: str, args: list[str] | None = None) -> dict[str, Any]:
    """Call one stage and return what it printed, as data.

    Stdout is captured for two reasons at once: it is how a stage returns its
    report, and on the stdio transport it is also the JSON-RPC channel — a stage
    printing into it would corrupt the stream mid-conversation.

    Failure is a value here, the way it is everywhere else in this project. A
    missing dependency, a bad path or a stage that exits non-zero all come back
    as a result with `ok: false` and the reason, so a client is never handed a
    traceback it cannot act on.
    """
    stage = name[len("revayat_"):] if name.startswith("revayat_") else name
    args = [str(a) for a in (args or [])]

    if stage == DOCTOR:
        return _doctor()
    if stage not in STAGES:
        return {"ok": False, "stage": stage,
                "error": f"unknown stage {stage!r}",
                "expected": [DOCTOR, *STAGES]}

    module = importlib.import_module(stage_module(stage))
    with _STDOUT_LOCK:
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                code = int(module.main(args) or 0)
        except SystemExit as exit_code:
            # argparse exits on a bad flag rather than raising. That is a normal
            # answer over a transport, not a reason to take the server down.
            code = int(exit_code.code or 0)
        except ir.MissingDependency as error:
            return {"ok": False, "stage": stage, "error": str(error),
                    "kind": "missing-dependency"}
        except (FileNotFoundError, ValueError) as error:
            return {"ok": False, "stage": stage,
                    "error": f"{type(error).__name__}: {error}"}

        text = captured.getvalue().strip()
    try:
        report = json.loads(text) if text else None
    except json.JSONDecodeError:
        report = {"output": text}
    return {"ok": code == 0, "stage": stage, "exit": code, "report": report}


def _doctor() -> dict[str, Any]:
    """`doctor` lives in the CLI script, which has a hyphen and cannot be
    imported by name. Loading it by path keeps one implementation rather than a
    copy that drifts."""
    import importlib.util

    path = Path(__file__).resolve().parent / "revayat-comic.py"
    spec = importlib.util.spec_from_file_location("revayat_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.doctor()
    return {"ok": bool(report.get("ready")), "stage": DOCTOR, "exit": 0,
            "report": report}


# --------------------------------------------------------------------------- #
# MCP, over stdio
# --------------------------------------------------------------------------- #

def _wire(payload: dict[str, Any]) -> str:
    """One JSON-RPC message as one line.

    Not `ir.dumps`: that indents for a human reading a stage report, and the
    stdio transport is newline-delimited, so an indented message arrives as a
    dozen malformed ones. The readable form still appears inside a tool result,
    where it is a string and its newlines are escaped.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, at most one out.

    `None` means the message was a notification — it has no `id` and the
    protocol forbids answering it. Getting that wrong is the usual reason a
    client hangs at startup waiting for a handshake that already finished.
    """
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if request_id is None:
        return None

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": ir.TOOL_VERSION},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": tools()})
    if method == "tools/call":
        name = params.get("name") or ""
        outcome = run(name, (params.get("arguments") or {}).get("args"))
        return _result(request_id, {
            "content": [{"type": "text", "text": ir.dumps(outcome)}],
            "isError": not outcome.get("ok", False),
        })
    return _error(request_id, -32601, f"unknown method {method!r}")


def serve_mcp(stream_in=None, stream_out=None) -> int:
    """Read newline-delimited JSON-RPC until the client closes the pipe."""
    stream_in = sys.stdin if stream_in is None else stream_in
    stream_out = sys.stdout if stream_out is None else stream_out

    for line in stream_in:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = _error(None, -32700, "invalid JSON")
        else:
            reply = handle(message)
        if reply is not None:
            stream_out.write(_wire(reply) + "\n")
            stream_out.flush()
    return 0


# --------------------------------------------------------------------------- #
# HTTP, on loopback
# --------------------------------------------------------------------------- #

def _handler_class(token: str):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = f"{SERVER_NAME}/{ir.TOOL_VERSION}"

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = ir.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self) -> bool:
            # A page in a browser can POST to localhost. It cannot read a token
            # printed in this terminal, and cross-origin rules stop it setting
            # this header at all without a preflight this server never answers.
            return secrets.compare_digest(
                self.headers.get("X-Revayat-Token", ""), token)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
            if not self._authorised():
                return self._send(401, {"ok": False, "error": "bad token"})
            if self.path.rstrip("/") == "/tools":
                return self._send(200, {"tools": tools()})
            self._send(404, {"ok": False, "error": "GET /tools"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorised():
                return self._send(401, {"ok": False, "error": "bad token"})
            if not self.path.startswith("/tools/"):
                return self._send(404, {"ok": False,
                                        "error": "POST /tools/<name>"})
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return self._send(400, {"ok": False, "error": "invalid JSON"})

            outcome = run(self.path[len("/tools/"):], body.get("args"))
            self._send(200 if outcome.get("ok") else 400, outcome)

        def log_message(self, *_args) -> None:
            """Silence the default access log: it prints to stderr on every
            request and says nothing a stage report does not."""

    return Handler


def serve_http(port: int = 8765, token: str | None = None,
               host: str = "127.0.0.1", announce=None):
    """A loopback HTTP server, returned running on its own thread.

    Loopback is not negotiable here. This answers requests by running pipeline
    stages that write files, and the moment it is reachable off the machine that
    is a remote file-writing service with a header for a password.
    """
    from http.server import ThreadingHTTPServer

    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(
            f"refusing to bind {host!r}: this server runs pipeline stages that "
            f"write files, and it is only safe on loopback"
        )
    token = token or secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer((host, port), _handler_class(token))
    if announce is not None:
        announce({"url": f"http://{host}:{httpd.server_address[1]}",
                  "token": token,
                  "tools": f"http://{host}:{httpd.server_address[1]}/tools"})
    # Serving on a thread rather than in the caller, so a test can drive the
    # server it just started and `main` has something to interrupt.
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, token


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Expose the pipeline stages over MCP or loopback HTTP. "
                    "The CLI remains the recommended path; this is for a host "
                    "that cannot run one.")
    sub = parser.add_subparsers(dest="transport", required=True)
    sub.add_parser("mcp", help="JSON-RPC 2.0 over stdio")
    http = sub.add_parser("http", help="loopback HTTP, token in a header")
    http.add_argument("--port", type=int, default=8765,
                      help="0 picks a free one and prints it")
    http.add_argument("--token", default=None,
                      help="use this token instead of a generated one")
    args = parser.parse_args(argv)

    if args.transport == "mcp":
        return serve_mcp()

    # Everything the server says goes to stderr, so a caller can pipe stdout.
    httpd, _ = serve_http(port=args.port, token=args.token,
                          announce=lambda where: print(ir.dumps(where),
                                                       file=sys.stderr))
    try:
        # The server is already running on its own thread; this just keeps the
        # process alive and gives Ctrl-C somewhere to land.
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
