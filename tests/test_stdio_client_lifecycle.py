"""Owned live-pipe lifecycle controls; tiny real children, no pipeline setup."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from stdio_client import StdioClient


def child(code, **kwargs):
    return StdioClient([sys.executable, "-u", "-c", code], **kwargs)


def assert_closed(client):
    assert client.process.poll() is not None
    assert all(pipe.closed for pipe in (client.process.stdin, client.process.stdout,
                                       client.process.stderr))
    assert not any(thread.is_alive() for thread in client.threads)


def test_silent_reply_has_a_deadline_and_closes_every_pipe():
    client = child("import sys; sys.stdin.buffer.readline(); print('{}', flush=True); "
                   "sys.stdin.buffer.readline(); sys.stdin.buffer.read()")
    assert client.request("ready") == {}
    client.idle = 0.3
    with pytest.raises(subprocess.TimeoutExpired):
        client.request("ping")
    assert_closed(client)


def test_stderr_pressure_does_not_block_reply_and_capture_is_capped(tmp_path):
    client = child("import sys; sys.stdin.buffer.readline(); "
                   "sys.stderr.buffer.write(b'x' * 262144); sys.stderr.flush(); "
                   "print('{\"result\":\"سلام😀\"}', flush=True)",
                   cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        assert client.request("ping") == {"result": "سلام😀"}
        assert client.close() == 0
        assert 0 < len(client.stderr) <= client.capture_limit
    finally:
        client.close()
    assert_closed(client)


@pytest.mark.parametrize("payload,exception", [(b"", EOFError),
                                               (b"\xff\n", UnicodeDecodeError),
                                               (b"not JSON\n", ValueError),
                                               (b"{}", EOFError)])
def test_eof_and_malformed_replies_close_the_owned_child(payload, exception):
    client = child(f"import sys; sys.stdin.buffer.readline(); sys.stdout.buffer.write({payload!r}); sys.stdout.flush()")
    with pytest.raises(exception):
        client.request("ping")
    assert_closed(client)


def test_a_live_unterminated_frame_is_bounded():
    client = child("import sys; sys.stdin.buffer.readline(); print('{}', flush=True); "
                   "sys.stdin.buffer.readline(); sys.stdout.write('{}'); "
                   "sys.stdout.flush(); sys.stdin.buffer.read()")
    assert client.request("ready") == {}
    client.idle = 0.3
    with pytest.raises(subprocess.TimeoutExpired):
        client.raw("ping")
    assert_closed(client)


def test_blocked_write_is_bounded():
    client = child("import sys; sys.stdin.buffer.readline(); print('{}', flush=True); "
                   "import threading; threading.Event().wait(30)")
    assert client.request("ready") == {}
    client.idle = 0.3
    with pytest.raises(subprocess.TimeoutExpired):
        client.raw("x" * 1048576)
    assert_closed(client)


def test_close_of_uncooperative_child_is_bounded():
    client = child("import sys; sys.stdin.buffer.readline(); print('{}', flush=True); "
                   "import threading; threading.Event().wait(30)")
    assert client.request("ping") == {}
    with pytest.raises(subprocess.TimeoutExpired):
        client.close(timeout=0.3)
    assert_closed(client)


def test_notifications_and_successive_replies_preserve_framing():
    client = child("import json,sys\nfor line in sys.stdin:\n "
                   "r=json.loads(line)\n if 'id' in r: print(json.dumps({'id':r['id']}), flush=True)")
    try:
        client.notify("initialized")
        assert client.request("ping") == {"id": 1}
        assert client.request("ping") == {"id": 2}
        assert client.close() == 0
    finally:
        client.close()
    assert_closed(client)


def test_nonzero_exit_is_not_replaced_by_cleanup_status():
    client = child("import sys; sys.stdin.buffer.readline(); print('{}', flush=True); "
                   "sys.stdin.buffer.read(); raise SystemExit(7)")
    assert client.request("ping") == {}
    assert client.close() == 7
    assert_closed(client)


def test_cancellation_still_closes_every_owned_resource(monkeypatch):
    client = child("import sys; sys.stdin.buffer.readline(); sys.stdin.buffer.read()")
    def cancel(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(client, "_line", cancel)
    with pytest.raises(KeyboardInterrupt):
        client.request("ping")
    assert_closed(client)


def test_oversize_response_is_refused_without_unbounded_capture():
    client = child("import sys; sys.stdin.buffer.readline(); "
                   "sys.stdout.buffer.write(b'x' * 65536); sys.stdout.flush(); sys.stdin.buffer.read()")
    client.frame_limit = 8192
    with pytest.raises(ValueError, match="bounded frame"):
        client.request("ping")
    assert_closed(client)


def test_close_terminates_a_real_descendant(tmp_path):
    # The ready reply is emitted by the descendant itself, not a timing sleep.
    # Pin its Windows handle BEFORE close; never treat an accounting-zero as exit.
    client = child("import subprocess,sys\nsubprocess.Popen([sys.executable,'-u','-c',"
                   "\"import os,sys; print('{\\\"pid\\\":%d}' % os.getpid(), flush=True); sys.stdin.buffer.read()\"],"
                   "stdin=subprocess.PIPE)\nsys.stdin.buffer.readline()\nsys.stdin.buffer.read()",
                   cwd=tmp_path)
    handle = None
    try:
        pid = client.request("ping")["pid"]
        if os.name == "nt":
            handle = client.job.api.OpenProcess(0x101000, False, pid)
            assert handle, "pin the actual live descendant before terminating it"
            api = client.job.api
        else:
            from process_support import run_process
            birth = run_process(["ps", "-o", "lstart=", "-p", str(pid)], timeout=5, idle=3).stdout.strip()
            assert birth, "record the actual live descendant identity before close"
        assert client.close() == 0
        if handle:
            assert api.WaitForSingleObject(handle, 0) == 0
        else:
            status = run_process(["ps", "-o", "stat=", "-o", "lstart=", "-p", str(pid)], timeout=5, idle=3)
            current = status.stdout.strip()
            assert not current or not current.endswith(birth) or current.startswith("Z")
    finally:
        client.close()
        if handle:
            api.CloseHandle(handle)
    assert_closed(client)
