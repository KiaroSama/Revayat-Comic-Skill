"""Contract tests for both the Python oracle and optional native text kernels."""

from itertools import combinations, product

import pytest

import bidi_rli

RLM, RLI, PDI = "‏", "⁧", "⁩"
LOCK = RLM + RLI

BIDI_CASES = (
    "Tokyo رسید.",
    "  «Tokyo رسید!»  ",
    "[Tokyo رسید]",
    "‎Tokyo رسید",
    "2Tokyo رسید",
    "امروز Tokyo رسید.",
    "Tokyo arrived.",
    "Tokyo. امروز رسید.",
    "امروز رسید. Tokyo کجاست؟",
    "Tokyo رسید! Osaka نیومد.\r\nامروز رسید.\nKyoto کجاست؟",
    "Dr. Asano گفت این کده: `x. y?` از https://ex.org/a.b یا a.b@ex.org بگیر.",
    "«Tokyo رسید.» Oslo نرسید.",
    f"{RLI}{RLI}Tokyo رسید.{PDI}{PDI}",
    f"{RLI}Tokyo رسید.",
    f"Tokyo رسید.{PDI}",
    f"Tokyo گفت ⁦OK.{PDI} همین الان.",
    "⁦Tokyo رسید.",
    f"{RLI}Tokyo{PDI} رسید.",
    f"Tokyo رسید {RLI}",
    "```\nTokyo رسید.\n```\nKyoto رسید.",
    f" «{RLI}(Tokyo رسید.){PDI}»",
    "Tokyo arrived, everyone.",
    "امروز Tokyo رسید.",
    "Tokyo رسید. Osaka نیومد.",
    "Tokyo رسید؟",
    "Spec Kit: CHAIN\nMBI صاحب اصلی بود.\nساده و روان.",
    "\x1c『A سلام.』 \rB. C. D رسید. é رسید.\x85 A.B سلام؟",
    "Tokyo سلام https://example.test/a.b. Kyoto رسید!",
    "Tokyo با ``x. ` y?`` رسید. Kyoto رسید!",
    f"Tokyo{RLI}رسید. Osaka{PDI}نیومد.",
    "",
)
FENCE_CASES = tuple(
    f"{marker * opener}\nTokyo رسید.\n{closer * close}\nKyoto رسید."
    for marker, closer, opener, close in (
        ("`", "`", 3, 4), ("`", "`", 3, 5), ("~", "~", 3, 4), ("~", "~", 3, 5),
        ("`", "`", 4, 3), ("~", "~", 4, 3), ("`", "~", 3, 3), ("~", "`", 3, 3),
    )
) + (
    "   ~~~fa\r\nTokyo رسید.\r\n ~~~~ \t\r\nKyoto رسید.",
    "    ~~~\nTokyo رسید.\n    ~~~\nKyoto رسید.",
    "```\nTokyo رسید.\n``` suffix\nKyoto رسید.\n`````",
)
NORMALIZE_CASES = (
    ("عـلي، كتاب و مدرسة هدى", "علی، کتاب و مدرسه هدی"),
    ("سال 2024، روز ١٢; چند؟ 7 کتاب", "سال ۲۰۲۴، روز ۱۲؛ چند؟ ۷ کتاب"),
    ("چرا? بعد; تمام, بله", "چرا؟ بعد؛ تمام، بله"),
    ("واژه دوم سوم\x85آخر\r\nپایان", "واژه\nدوم\nسوم\nآخر\r\nپایان"),
    ("مي رود و نمي دانم؛ بهترين و بهتر ترین. كتاب ها را ببین.",
     "می‌رود و نمی‌دانم؛ بهترین و بهتر‌ترین. کتاب‌ها را ببین."),
    ("می‌ رود، كتاب ‌هایم، خوب‌ ترین", "می‌رود، کتاب‌هایم، خوب‌ترین"),
    ("حواست باشه ها! این کار رو نکن ها. می بر زمین ریخت.",
     "حواست باشه ها! این کار رو نکن ها. می بر زمین ریخت."),
    ("عدد 1.2.3 و v2.0-beta؛ https://example.test/ي12 و نام١@ex.test `كي 12?`",
     "عدد 1.2.3 و v2.0-beta؛ https://example.test/ي12 و نام١@ex.test `كي 12?`"),
    ("~~~fa\nكي 12?\n~~~~\nكي 12?", "~~~fa\nكي 12?\n~~~~\nکی ۱۲؟"),
    ("قبل ```\nكي 12?\n```\nكي 12?", "قبل\n```\nكي 12?\n```\nکی ۱۲؟"),
    ("Version 12, what? مرحبا", "Version 12, what؟ مرحبا"),
    ("A1, B2; v2.00?", "A1, B2; v2.00?"),
    ("", ""),
)
WRAP_CASES = (
    (([4, 4, 4], 1, [10, 5]), [[0, 2], [2, 3]]),
    (([4, 4, 4], 1, [5, 10]), [[0, 1], [1, 3]]),
    (([3, 1, 1, 3], 1, [8, 8]), [[0, 2], [2, 4]]),
    (([4, 4, 4], 1, [10, 10]), [[0, 1], [1, 3]]),
    (([4, 4], 0, [8, 4]), [[0, 2]]),
    (([2, 3], 1, [1, 30]), []),
    (([2, 3], 1, [3]), []),
    (([2], 0, [0]), []),
    (([], 0, [0]), []),
    (([2**100, 1, 2**100], 0, [2**101, 2**101]), [[0, 1], [1, 3]]),
)
WRAP_ERRORS = (
    (([-1], 0, [2]), "word widths must be positive"),
    (([0], 0, [2]), "word widths must be positive"),
    (([1], -1, [2]), "space width must be non-negative"),
    (([1], 0, [-1]), "band widths must be non-negative"),
    (([], 0, []), "band widths must not be empty"),
)


@pytest.fixture(params=["reference", "selected"])
def text_backend(request):
    from importlib import import_module, util

    assert util.find_spec("textcore") is not None, "textcore is not available"
    if request.param == "reference":
        return import_module("textcore.kernels")
    backend = import_module("textcore")
    # A wheel present but silently falling back must fail the native verification lane.
    if util.find_spec("textcore_rs") is not None:
        assert backend.BACKEND == "rust"
    return backend


@pytest.mark.parametrize("text", BIDI_CASES + FENCE_CASES)
def test_sentence_isolation_matches_legacy(text_backend, text):
    assert text_backend.starts_with_latin_in_persian(text) == bidi_rli.starts_with_latin_in_persian(text)
    expected = bidi_rli.ensure_rli_pdi(text)
    assert text_backend.ensure_rli_pdi(text) == expected
    assert text_backend.ensure_rli_pdi(expected) == expected


@pytest.mark.parametrize("text", BIDI_CASES[:19] + BIDI_CASES[20:25])
def test_paragraph_isolation_matches_legacy_outside_fences(text_backend, text):
    expected = bidi_rli.ensure_rlm_rli_pdi(text)
    assert text_backend.ensure_rlm_rli_pdi(text) == expected
    assert text_backend.ensure_rlm_rli_pdi(expected) == expected


def test_paragraph_isolation_preserves_fenced_code(text_backend):
    code = "   ~~~ زبان\r\nTokyo رسید.\r\n ~~~~ \t\r\n"
    text = code + "  کیوتو رسید.   English only.\x85آخر."
    expected = code + f"  {LOCK}کیوتو رسید.{PDI}   English only.\x85{LOCK}آخر.{PDI}"
    assert text_backend.ensure_rlm_rli_pdi(text) == expected
    assert text_backend.ensure_rlm_rli_pdi(expected) == expected


@pytest.mark.parametrize(("text", "expected"), NORMALIZE_CASES)
def test_normalization_preserves_protected_text_and_is_idempotent(text_backend, text, expected):
    assert text_backend.normalize_persian_text(text) == expected
    assert text_backend.normalize_persian_text(expected) == expected


@pytest.mark.parametrize(("args", "expected"), WRAP_CASES)
def test_balanced_wrap_contract(text_backend, args, expected):
    assert text_backend.balanced_wrap_lines(*args) == expected


@pytest.mark.parametrize(("args", "message"), WRAP_ERRORS)
def test_balanced_wrap_rejects_invalid_geometry(text_backend, args, message):
    with pytest.raises(ValueError, match=message):
        text_backend.balanced_wrap_lines(*args)


def test_balanced_wrap_matches_exhaustive_minimum(text_backend):
    for words in product(range(1, 4), repeat=4):
        for bands in ([3, 5, 6], [6, 3, 5], [6, 8], [11, 5, 2]):
            feasible = []
            for count in range(min(len(words), len(bands))):
                for cuts in combinations(range(1, len(words)), count):
                    ends = (*cuts, len(words))
                    widths = [sum(words[i:j]) + j - i - 1 for i, j in zip((0, *cuts), ends, strict=True)]
                    gaps = [band - width for band, width in zip(bands, widths)]
                    if min(gaps) >= 0:
                        feasible.append((sum(gap * gap for gap in gaps), ends))
            ends = min(feasible)[1] if feasible else ()
            expected = [[i, j] for i, j in zip((0, *ends), ends)]
            assert text_backend.balanced_wrap_lines(list(words), 1, bands) == expected
