"""Code-fence boundaries do not hide Persian prose from isolation."""

import pytest

from bidi_rli import PDI, RLI, with_rli_pdi


@pytest.mark.parametrize("marker", ["`", "~"])
@pytest.mark.parametrize("extra_markers", [1, 2])
def test_longer_closing_fence_does_not_hide_following_prose(marker, extra_markers):
    code = f"{marker * 3}\nTokyo رسید.\n{marker * (3 + extra_markers)}\n"
    expected = code + f"{RLI}Kyoto رسید.{PDI}"

    assert with_rli_pdi(code + "Kyoto رسید.") == (expected, 1)
    assert with_rli_pdi(expected) == (expected, 0)


@pytest.mark.parametrize("marker", ["`", "~"])
def test_shorter_fence_does_not_end_a_protected_code_block(marker):
    text = f"{marker * 4}\nTokyo رسید.\n{marker * 3}\nKyoto رسید."

    assert with_rli_pdi(text) == (text, 0)


@pytest.mark.parametrize(("opening", "closing"), [("`", "~"), ("~", "`")])
def test_different_fence_marker_does_not_end_a_protected_code_block(opening, closing):
    text = f"{opening * 3}\nTokyo رسید.\n{closing * 3}\nKyoto رسید."

    assert with_rli_pdi(text) == (text, 0)
