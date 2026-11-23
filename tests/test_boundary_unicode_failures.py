"""Malformed external Unicode must fail at its boundary, before page writes."""
from __future__ import annotations

import http.client
import io
import json
import logging

import pytest
from PIL import Image

import adapters
import ocr
import pageir as ir
import providers
import qa
import readers
import server
import translate

LOG = logging.getLogger(__name__)


@pytest.mark.parametrize("role", ["ocr", "translation", "vision"])
@pytest.mark.parametrize("text", ["bad\ud800text", "bad\udffftext"])
def test_invalid_provider_unicode_is_a_failure_status(role, text):
    class InvalidText:
        def read(self, *_args):
            return text, 0.9

        translate = read
        describe = read

    result = providers.call(InvalidText(), role, "input", "context", timeout=1)

    assert not result.ok and result.status == "error"
    assert result.data is None
    result.detail.encode("utf-8", errors="strict")
    LOG.info("Invalid %s output refused before document mutation", role)


def test_escaped_surrogate_from_hosted_json_is_refused(endpoint):
    endpoint.chat = {"choices": [{"message": {"content": "bad\ud800text"},
                                  "finish_reason": "stop"}]}

    result = providers.call(adapters.HostedTranslation(), "translation",
                            "Hello", {}, timeout=2)

    assert not result.ok and result.status == "error"
    assert result.data is None


@pytest.mark.parametrize("role,field", [("ocr", "source_text"),
                                       ("translation", "target_text")])
def test_invalid_answer_does_not_discard_other_answers_on_the_page(
        detected, monkeypatch, role, field):
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    page["regions"] = page["regions"][:3]
    assert len(page["regions"]) == 3
    for region in page["regions"]:
        region["kind"] = "speech"
        region["source_text"] = "Hello" if role == "translation" else ""
        region["target_text"] = ""
    ir.save_doc(doc, detected)
    answers = iter(["درود", "bad\ud800text", "خوبی؟"])

    class ThreeAnswers:
        def read(self, *_args):
            return next(answers), 0.9

        translate = read

    monkeypatch.setitem(providers._REGISTRY[role], "unicode-boundary", ThreeAnswers)
    run = ocr.read_document if role == "ocr" else translate.translate_document
    report = run(detected, provider="unicode-boundary", pages=[page["id"]])

    assert report["totals"]["applied"] == 2
    assert report["totals"]["failed"] == 1
    saved = ir.load_doc(detected)["pages"][0]["regions"]
    assert [region[field] for region in saved] == ["درود", "", "خوبی؟"]
    assert saved[1]["provenance"][-1]["status"] == "error"
    LOG.info("%s retained successful page answers around one refused value", role)


def test_valid_supplementary_unicode_is_preserved():
    text = "درود! \U0001f600 \U00020000"
    result = providers.call(providers.FakeOCR(text=text), "ocr", "crop", "ja")

    assert result.ok and result.data == text


def test_invalid_vision_advisory_cannot_poison_ocr_page_save(detected, monkeypatch):
    doc = ir.load_doc(detected)
    page = doc["pages"][0]
    page["regions"] = page["regions"][:2]
    assert len(page["regions"]) == 2
    region = page["regions"][0]
    region.update(source_text="approved source", locked=True)
    page["regions"][1].update(source_text="", locked=False)
    ir.save_doc(doc, detected)

    class InvalidVision:
        def describe(self, *_args):
            return "bad\ud800advisory"

    monkeypatch.setitem(providers._REGISTRY["vision"], "unicode-vision", InvalidVision)
    report = ocr.read_document(detected, provider="fake-ocr", vision="unicode-vision",
                               pages=[page["id"]])

    assert report["disagreement_count"] == 1
    assert report["totals"]["applied"] == 1
    assert "vision" not in report["disagreements"][0]
    saved = ir.load_doc(detected)["pages"][0]["regions"]
    assert saved[0]["source_text"] == "approved source"
    assert saved[1]["source_text"] == "テスト"
    verdict = saved[0]["provenance"][-1]
    assert verdict["role"] == "vision" and verdict["status"] == "error"
    LOG.info("Invalid vision advisory remained a status and preserved the OCR page")


@pytest.mark.parametrize("role,value", [
    ("vision", {"description": "گفت‌وگو"}),
    ("visual_qa", [{"code": "speaker-mismatch", "note": "توضیح"}]),
    ("image_edit", None),
])
def test_unicode_guard_preserves_structured_and_binary_results(role, value):
    if role == "image_edit":
        encoded = io.BytesIO()
        Image.new("RGB", (1, 1), (0, 128, 255)).save(encoded, "PNG")
        value = encoded.getvalue()

    class NonTextResult:
        def describe(self, *_args):
            return value

        inspect = describe
        repair = describe

    result = providers.call(NonTextResult(), role, "input", "context", timeout=1)
    assert result.ok and result.data is value


@pytest.mark.parametrize("field", ["note", "region"])
@pytest.mark.parametrize("converted", [False, True])
def test_visual_findings_refuse_invalid_retained_unicode(field, converted):
    class InvalidText:
        def __str__(self):
            return "bad\ud800advisory"

    invalid = InvalidText() if converted else "bad\udfffadvisory"
    malformed = {"code": "speaker-mismatch", field: invalid}
    valid = {"code": "missed-text", "region": 12, "note": "درود \U0001f600"}

    kept, dropped = qa._normalise([malformed, valid], "p0001")

    assert dropped == 1
    assert kept == [{"code": "missed-text", "page": "p0001",
                     "region": "12", "note": "درود \U0001f600"}]
    ir.dumps(kept).encode("utf-8", errors="strict")


def test_http_malformed_visual_advice_retains_good_findings_and_next_request(
        tmp_path, monkeypatch):
    image = tmp_path / "page.png"
    Image.new("RGB", (10, 10), "white").save(image)
    imported = readers.import_source(image, tmp_path / "work")
    document = imported["document"]
    before = (tmp_path / "work" / "comic.json").read_bytes()

    class MixedAdvice:
        def inspect(self, *_args):
            return [
                {"code": "speaker-mismatch", "note": "bad\ud800advisory"},
                {"code": "speaker-mismatch", "region": "bad\udfffregion"},
                {"code": "missed-text", "note": "توضیح \U0001f600"},
            ]

    monkeypatch.setitem(providers._REGISTRY["visual_qa"], "unicode-advice", MixedAdvice)
    service, token = server.serve_http(port=0)
    client = http.client.HTTPConnection("127.0.0.1", service.server_address[1],
                                        timeout=3)
    try:
        body = json.dumps({"args": ["visual", "--doc", str(document),
                                    "--provider", "unicode-advice"]})
        client.request("POST", "/tools/revayat_qa", body=body,
                       headers={"X-Revayat-Token": token})
        response = client.getresponse()
        assert response.status == 200
        report = json.loads(response.read())["report"]
        assert report["malformed"] == 2 and report["note_count"] == 1
        assert report["notes"][0]["note"] == "توضیح \U0001f600"
        assert (tmp_path / "work" / "comic.json").read_bytes() == before

        client.request("GET", "/tools", headers={"X-Revayat-Token": token})
        healthy = client.getresponse()
        assert healthy.status == 200 and json.loads(healthy.read())["tools"]
        LOG.info("Malformed visual advice was ignored and the next HTTP request succeeded")
    finally:
        client.close()
        service.shutdown()
        service.server_close()


def test_http_non_ascii_token_is_unauthorised_and_service_survives():
    service, token = server.serve_http(port=0)
    client = http.client.HTTPConnection("127.0.0.1", service.server_address[1],
                                        timeout=3)
    try:
        client.request("GET", "/tools", headers={"X-Revayat-Token": "bad-\xff"})
        refused = client.getresponse()
        assert refused.status == 401
        assert json.loads(refused.read())["ok"] is False

        client.request("GET", "/tools", headers={"X-Revayat-Token": token})
        valid = client.getresponse()
        assert valid.status == 200
        assert json.loads(valid.read())["tools"]
        LOG.info("HTTP refused invalid authentication and served the next valid request")
    finally:
        client.close()
        service.shutdown()
        service.server_close()


@pytest.mark.parametrize("token", ["bad-\u00ff", "bad\nvalue", "bad\x00value"])
def test_http_invalid_configured_token_is_refused_before_startup(token):
    service = None
    try:
        with pytest.raises(ValueError, match="token"):
            service, _ = server.serve_http(port=0, token=token)
    finally:
        if service is not None:
            service.shutdown()
            service.server_close()
