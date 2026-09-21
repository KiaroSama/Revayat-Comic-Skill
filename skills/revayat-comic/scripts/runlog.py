"""One sanitized UTF-8 file per CLI run, shared by nested stage calls."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import functools
import logging
from pathlib import Path
import sys
import time
import traceback
import uuid

_active = ContextVar("revayat_run_log", default=None)


def _folder(argv: list[str]) -> Path:
    for index, arg in enumerate(argv):
        if arg == "--doc" and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser().resolve().parent / "logs"
        if arg.startswith("--doc="):
            return Path(arg.split("=", 1)[1]).expanduser().resolve().parent / "logs"
    return Path(__file__).resolve().parent / "logs"


def _invoke(function, argv, logger, component):
    extra = {"component": component}
    start = time.monotonic()
    if logger:
        logger.info("start", extra=extra)
    try:
        code = function(argv)
    except BaseException as error:
        if logger:
            if isinstance(error, SystemExit):
                code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
                logger.log(logging.INFO if code == 0 else logging.ERROR,
                           "end exit=%s elapsed=%.3fs", code, time.monotonic() - start, extra=extra)
            else:
                frames = traceback.extract_tb(error.__traceback__)[-10:]
                trace = " <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in frames)
                logger.error("failed type=%s stack=%s", type(error).__name__, trace, extra=extra)
        raise
    if logger:
        logger.log(logging.INFO if not code else logging.ERROR,
                   "end exit=%s elapsed=%.3fs", code or 0, time.monotonic() - start, extra=extra)
    return code


def cli(function):
    @functools.wraps(function)
    def logged(argv=None):
        import pageir as ir

        ir.use_utf8_stdio()
        argv = list(sys.argv[1:] if argv is None else argv)
        component = Path(function.__globals__.get("__file__", function.__name__)).stem
        logger = _active.get()
        if logger is not None:
            return _invoke(function, argv, logger, component)
        handler = None
        try:
            folder = _folder(argv)
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_UTC")
            path = folder / f"{component}_{stamp}.log"
            try:
                handler = logging.FileHandler(path, mode="x", encoding="utf-8")
            except FileExistsError:
                handler = logging.FileHandler(path.with_stem(path.stem + "_" + uuid.uuid4().hex[:8]),
                                              mode="x", encoding="utf-8")
            formatter = logging.Formatter("[%(asctime)s UTC] [%(levelname)s] [%(component)s] %(message)s",
                                          datefmt="%Y-%m-%d %H:%M:%S")
            formatter.converter = time.gmtime
            handler.setFormatter(formatter)
            logger = logging.Logger("revayat-comic", logging.INFO)
            logger.addHandler(handler)
        except OSError as error:
            if handler:
                handler.close()
            handler = None
            logger = None
            print(f"file logging unavailable ({type(error).__name__})", file=sys.stderr)
        token = _active.set(logger)
        try:
            return _invoke(function, argv, logger, component)
        finally:
            _active.reset(token)
            if handler:
                logger.removeHandler(handler)
                handler.close()
    return logged
