"""Timeout cleanup at the native wrapper/descendant boundary."""
import json
import os
import subprocess
import sys

import pytest

from process_support import run_process


def test_idle_timeout_terminates_wrapper_and_descendant(tmp_path):
    marker = tmp_path / "child.pid"
    child = """
import ctypes, json, os, pathlib, sys, threading
birth = None
if os.name == 'nt':
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
    created, exited, system, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
    assert kernel.GetProcessTimes(kernel.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user))
    birth = (created.dwHighDateTime << 32) | created.dwLowDateTime
pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid': os.getpid(), 'birth': birth}), encoding='utf-8')
print('child ready', flush=True)
threading.Event().wait(30)
"""
    parent = "import subprocess,sys,threading; subprocess.Popen([sys.executable,'-u','-c',sys.argv[1],sys.argv[2]]); threading.Event().wait(30)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-u", "-c", parent, child, str(marker)], timeout=15, idle=3)
    assert marker.is_file(), "the actual descendant must start before timeout"
    identity = json.loads(marker.read_text(encoding="utf-8"))
    pid = identity["pid"]
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        handle = kernel.OpenProcess(0x101000, False, pid)
        if handle:
            try:
                created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
                assert kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                               ctypes.byref(system), ctypes.byref(user))
                birth = (created.dwHighDateTime << 32) | created.dwLowDateTime
                # A reused PID is not the child this test owned; never kill it.
                assert birth != identity["birth"] or kernel.WaitForSingleObject(handle, 0) == 0
            finally:
                kernel.CloseHandle(handle)
        else:
            assert ctypes.get_last_error() == 87
    else:
        status = run_process(["ps", "-o", "stat=", "-p", str(pid)], timeout=5, idle=3)
        assert not status.stdout.strip() or status.stdout.strip().startswith("Z")


def test_cleanup_error_still_closes_job_and_reaps_root(monkeypatch):
    from types import SimpleNamespace
    import process_support
    events = []
    class Job:
        def assign(self, process):
            events.append("assigned")
        def stop(self):
            raise OSError("controlled membership failure")
        def close(self):
            events.append("closed")
    class Process:
        returncode = 0
        def communicate(self, *args, **kwargs):
            events.append("reaped")
            return b"", b""
        def poll(self):
            return 0
    monkeypatch.setattr(process_support, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(process_support, "WindowsJob", Job)
    monkeypatch.setattr(process_support.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(process_support.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(OSError, match="controlled membership failure"):
        run_process(["unused controlled command"])
    assert events == ["assigned", "reaped", "closed", "reaped"]


def test_normal_child_returns_utf8_output_and_exit_code():
    result = run_process([sys.executable, "-c", "print('فارسی'); raise SystemExit(7)"], timeout=10, idle=5,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 7 and result.stdout.strip() == "فارسی"
