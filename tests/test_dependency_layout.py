"""Manifest boundary and consuming lanes, without changing any environment."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def requirements(path):
    return {line.split("#", 1)[0].strip().split(">=", 1)[0].lower()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()}


def test_runtime_manifest_excludes_all_developer_tools():
    runtime = requirements(ROOT / "skills/revayat-comic/requirements.txt")
    developer = requirements(ROOT / "tests/requirements.txt")
    assert {"pytest", "pytest-timeout", "ruff", "fonttools"} <= developer
    assert not runtime & developer
    assert runtime == {"pillow", "numpy", "opencv-python-headless", "pymupdf",
                       "arabic-reshaper", "python-bidi"}


def test_test_and_lint_lanes_install_the_developer_manifest():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for name, next_name in (("test", "minimum-dependencies"),
                            ("minimum-dependencies", "pipeline"), ("lint", None)):
        job = text.split(f"  {name}:", 1)[1]
        if next_name:
            job = job.split(f"  {next_name}:", 1)[0]
        assert "python -m pip install -r tests/requirements.txt" in job, name
    # End-to-end still proves runtime-only installation; stdlib owns its children.
    pipeline = text.split("  pipeline:", 1)[1].split("  install:", 1)[0]
    assert "tests/requirements.txt" not in pipeline
    assert "python tests/e2e_pipeline.py" in pipeline
    integration = (ROOT / ".github/workflows/integration.yml").read_text(encoding="utf-8")
    assert "python -m pip install -r tests/requirements.txt" in integration.split("  full_resolution:", 1)[0]


def test_advisory_and_update_consumers_keep_both_manifests():
    audit = (ROOT / ".github/workflows/dependency-audit.yml").read_text(encoding="utf-8")
    assert "-r skills/revayat-comic/requirements.txt -r tests/requirements.txt" in audit
    updates = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert "directory: /skills/revayat-comic" in updates and "directory: /tests" in updates
    manifest = (ROOT / "install/skill-files.txt").read_text(encoding="utf-8").splitlines()
    assert "requirements.txt" in manifest
    assert not any("tests/requirements" in name for name in manifest)


def test_standalone_runtime_source_does_not_import_test_tools():
    for path in (ROOT / "skills/revayat-comic/scripts").glob("*.py"):
        imports = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "").split(".")[0])
        assert not {"pytest", "pytest_timeout", "ruff", "fontTools"} & set(imports), path.name
