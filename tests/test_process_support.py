"""Timeout cleanup at the native wrapper/descendant boundary."""
import os
import subprocess
import sys

import pytest

from process_support import run_process


def test_idle_timeout_terminates_wrapper_and_descendant(tmp_path):
    marker = tmp_path / "child.pid"
    child = "import os,pathlib,sys,threading; pathlib.Path(sys.argv[1]).write_text(str(os.getpid()),encoding='utf-8'); print('child ready',flush=True); threading.Event().wait(30)"
    parent = "import subprocess,sys,threading; subprocess.Popen([sys.executable,'-u','-c',sys.argv[1],sys.argv[2]]); threading.Event().wait(30)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-u", "-c", parent, child, str(marker)], timeout=15, idle=3)
    assert marker.is_file(), "the actual descendant must start before timeout"
    pid = int(marker.read_text(encoding="utf-8"))
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle, 0) == 0
            finally:
                kernel.CloseHandle(handle)
        else:
            assert ctypes.get_last_error() == 87
    else:
        status = run_process(["ps", "-o", "stat=", "-p", str(pid)], timeout=5, idle=3)
        assert not status.stdout.strip() or status.stdout.strip().startswith("Z")


def test_normal_child_returns_utf8_output_and_exit_code():
    result = run_process([sys.executable, "-c", "print('فارسی'); raise SystemExit(7)"], timeout=10, idle=5,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 7 and result.stdout.strip() == "فارسی"
