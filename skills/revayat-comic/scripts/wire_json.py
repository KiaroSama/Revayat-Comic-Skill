"""Bounded JSON decoding shared by MCP and loopback HTTP.

Limit structure and numeric tokens before constructing objects. Do not change
Python's process-wide recursion or integer settings for one client request.
"""

from __future__ import annotations

import json
import math
from typing import Any

MAX_DEPTH = 128
MAX_INTEGER_DIGITS = 1024


def _integer(value: str) -> int:
    if len(value.lstrip("-")) > MAX_INTEGER_DIGITS:
        raise ValueError("JSON integer exceeds the supported digit limit")
    return int(value)


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number is not finite")
    return number


def _constant(_value: str) -> None:
    raise ValueError("nonstandard JSON number")


def _validate_strings(value: Any) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ValueError("JSON contains unsupported Unicode") from None
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_strings(key)
            _validate_strings(item)
    elif isinstance(value, list):
        for item in value:
            _validate_strings(item)


def loads(text: str) -> Any:
    """Decode one bounded frame; callers turn ValueError into protocol errors."""
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError("JSON nesting exceeds the supported depth")
        elif char in "]}":
            depth -= 1
    # Syntax and matching delimiters are the standard decoder's job.
    value = json.loads(text, parse_int=_integer, parse_float=_float,
                       parse_constant=_constant)
    _validate_strings(value)
    return value
