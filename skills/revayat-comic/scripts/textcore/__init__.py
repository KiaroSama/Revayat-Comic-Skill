"""Persian text kernels with optional Rust acceleration."""

from importlib import import_module as _import_module

from . import kernels as _reference

__all__ = [
    "BACKEND",
    "balanced_wrap_lines",
    "ensure_rli_pdi",
    "ensure_rlm_rli_pdi",
    "normalize_persian_text",
    "starts_with_latin_in_persian",
]

try:
    _native = _import_module("textcore_rs")
except ImportError:
    _native = None

_backend = _native if all(callable(getattr(_native, name, None)) for name in __all__[1:]) else _reference
BACKEND = "python" if _backend is _reference else "rust"
balanced_wrap_lines = _backend.balanced_wrap_lines
ensure_rli_pdi = _backend.ensure_rli_pdi
ensure_rlm_rli_pdi = _backend.ensure_rlm_rli_pdi
normalize_persian_text = _backend.normalize_persian_text
starts_with_latin_in_persian = _backend.starts_with_latin_in_persian
