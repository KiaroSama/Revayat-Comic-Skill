"""Bounded physical frames on an exclusively owned, borrowed input stream.

Borrow an unread text wrapper's binary buffer before any text read-ahead. Never
close it. Decoded-only stand-ins retain character caps; their byte discard can
overshoot by one capped chunk. Arbitrary stdin has no inactivity deadline here.
"""
from __future__ import annotations


def read_frame(stream, limit: int) -> tuple[str, str | None, int | None]:
    """Return text, fixed error kind, and optional EOF/discard-stop exit code."""
    line = stream.readline(limit + 1)
    if not line:
        return "", None, 0
    binary = isinstance(line, bytes)
    newline = b"\n" if binary else "\n"
    # surrogatepass measures decoded invalid scalars, never accepts them.
    size = len(line) if binary else len(line.encode("utf-8", errors="surrogatepass"))
    if size > limit:
        discarded = size
        while not line.endswith(newline):
            if discarded >= 4 * limit:
                return "", "oversize", 1
            line = stream.readline(min(limit + 1, 4 * limit - discarded + 1))
            if not line:
                return "", "oversize", 0
            discarded += (len(line) if binary else
                          len(line.encode("utf-8", errors="surrogatepass")))
        return "", "oversize", None
    try:
        if binary:
            line = line.decode("utf-8", errors="strict")
        else:
            line.encode("utf-8", errors="strict")
    except UnicodeError:
        return "", "unicode", None
    return line, None, None
