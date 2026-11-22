"""Contract tests for the five plugin manifest formats and three marketplaces."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PLUGIN_MANIFESTS = (
    ROOT / "plugin.json",
    ROOT / ".claude-plugin/plugin.json",
    ROOT / ".codex-plugin/plugin.json",
    ROOT / ".cursor-plugin/plugin.json",
    ROOT / ".antigravity-plugin/plugin.json",
)

MARKETPLACE_FILES = (
    ROOT / ".agents/plugins/marketplace.json",
    ROOT / ".claude-plugin/marketplace.json",
    ROOT / ".cursor-plugin/marketplace.json",
)

AGENT_PLUGINS_1_0_ALLOWED_KEYS = frozenset(
    {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "extensions",
    }
)
AGENT_PLUGINS_1_0_AUTHOR_KEYS = frozenset({"name", "email", "url"})
AGENT_PLUGINS_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def _load(path: Path) -> dict:
    assert path.is_file(), f"Missing manifest: {path.relative_to(ROOT)}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_five_plugin_manifests_exist_and_agree_on_identity():
    versions = set()
    for path in PLUGIN_MANIFESTS:
        data = _load(path)
        assert data["name"] == "revayat-comic", f"{path}: unexpected name"
        assert data["license"] == "GPL-3.0-or-later", f"{path}: unexpected license"
        assert data.get("description"), f"{path}: missing description"
        assert data.get("version"), f"{path}: missing version"
        versions.add(data["version"])

    assert len(versions) == 1, f"Plugin manifests disagree on version: {versions}"


def test_root_agent_plugins_manifest_matches_1_0_schema():
    data = _load(ROOT / "plugin.json")
    assert data["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    extra = set(data) - AGENT_PLUGINS_1_0_ALLOWED_KEYS
    assert not extra, f"Disallowed top-level keys in root plugin.json: {sorted(extra)}"
    assert AGENT_PLUGINS_NAME_RE.match(data["name"])
    author = data.get("author")
    if author is not None:
        extra_author = set(author) - AGENT_PLUGINS_1_0_AUTHOR_KEYS
        assert not extra_author, f"Disallowed author keys in root plugin.json: {sorted(extra_author)}"


def test_host_specific_plugin_fields():
    codex = _load(ROOT / ".codex-plugin/plugin.json")
    assert codex["skills"] == "./skills/"
    iface = codex["interface"]
    for field in ("displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities", "websiteURL", "defaultPrompt"):
        assert iface.get(field), f".codex-plugin/plugin.json missing interface.{field}"

    antigravity = _load(ROOT / ".antigravity-plugin/plugin.json")
    assert antigravity["$schema"] == "https://antigravity.google/schemas/v1/plugin.json"
    assert antigravity.get("displayName")
    assert isinstance(antigravity.get("suggestedPrompts"), list) and antigravity["suggestedPrompts"]
    assert isinstance(antigravity.get("category"), list) and antigravity["category"]


def test_all_three_marketplaces_reference_revayat_comic_and_match_version():
    expected_version = _load(ROOT / "plugin.json")["version"]

    agents_market = _load(ROOT / ".agents/plugins/marketplace.json")
    assert agents_market["interface"]["displayName"]
    assert agents_market["plugins"][0]["name"] == "revayat-comic"
    assert agents_market["plugins"][0]["source"]["source"] == "url"
    assert agents_market["plugins"][0]["source"]["url"].endswith("KiaroSama/Revayat-Comic-Skill.git")

    claude_market = _load(ROOT / ".claude-plugin/marketplace.json")
    assert claude_market["$schema"] == "https://code.claude.com/schemas/marketplace.json"
    assert claude_market["metadata"]["description"]
    assert claude_market["plugins"][0]["name"] == "revayat-comic"
    assert claude_market["plugins"][0]["version"] == expected_version

    cursor_market = _load(ROOT / ".cursor-plugin/marketplace.json")
    assert cursor_market["owner"]["name"]
    assert cursor_market["plugins"][0]["name"] == "revayat-comic"
    assert cursor_market["plugins"][0]["source"] == "./"
