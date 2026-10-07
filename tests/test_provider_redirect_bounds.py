"""Redirect compatibility keeps response allocation bounded and closes input."""
import io
import urllib.request
from email.message import Message

import pytest

import adapters
from provider_errors import PublicProviderError


@pytest.mark.parametrize("status", [301, 302, 303, 307])
def test_intermediate_redirect_is_bounded_and_closed(monkeypatch, status):
    monkeypatch.setattr(adapters, "MAX_RESPONSE_BYTES", 16)
    opener = adapters._redirect_guard()
    handler = next(value for value in opener.handlers
                   if isinstance(value, urllib.request.HTTPRedirectHandler))
    headers = Message()
    headers["Location"] = "/next"
    response = io.BytesIO(b"x" * 32)
    called = []
    monkeypatch.setattr(opener, "open", lambda *args, **kw: called.append(args))
    request = urllib.request.Request("https://example.invalid/start")
    with pytest.raises(PublicProviderError, match="byte limit"):
        getattr(handler, f"http_error_{status}")(request, response, status, "redirect", headers)
    assert response.closed
    assert called == []


def test_post_307_error_transfers_a_live_bounded_body():
    import urllib.error

    opener = adapters._redirect_guard()
    handler = next(value for value in opener.handlers
                   if isinstance(value, urllib.request.HTTPRedirectHandler))
    headers = Message()
    headers["Location"] = "/next"
    response = io.BytesIO(b"refused")
    request = urllib.request.Request("https://example.invalid/start", data=b"body")
    with pytest.raises(urllib.error.HTTPError) as caught:
        handler.http_error_307(request, response, 307, "redirect", headers)
    try:
        assert not response.closed
        assert caught.value.read() == b"refused"
    finally:
        caught.value.close()
    assert response.closed


def test_missing_location_preserves_response_for_next_handler():
    opener = adapters._redirect_guard()
    handler = next(value for value in opener.handlers
                   if isinstance(value, urllib.request.HTTPRedirectHandler))
    response = io.BytesIO(b"unchanged")
    request = urllib.request.Request("https://example.invalid/start")
    assert handler.http_error_302(request, response, 302, "redirect", Message()) is None
    assert response.read() == b"unchanged"
    response.close()


def test_small_same_origin_redirect_retains_stdlib_behavior(monkeypatch):
    opener = adapters._redirect_guard()
    handler = next(value for value in opener.handlers
                   if isinstance(value, urllib.request.HTTPRedirectHandler))
    headers = Message()
    headers["Location"] = "/next"
    response = io.BytesIO(b"ok")
    called = []
    monkeypatch.setattr(opener, "open", lambda request, **kw: called.append(request.full_url))
    request = urllib.request.Request("https://example.invalid/start")
    request.timeout = 1
    handler.http_error_302(request, response, 302, "redirect", headers)
    assert called == ["https://example.invalid/next"]
    assert response.closed
