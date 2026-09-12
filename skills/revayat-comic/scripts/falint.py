"""Persian typography — the mechanical pass over translated dialogue.

Persian written by a translation model is usually *correct* and typographically
wrong: an Arabic yeh where a Persian one belongs, a Latin comma in a Persian
sentence, a space where a zero-width non-joiner should be. None of that is a
translation problem, so none of it should cost a re-translation.

Two properties matter more than coverage:

* **It is idempotent.** Running it twice changes nothing the second time. That
  is why the digit rule says ``[0-9]`` and not ``\\d`` — Python's ``\\d`` also
  matches Persian digits, so a second pass would try to convert its own output.
* **Rules are context-gated.** A comma becomes ``،`` only when a Persian letter
  precedes it, so ``Vol. 2, ch. 3`` inside a caption survives. A ZWNJ is
  inserted only for suffix and prefix patterns that are unambiguous, because
  ZWNJ carries meaning and a blind pass corrupts real words.

Balloons add one rule the novel side does not need: the line breaks a reader
put in the worksheet are kept, because a balloon that says two things on two
lines is meant to.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import pageir as ir
import stages

ZWNJ = "‌"

_CHAR_MAP = {
    "ي": "ی",   # Arabic yeh      -> Persian yeh
    "ى": "ی",   # alef maksura    -> Persian yeh
    "ك": "ک",   # Arabic kaf      -> Persian keheh
    "ـ": "",    # tatweel: decorative elongation, never wanted
    " ": " ",   # no-break space
    "​": "",    # zero-width space — not ZWNJ, which is meaningful
    "﻿": "",    # stray BOM
}
_ARABIC_INDIC = {chr(0x0660 + n): chr(0x06F0 + n) for n in range(10)}
_LATIN_TO_PERSIAN_DIGIT = {str(n): chr(0x06F0 + n) for n in range(10)}

PERSIAN_LETTER = r"ء-غف-يٮ-ۓۺ-ۿ"
PERSIAN_DIGIT = r"۰-۹"

_PROTECTED = re.compile(
    r"""(?xi)
    (?:https?://|www\.)\S+
    | [\w.+-]+@[\w-]+\.[\w.-]+
    | \b[0-9]{1,4}(?:[.:/-][0-9]{1,4})+\b
    | \b[A-Za-z][\w.'’-]*\b
    """
)

# The plural and possessive family, joined automatically. `<noun> ها` is the
# plural in every register that appears in comic dialogue; the interjection
# `ها` does not sit immediately after a noun with a space before it.
_ZWNJ_SUFFIXES = (
    "هایشان", "هایتان", "هایمان", "هایی", "هایم", "هایت", "هایش", "های", "ها",
)
#: `نمی` is not a Persian word by itself, so this one can never be wrong.
_ZWNJ_PREFIXES = ("نمی",)

# `تر` is both the comparative suffix and the adjective "wet". `موهایم تر شد`
# means "my hair got wet"; joined, it says something else entirely. Nothing
# short of a lexicon separates the two, so the join is REPORTED and not
# applied — a tool that quietly rewrites a sentence is worse than one that
# leaves a typo.
_AMBIGUOUS_SUFFIXES = ("ترین", "تری", "تر")

#: `می` is the verbal prefix and also the noun "wine". The prefix attaches to
#: a conjugated verb, and a Persian verb carries a personal ending, so a
#: following word that ends in one is joined and anything else is reported.
#: `می روم` joins; `می ناب` ("fine wine") does not.
_VERB_ENDING = "مویدنهٔ"

_SUFFIX_SPACE = re.compile(
    rf"([{PERSIAN_LETTER}]{{2,}}) +({'|'.join(_ZWNJ_SUFFIXES)})\b"
)
_PREFIX_SPACE = re.compile(
    rf"\b({'|'.join(_ZWNJ_PREFIXES)}) +([{PERSIAN_LETTER}]{{2,}})"
)
#: `می` followed by something that conjugates. Applied.
_MI_VERB = re.compile(
    rf"\b(می) +([{PERSIAN_LETTER}]{{2,}}[{_VERB_ENDING}])\b"
)
#: What is left over for a reader to decide.
_AMBIGUOUS_JOIN = re.compile(
    rf"[{PERSIAN_LETTER}]{{2,}} +(?:{'|'.join(_AMBIGUOUS_SUFFIXES)})\b"
    rf"|\bمی +(?![{PERSIAN_LETTER}]{{2,}}[{_VERB_ENDING}]\b)[{PERSIAN_LETTER}]{{2,}}"
)

_PERSIAN_PUNCT = "،؛؟!:.»…"
_COMMA = re.compile(rf"(?<=[{PERSIAN_LETTER}{PERSIAN_DIGIT}]) *,")
_SEMICOLON = re.compile(rf"(?<=[{PERSIAN_LETTER}{PERSIAN_DIGIT}]) *;")
_QUESTION = re.compile(rf"(?<=[{PERSIAN_LETTER}{PERSIAN_DIGIT}]) *\?")
_ELLIPSIS = re.compile(r"\.{3,}")
#: A space before punctuation is a typo — except before an ellipsis that *opens*
#: a phrase, where it is the only thing separating two sentences. Comic dialogue
#: is full of them: `…آره. …ببخشید.` lost its space, became one unbreakable
#: 13-character token, and overflowed a balloon it would otherwise have fitted.
#: A trailing ellipsis (`سلام…`) is not followed by a letter, so it still closes up.
_SPACE_BEFORE_PUNCT = re.compile(
    rf"[ \t]+(?!…[{PERSIAN_LETTER}])([{re.escape(_PERSIAN_PUNCT)}])"
)
_MISSING_SPACE_AFTER = re.compile(rf"([،؛؟!:])(?=[{PERSIAN_LETTER}])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_QUOTE_PAIR = re.compile(r"[\"“](.+?)[\"”]", re.S)
_GUILLEMET_INNER = re.compile(r"«\s+|\s+»")
#: Explicitly [0-9]. See the module docstring: \d would match its own output.
_DIGIT_RUN = re.compile(r"(?<![\w.:/-])[0-9]+(?![\w.:/-])")

#: Comic dialogue leans on these; a model reaching for the ASCII form is common.
_EMPHATIC = re.compile(r"([!؟])\1{2,}")


class Options:
    def __init__(
        self, *, digits: str = "persian", quotes: bool = True,
        ellipsis: bool = True, zwnj: bool = True, punctuation: bool = True,
    ) -> None:
        self.digits = digits
        self.quotes = quotes
        self.ellipsis = ellipsis
        self.zwnj = zwnj
        self.punctuation = punctuation


#: C0 controls except tab. A NUL never belongs in dialogue, and it used to be
#: the protection's own sentinel: a line holding `\x00<digits>\x00` was
#: unmasked into somebody else's URL, or raised IndexError on a leading one.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

#: Persian, for deciding whether a bare numeral on this line is Persian too.
_HAS_PERSIAN = re.compile(rf"[{PERSIAN_LETTER}]")


def _fix_segment(text: str, options: Options, persian_line: bool) -> str:
    """Everything that may rewrite characters. Never sees a protected span."""
    for source, target in _CHAR_MAP.items():
        text = text.replace(source, target)
    for source, target in _ARABIC_INDIC.items():
        text = text.replace(source, target)

    if options.quotes:
        text = _QUOTE_PAIR.sub(lambda m: f"«{m.group(1)}»", text)
    if options.ellipsis:
        text = _ELLIPSIS.sub("…", text)

    # Before the punctuation rules, not after. Those rules look BEHIND for a
    # Persian digit, so converting afterwards left `۱,۲۰۰` on the first run and
    # `۱،۲۰۰` on the second — a function that says it is idempotent and is not.
    if options.digits == "persian" and persian_line:
        # `Vol. 2, ch. 3` is not a Persian sentence and its numerals are not
        # Persian numerals. Latin words are protected; the bare digits between
        # them were not, and came out in Persian inside English text.
        text = _DIGIT_RUN.sub(
            lambda m: "".join(_LATIN_TO_PERSIAN_DIGIT[d] for d in m.group(0)),
            text,
        )

    if options.punctuation:
        text = _COMMA.sub("،", text)
        text = _SEMICOLON.sub("؛", text)
        text = _QUESTION.sub("؟", text)
        text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
        text = _MISSING_SPACE_AFTER.sub(r"\1 ", text)
        text = _GUILLEMET_INNER.sub(lambda m: m.group(0).strip(), text)
        # Shouting is part of comic dialogue; three marks is emphatic, seven is
        # a typo, and a balloon has no room for either way of finding out.
        text = _EMPHATIC.sub(r"\1\1\1", text)
    if options.zwnj:
        # "کتاب ها ی" style chains need more than one pass to settle.
        for _ in range(3):
            replaced = _SUFFIX_SPACE.sub(rf"\1{ZWNJ}\2", text)
            replaced = _PREFIX_SPACE.sub(rf"\1{ZWNJ}\2", replaced)
            replaced = _MI_VERB.sub(rf"\1{ZWNJ}\2", replaced)
            if replaced == text:
                break
            text = replaced

    return _MULTI_SPACE.sub(" ", text)


def _fix_once(text: str, options: Options) -> str:
    persian_line = bool(_HAS_PERSIAN.search(text))
    pieces: list[str] = []
    last = 0
    for match in _PROTECTED.finditer(text):
        pieces.append(_fix_segment(text[last:match.start()], options, persian_line))
        # A URL, an email address or a Latin word, byte for byte. Folding an
        # Arabic kaf, converting a digit or pairing a quote inside one of these
        # produces a dead link that still looks like a link.
        pieces.append(match.group(0))
        last = match.end()
    pieces.append(_fix_segment(text[last:], options, persian_line))
    return "".join(pieces)


def fix_line(text: str, options: Options) -> str:
    text = _CONTROL.sub("", text)
    # Run to a fixed point rather than reasoning about every pair of rules. One
    # rule feeding another is exactly how this stopped being idempotent, and a
    # stored value that still moves has no settled answer to store.
    for _ in range(3):
        once = _fix_once(text, options)
        if once == text:
            break
        text = once
    return text.strip()


def fix_text(text: str, options: Options | None = None) -> str:
    """Fix each line separately so deliberate balloon line breaks survive."""
    if not text:
        return text
    options = options or Options()
    return "\n".join(fix_line(line, options) for line in text.split("\n")).strip()


# --------------------------------------------------------------------------- #
# Linting
# --------------------------------------------------------------------------- #

_LATIN_SENTENCE = re.compile(r"[A-Za-z][A-Za-z ,'’-]{20,}")
_DOUBLE_PUNCT = re.compile(r"([،؛])\1+")
_ARABIC_LEFTOVER = re.compile(r"[يكىـ٠-٩]")


def lint_text(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not (text or "").strip():
        return issues

    def note(code: str, detail: str) -> None:
        issues.append({"code": code, "detail": detail[:140]})

    if _ARABIC_LEFTOVER.search(text):
        note("arabic-forms", "Arabic yeh/kaf/tatweel or Arabic-Indic digits remain")
    opens, closes = text.count("«"), text.count("»")
    if opens != closes:
        note("guillemets", f"unbalanced Persian quotes: {opens} « vs {closes} »")
    if '"' in text or "“" in text or "”" in text:
        note("latin-quotes", "Latin quotation marks in Persian dialogue")
    if _DOUBLE_PUNCT.search(text):
        note("double-punctuation", "repeated punctuation mark")
    ambiguous = _AMBIGUOUS_JOIN.search(text)
    if ambiguous:
        note("zwnj-review",
             f"`{ambiguous.group(0)}` may want a ZWNJ, or may be two words "
             "— only a reader can tell; not changed automatically")

    counts = ir.script_counts(text)
    total = sum(counts.values())
    if total:
        match = _LATIN_SENTENCE.search(text)
        if match and counts["latin"] / total > 0.35:
            note("untranslated", f"long Latin passage: {match.group(0)[:70]}")
        source_script = counts["hiragana"] + counts["katakana"] + counts["han"] + counts["hangul"]
        if source_script:
            note("source-script-left",
                 f"{source_script} character(s) of the source script survive")
        if counts["arabic"] == 0:
            note("untranslated", "no Persian characters at all")

    if re.search(rf"[{PERSIAN_LETTER}][A-Za-z]|[A-Za-z][{PERSIAN_LETTER}]", text):
        note("script-collision", "Latin and Persian letters with no space between")
    return issues


# --------------------------------------------------------------------------- #
# Document driver
# --------------------------------------------------------------------------- #

def fix_document(doc_path: str | Path, options: Options | None = None) -> dict[str, Any]:
    doc_path = Path(doc_path)
    doc = ir.load_doc(doc_path)
    options = options or Options()
    changed: list[str] = []
    for _, region in ir.iter_regions(doc):
        before = region.get("target_text") or ""
        after = fix_text(before, options)
        if after != before:
            region["target_text"] = after
            changed.append(region["id"])
    stages.stamp_stage(doc, "falint", {"changed": len(changed)})
    ir.save_doc(doc, doc_path)
    return {"changed": changed[:40], "changed_count": len(changed)}


def lint_document(doc_path: str | Path) -> dict[str, Any]:
    doc = ir.load_doc(Path(doc_path))
    findings: list[dict[str, Any]] = []
    for _, region in ir.iter_regions(doc):
        if region.get("dropped"):
            continue
        for issue in lint_text(region.get("target_text") or ""):
            findings.append({"region": region["id"], **issue})
    by_code: dict[str, int] = {}
    for finding in findings:
        by_code[finding["code"]] = by_code.get(finding["code"], 0) + 1
    return {"findings": findings[:40], "count": len(findings), "by_code": by_code}


def main(argv: list[str] | None = None) -> int:
    ir.use_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="revayat-comic falint",
        description="Persian typography: fix mechanically, or report.",
    )
    parser.add_argument("action", choices=["fix", "lint"])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--digits", choices=["persian", "keep"], default="persian")
    parser.add_argument("--no-quotes", action="store_true")
    parser.add_argument("--no-zwnj", action="store_true")
    parser.add_argument("--no-ellipsis", action="store_true")
    args = parser.parse_args(argv)

    if args.action == "fix":
        report = fix_document(args.doc, Options(
            digits=args.digits,
            quotes=not args.no_quotes,
            zwnj=not args.no_zwnj,
            ellipsis=not args.no_ellipsis,
        ))
    else:
        report = lint_document(args.doc)
    ir.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
