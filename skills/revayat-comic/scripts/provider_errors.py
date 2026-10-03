"""Credential-free diagnostics at the public provider boundary."""
from __future__ import annotations

import re


class PublicProviderError(RuntimeError):
    """Trusted first-party guidance: never include credentials or response data."""


_MISSING = re.compile(r"REVAYAT_[A-Z][A-Z0-9_]* is not set\Z")


def public_detail(error: BaseException) -> str:
    """Unknown exceptions expose their type, not arbitrary SDK/network payloads."""
    # Do not invoke unknown exception __str__: even stringification can exit
    # or disclose a header. Only an exact one-string missing-setting form is public.
    message = error.args[0] if len(error.args) == 1 and type(error.args[0]) is str else ""
    if isinstance(error, PublicProviderError) or _MISSING.fullmatch(message):
        return " ".join(message.split())[:500]
    kind = type(error).__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", kind):
        kind = "ProviderError"
    return f"{kind}: provider failed; check configuration and service availability"


def validate_bearer(key: str) -> None:
    """Validate the raw value before constructing any network object."""
    if key and any(not 0x21 <= ord(char) <= 0x7E for char in key):
        raise PublicProviderError(
            "REVAYAT_API_KEY must be printable ASCII without whitespace")
