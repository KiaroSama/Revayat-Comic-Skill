"""Workspace and destination ownership, shared by every persistent writer.

Locks are fail-fast and removed only by their owner. Explicit recovery may
release a known local claim only after proving its process is gone. A snapshot
also carries its loaded digest so saving it cannot erase an intervening edit.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
import socket
import threading
import uuid
from typing import Any

_local = threading.local()


class Document(dict):
    """A JSON document with an IO generation that is never serialized into it."""

    path: Path | None = None
    generation: str | None = None


def identity(path: Path) -> tuple[int, int]:
    stat = path.stat(follow_symlinks=False)
    return stat.st_dev, stat.st_ino


class Claim:
    def __init__(self, path: Path, *, what: str, reentrant: bool = False,
                 document: Path | None = None):
        self.path = path.resolve()
        self.reentrant = reentrant
        self.borrowed = False
        self.record = {"owner": "revayat-comic", "token": uuid.uuid4().hex,
                       "pid": os.getpid(), "host": socket.gethostname(), "what": what,
                       "document": str(document.resolve()) if document else None}

    def __enter__(self):
        active = getattr(_local, "claims", {})
        owner = active.get(self.path)
        if self.reentrant and owner is not None and owner.owns():
            self.borrowed = True
            return owner
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise RuntimeError(
                f"another run is already writing {self.path.parent}; claim {self.path}. "
                "Wait for it to finish. For an interrupted export use `export --recover`.") from None
        self.inode = identity(self.path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                json.dump(self.record, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if identity(self.path) == self.inode:
                self.path.unlink()
            raise
        active[self.path] = self
        _local.claims = active
        return self

    def owns(self) -> bool:
        try:
            return (identity(self.path) == self.inode
                    and read_claim(self.path).get("token") == self.record["token"])
        except (OSError, ValueError):
            return False

    def __exit__(self, *_exc):
        if self.borrowed:
            return
        try:
            if self.owns():
                self.path.unlink()
        finally:
            getattr(_local, "claims", {}).pop(self.path, None)


class workspace_lock(Claim):
    def __init__(self, folder: str | os.PathLike[str], *, what: str = "write",
                 reentrant: bool = False):
        super().__init__(Path(folder) / ".revayat-lock", what=what, reentrant=reentrant)


def destination_claim(out: Path, doc_path: Path) -> Claim:
    out = out.resolve()
    return Claim(out.with_name(out.name + ".revayat-claim"),
                 what="export", document=doc_path)


def remember_staging(path: Path) -> None:
    """Bind a pre-journal scratch inode to the destination's separate claim."""
    if not path.name.endswith(".revayat-part"):
        return
    claim_path = path.with_name(path.name[:-len(".revayat-part")] + ".revayat-claim").resolve()
    claim = getattr(_local, "claims", {}).get(claim_path)
    if claim is None:
        return
    if not claim.owns():
        raise RuntimeError("destination ownership changed before assembly")
    import pageir as ir

    claim.record["scratch"] = {"path": str(path.resolve()), "identity": list(identity(path))}
    ir.write_text(claim.path, json.dumps(claim.record) + "\n")
    claim.inode = identity(claim.path)


def mutating(function):
    """Lock before loading state or producing assets, including library callers."""
    @functools.wraps(function)
    def guarded(doc_path, *args, **kwargs):
        with workspace_lock(Path(doc_path).resolve().parent, what=function.__name__):
            if kwargs.get("pages") is not None:
                import pageir as ir

                doc = ir.load_doc(doc_path)
                kwargs["pages"] = [page["id"] for page in selected_pages(doc, kwargs["pages"])]
            return function(doc_path, *args, **kwargs)
    return guarded


def selected_pages(doc: dict[str, Any], pages) -> list[dict[str, Any]]:
    if pages is None:
        return list(doc["pages"])
    if isinstance(pages, str):
        raise ValueError("pages must be a collection of page IDs")
    requested = list(pages)
    if any(not isinstance(page, str) for page in requested):
        raise ValueError("page IDs must be strings")
    wanted = set(requested)
    missing = wanted - {page["id"] for page in doc["pages"]}
    if missing:
        raise ValueError(f"unknown page IDs: {', '.join(sorted(missing))}")
    return [page for page in doc["pages"] if page["id"] in wanted]


def parse_pages(value: str | None) -> list[str] | None:
    return None if value is None else [part.strip() for part in value.split(",") if part.strip()]


def read_claim(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("a symlink is not an owned claim")
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("claim is too large")
    record = json.loads(raw.decode("utf-8"))
    if (not isinstance(record, dict) or record.get("owner") != "revayat-comic"
            or not isinstance(record.get("token"), str)
            or len(record["token"]) != 32 or not isinstance(record.get("pid"), int)):
        raise ValueError("unrecognized claim; preserve it for inspection")
    return record


def _alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # invalid PID; access denied is unknown/live
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_claim(path: Path, *, document: Path | None = None) -> dict[str, Any] | None:
    """Explicit, bounded recovery. Unknown or live owners are never displaced."""
    if not path.exists():
        return None
    inode = identity(path)
    record = read_claim(path)
    if record.get("host") != socket.gethostname() or _alive(record["pid"]):
        raise RuntimeError(f"{path}: owner is live or cannot be proven absent")
    if document is not None and record.get("document") != str(document.resolve()):
        raise ValueError(f"{path}: claim belongs to another document")
    if identity(path) != inode or read_claim(path) != record:
        raise RuntimeError(f"{path}: ownership changed during recovery")
    path.unlink()
    return record
