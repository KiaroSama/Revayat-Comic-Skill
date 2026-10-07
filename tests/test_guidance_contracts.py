"""Shipped secondary instructions preserve primary safety policy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "skills" / "revayat-comic" / "references"


def test_secondary_guidance_does_not_relax_preservation():
    detection = (REF / "detection.md").read_text(encoding="utf-8")
    trouble = (REF / "troubleshooting.md").read_text(encoding="utf-8")
    typesetting = (REF / "persian-typesetting.md").read_text(encoding="utf-8")
    assert "Downsample the pages before importing" not in detection
    assert "or lower `--dpi`" not in trouble
    assert "put a reverse proxy in front" not in trouble
    assert "--min-size 11" not in typesetting
    assert "fa_full" in typesetting
    assert "qa check --doc" in trouble
    assert "YesAndRightToLeft" in trouble


def test_resume_preserves_accepted_persian_and_current_pair_review():
    text = (ROOT / "commands" / "revayat-comic-resume.md").read_text(encoding="utf-8")
    assert "Re-translate those pages" not in text
    assert "worksheet reconcile" in text
    assert "source/full/display" in text


def test_authority_is_not_derived_from_rendered_ink():
    text = (REF / "artwork-preservation.md").read_text(encoding="utf-8")
    assert "boxes actually painted" not in text
    assert "independently approved" in text
    assert "working `--provider`" in text


def test_repo_only_evaluation_is_not_an_installed_path_dependency():
    text = (REF / "translation-policy.md").read_text(encoding="utf-8")
    assert "https://github.com/KiaroSama/Revayat-Comic-Skill/blob/main/evaluation/README.md" in text
    assert "standalone installed skill" in text
    assert "[evaluation.md](evaluation.md)" in text
