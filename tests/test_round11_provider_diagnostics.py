"""Provider failures are public diagnostics, never credential containers."""
from __future__ import annotations

import json
import traceback
import urllib.request

import pytest

import adapters
import pageir as ir
import providers
import translate

SECRET = "synthetic-round11-credential-DO-NOT-USE"


def test_failed_translation_persists_safe_diagnostic(detected, monkeypatch):
    class Failing:
        name = "offline"

        def translate(self, text, context):
            raise ValueError("invalid Authorization: Bearer " + SECRET)

    doc = ir.load_doc(detected)
    for _, region in ir.iter_regions(doc):
        region["source_text"] = "Hello"
    ir.save_doc(doc, detected)
    monkeypatch.setitem(providers._REGISTRY["translation"], "offline-r11", Failing)
    assert translate.translate_document(detected, provider="offline-r11")["totals"]["failed"]
    doc = ir.load_doc(detected)
    recorded = json.dumps(doc, ensure_ascii=False)
    assert SECRET not in recorded
    assert "ValueError" in recorded
    assert "configuration" in recorded.lower()


@pytest.mark.parametrize("suffix", ["\n", "\r\n", "\t", " ", "é", "\x7f"])
def test_invalid_bearer_never_constructs_network(monkeypatch, suffix):
    monkeypatch.setenv(adapters.TRANSLATION_MODEL, "offline-model")
    monkeypatch.setenv(adapters.API_BASE, "http://127.0.0.1:9999/v1")
    monkeypatch.setenv(adapters.API_KEY, SECRET + suffix)
    calls = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: calls.append(args))
    monkeypatch.setattr(urllib.request, "Request", lambda *args, **kwargs: calls.append(args))
    result = providers.call(adapters.HostedTranslation(), "translation", "Hello", {})
    assert not result.ok and not calls
    assert SECRET not in result.detail
    assert adapters.API_KEY in result.detail


def test_factory_traceback_does_not_show_raw_payload(monkeypatch):
    def factory():
        raise ValueError(SECRET)

    monkeypatch.setitem(providers._REGISTRY["translation"], "offline-factory-r11", factory)
    try:
        providers.get("translation", "offline-factory-r11")
    except ValueError as error:
        trace = "".join(traceback.format_exception(error))
    else:
        pytest.fail("factory error was ignored")
    assert SECRET not in trace


def test_broken_exception_stringification_is_contained():
    class Unprintable(Exception):
        def __str__(self):
            raise RuntimeError(SECRET)

    class Failing:
        def translate(self, text, context):
            raise Unprintable()

    result = providers.call(Failing(), "translation", "Hello", {})
    assert not result.ok and "Unprintable" in result.detail
    assert SECRET not in result.detail


def test_legacy_missing_setting_stays_actionable():
    class Missing:
        def translate(self, text, context):
            raise ValueError("REVAYAT_API_BASE is not set")

    result = providers.call(Missing(), "translation", "Hello", {})
    assert "REVAYAT_API_BASE is not set" in result.detail


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, OSError])
def test_worker_payload_never_reaches_provenance(error_type):
    class Failing:
        def translate(self, text, context):
            raise error_type(SECRET)

    result = providers.call(Failing(), "translation", "Hello", {}, timeout=1)
    region = ir.new_region("p0001r001", [0, 0, 20, 20], kind="speech")
    assert providers.apply(region, "target_text", result) == "failed"
    assert SECRET not in json.dumps(region)
    assert error_type.__name__ in result.detail


def test_trusted_public_guidance_is_bounded_and_single_line():
    from provider_errors import PublicProviderError
    class Failing:
        def translate(self, text, context):
            raise PublicProviderError("Check configuration\n" + "a" * 700)

    result = providers.call(Failing(), "translation", "Hello", {}, timeout=1)
    assert len(result.detail) <= 500 and "\n" not in result.detail
    assert result.detail.startswith("Check configuration ")


def test_missing_setting_with_extra_payload_is_not_public():
    class Failing:
        def translate(self, text, context):
            raise ValueError("REVAYAT_API_BASE is not set " + SECRET)

    result = providers.call(Failing(), "translation", "Hello", {}, timeout=1)
    assert SECRET not in result.detail and "configuration" in result.detail


def test_nul_key_from_config_reader_is_refused_before_network(monkeypatch):
    import os
    key = SECRET + "\x00"
    original = os.environ.get
    monkeypatch.setattr(os.environ, "get", lambda name, default=None:
                        key if name == adapters.API_KEY else original(name, default))
    monkeypatch.setenv(adapters.API_BASE, "http://127.0.0.1:9999/v1")
    monkeypatch.setenv(adapters.TRANSLATION_MODEL, "offline-model")
    calls = []
    monkeypatch.setattr(urllib.request, "Request", lambda *args, **kwargs: calls.append(args))
    result = providers.call(adapters.HostedTranslation(), "translation", "Hello", {}, timeout=1)
    assert not result.ok and not calls and SECRET not in result.detail


@pytest.mark.parametrize('termination', [SystemExit, KeyboardInterrupt])
def test_error_stringification_cannot_terminate_reporting(termination):
    class Unprintable(Exception):
        def __str__(self):
            raise termination(SECRET)

    class Failing:
        def translate(self, text, context):
            raise Unprintable()

    result = providers.call(Failing(), 'translation', 'Hello', {}, timeout=1)
    assert not result.ok and SECRET not in result.detail
