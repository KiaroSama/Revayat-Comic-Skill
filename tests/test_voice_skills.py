"""Contracts for the published voice skills and manual project validation."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/revayat-comic"
VOICE = SKILL / "references/voice"


@pytest.mark.parametrize(("tag", "name"), [("fa", "persian"), ("en", "humanizer"), ("ru", "great-russian")])
def test_documented_voice_route_uses_output_language(tag, name):
    workflow = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "references/voice/index.md" in workflow
    guide = (VOICE / "index.md").read_text(encoding="utf-8")
    assert f"| `{tag}` | [{name}]({name}/SKILL.md) |" in guide
    assert "output language, not the source language" in guide
    assert "Persian-only" in guide
    assert "no matching guide" in guide


@pytest.mark.parametrize(("name", "required"), [
    ("humanizer", ()),
    ("great-russian", ("references/typography.md", "references/style-matching.md")),
    ("persian", ("NOTICE", "scripts/persian_lint.py", "scripts/lookup.py",
                 "scripts/data/glossary.tsv", "scripts/data/idioms.tsv", "references/review-lenses.md")),
])
def test_voice_skill_is_registered_and_in_the_standalone_payload(name, required):
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    folder = VOICE / name
    assert "./" + folder.relative_to(ROOT).as_posix() + "/" in plugin["skills"]
    manifest = set((ROOT / "install/skill-files.txt").read_text(encoding="utf-8").splitlines())
    files = {p.relative_to(SKILL).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert files <= manifest
    for member in ("SKILL.md", "LICENSE", *required):
        assert (folder / member).relative_to(SKILL).as_posix() in files
    assert (folder / "SKILL.md").read_text(encoding="utf-8").splitlines()[1] == f"name: {name}"
    assert "MIT License" in (folder / "LICENSE").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["ci", "integration", "source-evidence"])
def test_project_validation_is_manual(name):
    workflow = (ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert triggers == "  workflow_dispatch:"
