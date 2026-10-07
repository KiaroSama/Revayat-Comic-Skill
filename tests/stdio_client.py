"""Finite JSON-lines test client, sharing the native gated process owner."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

from process_support import start_owned, stop_owned


class StdioClient:
    # Existing real three-page CLI stages complete in seconds. Allow startup and
    # slower CI runners 30s wall/20s idle; cleanup adds at most 5s per owner/join.
    capture_limit = 65536
    frame_limit = 4 << 20

    def __init__(self, argv, *, env=None, cwd=None, timeout=30, idle=20):
        if timeout <= 0 or idle <= 0:
            raise ValueError("client wall and idle limits must be positive")
        self.argv, self.timeout, self.idle = argv, timeout, idle
        self.process, self.job = start_owned(argv, env=env, cwd=cwd, interactive=True)
        self._id = 0
        self._closed = False
        self._progress = time.monotonic()
        self._stdout = queue.Queue(maxsize=1024)
        self._writes = queue.Queue(maxsize=1)
        self._buffer = bytearray()
        self._stderr = bytearray()
        self._failure = None
        self.threads = [threading.Thread(target=self._read, args=(self.process.stdout, True)),
                        threading.Thread(target=self._read, args=(self.process.stderr, False)),
                        threading.Thread(target=self._write)]
        try:
            for thread in self.threads:
                thread.start()
            self._send(b"1", time.monotonic() + timeout)
        except BaseException:
            self._dispose()
            raise

    @property
    def stderr(self):
        return bytes(self._stderr)

    def _read(self, pipe, stdout):
        try:
            while True:
                chunk = os.read(pipe.fileno(), 4096)
                self._progress = time.monotonic()
                if stdout:
                    try:
                        self._stdout.put_nowait(chunk)
                    except queue.Full:
                        self._failure = ValueError("server stdout exceeded the bounded queue")
                elif chunk:
                    self._stderr.extend(chunk)
                    del self._stderr[:-self.capture_limit]
                if not chunk:
                    break
        except (OSError, ValueError) as error:
            if not self._closed:
                self._failure = error

    def _write(self):
        while not self._closed:
            try:
                action = self._writes.get(timeout=0.1)
            except queue.Empty:
                continue
            payload, done, errors = action
            try:
                if payload is None:
                    self.process.stdin.close()
                else:
                    view = memoryview(payload)
                    while view:
                        size = os.write(self.process.stdin.fileno(), view)
                        if size <= 0:
                            raise BrokenPipeError("server stdin accepted no bytes")
                        view = view[size:]
                        self._progress = time.monotonic()
            except (OSError, ValueError) as error:
                errors.append(error)
            finally:
                done.set()

    def _remaining(self, deadline):
        if self._failure:
            raise self._failure
        remaining = min(deadline - time.monotonic(),
                        self.idle - (time.monotonic() - self._progress))
        if remaining <= 0:
            raise subprocess.TimeoutExpired(self.argv, self.timeout,
                                            output=bytes(self._buffer), stderr=self.stderr)
        return min(remaining, 0.1)

    def _send(self, payload, deadline):
        done, errors = threading.Event(), []
        self._writes.put_nowait((payload, done, errors))
        while not done.wait(self._remaining(deadline)):
            pass
        if errors:
            raise errors[0]

    def _line(self, deadline):
        while True:
            if b"\n" in self._buffer:
                line, _, rest = self._buffer.partition(b"\n")
                self._buffer = bytearray(rest)
                return bytes(line)
            try:
                chunk = self._stdout.get(timeout=self._remaining(deadline))
            except queue.Empty:
                continue
            if not chunk:
                raise EOFError("server closed stdout without a complete LF reply")
            self._buffer.extend(chunk)
            if len(self._buffer) > self.frame_limit:
                raise ValueError("server reply exceeded the bounded frame")

    def raw(self, line: str):
        if self._closed:
            raise ValueError("client is closed")
        self._progress = time.monotonic()
        deadline = self._progress + self.timeout
        try:
            self._send((line + "\n").encode("utf-8"), deadline)
            return json.loads(self._line(deadline).decode("utf-8"))
        except BaseException:
            self._dispose()
            raise

    def request(self, method, **params):
        self._id += 1
        return self.raw(json.dumps({"jsonrpc": "2.0", "id": self._id,
                                   "method": method, "params": params}))

    def notify(self, method, **params):
        if self._closed:
            raise ValueError("client is closed")
        self._progress = time.monotonic()
        try:
            self._send((json.dumps({"jsonrpc": "2.0", "method": method,
                                   "params": params}) + "\n").encode("utf-8"),
                       self._progress + self.timeout)
        except BaseException:
            self._dispose()
            raise

    def close(self, timeout=20):
        if self._closed:
            return self.process.returncode
        self._progress = time.monotonic()
        deadline = self._progress + min(timeout, self.timeout)
        try:
            self._send(None, deadline)
            while self.process.poll() is None:
                remaining = self._remaining(deadline)
                try:
                    self.process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    continue
            return self.process.returncode
        finally:
            self._dispose()

    def _dispose(self):
        if self._closed:
            return
        self._closed = True
        try:
            stop_owned(self.process, self.job, drain=False)
        finally:
            self.job = None
            # Killing the owned tree releases blocked pipe I/O before joining.
            deadline = time.monotonic() + 5
            try:
                for thread in self.threads:
                    if thread.ident is not None:
                        thread.join(max(0, deadline - time.monotonic()))
            finally:
                for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                    pipe.close()
            if any(thread.is_alive() for thread in self.threads):
                raise RuntimeError("owned client pipe worker did not terminate")
