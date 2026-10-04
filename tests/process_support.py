"""Bound native test children, including wrapper descendants, without windows."""
from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from threading import Event


class WindowsJob:
    def __init__(self):
        from ctypes import wintypes as w
        class Limits(ctypes.Structure):
            _fields_ = [("user", ctypes.c_longlong), ("job", ctypes.c_longlong),
                        ("flags", w.DWORD), ("min", ctypes.c_size_t), ("max", ctypes.c_size_t),
                        ("active", w.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", ctypes.c_ulonglong * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_longlong * 4), ("faults", w.DWORD),
                        ("total", w.DWORD), ("active", w.DWORD), ("terminated", w.DWORD)]
        self.accounting = Accounting
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway permission.
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.api.CloseHandle(self.handle)
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def stop(self):
        if not self.api.TerminateJobObject(self.handle, 124):
            raise ctypes.WinError(ctypes.get_last_error())

    def active(self):
        information = self.accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(information),
                                                   ctypes.sizeof(information), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return information.active

    def close(self):
        self.api.CloseHandle(self.handle)


def run_process(command, *, env=None, cwd=None, timeout=30, idle=20, check=False):
    """A gated child joins its ownership group before it can launch the command."""
    gate = "import json,subprocess,sys; sys.stdin.buffer.read(1); sys.exit(subprocess.call(json.loads(sys.argv[1]), stdin=subprocess.DEVNULL))"
    job = WindowsJob() if os.name == "nt" else None
    process = None
    started = progress = time.monotonic()
    size = 0
    try:
        # A Windows venv redirector can spawn its interpreter before job assignment.
        # The stdlib-only gate must be the real interpreter, then launch the venv
        # command only after it belongs to our non-breakaway ownership job.
        bootstrap = getattr(sys, "_base_executable", sys.executable) if job else sys.executable
        process = subprocess.Popen([bootstrap, "-B", "-c", gate, json.dumps(command)],
                                   env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=job is None,
                                   creationflags=subprocess.CREATE_NO_WINDOW if job else 0)
        if job:
            job.assign(process)
        first = True
        while True:
            remaining = min(timeout - (time.monotonic() - started), idle - (time.monotonic() - progress))
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(b"1" if first else None, timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired as error:
                observed = len(error.output or b"") + len(error.stderr or b"")
                if observed > size:
                    size, progress = observed, time.monotonic()
                first = False
        result = subprocess.CompletedProcess(command, process.returncode,
                                             stdout.decode("utf-8"), stderr.decode("utf-8"))
        if check:
            result.check_returncode()
        return result
    finally:
        if process:
            if job:
                job.stop()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        if job:
            try:
                deadline = time.monotonic() + 5
                while job.active():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("owned Windows child processes survived termination")
                    # Job accounting, not root liveness, proves descendant cleanup.
                    Event().wait(min(0.02, max(0, deadline - time.monotonic())))
            finally:
                job.close()
