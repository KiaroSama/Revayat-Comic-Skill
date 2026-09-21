"""Declared source guidance reaches the provider without replacing reader decisions."""

import json

import pytest

import adapters
import context
import pageir as ir
import translate


@pytest.mark.parametrize("source,profile,marker", [
    ("Japanese", "ja", "furigana"),
    ("ko-KR", "ko", "Hangul"),
    ("zh_Hant", "zh", "Traditional"),
    ("fr-CA", "fr", "tu/vous"),
    ("Spanish", "es", "tú"),
    ("EN_us", "en", "don't have to"),
    ("x-unknown", "generic", "directly into Persian"),
    (None, "generic", "directly into Persian"),
])
def test_declared_language_guidance_survives_the_real_request(
        tmp_path, endpoint, source, profile, marker):
    doc = ir.new_doc(source_language=source)
    if source is None:
        doc["meta"].pop("source_language")
    doc["meta"]["title_policy"] = {"honorifics": "keep established forms"}
    doc["meta"]["cast"] = {"A": {"register": "formal", "voice": "measured"}}
    doc["glossary"] = {"entries": {"李": {"target": "لی", "locked": True}}}
    page = ir.new_page("p0001", 0, "pages/p0001.png", 100, 100, "0" * 64)
    region = ir.new_region("p0001r001", [10, 10, 50, 50], kind="speech")
    # Han-only text must not override the declared chapter language.
    region.update(source_text="李", speaker="A")
    page["regions"] = [region]
    doc["pages"] = [page]
    before = ir.dumps(doc)
    package = context.build(doc, page["id"])
    guidance = package["context"]["language_guidance"]
    assert guidance["profile"] == profile
    assert guidance["target_language"] == "fa"
    assert marker in " ".join(guidance["rules"])
    assert "cast" in guidance["priority"] and "title policy" in guidance["priority"]
    assert package["constraints"]["policy"]["source_language"] == (source or "auto")
    assert ir.dumps(package) == ir.dumps(context.build(doc, page["id"]))
    assert ir.dumps(doc) == before

    path = tmp_path / "comic.json"
    ir.save_doc(doc, path)
    report = translate.translate_document(path, provider=adapters.HostedTranslation.name)
    assert not report["refused"], report
    sent = json.loads(endpoint.requests[-1]["payload"]["messages"][-1]["content"])
    assert sent["context"]["language_guidance"] == guidance
    assert sent["constraints"]["glossary"] == {"李": "لی"}
    assert sent["constraints"]["policy"]["honorifics"] == "keep established forms"
    assert sent["context"]["speakers"][0]["voice"] == "measured"
    assert sent["context"]["speakers"][0]["register"] == "formal"
