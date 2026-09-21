"""What a recorded answer is an answer TO.

Resume rests on one comparison: the question this run would ask against the
question the recorded answer was produced from. Everything here is about the
parts of that question the record could not see — so a chapter carried answers
from one model under the name of another, from one endpoint under the name of a
second, and from a crop of a page that has since been redrawn.

The hosted adapters are exercised against a loopback server, not a fake object,
because the defect is exactly that the configuration lives outside the object:
`HostedTranslation` reads its model from the environment at call time and has no
`model` attribute for anything to read.
"""
from __future__ import annotations

from pathlib import Path

import adapters
import ocr
import pageir as ir
import providers
import translate


def _identity_of_translator():
    return providers.engine_identity(adapters.HostedTranslation())


# --------------------------------------------------------------------------- #
# The adapter describes the request it would make
# --------------------------------------------------------------------------- #

def test_changing_the_model_changes_what_the_translator_is(endpoint,
                                                           monkeypatch):
    """The defect, in its plainest form. `engine_identity` read the object's
    attributes; the model is an environment variable this object never stores,
    so every line in the chapter kept looking like an answer from whichever
    model was configured now."""
    before = _identity_of_translator()
    monkeypatch.setenv(adapters.TRANSLATION_MODEL, "a-completely-other-model")

    assert _identity_of_translator() != before


def test_changing_the_endpoint_changes_what_the_translator_is(endpoint,
                                                              monkeypatch):
    """The same service name in front of a different service is a different
    answer, and nothing recorded which one had been asked."""
    before = _identity_of_translator()
    monkeypatch.setenv(adapters.API_BASE, "https://elsewhere.invalid/v1")

    assert _identity_of_translator() != before


def test_changing_the_prompt_changes_what_the_translator_is(endpoint,
                                                            monkeypatch):
    """The instructions are part of the question. An answer produced under
    wording nobody is giving any more is not a resume of this one."""
    before = _identity_of_translator()
    monkeypatch.setattr(adapters, "PROMPT_VERSION", adapters.PROMPT_VERSION + "-changed")

    assert _identity_of_translator() != before


def test_the_image_adapter_names_its_model_too(endpoint, monkeypatch):
    before = providers.engine_identity(adapters.HostedImageEdit())
    monkeypatch.setenv(adapters.IMAGE_MODEL, "another-image-model")

    assert providers.engine_identity(adapters.HostedImageEdit()) != before


def test_no_credential_reaches_the_identity(endpoint, monkeypatch):
    """This string is written into the document. A key, a token, or a password
    inside a URL must never be in it."""
    monkeypatch.setenv(adapters.API_KEY, "sk-not-a-real-key")
    monkeypatch.setenv(adapters.API_BASE,
                       "https://someone:hunter2@example.invalid/v1?t=abc")

    identity = _identity_of_translator()

    assert "sk-not-a-real-key" not in identity
    assert "hunter2" not in identity and "someone" not in identity
    assert "abc" not in identity
    assert "example.invalid" in identity, "the endpoint is still identified"


# --------------------------------------------------------------------------- #
# End to end, against the real adapter
# --------------------------------------------------------------------------- #

def _sourced(doc_path):
    doc = ir.load_doc(doc_path)
    for _page, region in ir.iter_regions(doc):
        region["source_text"] = "やめろ"
        region["target_text"] = ""
        region["locked"] = False
    ir.save_doc(doc, doc_path)


def test_an_unchanged_rerun_asks_the_endpoint_nothing(detected, endpoint):
    _sourced(detected)
    translate.translate_document(detected, provider="openai-compatible")
    asked = len(endpoint.requests)
    assert asked, "the fixture translated nothing"

    translate.translate_document(detected, provider="openai-compatible")

    assert len(endpoint.requests) == asked, "the same question was paid for twice"


def test_the_same_chapter_under_another_model_is_asked_again(detected, endpoint,
                                                             monkeypatch):
    _sourced(detected)
    translate.translate_document(detected, provider="openai-compatible")
    asked = len(endpoint.requests)

    monkeypatch.setenv(adapters.TRANSLATION_MODEL, "a-second-model")
    translate.translate_document(detected, provider="openai-compatible")

    assert len(endpoint.requests) > asked, "another model was resumed"


# --------------------------------------------------------------------------- #
# Reading a crop
# --------------------------------------------------------------------------- #

class _Reader:
    """An OCR engine that counts the crops it was handed."""

    role = "ocr"
    name = "counting"

    def __init__(self, model="r1"):
        self.model = model
        self.crops: list[str] = []

    def read(self, crop_path, language, **_):
        self.crops.append(crop_path)
        return "やめろ"


def _reader(monkeypatch, made=None):
    made = made or _Reader()
    monkeypatch.setitem(providers._REGISTRY["ocr"], "counting", lambda: made)
    return made


def test_reading_the_same_crops_again_costs_nothing(detected, monkeypatch):
    reader = _reader(monkeypatch)
    ocr.read_document(detected, provider="counting")
    read = len(reader.crops)
    assert read

    ocr.read_document(detected, provider="counting")

    assert len(reader.crops) == read


def test_another_reader_is_not_resumed(detected, monkeypatch):
    """The record held the NAME the provider was registered under, and nothing
    about which reader that name resolved to. Pointing it at another model left
    every transcription in the chapter looking like an answer from the new
    one."""
    reader = _reader(monkeypatch)
    ocr.read_document(detected, provider="counting")
    read = len(reader.crops)

    reader.model = "r2"
    ocr.read_document(detected, provider="counting")

    assert len(reader.crops) > read, "a different reader was resumed"


def test_a_crop_that_is_not_the_picture_that_was_read_is_not_resumed(
        detected, monkeypatch):
    """The identity was a hash of the geometry the crop was NAMED for. Change
    what the cropper draws and every region resumes against a reading of an
    image that no longer exists — the file name matches and the picture does
    not."""
    reader = _reader(monkeypatch)
    ocr.read_document(detected, provider="counting")
    read = len(reader.crops)

    # The same crop path, different pixels: exactly what a change to the
    # cropper's padding or rendering produces.
    from PIL import Image

    for path in {Path(crop) for crop in reader.crops}:
        with Image.open(path) as image:
            repainted = Image.new("RGB", image.size, (13, 17, 19))
        repainted.save(path)

    ocr.read_document(detected, provider="counting")

    assert len(reader.crops) > read, "a different picture was resumed"
