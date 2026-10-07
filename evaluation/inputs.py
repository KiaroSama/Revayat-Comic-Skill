"""Admit complete custom evaluation records before scoring or writing pages."""
from __future__ import annotations

import math
import re


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_RESERVED = {"con", "prn", "aux", "nul", "conin", "conout"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


def validate_cases(cases, *, drawing=False):
    if not isinstance(cases, list) or not cases:
        raise ValueError("evaluation cases must be a nonempty list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each evaluation case must be an object")
        name = case.get("id")
        if (not isinstance(name, str) or not _ID.fullmatch(name)
                or name.casefold() in seen or name.casefold() in _RESERVED):
            raise ValueError("evaluation case IDs must be unique safe ASCII names")
        seen.add(name.casefold())
        for field in ("source", "language"):
            if (field in case or drawing) and not isinstance(case.get(field), str):
                raise ValueError("evaluation source and language must be strings")
        for field in ("context", "human_note", "continues_into", "continues_from"):
            if field in case and not isinstance(case[field], str):
                raise ValueError("evaluation context and continuation fields must be strings")
        for field in ("accept", "difficulty"):
            if field in case and (not isinstance(case[field], list)
                                  or any(not isinstance(value, str) for value in case[field])):
                raise ValueError("evaluation alternatives and difficulties must be string lists")
        if "human_only" in case and not isinstance(case["human_only"], bool):
            raise ValueError("evaluation human_only must be boolean")
        if case.get("units") is not None and (type(case["units"]) is not int or case["units"] < 0):
            raise ValueError("evaluation units must be a nonnegative integer")
        balloon = case.get("balloon")
        if balloon is not None or drawing:
            if (not isinstance(balloon, list) or len(balloon) != 2
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           or not 0 < value <= 1 for value in balloon)):
                raise ValueError("evaluation balloon must contain two finite fractions in (0, 1]")
            if drawing and (int(1000 * balloon[0]) < 2 or int(1500 * balloon[1]) < 2):
                raise ValueError("evaluation balloon is too small for the generated page")
        preserved = case.get("must_preserve")
        if preserved is None:
            preserved = {}
        if not isinstance(preserved, dict):
            raise ValueError("evaluation must_preserve must be an object")
        for field in ("negation", "ellipsis", "contrastive_subject"):
            if field in preserved and not isinstance(preserved[field], bool):
                raise ValueError("evaluation preservation flags must be boolean")
        for field in ("numbers", "terms"):
            if field not in preserved:
                continue
            values = preserved[field]
            if not isinstance(values, list) or any(
                    not isinstance(value, str) and (field != "numbers"
                    or not isinstance(value, list) or not value
                    or any(not isinstance(item, str) for item in value)) for value in values):
                raise ValueError("evaluation preserved forms must be strings or number alternatives")
    return cases


def validate_answers(answers):
    if not isinstance(answers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in answers.items()):
        raise ValueError("evaluation answers must be an object of string answers")
    return answers
