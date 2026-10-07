"""Bound native test children, including wrapper descendants, without windows."""
from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import time


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
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "IsProcessInJob": ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
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
        from ctypes import wintypes as w
        # Accounting may reach zero before the kernel process object is signaled.
        # Pin current members before termination, then wait on those exact handles.
        class Members(ctypes.Structure):
            _fields_ = [("assigned", w.DWORD), ("listed", w.DWORD),
                        ("pids", ctypes.c_size_t * 128)]
        members = Members()
        if not self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(members),
                                                   ctypes.sizeof(members), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if members.listed != members.assigned:
            raise RuntimeError("owned Windows process membership exceeded the bounded buffer")
        handles = []
        try:
            for pid in members.pids[:members.listed]:
                handle = self.api.OpenProcess(0x101000, False, pid)
                if not handle:
                    if ctypes.get_last_error() == 87:
                        continue
                    raise ctypes.WinError(ctypes.get_last_error())
                owned = w.BOOL()
                if not self.api.IsProcessInJob(handle, self.handle, ctypes.byref(owned)):
                    self.api.CloseHandle(handle)
                    raise ctypes.WinError(ctypes.get_last_error())
                if owned.value:
                    handles.append(handle)
                else:
                    self.api.CloseHandle(handle)
            if not self.api.TerminateJobObject(self.handle, 124):
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + 5
            for handle in handles:
                if self.api.WaitForSingleObject(handle, max(0, int((deadline - time.monotonic()) * 1000))) != 0:
                    raise RuntimeError("owned Windows process did not finish termination")
        finally:
            for handle in handles:
                self.api.CloseHandle(handle)

    def active(self):
        information = self.accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(information),
                                                   ctypes.sizeof(information), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return information.active

    def close(self):
        self.api.CloseHandle(self.handle)


def start_owned(command, *, env=None, cwd=None, interactive=False):
    """Return an assigned, unreleased gate; no target runs before ownership."""
    gate = ("import json,os,subprocess,sys; os.read(sys.stdin.fileno(),1); "
            "sys.exit(subprocess.call(json.loads(sys.argv[1]), stdin="
            + ("sys.stdin" if interactive else "subprocess.DEVNULL") + "))")
    job = WindowsJob() if os.name == "nt" else None
    process = None
    try:
        # A Windows venv redirector can spawn before assignment: gate with its
        # REAL base interpreter, then release the venv command inside the job.
        bootstrap = getattr(sys, "_base_executable", sys.executable) if job else sys.executable
        process = subprocess.Popen([bootstrap, "-B", "-c", gate, json.dumps(command)],
                                   env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=job is None,
                                   bufsize=0 if interactive else -1,
                                   creationflags=subprocess.CREATE_NO_WINDOW if job else 0)
        if job:
            job.assign(process)
        return process, job
    except BaseException:
        stop_owned(process, job)
        raise


def stop_owned(process, job, *, drain=True):
    """Stop exact owned members; closure/reaping survive membership errors."""
    try:
        if process:
            try:
                if job:
                    job.stop()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # Darwin returns EPERM for a group containing only zombies.
                        # Suppress only after a bounded exact-group liveness check;
                        # a live member or failed observation remains a real error.
                        if sys.platform != "darwin":
                            raise
                        status = subprocess.run(["/bin/ps", "-axo", "pgid=,stat="],
                                                stdin=subprocess.DEVNULL,
                                                capture_output=True, text=True,
                                                encoding="utf-8", timeout=5, check=True)
                        members = [line.split() for line in status.stdout.splitlines()
                                   if line.split() and line.split()[0] == str(process.pid)]
                        if any(len(member) != 2 or not member[1].startswith("Z")
                               for member in members):
                            raise
            finally:
                if job:
                    job.close()
                    job = None
                if process.poll() is None:
                    process.kill()
                if drain:
                    process.communicate(timeout=5)
                else:
                    process.wait(timeout=5)
    finally:
        if job:
            job.close()


def run_process(command, *, env=None, cwd=None, timeout=30, idle=20, check=False,
                input=None, text=True):
    """One-shot owned wall/idle execution, optionally with raw byte input."""
    process = job = None
    started = progress = time.monotonic()
    size = 0
    try:
        process, job = start_owned(command, env=env, cwd=cwd, interactive=input is not None)
        first = True
        while True:
            remaining = min(timeout - (time.monotonic() - started), idle - (time.monotonic() - progress))
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(b"1" + (input or b"") if first else None,
                                                     timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired as error:
                observed = len(error.output or b"") + len(error.stderr or b"")
                if observed > size:
                    size, progress = observed, time.monotonic()
                first = False
        result = subprocess.CompletedProcess(command, process.returncode,
                                             stdout.decode("utf-8") if text else stdout,
                                             stderr.decode("utf-8") if text else stderr)
        if check:
            result.check_returncode()
        return result
    finally:
        stop_owned(process, job)
