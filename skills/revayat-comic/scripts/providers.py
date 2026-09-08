"""Optional adapters for work the host agent would otherwise do itself.

**Read this before adding one.** The default is no provider at all. An Agent
Skill runs inside a multimodal model that is already holding the chapter, so
asking a *second* model to read a page the first one can see is a second
inference bill for an answer already in context. That is why `revayat-comic`
has no provider in its default pipeline and why `doctor` reports none.

What this module is for is the narrow set of cases where a second model
genuinely knows something the host does not:

* the host has no vision at all (a scripted batch run, a text-only client);
* a specialist beats a generalist on one narrow job, and somebody has measured
  that on their own pages rather than assumed it;
* **drawing pixels** — the one thing a coding agent truly cannot do, which is
  why `ImageEditProvider` is the role with a real wiring already built.

Four rules hold for every role here, and they are the reason the boundary is
worth having at all rather than each stage growing its own SDK call:

**A provider never becomes the page.** Nothing a provider returns is written
straight to disk. An image comes back through the same hard-mask composite
every other cleaner uses; text comes back into the IR through `apply` below,
which refuses to touch a region a human has locked.

**Failure is a status, not an exception.** A provider that times out, errors,
returns nonsense or is not installed produces a `Result` with `ok=False` and a
reason. The stage carries on down the path it would have taken with no provider
configured. Nothing half-written, nothing silently degraded.

**Provenance travels with the data.** Every applied result stamps which provider
produced it, when, and how confident it was, into `region["provenance"]`. A
later run can tell a machine's guess from a human's decision, which is the whole
basis on which the `locked` rule can be enforced.

**Fakes are first-class.** Every role has a deterministic fake registered under
`fake-*`. The suite exercises the boundary, the failure paths and the composite
guarantee without a network, an API key or a credential of any kind.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

#: Seconds a single provider call may take before the stage gives up on it.
#: Generous, because a hosted image model on a large page is genuinely slow, and
#: bounded, because a stage that hangs is worse than a stage that falls back.
DEFAULT_TIMEOUT = 120.0

#: Every role a provider can fill. The names are the ones the audits asked for.
ROLES = ("vision", "ocr", "translation", "image_edit", "visual_qa")

#: What a call can end as. `unavailable` is not a failure — it is the ordinary
#: state of a machine with no provider configured, which is most of them.
STATUSES = ("ok", "timeout", "error", "unavailable", "refused")


@dataclass
class Result:
    """One provider call's outcome, successful or not.

    `ok` is the only field a caller has to check. Everything else exists so the
    fallback can say *why* in a sentence a user can act on, and so the IR can
    record where a value came from.
    """

    ok: bool
    status: str
    provider: str
    role: str
    data: Any = None
    confidence: float | None = None
    detail: str = ""
    elapsed: float = 0.0

    def as_provenance(self) -> dict[str, Any]:
        record = {
            "provider": self.provider,
            "role": self.role,
            "status": self.status,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if self.confidence is not None:
            record["confidence"] = round(float(self.confidence), 3)
        if self.detail:
            record["detail"] = self.detail
        return record


# --------------------------------------------------------------------------- #
# The roles
# --------------------------------------------------------------------------- #
# Protocols rather than base classes: a provider is anything with the right
# method, so an adapter can be twenty lines in a user's own file and needs to
# import nothing from here.

@runtime_checkable
class VisionProvider(Protocol):
    def describe(self, image_path: str, regions: list[dict[str, Any]]) -> Any:
        """What is on this page — speakers, reading order, missed text."""


@runtime_checkable
class OCRProvider(Protocol):
    def read(self, crop_path: str, language: str) -> Any:
        """``(text, confidence)`` for one region crop."""


@runtime_checkable
class TranslationProvider(Protocol):
    def translate(self, source: str, context: dict[str, Any]) -> Any:
        """Persian for one source string, given bounded chapter context."""


@runtime_checkable
class ImageEditProvider(Protocol):
    def repair(self, page_png: bytes, mask_png: bytes, instructions: str) -> Any:
        """A repaired page, as PNG bytes the *caller* will mask before use."""


@runtime_checkable
class VisualQAProvider(Protocol):
    def inspect(self, image_path: str, regions: list[dict[str, Any]]) -> Any:
        """Advisory findings a deterministic check cannot make."""


_METHODS = {
    "vision": "describe",
    "ocr": "read",
    "translation": "translate",
    "image_edit": "repair",
    "visual_qa": "inspect",
}


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, dict[str, Callable[[], Any]]] = {role: {} for role in ROLES}


def register(role: str, name: str, factory: Callable[[], Any]) -> None:
    """Make a provider selectable by name.

    A *factory*, not an instance: an adapter that opens a client or reads a key
    should not do it because this module was imported. Nothing is constructed
    until a stage actually asks for that provider by name.
    """
    if role not in ROLES:
        raise ValueError(f"unknown provider role {role!r}; expected one of {ROLES}")
    _REGISTRY[role][name] = factory


def available(role: str | None = None) -> dict[str, list[str]]:
    """What is registered, for `doctor` and for an error message worth reading."""
    roles = ROLES if role is None else (role,)
    return {r: sorted(_REGISTRY[r]) for r in roles}


def get(role: str, name: str | None):
    """The named provider, or ``None`` meaning *the host agent does this*.

    ``None`` is the default and the common case. A name that is not registered
    raises rather than falling back silently: a user who typed `--ocr mangaocr`
    and got the host agent's own reading would have no way to tell.
    """
    if not name:
        return None
    if role not in ROLES:
        raise ValueError(f"unknown provider role {role!r}")
    try:
        factory = _REGISTRY[role][name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY[role])) or "none registered"
        raise ValueError(
            f"no {role} provider named {name!r}. Available: {known}"
        ) from None
    return factory()


def call(provider, role: str, *args, timeout: float = DEFAULT_TIMEOUT,
         name: str | None = None, **kwargs) -> Result:
    """Run one provider call and turn every possible outcome into a `Result`.

    The timeout is enforced by waiting on a worker thread. Python cannot kill a
    thread, so a hung provider's thread may outlive the call — what is
    guaranteed is that its answer is never used and the stage is never blocked
    past `timeout`. That is the honest bound, and it is the reason a provider
    should be given a network timeout of its own as well.
    """
    label = name or getattr(provider, "name", type(provider).__name__)
    if provider is None:
        return Result(False, "unavailable", "none", role,
                      detail="no provider configured; the host agent does this")

    method = getattr(provider, _METHODS[role], None)
    if method is None:
        return Result(False, "error", label, role,
                      detail=f"{label} has no {_METHODS[role]}() and cannot fill "
                             f"the {role} role")

    started = time.monotonic()
    # NOT `with ThreadPoolExecutor(...)`. Its __exit__ calls shutdown(wait=True)
    # and blocks until the worker returns, so a hung provider stalls the stage
    # for its full run time and the timeout bounds nothing at all. Caught by
    # `test_a_provider_that_hangs_is_bounded`, which measured 30s against a
    # 0.25s limit.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        value = pool.submit(method, *args, **kwargs).result(timeout=timeout)
    except _Timeout:
        pool.shutdown(wait=False)
        return Result(False, "timeout", label, role,
                      detail=f"no answer within {timeout:g}s",
                      elapsed=time.monotonic() - started)
    except Exception as error:  # noqa: BLE001 - a provider may raise anything
        pool.shutdown(wait=False)
        return Result(False, "error", label, role,
                      detail=f"{type(error).__name__}: {error}",
                      elapsed=time.monotonic() - started)
    else:
        pool.shutdown(wait=False)

    elapsed = time.monotonic() - started
    confidence = None
    if isinstance(value, tuple) and len(value) == 2:
        value, confidence = value
    if value is None:
        return Result(False, "refused", label, role,
                      detail="the provider declined to answer",
                      elapsed=elapsed)
    return Result(True, "ok", label, role, data=value,
                  confidence=confidence, elapsed=elapsed)


# --------------------------------------------------------------------------- #
# Writing a result back into the IR
# --------------------------------------------------------------------------- #

def apply(region: dict[str, Any], field_name: str, result: Result, *,
          min_confidence: float = 0.0) -> str:
    """Put a provider's answer into one region, or explain why it was not.

    Returns what happened, one of ``applied``, ``locked``, ``failed`` or
    ``needs_review``. The two rules that matter:

    **A locked region is never overwritten.** `locked` means a person or the
    reading model committed to that value. A provider is a second opinion, and a
    second opinion does not get to replace a decision — it gets recorded as a
    disagreement so somebody can look.

    **A low-confidence answer becomes a review note, never text.** Inventing
    source text is the one failure this pipeline cannot recover from, because
    every later stage trusts it.
    """
    provenance = region.setdefault("provenance", [])

    if not result.ok:
        provenance.append(result.as_provenance())
        return "failed"

    text = result.data if isinstance(result.data, str) else None
    if text is not None:
        text = text.strip()

    if region.get("locked"):
        provenance.append({**result.as_provenance(), "outcome": "locked"})
        existing = (region.get(field_name) or "").strip()
        if text and text != existing:
            region.setdefault("review", []).append(
                f"{result.provider} read this as {text!r}; the locked value "
                f"{existing!r} was kept"
            )
            return "needs_review"
        return "locked"

    if result.confidence is not None and result.confidence < min_confidence:
        provenance.append({**result.as_provenance(), "outcome": "low_confidence"})
        region.setdefault("review", []).append(
            f"{result.provider} was only {result.confidence:.2f} confident here; "
            f"nothing was written"
        )
        return "needs_review"

    if not text:
        provenance.append({**result.as_provenance(), "outcome": "empty"})
        return "failed"

    region[field_name] = text
    provenance.append({**result.as_provenance(), "outcome": "applied"})
    return "applied"


# --------------------------------------------------------------------------- #
# Fakes — deterministic, offline, and the only providers CI ever sees
# --------------------------------------------------------------------------- #

@dataclass
class FakeOCR:
    """Returns a fixed reading. `confidence` and `fail` drive the failure paths."""

    name: str = "fake-ocr"
    text: str = "テスト"
    confidence: float = 0.92
    fail: str = ""

    def read(self, crop_path: str, language: str):
        if self.fail == "raise":
            raise RuntimeError("the fake was told to fail")
        if self.fail == "hang":
            time.sleep(30)
        if self.fail == "none":
            return None
        return self.text, self.confidence


@dataclass
class FakeTranslation:
    name: str = "fake-translation"
    prefix: str = "ترجمهٔ "
    fail: str = ""

    def translate(self, source: str, context: dict[str, Any]):
        if self.fail == "raise":
            raise RuntimeError("the fake was told to fail")
        return self.prefix + source


@dataclass
class FakeImageEdit:
    """Returns a page that has changed **every** pixel.

    That is the point of it. The composite is only trustworthy if a provider
    doing the worst possible thing still cannot reach a pixel outside the mask,
    and a polite fake would never prove that.
    """

    name: str = "fake-image-edit"
    colour: tuple[int, int, int] = (255, 0, 0)
    fail: str = ""

    def repair(self, page_png: bytes, mask_png: bytes, instructions: str):
        if self.fail == "raise":
            raise RuntimeError("the fake was told to fail")
        if self.fail == "hang":
            time.sleep(30)
        if self.fail == "none":
            return None
        import io

        from PIL import Image

        page = Image.open(io.BytesIO(page_png)).convert("RGB")
        if self.fail == "wrong_size":
            page = page.resize((page.width // 2, page.height // 2))
        else:
            page = Image.new("RGB", page.size, self.colour)
        buffer = io.BytesIO()
        page.save(buffer, format="PNG")
        return buffer.getvalue()


@dataclass
class FakeVisualQA:
    name: str = "fake-visual-qa"
    findings: list[dict[str, Any]] = field(default_factory=list)
    fail: str = ""

    def inspect(self, image_path: str, regions: list[dict[str, Any]]):
        if self.fail == "raise":
            raise RuntimeError("the fake was told to fail")
        if self.fail == "malformed":
            return "not a list of findings"
        return list(self.findings)


@dataclass
class FakeVision:
    name: str = "fake-vision"
    payload: dict[str, Any] = field(default_factory=dict)

    def describe(self, image_path: str, regions: list[dict[str, Any]]):
        return dict(self.payload)


register("ocr", "fake-ocr", FakeOCR)
register("translation", "fake-translation", FakeTranslation)
register("image_edit", "fake-image-edit", FakeImageEdit)
register("visual_qa", "fake-visual-qa", FakeVisualQA)
register("vision", "fake-vision", FakeVision)
