"""Timed-out provider diagnostics cannot become a later result or wire frame."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sys
import textwrap

import pytest

import server
from process_support import run_process

LOG = logging.getLogger(__name__)
MARKER = "SYNTHETIC_PROVIDER_OUTPUT_DO_NOT_DISCLOSE"


@pytest.mark.parametrize("mode", ["between_requests", "during_next_stage"])
def test_timed_out_provider_output_cannot_escape_over_real_stdio(tmp_path, mode):
    child = tmp_path / "noisy_provider_server.py"
    child.write_text(textwrap.dedent(r'''
        from datetime import datetime, timezone
        import json
        import logging
        from pathlib import Path
        import sys
        import threading

        sys.path.insert(0, sys.argv[1])
        import providers
        import server
        import translate

        logging.basicConfig(level=logging.DEBUG,
                            format="%(asctime)s [%(levelname)s] %(message)s")
        log = logging.getLogger("test.noisy_provider")
        mode = sys.argv[2]
        marker = "SYNTHETIC_PROVIDER_OUTPUT_DO_NOT_DISCLOSE"
        release, finished = threading.Event(), threading.Event()

        class NoisyProvider:
            def translate(self, *_args):
                if not release.wait(5):
                    log.error("Synthetic provider was never released")
                    raise RuntimeError("worker release deadline")
                print(marker, flush=True)
                print(marker, file=sys.stderr, flush=True)
                finished.set()
                return "unused late answer"

        def release_provider():
            release.set()
            if not finished.wait(5):
                log.error("Synthetic provider failed to finish")
                raise RuntimeError("worker completion deadline")

        def stage(args):
            if args == ["timeout"]:
                result = providers.call(NoisyProvider(), "translation", "source", {},
                                        timeout=0.01)
                assert result.status == "timeout"
                log.warning("Synthetic provider timeout exercised")
                print(json.dumps({"status": result.status}))
                return 1
            assert args == ["healthy"]
            release_provider()
            print(json.dumps({"answer": "healthy"}))
            return 0

        class Incoming:
            def __init__(self):
                self.count = 0

            def readline(self, limit):
                self.count += 1
                if self.count == 2:
                    print(datetime.now(timezone.utc).isoformat() +
                          " [DEBUG] Service diagnostic", file=sys.stderr, flush=True)
                if self.count == 2 and mode == "between_requests":
                    release_provider()
                return sys.stdin.buffer.readline(limit)

        log.info("Starting bounded noisy-provider conversation")
        log.debug("Scenario: %s", mode)
        translate.main = stage
        try:
            code = server.serve_mcp(Incoming(), sys.stdout)
        finally:
            release_provider()
        log.info("Conversation finished with exit %s", code)
        raise SystemExit(code)
    '''), encoding="utf-8")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "revayat_translate", "arguments": {"args": ["timeout"]}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "revayat_translate", "arguments": {"args": ["healthy"]}}},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    raw = "".join(json.dumps(request) + "\n" for request in requests).encode("utf-8")
    result = run_process([sys.executable, str(child), str(Path(server.__file__).parent), mode],
                         cwd=tmp_path, input=raw, timeout=15, idle=10,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8:strict"})

    assert result.returncode == 0, result.stderr
    assert MARKER not in result.stdout and MARKER not in result.stderr
    assert "[DEBUG] Service diagnostic" in result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3]
    failed = json.loads(responses[0]["result"]["content"][0]["text"])
    assert failed["report"] == {"status": "timeout"}
    healthy = json.loads(responses[1]["result"]["content"][0]["text"])
    assert healthy["ok"] and healthy["report"] == {"answer": "healthy"}
    assert responses[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}
    LOG.info("Late provider output stayed private in scenario %s", mode)
