"""Mixed-direction sentences retain their logical spelling and punctuation."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import bidi_rli
import falint
import typefont

SCRIPTS = Path(typefont.__file__).resolve().parent
VOICE = SCRIPTS.parent / "references" / "voice" / "persian" / "scripts" / "persian_lint.py"
RLI, PDI = "⁧", "⁩"


@pytest.mark.parametrize(("text", "expected"), [
    ("Tokyo رسید.", f"{RLI}Tokyo رسید.{PDI}"),
    ("  «Tokyo رسید!»  ", f"  {RLI}«Tokyo رسید!»{PDI}  "),
    ("[Tokyo رسید]", f"{RLI}[Tokyo رسید]{PDI}"),
    ("‎Tokyo رسید", f"{RLI}‎Tokyo رسید{PDI}"),
    ("2Tokyo رسید", "2Tokyo رسید"),
    ("امروز Tokyo رسید.", "امروز Tokyo رسید."),
    ("Tokyo arrived.", "Tokyo arrived."),
    ("Tokyo. امروز رسید.", "Tokyo. امروز رسید."),
    ("امروز رسید. Tokyo کجاست؟", f"امروز رسید. {RLI}Tokyo کجاست؟{PDI}"),
    ("Tokyo رسید! Osaka نیومد.\r\nامروز رسید.\nKyoto کجاست؟",
     f"{RLI}Tokyo رسید!{PDI} {RLI}Osaka نیومد.{PDI}\r\nامروز رسید.\n{RLI}Kyoto کجاست؟{PDI}"),
    ("Dr. Asano گفت این کده: `x. y?` از https://ex.org/a.b یا a.b@ex.org بگیر.",
     f"{RLI}Dr. Asano گفت این کده: `x. y?` از https://ex.org/a.b یا a.b@ex.org بگیر.{PDI}"),
    ("«Tokyo رسید.» Oslo نرسید.", f"{RLI}«Tokyo رسید.»{PDI} {RLI}Oslo نرسید.{PDI}"),
    (f"{RLI}{RLI}Tokyo رسید.{PDI}{PDI}", f"{RLI}Tokyo رسید.{PDI}"),
    (f"{RLI}Tokyo رسید.", f"{RLI}Tokyo رسید.{PDI}"),
    (f"Tokyo رسید.{PDI}", f"{RLI}Tokyo رسید.{PDI}"),
    (f"Tokyo گفت ⁦OK.{PDI} همین الان.", f"{RLI}Tokyo گفت ⁦OK.{PDI} همین الان.{PDI}"),
    ("⁦Tokyo رسید.", f"{RLI}Tokyo رسید.{PDI}"),
    (f"{RLI}Tokyo{PDI} رسید.", f"{RLI}Tokyo رسید.{PDI}"),
    (f"Tokyo رسید {RLI}", f"{RLI}Tokyo رسید{PDI}"),
    ("```\nTokyo رسید.\n```\nKyoto رسید.", f"```\nTokyo رسید.\n```\n{RLI}Kyoto رسید.{PDI}"),
])
def test_isolates_matching_sentences_without_changing_their_contents(text, expected):
    from bidi_rli import ensure_rli_pdi

    assert ensure_rli_pdi(text) == expected
    assert ensure_rli_pdi(expected) == expected


def test_latin_predicate_skips_quotes_brackets_and_isolates():
    from bidi_rli import starts_with_latin_in_persian

    assert starts_with_latin_in_persian(f" «{RLI}(Tokyo رسید.){PDI}»")
    assert not starts_with_latin_in_persian("Tokyo arrived, everyone.")
    assert not starts_with_latin_in_persian("امروز Tokyo رسید.")


def test_comic_linter_detects_and_fixes_isolates():
    original = "Tokyo رسید. Osaka نیومد."
    fixed = f"{RLI}Tokyo رسید.{PDI} {RLI}Osaka نیومد.{PDI}"
    assert "missing-rli-pdi" in {issue["code"] for issue in falint.lint_text(original)}
    assert falint.fix_text(original) == fixed
    assert all(issue["code"] != "missing-rli-pdi" for issue in falint.lint_text(fixed))
    assert falint.fix_text(fixed) == fixed


def test_bundled_voice_cli_reports_and_fixes_isolates(tmp_path):
    original = tmp_path / "dialogue.txt"
    original.write_text("Tokyo رسید.\n```\nTokyo رسید.\n```\n", encoding="utf-8")

    def run(*args):
        return subprocess.run([sys.executable, str(VOICE), *args, str(original)],
                              cwd=tmp_path, capture_output=True, encoding="utf-8", timeout=15)

    checked = run("--check", "--json")
    assert checked.returncode == 1, checked.stderr
    assert json.loads(checked.stdout)["stats"]["missing-rli-pdi"] == 1
    assert run("--fix", "--in-place").returncode == 0
    assert original.read_text(encoding="utf-8") == f"{RLI}Tokyo رسید.{PDI}\n```\nTokyo رسید.\n```\n"
    assert run("--check").returncode == 0


def test_raqm_preparation_isolates_unlinted_text(monkeypatch):
    # Select the preparation path independently of the host's FriBiDi installation.
    monkeypatch.setattr(typefont, "raqm_available", lambda: True)
    shaper = typefont.Shaper()
    assert shaper.prepare("Tokyo رسید؟") == f"{RLI}Tokyo رسید؟{PDI}"


def test_fallback_receives_isolates_before_shaping(monkeypatch):
    expected = f"{RLI}Tokyo رسید؟{PDI}"
    shaper = typefont.Shaper(force_fallback=True)

    def render(isolated):
        assert isolated == expected
        return "rendered"

    monkeypatch.setattr(typefont, "shape_fallback", render)
    assert shaper.prepare("Tokyo رسید؟") == "rendered"


def test_ensure_rlm_rli_pdi_locks_persian_lines_and_keeps_english_plain():
    sample = "Spec Kit: CHAIN\nMBI صاحب اصلی بود.\nساده و روان."
    wrapped = bidi_rli.ensure_rlm_rli_pdi(sample)
    lines = wrapped.splitlines()
    assert lines[0] == "Spec Kit: CHAIN"
    assert lines[1] == f"{bidi_rli.RLM}{RLI}MBI صاحب اصلی بود.{PDI}"
    assert lines[2] == f"{bidi_rli.RLM}{RLI}ساده و روان.{PDI}"
    assert bidi_rli.ensure_rlm_rli_pdi(wrapped) == wrapped

