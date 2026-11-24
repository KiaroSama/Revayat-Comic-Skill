"""Reference kernels for mixed Persian text and shaped balloon lines."""

from __future__ import annotations

import re
import unicodedata

_RLM, _RLI, _PDI = "‏", "⁧", "⁩"
_LOCK = _RLM + _RLI
_ISOLATES = "⁦⁧⁨"
_ALL_ISOLATES = _ISOLATES + _PDI
_LEADING_MARKS = _ALL_ISOLATES + "‎‏؜﻿\"'"
_PERSIAN = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-ﻼ]")
_FENCE_PATTERN = (
    r"(?ms:^ {0,3}(?P<fence>(?P<marker>[`~])(?P=marker){2,})(?!(?P=marker))[^\n]*\n.*?"
    r"(?:^ {0,3}(?P=fence)(?P=marker)*[ \t]*(?=\r?$)|\Z))"
)
_CODE_PATTERN = r"(?P<code>`+)[^\r\n]*?(?P=code)"
_ADDRESS_PATTERN = r"(?i:https?://|www\.)[^\s<>\"'«»⁦-⁩`]+|\b[\w.+%-]+@[\w-]+(?:\.[\w-]+)+"
_FENCES = re.compile(_FENCE_PATTERN)
_PROTECTED = re.compile(
    rf"{_FENCE_PATTERN}|{_CODE_PATTERN}|(?P<address>{_ADDRESS_PATTERN})"
    r"|\b(?:[A-Za-z]\.){2,}|\b(?i:Mr|Mrs|Ms|Dr|Prof|St|vs)\.(?=\s)"
)
_END = re.compile(r"[.!?؟…]+[\]\)}»›\"'”’⁩]*")
_LINE_BREAK = re.compile(r"(\r\n|[\r\n\v\f\x85  ])")


def _leading(ch: str) -> bool:
    return ch.isspace() or ch in _LEADING_MARKS or unicodedata.category(ch) in {"Ps", "Pi"}


def starts_with_latin_in_persian(text: str) -> bool:
    """Match the original ASCII-leading mixed-script predicate."""
    for ch in text:
        if not _leading(ch):
            return ch.isascii() and ch.isalpha() and bool(_PERSIAN.search(text))
    return False


def _shadow(match: re.Match[str]) -> str:
    token = match[0]
    body = token.rstrip(".!?؟…)]}»›\"'”’") if match["address"] else token
    masked = "".join(ch if _LINE_BREAK.fullmatch(ch) else "\0" for ch in body)
    if match["address"] or token[0].isascii() and token[0].isalpha():
        masked = token[0] + masked[1:]
    return masked + token[len(body):]


def _pairs(text: str) -> dict[int, int]:
    pending = []
    pairs = {}
    for i, ch in enumerate(text):
        if ch in _ISOLATES:
            pending.append(i)
        elif ch == _PDI and pending:
            pairs[pending.pop()] = i
    return pairs


def _sentences(shadow: str):
    starts = _pairs(shadow)
    ends = set(starts.values())
    left = scanned = 0
    active = []
    for match in _END.finditer(shadow):
        start, right = match.span()
        for i in range(scanned, start):
            if i in starts:
                active.append(i)
            elif i in ends:
                active.pop()
        # A period within a paired inline isolate does not end the sentence.
        embedded = active and any(not _leading(ch) for ch in shadow[left:active[-1]])
        for i in range(start, right):
            if i in ends:
                active.pop()
        scanned = right
        if active or embedded:
            continue
        if (match[0] == "." and start and right < len(shadow)
                and all(ch.isascii() and ch.isalnum() for ch in (shadow[start - 1], shadow[right]))):
            continue
        yield left, right
        left = right
    yield left, len(shadow)


def _wrap(sentence: str, visible: str) -> str:
    if not starts_with_latin_in_persian(visible):
        return sentence
    first = len(sentence) - len(sentence.lstrip())
    last = len(sentence.rstrip())
    body, visible = sentence[first:last], visible[first:last]
    pairs = _pairs(visible)
    paired = pairs.keys() | set(pairs.values())
    removed = {i for i, ch in enumerate(visible) if ch in _ALL_ISOLATES and i not in paired}
    # Replace a leading RLI even if it closes early or is duplicated.
    for i, ch in enumerate(visible):
        if i in removed or ch.isspace():
            continue
        if ch != _RLI:
            break
        removed.update((i, pairs[i]))
    clean = []
    gap = False
    for i, ch in enumerate(body):
        if i in removed:
            gap |= i not in paired
        else:
            if gap and clean and clean[-1].isalnum() and ch.isalnum():
                clean.append(" ")
            clean.append(ch)
            gap = False
    return sentence[:first] + _RLI + "".join(clean).strip() + _PDI + sentence[last:]


def ensure_rli_pdi(text: str) -> str:
    """Isolate ASCII-leading Persian sentences, preserving protected spans."""
    if not _PERSIAN.search(text):
        return text
    shadow = _PROTECTED.sub(_shadow, text)
    return "".join(
        _wrap(line[left:right], visible[left:right])
        for line, visible in zip(_LINE_BREAK.split(text), _LINE_BREAK.split(shadow), strict=True)
        for left, right in _sentences(visible)
    )


def _lock_line(line: str) -> str:
    if not _PERSIAN.search(line):
        return line
    body = line.strip()
    if body.startswith(_LOCK) and body.endswith(_PDI):
        return line
    inner = body.lstrip(_RLM)
    if inner.startswith(_RLI) and inner.endswith(_PDI):
        inner = inner[1:-1]
    return line[:len(line) - len(line.lstrip())] + _LOCK + inner + _PDI + line[len(line.rstrip()):]


def ensure_rlm_rli_pdi(text: str) -> str:
    """Lock Persian-bearing paragraphs outside fenced code blocks."""
    if not _PERSIAN.search(text):
        return text
    parts = []
    last = 0
    for fence in _FENCES.finditer(text):
        parts.extend(map(_lock_line, _LINE_BREAK.split(text[last:fence.start()])))
        parts.append(fence[0])
        last = fence.end()
    parts.extend(map(_lock_line, _LINE_BREAK.split(text[last:])))
    return "".join(parts)


_LETTERS = r"ء-غف-يٮ-ۓۺ-ۿ"
_LETTER = re.compile(rf"[{_LETTERS}]")
_WORD = re.compile(rf"[{_LETTERS}]+")
_AFFIX = re.compile(rf"(?P<left>[{_LETTERS}]+)(?P<gap>[ ‌]+)(?=[{_LETTERS}])")
_PLURAL_ANCHOR = re.compile(r" +(?:را|ی)\b")
_VERSION = (
    r"(?<!\w)(?:[vV]?(?:[0-9٠-٩۰-۹]+[.:/\-]){1,}[0-9٠-٩۰-۹]+(?:[-+][A-Za-z0-9][A-Za-z0-9.-]*)?"
    r"|[vV][0-9]+)(?!\w)"
)
# Recognize the line breaks that this pass will write as LF before protecting fences.
_NORMAL_FENCE = (_FENCE_PATTERN
                 .replace("^ {0,3}", r"(?:^|(?<=[\x85  ])) {0,3}")
                 .replace(r"[^\n]*\n", r"[^\n\x85  ]*[\n\x85  ]")
                 .replace(r"(?=\r?$)", r"(?=\r?(?:$|[\x85  ]))"))
_NORMAL_PROTECTED = re.compile(rf"{_NORMAL_FENCE}|{_CODE_PATTERN}|{_ADDRESS_PATTERN}|{_VERSION}")
_CHAR_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ـ": None,
                          " ": "\n", " ": "\n", "\x85": "\n"})
_DIGITS = re.compile(r"[0-9٠-٩]+")
_DIGIT_MAP = str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹")
_PUNCT = {",": "،", ";": "؛", "?": "؟"}
_MI_STEMS = (
    "رو", "کن", "شو", "خواه", "توان", "دان", "گوی", "بین", "آی", "گیر",
    "خور", "زن", "آور", "افت", "رس", "مان", "نویس", "خوان", "پرس", "ترس",
    "فهم", "شناس", "ایست", "نشین", "گرد", "کش", "دار", "گذار", "ساز", "شکن",
    "بند", "پوش", "خند", "گری",
)
_MI_VERBS = frozenset(stem + ending for stem in _MI_STEMS for ending in ("م", "ی", "د", "یم", "ید", "ند"))
_POSSESSIVES = {"هایشان", "هایتان", "هایمان", "هایی", "هایم", "هایت", "هایش"}


def _neighbor(text: str, i: int, step: int) -> str:
    while 0 <= i < len(text) and text[i] in " \t":
        i += step
    return text[i] if 0 <= i < len(text) else ""


def _letter(ch: str) -> bool:
    return bool(_LETTER.fullmatch(ch))


def _punct_context(ch: str) -> bool:
    return _letter(ch) or "۰" <= ch <= "۹"


def _normalize_segment(text: str) -> str:
    text = text.translate(_CHAR_MAP)

    def digits(match: re.Match[str]) -> str:
        start, end = match.span()
        left, right = text[start - 1:start] if start else "", text[end:end + 1]
        if any(ch.isascii() and (ch.isalnum() or ch == "_") for ch in (left, right)):
            return match[0]
        if _letter(_neighbor(text, start - 1, -1)) or _letter(_neighbor(text, end, 1)):
            return match[0].translate(_DIGIT_MAP)
        return match[0]

    text = _DIGITS.sub(digits, text)
    text = "".join(
        _PUNCT[ch] if ch in _PUNCT and (
            _punct_context(_neighbor(text, i - 1, -1)) or _punct_context(_neighbor(text, i + 1, 1))
        ) else ch
        for i, ch in enumerate(text)
    )

    def affix(match: re.Match[str]) -> str:
        left, gap = match.groups()
        right = _WORD.match(text, match.end())
        if right is not None:
            suffix = right[0]
            existing = "‌" in gap
            # Bare plural can also be a warning particle; use the grammar anchor.
            if (left in {"می", "نمی"} and (existing or suffix in _MI_VERBS)
                    or len(left) >= 2 and (suffix == "ترین" or suffix in _POSSESSIVES
                    or suffix in {"ها", "های"} and (existing or _PLURAL_ANCHOR.match(text, right.end())))):
                return left + "‌"
        return match[0]

    return _AFFIX.sub(affix, text)


def normalize_persian_text(text: str) -> str:
    """Normalize Persian prose without changing code, addresses, or versions."""
    if not _PERSIAN.search(text) and not any(ch in text for ch in "  \x85"):
        return text
    parts = []
    last = 0
    for match in _NORMAL_PROTECTED.finditer(text):
        parts.extend((_normalize_segment(text[last:match.start()]), match[0]))
        last = match.end()
    parts.append(_normalize_segment(text[last:]))
    return "".join(parts)


def balanced_wrap_lines(word_widths: list[int], space_width: int, band_widths: list[int]) -> list[list[int]]:
    """Minimize squared unused width across occupied bands, breaking ties earliest."""
    if any(width <= 0 for width in word_widths):
        raise ValueError("word widths must be positive")
    if space_width < 0:
        raise ValueError("space width must be non-negative")
    if any(width < 0 for width in band_widths):
        raise ValueError("band widths must be non-negative")
    if not band_widths:
        raise ValueError("band widths must not be empty")
    n = len(word_widths)
    if not n:
        return []
    # Each occupied band consumes at least one word. A finished paragraph may leave bands unused.
    next_costs = [None] * n + [0]
    choices = []
    for band in reversed(band_widths[:n]):
        costs = [None] * n + [0]
        ends = [0] * n
        for start in range(n):
            width = -space_width
            for j in range(start, n):
                width += word_widths[j] + space_width
                if width > band:
                    break
                after = next_costs[j + 1]
                if after is not None:
                    cost = (band - width) ** 2 + after
                    if costs[start] is None or cost < costs[start]:
                        costs[start], ends[start] = cost, j + 1
        choices.append(ends)
        next_costs = costs
    if next_costs[0] is None:
        return []
    start, result = 0, []
    for ends in reversed(choices):
        end = ends[start]
        result.append([start, end])
        if end == n:
            break
        start = end
    return result
