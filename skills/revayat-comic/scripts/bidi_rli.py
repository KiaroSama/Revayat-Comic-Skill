"""Keep Latin-leading Persian sentences in logical right-to-left order."""

from __future__ import annotations

import re
import unicodedata

RLM = "‏"
RLI = "⁧"
PDI = "⁩"
_ISOLATES = "⁦⁧⁨"
_ALL_ISOLATES = _ISOLATES + PDI
_LEADING_MARKS = _ALL_ISOLATES + "‎‏؜﻿\"'"
_PERSIAN = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-ﻼ]")
_PROTECTED = re.compile(
    r"(?ms)^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}(?P=fence)[ \t]*(?=\r?$)|\Z)"
    r"|(?P<code>`+)[^\r\n]*?(?P=code)"
    r"|(?P<address>(?i:https?://|www\.)[^\s<>\"'«»⁦-⁩`]+"
    r"|\b[\w.+%-]+@[\w-]+(?:\.[\w-]+)+)"
    r"|\b(?:[A-Za-z]\.){2,}|\b(?i:Mr|Mrs|Ms|Dr|Prof|St|vs)\.(?=\s)"
)
_END = re.compile(r"[.!?؟…]+[\]\)}»›\"'”’⁩]*")
_UNICODE_OPEN = {"Ps", "Pi"}
_LINE_BREAK = re.compile(r"(\r\n|[\r\n\v\f\x85  ])")


def _leading(character: str) -> bool:
    return (character.isspace() or character in _LEADING_MARKS
            or unicodedata.category(character) in _UNICODE_OPEN)


def starts_with_latin_in_persian(sentence: str) -> bool:
    """Does the first token start with an ASCII letter in mixed-script text?"""
    for character in sentence:
        if _leading(character):
            continue
        return ("A" <= character <= "Z" or "a" <= character <= "z") and bool(
            _PERSIAN.search(sentence)
        )
    return False


def _shadow(match: re.Match[str]) -> str:
    """Hide punctuation inside protected spans without shifting any offsets."""
    token = match.group()
    body = token.rstrip(".!?؟…)]}»›\"'”’") if match["address"] else token
    masked = "".join(ch if _LINE_BREAK.fullmatch(ch) else "\0" for ch in body)
    if match["address"] or token[0].isascii() and token[0].isalpha():
        masked = token[0] + masked[1:]
    return masked + token[len(body):]


def _pairs(line: str) -> dict[int, int]:
    pending: list[int] = []
    pairs = {}
    for index, character in enumerate(line):
        if character in _ISOLATES:
            pending.append(index)
        elif character == PDI and pending:
            pairs[pending.pop()] = index
    return pairs


def _sentences(line: str, shadow: str):
    starts = _pairs(shadow)
    ends = set(starts.values())
    left = scanned = 0
    active: list[int] = []
    for match in _END.finditer(shadow):
        right = match.end()
        for index in range(scanned, match.start()):
            if index in starts:
                active.append(index)
            elif index in ends:
                active.pop()
        # Punctuation at the end of an embedded isolate is not a sentence break.
        embedded = active and any(not _leading(ch) for ch in shadow[left:active[-1]])
        for index in range(match.start(), right):
            if index in ends:
                active.pop()
        scanned = right
        if active or embedded:
            continue
        if (match[0] == "." and match.start() and right < len(line)
                and shadow[match.start() - 1].isascii() and shadow[right].isascii()
                and shadow[match.start() - 1].isalnum() and shadow[right].isalnum()):
            continue
        yield line[left:right], shadow[left:right]
        left = right
    yield line[left:], shadow[left:]


def _wrap(sentence: str, shadow: str) -> str:
    if not starts_with_latin_in_persian(shadow):
        return sentence
    first = len(sentence) - len(sentence.lstrip())
    last = len(sentence.rstrip())
    body, visible = sentence[first:last], shadow[first:last]
    pairs = _pairs(visible)
    paired = pairs.keys() | set(pairs.values())
    removed = {i for i, ch in enumerate(visible) if ch in _ALL_ISOLATES and i not in paired}
    # An outer RLI may be doubled, or close after the first token instead of the sentence.
    for index, ch in enumerate(visible):
        if index in removed or ch.isspace():
            continue
        if ch != RLI:
            break
        removed.update((index, pairs[index]))
    if any(index not in paired for index in removed):
        # Keep word boundaries when stray controls separated otherwise adjacent tokens.
        cleaned = []
        gap = False
        for index, ch in enumerate(body):
            if index in removed:
                gap |= index not in paired
                continue
            if gap and cleaned and cleaned[-1].isalnum() and ch.isalnum():
                cleaned.append(" ")
            cleaned.append(ch)
            gap = False
        clean = "".join(cleaned)
    else:
        clean = "".join(ch for index, ch in enumerate(body) if index not in removed)
    return sentence[:first] + RLI + clean.strip() + PDI + sentence[last:]


def with_rli_pdi(text: str) -> tuple[str, int]:
    """Return the text and the number of sentences whose isolation changed."""
    if not _PERSIAN.search(text):
        return text, 0
    output = []
    changed = 0
    lines = _LINE_BREAK.split(text)
    shadows = _LINE_BREAK.split(_PROTECTED.sub(_shadow, text))
    for line, shadow in zip(lines, shadows, strict=True):
        for sentence, visible in _sentences(line, shadow):
            fixed = _wrap(sentence, visible)
            changed += fixed != sentence
            output.append(fixed)
    return "".join(output), changed


def ensure_rli_pdi(text: str) -> str:
    """Isolate each matching sentence without altering surrounding text."""
    return with_rli_pdi(text)[0]


def ensure_rlm_rli_pdi(text: str) -> str:
    """Lock RTL paragraph alignment and isolation on every Persian-bearing line.

    Prepends RLM (U+200F) + RLI (U+2067) at the start of each line containing
    Persian characters and closes it with PDI (U+2069), keeping purely LTR/non-
    Persian lines untouched (UAX #9 P2/P3 safe for `dir="auto"` renderers).
    """
    if not _PERSIAN.search(text):
        return text
    parts = _LINE_BREAK.split(text)
    out: list[str] = []
    for part in parts:
        if _LINE_BREAK.fullmatch(part) or not _PERSIAN.search(part):
            out.append(part)
            continue
        body = part.strip()
        if body.startswith(RLM + RLI) and body.endswith(PDI):
            out.append(part)
            continue
        # Strip outer RLM/RLI/PDI wrapper if partially present, then wrap cleanly.
        inner = body.lstrip(RLM)
        if inner.startswith(RLI) and inner.endswith(PDI):
            inner = inner[1:-1]
        lead = part[: len(part) - len(part.lstrip())]
        trail = part[len(part.rstrip()) :]
        out.append(lead + RLM + RLI + inner + PDI + trail)
    return "".join(out)
