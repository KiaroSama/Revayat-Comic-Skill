"""Shared fixtures.

Fixtures are *generated*, never committed as binaries: the suite stays fast, the
repository stays small, and no third-party artwork is vendored into a GPL tree.

## Why the pipeline stages are built once and then copied

Every stage below — import, detect, mask, clean, typeset — is real image
processing, and it used to run again for every test that asked for it. Measured
on this suite: about **3 seconds of `setup` per test**, and `--durations` showed
ten of the twelve slowest entries were setup rather than any test's own work.
That is the same chapter being rebuilt a hundred and fifty times to produce a
hundred and fifty identical copies of it.

So each stage is built **once per session** into a template directory, and a
test that asks for it gets a `copytree` of that template into its own `tmp_path`.
Isolation is unchanged — every test still owns a private, freely mutable
directory, and nothing reaches back into the template — but the cost per test
falls from seconds of OpenCV and Pillow work to milliseconds of file copying.

The layout a test sees is identical to before: `tmp_path` *is* the working
folder, and the fixture returns `tmp_path / "comic.json"`.

Two rules for anyone adding a fixture here:

- **Expensive and read-mostly → session scope plus a copy.** Never a
  session-scoped object that tests mutate; the copy is what keeps them honest.
- **Ask for the latest stage you actually need.** Requesting `finished` when
  `detected` would do pays for `clean` and `typeset` you never look at.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "revayat-comic" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests_support import manga_page, page_bytes, write_cbz  # noqa: E402

import adapters  # noqa: E402 - the scripts directory is on the path above


# --------------------------------------------------------------------------- #
# A real MCP client: a subprocess, two pipes, no shared memory
#
# In conftest because two suites need it. Driving `handle()` in-process tests
# the protocol and proves nothing about the transport: pipe buffering, the
# child's stdout encoding, whether the process exits when the pipe closes.
# --------------------------------------------------------------------------- #

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

    def raw(self, line: str):
        """One line exactly as written, so a test can send what no client
        library would let it send."""
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        answer = self.process.stdout.readline()
        assert answer, "the server closed the pipe without answering"
        return json.loads(answer)

    def notify(self, method, **params):
        self.process.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        self.process.stdin.flush()

    def close(self, timeout=20):
        self.process.stdin.close()
        return self.process.wait(timeout=timeout)


@pytest.fixture
def stdio_client():
    import server

    cli = Path(server.__file__).resolve().parent / "revayat-comic.py"
    client = _StdioClient([sys.executable, str(cli), "serve", "mcp"])
    try:
        yield client
    finally:
        if client.process.poll() is None:
            client.process.kill()
            client.process.wait(timeout=10)


# --------------------------------------------------------------------------- #
# A loopback OpenAI-compatible endpoint
#
# Here rather than in one suite because two need it: the adapter boundary, and
# what a recorded answer is an answer TO. No key and no network - the server is
# a `ThreadingHTTPServer` on a free port of 127.0.0.1, and every request it
# receives is kept so a test can assert what was actually asked.
# --------------------------------------------------------------------------- #

def _parse_multipart(content_type: str, body: bytes) -> dict[str, bytes]:
    """The parts of a `multipart/form-data` body, by field name.

    Hand-rolled on purpose: `email`'s parser re-encodes a binary part, and the
    thing under test here is whether a PNG arrived intact.
    """
    boundary = content_type.split("boundary=")[1].strip().encode()
    parts: dict[str, bytes] = {}
    for chunk in body.split(b"--" + boundary):
        if not chunk.strip(b"-\r\n"):
            continue  # the preamble and the closing `--`
        head, _, payload = chunk.partition(b"\r\n\r\n")
        name = head.decode("utf-8", "replace").split('name="')[1].split('"')[0]
        parts[name] = payload[:-2] if payload.endswith(b"\r\n") else payload
    return parts


class _Endpoint:
    """An OpenAI-compatible server that answers however a test needs it to."""

    def __init__(self):
        self.requests: list[dict] = []
        self.chat = {"choices": [{"message": {"content": "بس کن"}}]}
        self.image: dict | None = None
        self.status = 200

    def serve(self):
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                kind = self.headers.get("Content-Type", "")
                if self.path.endswith("images/edits"):
                    # `images/edits` is multipart, and this server now refuses
                    # anything else. It used to read JSON from every path, and
                    # that is the whole reason a JSON image request looked like
                    # it worked for as long as it did: nothing but this handler
                    # had ever accepted one.
                    if not kind.startswith("multipart/form-data"):
                        endpoint.requests.append(
                            {"path": self.path, "refused": kind})
                        self.send_response(400)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    payload = _parse_multipart(kind, raw)
                else:
                    payload = json.loads(raw.decode("utf-8"))
                endpoint.requests.append({
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "content_type": kind,
                    "payload": payload,
                })
                if endpoint.status != 200:
                    self.send_response(endpoint.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                answer = (endpoint.image if self.path.endswith("images/edits")
                          else endpoint.chat)
                body = json.dumps(answer).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                """No access log: it goes to stderr on every request."""

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"


@pytest.fixture
def endpoint(monkeypatch):
    server = _Endpoint()
    base = server.serve()
    monkeypatch.setenv(adapters.API_BASE, base)
    monkeypatch.setenv(adapters.TRANSLATION_MODEL, "a-model")
    monkeypatch.setenv(adapters.IMAGE_MODEL, "an-image-model")
    monkeypatch.delenv(adapters.API_KEY, raising=False)
    try:
        yield server
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()


def _clone(template: Path, destination: Path) -> Path:
    """A private copy of a prepared working folder, and its document."""
    shutil.copytree(template, destination, dirs_exist_ok=True)
    return destination / "comic.json"


@pytest.fixture(scope="session")
def sample_cbz(tmp_path_factory) -> Path:
    """Three pages: light balloons, dark balloons, light again, each with an SFX."""
    return write_cbz(tmp_path_factory.mktemp("cbz") / "chapter.cbz", pages=3)


@pytest.fixture(scope="session")
def sample_page(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("page") / "p.png"
    path.write_bytes(page_bytes(manga_page()))
    return path


# --------------------------------------------------------------------------- #
# The stage templates. Built once; never handed to a test directly.
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def _stage_imported(sample_cbz, tmp_path_factory) -> Path:
    import readers

    work = tmp_path_factory.mktemp("stage-imported")
    readers.import_source(sample_cbz, work, source_language="ja", direction="rtl")
    return work


@pytest.fixture(scope="session")
def _stage_detected(_stage_imported, tmp_path_factory) -> Path:
    import detect
    import masks

    work = tmp_path_factory.mktemp("stage-detected")
    doc_path = _clone(_stage_imported, work)
    detect.detect_document(doc_path)
    masks.build_document(doc_path)
    return work


@pytest.fixture(scope="session")
def _stage_translated(_stage_detected, tmp_path_factory) -> Path:
    import pageir as ir

    work = tmp_path_factory.mktemp("stage-translated")
    doc_path = _clone(_stage_detected, work)

    doc = ir.load_doc(doc_path)
    lines = [
        "بس کن! این‌جا چه خبر است؟",
        "هیچ‌کس نمی‌داند او کجا رفته.",
        "دوباره برگشتی؟",
    ]
    sources = ["やめろ！", "誰も知らない。", "また来たのか"]
    for index, (_, region) in enumerate(ir.iter_regions(doc)):
        region["source_text"] = sources[index % len(sources)]
        region["target_text"] = lines[index % len(lines)]
        region["speaker"] = "هاروکا" if index % 2 == 0 else "کنجی"
        region["locked"] = True
    ir.save_doc(doc, doc_path)
    return work


@pytest.fixture(scope="session")
def _stage_finished(_stage_translated, tmp_path_factory) -> Path:
    import clean
    import typeset

    work = tmp_path_factory.mktemp("stage-finished")
    doc_path = _clone(_stage_translated, work)
    clean.clean_document(doc_path)
    typeset.typeset_document(doc_path)
    return work


# --------------------------------------------------------------------------- #
# What tests ask for: a private copy of one of those stages.
# --------------------------------------------------------------------------- #

@pytest.fixture
def imported(_stage_imported, tmp_path) -> Path:
    """A working folder with `import` already run. Returns the document path."""
    return _clone(_stage_imported, tmp_path)


@pytest.fixture
def detected(_stage_detected, tmp_path) -> Path:
    """…and `detect` and `mask`."""
    return _clone(_stage_detected, tmp_path)


@pytest.fixture
def translated(_stage_translated, tmp_path) -> Path:
    """Every region filled in with plausible Persian, merged into the document."""
    return _clone(_stage_translated, tmp_path)


@pytest.fixture
def finished(_stage_finished, tmp_path) -> Path:
    """A document taken all the way through `clean` and `typeset`.

    Shared because three suites need a page that has actually been rendered —
    the QA gate, the visual-QA pass and the provider tests all assert against
    final pixels, and a local copy in each would drift.
    """
    return _clone(_stage_finished, tmp_path)
