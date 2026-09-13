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
from typing import Any, Sequence

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

#: A span that is Latin because of what it IS — an address, not a word. These
#: are the ones a script-mix check has to look past: an email address in a
#: balloon is not an untranslated sentence, and no edit can make it Persian.
_STRUCTURED = r"""
    (?:https?://|www\.)\S+
    | [\w.+-]+@[\w-]+\.[\w.-]+
    | \b[0-9]{1,4}(?:[.:/-][0-9]{1,4})+\b
"""
#: Everything the FIXER keeps its hands off: the above, plus any Latin word,
#: because folding an Arabic kaf or pairing a quote inside one corrupts it.
_PROTECTED = re.compile(
    rf"""(?xi)
    {_STRUCTURED}
    | \b[A-Za-z][\w.'’-]*\b
    """
)
_STRUCTURED_ONLY = re.compile(rf"(?xi){_STRUCTURED}")

# The possessive family, joined automatically. These carry a personal ending —
# `هایم`, `هایت`, `هایشان` — and the interjection takes none, so no reading of
# them is anything but the plural plus a possessive. That is morphology, not a
# guess about which word is likelier.
_ZWNJ_SUFFIXES = (
    "هایشان", "هایتان", "هایمان", "هایی", "هایم", "هایت", "هایش",
)

#: Bare `ها` and `های` are NOT in that list, and the comment that used to
#: justify them said "the interjection does not sit immediately after a noun
#: with a space before it" — which the code never tested. It tested for two
#: Persian letters, and in conversational Persian `حواست باشه ها!` and
#: `این کار رو نکن ها.` carry the warning particle after a VERB. They came out
#: as `باشه‌ها` and `نکن‌ها`, which is not what either sentence says. `های` is
#: no safer: `های های گریه کرد` is sobbing, not a plural.
#:
#: So the bare forms are joined only where the NEXT word settles it. `را` is
#: the direct-object marker and a bare `ی` is the ezafe; both can only follow a
#: complete noun phrase, and the particle never closes one. Everything else
#: goes to a reader.
_ANCHORED_PLURAL = re.compile(
    rf"([{PERSIAN_LETTER}]{{2,}}) +(های|ها)(?= +(?:را|ی)\b)"
)
#: Prefixes joined automatically: none.
#:
#: `نمی` was here on the grounds that it "is not a Persian word by itself". It
#: is: نَمی, *a trace of moisture* — `نمی از باران روی صورتم نشست` is an
#: ordinary sentence, and the rule turned its subject into the negative prefix
#: of the following preposition.
_ZWNJ_PREFIXES: tuple[str, ...] = ()

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
#: `می` is two words in Persian. It is the imperfective prefix — `می‌روم` — and
#: it is also the noun *wine*. The two are written identically and only the
#: NEXT word separates them.
#:
#: The previous rule joined `می` to anything ending in one of م و ی د ن ه, on
#: the theory that those are conjugation endings. They are also the last letter
#: of ordinary adjectives and nouns, so `می شیرین را نوشید` (*he drank the sweet
#: wine*) became `می‌شیرین`, and so did `می کهنه` (*old wine*) and `می گران`
#: (*expensive wine*). A guess that changes the meaning of a sentence is worse
#: than no rule, because the reader is never asked.
#:
#: A closed list of conjugated forms was tried next, and a closed list is still
#: a guess about the word AFTER it, which is the word that decides. `بر` is on
#: it as the stem of *بردن*, and it is also the preposition *on*:
#: `می بر زمین ریخت` — *the wine spilled on the ground* — became `می‌بر`. `ده`
#: is on it, and `می ده‌ساله را آورد` became `می‌ده‌ساله`.
#:
#: **So nothing prefixed with `می` is joined automatically any more.** The list
#: below survives as the vocabulary the REVIEW note reads from, so the
#: suggestion can say which reading it has in mind; it applies nothing. Three
#: more exceptions would not have closed this — the rule was unsafe in kind,
#: not in coverage, and this module's own comment says it: a tool that quietly
#: rewrites a sentence is worse than one that leaves a typo.
_MI_STEMS = (
    "رو", "کن", "شو", "خواه", "توان", "دان", "گوی", "بین", "آی", "گیر",
    "ده", "خور", "زن", "برم", "بر", "آور", "افت", "رس", "مان", "نویس",
    "خوان", "پرس", "ترس", "فهم", "شناس", "ایست", "نشین", "گرد", "کش",
    "دار", "گذار", "ساز", "شکن", "بند", "پوش", "خند", "گری",
)
#: The person endings those stems take. `می‌روم`, `می‌روی`, `می‌رود`, …
_MI_ENDINGS = ("م", "ی", "د", "یم", "ید", "ند", "")

#: Every form the rule will join, built once.
MI_VERBS = frozenset(
    stem + ending for stem in _MI_STEMS for ending in _MI_ENDINGS)

_SUFFIX_SPACE = re.compile(
    rf"([{PERSIAN_LETTER}]{{2,}}) +({'|'.join(_ZWNJ_SUFFIXES)})\b"
)
#: `می` followed by a form this project can name as a verb — REPORTED, so the
#: note can say "this looks like the imperfective prefix" rather than only
#: "something here is ambiguous".
_MI_VERB = re.compile(
    rf"\b(می) +({'|'.join(sorted(MI_VERBS, key=len, reverse=True))})\b"
)
#: Everything a reader has to decide: a comparative that may be the adjective
#: *wet*, and every `می`/`نمی` — both of which are ordinary nouns as well as
#: prefixes, and neither of which any pattern here can tell apart.
_AMBIGUOUS_JOIN = re.compile(
    rf"[{PERSIAN_LETTER}]{{2,}} +(?:{'|'.join(_AMBIGUOUS_SUFFIXES)})\b"
    # A bare plural nothing anchors: the plural suffix, or the colloquial
    # particle that turns a sentence into a warning.
    rf"|[{PERSIAN_LETTER}]{{2,}} +(?:های|ها)\b(?! +(?:را|ی)\b)"
    rf"|\b(?:نمی|می) +[{PERSIAN_LETTER}]{{2,}}"
)

#: The bare plural, for a note that can name both readings instead of saying
#: only that something here is ambiguous.
_BARE_PLURAL = re.compile(rf"[{PERSIAN_LETTER}]{{2,}} +(?:های|ها)\b")

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
        # The possessive family, plus a bare plural the next word anchors. The
        # test for whether a join belongs here is not "this is usually right"
        # but "this cannot be wrong".
        #
        # "کتاب ها ی" style chains need more than one pass to settle.
        for _ in range(3):
            replaced = _ANCHORED_PLURAL.sub(rf"\1{ZWNJ}\2", text)
            replaced = _SUFFIX_SPACE.sub(rf"\1{ZWNJ}\2", replaced)
            if replaced == text:
                break
            text = replaced

    return _MULTI_SPACE.sub(" ", text)


def segments(text: str):
    """`(is_protected, piece)` across the whole line, in order.

    ONE lexer, used by the fixer and by the linter. They had one each: the
    fixer left a URL alone and the linter then reported the Arabic letters
    inside it as `arabic-forms`, demanding an edit the fixer would never make
    and QA would never stop asking for.
    """
    last = 0
    for match in _PROTECTED.finditer(text):
        if match.start() > last:
            yield False, text[last:match.start()]
        # A URL, an email address or a Latin word, byte for byte. Folding an
        # Arabic kaf, converting a digit or pairing a quote inside one of these
        # produces a dead link that still looks like a link.
        yield True, match.group(0)
        last = match.end()
    if last < len(text):
        yield False, text[last:]


def unprotected(text: str) -> str:
    """The line with every protected span blanked, for a check to read."""
    return "".join(" " * len(piece) if guarded else piece
                   for guarded, piece in segments(text))


def without_addresses(text: str) -> str:
    """The line with URLs, emails and numeric runs blanked — Latin WORDS kept.

    The narrower view, for the checks that ask what script this line is in.
    `unprotected` blanks every Latin word, so an English sentence left
    untranslated came back as blanks and the gate that exists to catch exactly
    that stopped firing. An address, by contrast, is Latin because of what it
    is: no edit makes it Persian, so measuring it as missing translation asks
    for a change nobody can make.
    """
    return _STRUCTURED_ONLY.sub(lambda m: " " * len(m.group(0)), text)


def _pair_quotes(text: str, options: Options) -> str:
    """Turn `"…"` into `«…»` across the whole line, protected spans included.

    Pairing happened inside each unprotected piece, so a quotation that has a
    Latin word in it — `گفت: "سلام Bob"` — was two pieces with one mark each
    and neither could find its partner. The marks are rewritten in place; not a
    byte between them is touched.
    """
    if not options.quotes:
        return text
    blanked = unprotected(text)
    out = list(text)
    opening = None
    for index, char in enumerate(blanked):
        if char not in '"\u201c\u201d':
            continue
        if opening is None:
            opening = index
            continue
        out[opening], out[index] = "«", "»"
        opening = None
    return "".join(out)


def _fix_once(text: str, options: Options) -> str:
    persian_line = bool(_HAS_PERSIAN.search(text))
    text = _pair_quotes(text, options)
    return "".join(
        piece if guarded else _fix_segment(piece, options, persian_line)
        for guarded, piece in segments(text))


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


def ambiguous_spans(text: str) -> list[str]:
    """Every `X Y` a reader would be asked about, in order.

    What a `zwnj-review` acknowledgment is recorded AGAINST, so it settles the
    words somebody actually looked at.
    """
    if not (text or "").strip():
        return []
    return [match.group(0)
            for match in _AMBIGUOUS_JOIN.finditer(unprotected(text))]


def record_acknowledgement(region: dict[str, Any], codes: Sequence[str],
                           target: str) -> None:
    """Store what a reader settled, and the exact text it was settled about.

    One writer, so a waiver cannot be recorded in a shape only one reader
    understands. The spans are what stop a bare code silencing a line for ever:
    a later edit introduces words nobody has looked at, and a decision taken
    about a different pair must not cover them.
    """
    region["review_ack"] = list(codes)
    spans = ambiguous_spans(target)
    if "compressed-variant" in codes:
        # What that one is about is the shortened line itself. Recorded the
        # same way, so the same rule applies to it: change the line and the
        # pair has to be read again.
        spans.append((target or "").strip())
    region["review_ack_spans"] = spans


def settled(region: dict[str, Any], code: str, span: str | None = None) -> bool:
    """Has a reader settled `code` here, for these words?

    `review_ack_spans` missing means the region predates span records and the
    code alone still stands — an older document is not evidence of anything
    wrong.
    """
    if code not in (region.get("review_ack") or ()):
        return False
    spans = region.get("review_ack_spans")
    return spans is None or span is None or span in set(spans)


def lint_region(region: dict[str, Any]) -> list[dict[str, str]]:
    """Lint one region with that region's own acknowledgements.

    One entry point, because there were two and they disagreed: the gate passed
    the codes AND the spans, `lint_document` passed only the codes — so the
    standalone linter honoured a waiver for ever while the gate re-asked, and
    which answer a reader got depended on which command they ran.
    """
    return lint_text(region.get("target_text") or "",
                     acknowledged=region.get("review_ack") or (),
                     acknowledged_spans=region.get("review_ack_spans"))


def lint_text(text: str, *, acknowledged: Sequence[str] = (),
              acknowledged_spans: Sequence[str] | None = None
              ) -> list[dict[str, str]]:
    """What a reader still has to decide about this line.

    `acknowledged` are codes somebody has already looked at and settled — a
    `zwnj-review` on a word they confirmed is two words. Without it strict QA
    asked for the same unsafe edit on every run, and the only ways to silence
    it were to make the edit or to stop running the gate.

    `acknowledged_spans` is what that decision was ABOUT. A bare code settled
    the line for ever, so a later edit that introduced a different ambiguity
    was silenced by a decision taken about a different pair of words. `None`
    means the region predates this record and the code alone still stands —
    an older document is not evidence of anything wrong.
    """
    issues: list[dict[str, str]] = []
    if not (text or "").strip():
        return issues
    settled = set(acknowledged or ())

    def note(code: str, detail: str) -> None:
        if code not in settled:
            issues.append({"code": code, "detail": detail[:140]})

    # Everything below reads the line with URLs, emails and Latin words blanked
    # out — the same spans the fixer refuses to touch. Reporting an Arabic kaf
    # inside a URL asked for an edit that would break the link.
    visible = unprotected(text)
    if _ARABIC_LEFTOVER.search(visible):
        note("arabic-forms", "Arabic yeh/kaf/tatweel or Arabic-Indic digits remain")
    opens, closes = visible.count("«"), visible.count("»")
    if opens != closes:
        note("guillemets", f"unbalanced Persian quotes: {opens} « vs {closes} »")
    if '"' in visible or "“" in visible or "”" in visible:
        note("latin-quotes", "Latin quotation marks in Persian dialogue")
    if _DOUBLE_PUNCT.search(visible):
        note("double-punctuation", "repeated punctuation mark")
    ambiguous = next(
        (match for match in _AMBIGUOUS_JOIN.finditer(visible)
         if acknowledged_spans is None
         or match.group(0) not in set(acknowledged_spans)),
        None)
    if ambiguous and acknowledged_spans is not None:
        # The decision was about specific words; the code alone no longer
        # silences a pair nobody has seen.
        settled.discard("zwnj-review")
    if ambiguous:
        found = ambiguous.group(0)
        if _MI_VERB.fullmatch(found):
            reading = " — this reads like the imperfective prefix"
        elif _BARE_PLURAL.fullmatch(found):
            reading = (" — the plural suffix, or the colloquial particle that "
                       "makes this a warning")
        else:
            reading = ", or may be two words"
        note("zwnj-review",
             f"`{found}` may want a ZWNJ{reading}"
             " — only a reader can tell; not changed automatically")

    # `visible`, not `text`. A protected span — an email address, a URL — is
    # Latin by construction and the fixer will never touch it, so measuring the
    # script mix over the raw line reported `untranslated` on a balloon that
    # was correct and offered no edit that could ever clear it.
    addressless = without_addresses(text)
    counts = ir.script_counts(addressless)
    total = sum(counts.values())
    if total:
        match = _LATIN_SENTENCE.search(addressless)
        if match and counts["latin"] / total > 0.35:
            note("untranslated", f"long Latin passage: {match.group(0)[:70]}")
        source_script = counts["hiragana"] + counts["katakana"] + counts["han"] + counts["hangul"]
        if source_script:
            note("source-script-left",
                 f"{source_script} character(s) of the source script survive")
        if counts["arabic"] == 0:
            note("untranslated", "no Persian characters at all")

    if re.search(rf"[{PERSIAN_LETTER}][A-Za-z]|[A-Za-z][{PERSIAN_LETTER}]",
                 addressless):
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
        for issue in lint_region(region):
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
