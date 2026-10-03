"""Lexical preservation of written quantities and explicitly approved forms.

This is not a semantic judge: no inferred aliases, unit conversion or guesses
about a time are made. The caller supplies equivalent written alternatives.
"""
from __future__ import annotations

import re
import unicodedata

from falint import PERSIAN_LETTER

_LATIN = r"A-Za-z\u00C0-\u024F\u1E00-\u1EFF"
# Include technical identifiers without changing the CJK no-spaces contract.
_BOUNDED = re.compile(rf"^[{_LATIN}0-9_\u0300-\u036f ./:@+#'’\-]+$")
_ATTACHING = re.compile(rf"[{PERSIAN_LETTER}]")


def _literal_pattern(form: str) -> str:
    body = r"\s+".join(re.escape(word) for word in form.split())
    # A punctuation-ended name such as C++ has no final word boundary. It
    # still must not match C+++ or C++20; ordinary sentence punctuation is OK.
    first = re.escape(form[0]) if not form[0].isalnum() else ""
    last = re.escape(form[-1]) if not form[-1].isalnum() else ""
    return rf"(?<![\w\u0300-\u036f{first}]){body}(?![\w\u0300-\u036f{last}])"


def used(text: str, candidates: list[str]) -> bool:
    """Match written forms with the glossary's script-aware boundary rules."""
    for form in candidates:
        if not form:
            continue
        if _BOUNDED.fullmatch(form) and any(c.isalnum() for c in form):
            if re.search(_literal_pattern(form), text):
                return True
        elif _ATTACHING.search(form):
            letter = f"[{PERSIAN_LETTER}]"
            if re.search(f"(?<!{letter}){re.escape(form)}(?!{letter})", text):
                return True
        elif form in text:
            # Japanese/Chinese and existing non-Latin forms have no generic
            # word-boundary rule. Preserve their explicit substring contract.
            return True
    return False


def numeric_text(text: str) -> str:
    """Normalize decimal digits and existing decimal/minus conventions only."""
    return "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c
                   for c in text).replace("٫", ".").replace("−", "-")


# Consume scientific tokens whole so their exponent never counts as a
# separate quantity; no exponent conversion is inferred. Units may follow a
# quantity without a space. Clock components remain individual tokens when
# a case explicitly asks for each component rather than the whole clock.
_NUMBER_BODY = r"[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"
NUMBER = re.compile(rf"(?<![\w.,]){_NUMBER_BODY}(?:[eE][+-]?\d+)?(?!\d|[.,]\d)")
_WHOLE_NUMBER = re.compile(_NUMBER_BODY)


def canonical_number(token: str) -> str:
    """Compare finite decimal spellings exactly, without float/int rounding."""
    token = numeric_text(token).replace(",", ".")
    negative = token.startswith("-")
    whole, _, fraction = token.lstrip("+-").partition(".")
    whole = whole.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    value = whole + ("." + fraction if fraction else "")
    return ("-" if negative and value != "0" else "") + value


def digits_in(text: str) -> set[str]:
    return {canonical_number(match.group()) for match in NUMBER.finditer(numeric_text(text))
            if _WHOLE_NUMBER.fullmatch(match.group())}


def number_spelling_used(spelling: str, answer: str, present: set[str]) -> bool:
    """Keep compounds ordered and contiguous, rather than a set of pieces."""
    wanted = numeric_text(spelling).strip()
    if _WHOLE_NUMBER.fullmatch(wanted):
        return canonical_number(wanted) in present
    if any(c.isdecimal() for c in wanted):
        # Case-authored compound (e.g. 12:30 or 1/2): same ordered spelling,
        # with optional spacing around separators, not scattered digits. No
        # inferred conversion from a decimal to a clock or vice versa.
        pattern = re.escape(wanted)
        pattern = pattern.replace(":", r"\s*:\s*").replace("/", r"\s*/\s*")
        return bool(re.search(rf"(?<![\w:/]){pattern}(?!\w|[.:/]\d)", numeric_text(answer)))
    # Written number alternatives are whole words, not prefixes of a name
    # or a ZWNJ compound such as سه‌شنبه. Additional inflections belong in
    # the case's explicit alternatives rather than a guessed morphology rule.
    body = r"\s+".join(re.escape(word) for word in spelling.split())
    return bool(body and re.search(rf"(?<![\w\u200c]){body}(?![\w\u200c])", answer))
