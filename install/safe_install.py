"""Transactional, standard-library installer shared by Bash and PowerShell.

Only manifest-owned source files are copied. Existing installs and AGENTS.md
are backed up before promotion; interrupted work is recovered explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import sys
import uuid

LOG = logging.getLogger("revayat.install")
AGENTS = {"claude": ".claude", "kiro": ".kiro", "codex": ".codex",
          "cursor": ".cursor", "cline": ".cline", "hermes": ".hermes",
          "opencode": ".opencode", "antigravity": ".agents"}
BEGIN = b"<!-- BEGIN revayat-comic -->"
END = b"<!-- END revayat-comic -->"
MAX_RECORD = 8 * 1024 * 1024


def linked(path: Path) -> bool:
    """Recognize Windows junctions as well as ordinary symbolic links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def safe_path(path: Path, base: Path) -> None:
    if not path.is_relative_to(base) or path == base:
        raise ValueError("installer destination must be inside the selected base")
    for part in (path, *path.parents):
        if part == base:
            break
        if linked(part):
            raise ValueError(f"refusing a linked installer destination: {part}")


def digest(path: Path) -> str | None:
    """Snapshot framed file hashes without following symlinks or junctions."""
    if linked(path):
        raise ValueError(f"refusing a linked artifact: {path}")
    if not path.exists():
        return None
    hashed = hashlib.sha256()
    queue = [path]
    while queue:
        entry = queue.pop()
        if linked(entry):
            raise ValueError(f"refusing a linked artifact: {entry}")
        info = entry.stat()
        name = entry.relative_to(path).as_posix()
        mode = stat.S_IMODE(info.st_mode)
        if entry.is_dir():
            row = [name, "directory", mode]
            queue.extend(reversed(sorted(entry.iterdir())))
        elif entry.is_file():
            content = hashlib.sha256()
            with entry.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    content.update(block)
            row = [name, "file", mode, content.hexdigest()]
        else:
            raise ValueError(f"unsupported artifact type: {entry}")
        hashed.update(json.dumps(row, separators=(",", ":")).encode())
    return hashed.hexdigest()


def atomic(path: Path, data: bytes) -> None:
    """Use an exclusive sibling, flush it, then atomically replace our record."""
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    owned = False
    try:
        with temp.open("xb") as stream:
            owned = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if owned:
            temp.unlink(missing_ok=True)


def read_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_RECORD + 1)
    if len(data) > MAX_RECORD:
        raise ValueError("installer record or AGENTS.md exceeds the size limit")
    return data


def pointer(raw: bytes, destinations: list[Path]) -> bytes:
    """Replace exactly one balanced block, preserving all outside bytes."""
    raw.decode("utf-8-sig")
    start = stop = None
    offset = 0
    for match in re.finditer(rb"[^\r\n]*(?:\r\n|\r|\n|$)", raw):
        line = match.group()
        if not line:
            continue
        content = line.rstrip(b"\r\n")
        bom = 3 if offset == 0 and content.startswith(b"\xef\xbb\xbf") else 0
        content = content[bom:]
        if content == BEGIN:
            if start is not None or stop is not None:
                raise ValueError("AGENTS.md has repeated or nested Revayat markers")
            start = offset + bom
        elif content == END:
            if start is None or stop is not None:
                raise ValueError("AGENTS.md has an unmatched Revayat end marker")
            stop = offset + len(line)
        offset += len(line)
    if start is not None and stop is None:
        raise ValueError("AGENTS.md has an unmatched Revayat begin marker; preserve and repair it")
    endings = re.search(rb"\r\n|\r|\n", raw)
    newline = endings.group() if endings else b"\n"
    lines = [BEGIN.decode(), "## Revayat Comic — Persian comic translation", "",
             "Use the installed skill below to translate a comic into Persian."]
    for destination in destinations:
        name = destination.as_posix()
        if any(char in name for char in "\r\n`"):
            raise ValueError("a pointer destination cannot contain a newline or backtick")
        lines.append(f"Follow `{name}/SKILL.md`; resolve `{{SKILL_DIR}}` as `{name}`.")
    block = newline.join(line.encode("utf-8") for line in [*lines, END.decode(), ""])
    if start is None:
        prefix = raw + (newline if raw and not raw.endswith((b"\n", b"\r")) else b"")
        return prefix + (newline if prefix else b"") + block
    return raw[:start] + block + raw[stop:]


def manifest(repo: Path) -> tuple[Path, list[str]]:
    source = repo / "skills/revayat-comic"
    safe_path(source, repo)
    names = (repo / "install/skill-files.txt").read_text(encoding="utf-8").splitlines()
    if not names or len(names) != len(set(names)):
        raise ValueError("invalid skill manifest")
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("invalid skill manifest path")
        path = source / relative
        safe_path(path, source)
        if not path.is_file():
            raise ValueError(f"incomplete source bundle: {name}")
    return source, names


def alive(pid: int) -> bool:
    if not 0 < pid < 2**31:
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
            return ctypes.get_last_error() != 87
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


def artifact_paths(control: Path, target: Path, token: str) -> tuple[Path, Path]:
    # Backups and incomplete candidates must never be discovered as active skills.
    name = token + "-" + hashlib.sha256(str(target).encode()).hexdigest()[:16]
    return control / "staging" / name, control / "backups" / name


def paths(item: dict) -> tuple[Path, Path, Path]:
    return tuple(Path(item[key]) for key in ("target", "stage", "backup"))


def remove_owned(path: Path, expected: str) -> None:
    if digest(path) != expected:
        raise RuntimeError(f"artifact changed; preserved for inspection: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def rollback(items: list[dict]) -> None:
    """Validate the entire transaction before restoring any old destination."""
    actions = []
    for item in items:
        target, stage, backup = paths(item)
        now, staged, previous = digest(target), digest(stage), digest(backup)
        old, new = item["old"], item["new"]
        if now == old and previous is None and staged is None:
            action = "restored"
        elif now == old and previous is None and staged == new:
            action = "unstarted"
        elif now is None and old is not None and previous == old and staged == new:
            action = "backed-up"
        elif now == new and staged is None and previous == old:
            action = "promoted"
        else:
            raise RuntimeError(f"installation ownership changed; backups retained: {target}")
        actions.append((item, action))
    for item, action in reversed(actions):
        target, stage, backup = paths(item)
        if action == "restored":
            continue
        if action == "promoted":
            target.rename(stage)
        if action != "unstarted" and item["old"] is not None:
            backup.rename(target)
        remove_owned(stage, item["new"])
    LOG.warning("Rolled back the interrupted installation; original destinations restored")


def load_record(path: Path, base: Path, targets: set[Path]) -> dict:
    record = json.loads(read_bytes(path))
    if not isinstance(record, dict):
        raise ValueError("unrecognized installer recovery record")
    token = record.get("token", "")
    if (type(record.get("version")) is not int or record["version"] != 1
            or not isinstance(token, str) or not re.fullmatch("[a-f0-9]{32}", token)
            or record.get("phase") not in ("prepared", "committed")
            or not isinstance(record.get("items"), list) or not 1 <= len(record["items"]) <= 9):
        raise ValueError("unrecognized installer recovery record; preserve it")
    seen = set()
    for item in record["items"]:
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str)
                                           for key in ("target", "stage", "backup")):
            raise ValueError("invalid recovery item")
        target, stage, backup = paths(item)
        if target not in targets or target in seen:
            raise ValueError("invalid recovery destination; preserve the record")
        seen.add(target)
        safe_path(target, base)
        if (stage, backup) != artifact_paths(path.parent, target, token):
            raise ValueError("invalid recovery artifact path")
        safe_path(stage, base)
        safe_path(backup, base)
        for key in ("old", "new"):
            value = item.get(key)
            if not (key == "old" and value is None) and not (
                    isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value)):
                raise ValueError("invalid recovery digest")
    return record


def finish(control: Path, record: dict) -> None:
    history = control / "history"
    if linked(history):
        raise ValueError("refusing linked installer history")
    history.mkdir(exist_ok=True)
    destination = history / (record["token"] + ".json")
    if destination.exists():
        raise RuntimeError("installation history already exists; preserve both records")
    (control / "pending.json").rename(destination)


def install(repo: Path, *, agent: str, scope: str, project: Path,
            force: bool = False, recover: bool = False) -> list[Path]:
    base = (Path.home() if scope == "user" else project).resolve(strict=True)
    if not base.is_dir():
        raise ValueError("the selected installation base is not a directory")
    folders = dict(AGENTS)
    if scope == "user":
        folders["opencode"] = ".config/opencode"
    targets = {name: base / folder / "skills/revayat-comic" for name, folder in folders.items()}
    valid_targets = {*targets.values(), base / "AGENTS.md"}
    control = base / ".revayat-comic-installer"
    safe_path(control, base)
    control.mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        control.chmod(0o700)
    lock = control / "lock.json"
    pending = control / "pending.json"
    safe_path(lock, base)
    safe_path(pending, base)
    if recover and lock.exists():
        previous_lock = read_bytes(lock)
        owner = json.loads(previous_lock)
        if not isinstance(owner, dict):
            raise ValueError("unknown installer lock; preserve it")
        if (owner.get("host") != socket.gethostname() or type(owner.get("pid")) is not int
                or alive(owner["pid"])):
            raise RuntimeError("installer owner is live or unknown; preserve its lock")
        if read_bytes(lock) != previous_lock:
            raise RuntimeError("installer lock changed during recovery")
        lock.unlink()
    token = uuid.uuid4().hex
    ownership = {"token": token, "host": socket.gethostname(), "pid": os.getpid()}
    with lock.open("x", encoding="utf-8") as stream:
        json.dump(ownership, stream)
        stream.flush()
        os.fsync(stream.fileno())
    staged_items = []
    committed = False
    prepared_here = False
    try:
        if pending.exists():
            record = load_record(pending, base, valid_targets)
            if not recover:
                raise RuntimeError("interrupted installation; run the installer with --recover")
            if record["phase"] == "prepared":
                rollback(record["items"])
                pending.unlink()
            else:
                for item in record["items"]:
                    target, stage, backup = paths(item)
                    if (digest(target) != item["new"] or digest(stage) is not None
                            or digest(backup) != item["old"]):
                        raise RuntimeError("committed installation changed; preserve recovery evidence")
                finish(control, record)
            LOG.info("Recovery finished")
            return []
        if recover:
            residue = control / "staging"
            if residue.exists() and any(residue.iterdir()):
                LOG.warning("Uncommitted staging copies retained at %s; active installs were not changed", residue)
            LOG.info("No pending installation to recover")
            return []
        source, names = manifest(repo)
        source_digests = {name: digest(source / name) for name in names}
        chosen = []
        for name in (folders if agent == "all" else [agent]):
            target = targets[name]
            if agent == "all" and not (base / folders[name]).is_dir():
                continue
            safe_path(target, base)
            if source == target or source in target.parents or target in source.parents:
                raise ValueError("source and destination overlap")
            if target.exists() and not target.is_dir():
                raise ValueError("an installation destination is not a directory")
            if target.exists() and not force:
                if not sys.stdin.isatty():
                    LOG.warning("Kept existing %s installation; replacement requires --force", name)
                    continue
                if input(f"Replace {name} installation? [y/N] ").strip().lower() not in ("y", "yes"):
                    continue
            chosen.append((name, target))
        if not chosen:
            raise ValueError("nothing selected for installation; existing files were kept")
        pointer_targets = []
        if any(name in ("opencode", "antigravity") for name, _ in chosen):
            selected = {target for _, target in chosen}
            for name in ("opencode", "antigravity"):
                target = targets[name]
                safe_path(target / "SKILL.md", base)
                # A one-agent upgrade must not erase another installed pointer.
                if target in selected or (target / "SKILL.md").is_file():
                    pointer_targets.append(target)
        pointer_path = base / "AGENTS.md"
        pointer_data = None
        expected = {target: digest(target) for _, target in chosen}
        if pointer_targets:
            safe_path(pointer_path, base)
            expected[pointer_path] = digest(pointer_path)
            pointer_data = pointer(read_bytes(pointer_path) if pointer_path.exists() else b"", pointer_targets)
            if digest(pointer_path) != expected[pointer_path]:
                raise RuntimeError("AGENTS.md changed during preflight")
        operations = [(target, None) for _, target in chosen]
        if pointer_data is not None:
            operations.append((pointer_path, pointer_data))
        for folder in (control / "staging", control / "backups"):
            safe_path(folder, base)
            folder.mkdir(exist_ok=True)
        for target, data in operations:
            target.parent.mkdir(parents=True, exist_ok=True)
            stage, backup = artifact_paths(control, target, token)
            if target.parent.stat().st_dev != control.stat().st_dev:
                raise ValueError("installation and recovery storage must be on the same filesystem")
            item = {"target": str(target), "stage": str(stage), "backup": str(backup),
                    "old": expected[target]}
            if data is None:
                stage.mkdir()
                staged_items.append(item)
                for relative in names:
                    original, copy = source / relative, stage / relative
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, copy)
                    if digest(copy) != source_digests[relative]:
                        raise RuntimeError("source changed while staging the skill")
            else:
                with stage.open("xb") as stream:
                    staged_items.append(item)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if target.exists():
                    stage.chmod(stat.S_IMODE(target.stat().st_mode))
            item["new"] = digest(stage)
            LOG.debug("Prepared and verified %s", target)
        if any(digest(source / name) != value for name, value in source_digests.items()):
            raise RuntimeError("source bundle changed during staging")
        record = {"version": 1, "token": token, "phase": "prepared", "items": staged_items}
        atomic(pending, json.dumps(record, indent=2).encode("utf-8"))
        prepared_here = True
        for item in staged_items:
            target, stage, backup = paths(item)
            if digest(target) != item["old"] or digest(stage) != item["new"] or backup.exists():
                raise RuntimeError("destination changed before promotion; preserving evidence")
            if item["old"] is not None:
                target.rename(backup)
            if target.exists() or linked(target):
                raise RuntimeError("another writer created the installation destination")
            stage.rename(target)
        for item in staged_items:
            target, stage, backup = paths(item)
            if (digest(target) != item["new"] or digest(stage) is not None
                    or digest(backup) != item["old"]):
                raise RuntimeError("installation changed before commit; preserve recovery evidence")
        record["phase"] = "committed"
        atomic(pending, json.dumps(record, indent=2).encode("utf-8"))
        committed = True
        finish(control, record)
        for item in staged_items:
            LOG.info("Installed %s", item["target"])
            if item["old"] is not None:
                LOG.info("Previous files retained at %s", item["backup"])
        return [target for _, target in chosen]
    except BaseException:
        if not committed and prepared_here and pending.exists():
            # Never discard evidence if recovery detects an intervening edit.
            rollback(load_record(pending, base, valid_targets)["items"])
            pending.unlink()
        elif not committed:
            for item in staged_items:
                stage = Path(item["stage"])
                if stage.exists():
                    if stage.is_dir():
                        shutil.rmtree(stage)
                    else:
                        stage.unlink()
        raise
    finally:
        try:
            if lock.exists() and not linked(lock) and json.loads(read_bytes(lock)) == ownership:
                lock.unlink()
        except (OSError, ValueError):
            LOG.warning("Installer lock changed or could not be released; preserved for inspection")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=[*AGENTS, "all"], default="all")
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--path", type=Path, default=Path.cwd())
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args(argv)
    level = os.environ.get("REVAYAT_LOG_LEVEL", "INFO").upper()
    levels = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
              "WARNING": logging.WARNING, "ERROR": logging.ERROR}
    logging.basicConfig(level=levels.get(level, logging.INFO),
                        format="%(asctime)s [%(levelname)s] [installer] %(message)s")
    if level not in levels:
        LOG.warning("Invalid diagnostic level; using INFO")
    try:
        install(Path(__file__).resolve().parents[1], agent=args.agent, scope=args.scope,
                project=args.path, force=args.force, recover=args.recover)
    except (OSError, ValueError, RuntimeError) as error:
        LOG.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
