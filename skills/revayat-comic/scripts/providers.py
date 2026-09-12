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

import inspect
import math
import numbers
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

#: Seconds a single provider call may take before the stage gives up on it.
#: Generous, because a hosted image model on a large page is genuinely slow, and
#: bounded, because a stage that hangs is worse than a stage that falls back.
DEFAULT_TIMEOUT = 120.0

#: How many workers a run may have abandoned to timeouts at once. Not a
#: concurrency limit — a healthy call returns its permit the moment it does —
#: but a ceiling on the pile. Without one, a stage whose provider has stopped
#: answering started a fresh thread per region and kept every one of them: 25
#: sequential timeouts, 25 live workers, and nothing anywhere saying stop.
MAX_OUTSTANDING_CALLS = 16

_OUTSTANDING = threading.BoundedSemaphore(MAX_OUTSTANDING_CALLS)

#: Whether the optional adapter layer has been offered a chance to register.
_ADAPTERS_TRIED = False

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
        """``(text, confidence)`` for one region crop.

        May also declare ``orientation`` — ``"vertical"`` or ``"horizontal"``,
        as the detector measured it — and it will be passed. It is optional
        because most engines find the writing direction themselves and an
        adapter should not have to accept an argument it ignores; see `wants`.
        """


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


def _register_adapters() -> None:
    """Make the real adapters selectable, once, and never fail the caller.

    A missing or broken `adapters.py` must not turn "unknown provider name"
    into an import error: the name is still going to be reported as unknown,
    which is the answer the caller can act on.
    """
    global _ADAPTERS_TRIED
    if _ADAPTERS_TRIED:
        return
    _ADAPTERS_TRIED = True
    try:
        import adapters

        adapters.register_all(probe=False)
    except Exception:  # noqa: BLE001 - an optional layer may be absent
        pass


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
    if name not in _REGISTRY[role]:
        # The real adapters live in `adapters.py` and register themselves when
        # that module is imported. Nothing imported it, so every entry point
        # offered the fakes alone and `--provider manga-ocr` came back as an
        # unknown name — the documented way to use the feature did not work
        # from the CLI or over MCP.
        #
        # Imported HERE, only on a miss, and with the usability probe off: an
        # ordinary run never pays for it, and asking whether `manga_ocr` is
        # installed costs an import of a package worth gigabytes.
        _register_adapters()
    try:
        factory = _REGISTRY[role][name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY[role])) or "none registered"
        raise ValueError(
            f"no {role} provider named {name!r}. Available: {known}"
        ) from None
    try:
        return factory()
    except Exception as error:  # noqa: BLE001 - a factory may raise anything
        # A provider that opens a client or reads a key fails here, and a
        # missing key is the ordinary case. Raised as it came, it left a
        # traceback on the CLI and took the MCP loop down with it; as a
        # `ValueError` it is the same refusal an unknown name already is, and
        # every caller of a stage already turns that into a result.
        raise ValueError(
            f"the {role} provider {name!r} could not be built: "
            f"{type(error).__name__}: {error}"
        ) from error


def wants(provider, role: str, keyword: str) -> bool:
    """Whether this provider's method accepts `keyword`.

    The boundary is duck-typed, so a stage cannot simply pass everything it
    knows: an adapter written against the two-argument shape in `adapters.py`
    would raise `TypeError` the moment a third argument appeared, and the whole
    point of a protocol rather than a base class is that nobody has to rewrite
    an adapter when the pipeline learns something new.

    So extra knowledge is *offered*, not imposed. An engine that wants the
    writing direction names it; every other engine is called exactly as before.
    A `**kwargs` signature counts as wanting everything.
    """
    method = getattr(provider, _METHODS.get(role, ""), None)
    if method is None:
        return False
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        # A C callable or a wrapper with no introspectable signature. Offering
        # it an argument it may not take is the riskier guess, so decline.
        return False
    if keyword in parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD
               for p in parameters.values())


def _not_a_confidence(value: Any) -> str:
    """Why this is not a confidence, or ``""`` if it is one.

    A provider's second tuple element is a number between 0 and 1, and half a
    check is worse than none: the floor in `apply` is a comparison, so a string
    raised `TypeError` there, and `NaN < floor` is *False* — a NaN cleared every
    floor, was applied, and serialised into `comic.json` as a bare `NaN` that no
    standard JSON parser will read back. That is a corrupted chapter produced by
    an adapter returning the wrong type.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return "is not a number"
    if not math.isfinite(value):
        return "is not finite"
    if not 0.0 <= value <= 1.0:
        return "is outside [0, 1]"
    return ""


def call(provider, role: str, *args, timeout: float = DEFAULT_TIMEOUT,
         name: str | None = None, **kwargs) -> Result:
    """Run one provider call and turn every possible outcome into a `Result`.

    The timeout is enforced by waiting on a worker thread. Python cannot kill a
    thread, so a hung provider's thread may outlive the call — what is
    guaranteed is that its answer is never used, the stage is never blocked past
    `timeout`, the *process* is never held open by it, and no more than
    `MAX_OUTSTANDING_CALLS` of them can pile up. That is the honest bound, and
    it is the reason a provider should be given a network timeout of its own.
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

    if not _OUTSTANDING.acquire(blocking=False):
        return Result(False, "error", label, role,
                      detail=f"{MAX_OUTSTANDING_CALLS} provider calls are still "
                             f"running from earlier timeouts, so this one was "
                             f"not started")

    # A plain daemon thread, NOT a `ThreadPoolExecutor`. Its workers are not
    # daemons and `shutdown(wait=False)` does not detach a running one, so the
    # interpreter joined it at exit: a call that timed out in 0.58s against an
    # 8s provider then held the process open for another 7.5 seconds. A daemon
    # thread is abandoned when the process is done with it, and the semaphore
    # above is what keeps the abandoned ones from piling up.
    outcome: dict[str, Any] = {}

    def _work() -> None:
        try:
            outcome["value"] = method(*args, **kwargs)
        except BaseException as error:  # noqa: BLE001 - anything at all
            outcome["error"] = error
        finally:
            _OUTSTANDING.release()

    started = time.monotonic()
    worker = threading.Thread(target=_work, name=f"provider-{label}",
                              daemon=True)
    worker.start()
    worker.join(timeout)
    elapsed = time.monotonic() - started

    if worker.is_alive():
        return Result(False, "timeout", label, role,
                      detail=f"no answer within {timeout:g}s", elapsed=elapsed)
    if "error" in outcome:
        error = outcome["error"]
        return Result(False, "error", label, role,
                      detail=f"{type(error).__name__}: {error}", elapsed=elapsed)

    value = outcome["value"]
    confidence = None
    if isinstance(value, tuple) and len(value) == 2:
        value, confidence = value
        wrong = _not_a_confidence(confidence)
        if wrong:
            return Result(False, "error", label, role,
                          detail=f"{label} returned a confidence of "
                                 f"{confidence!r}, which {wrong}",
                          elapsed=elapsed)
    if value is None:
        return Result(False, "refused", label, role,
                      detail="the provider declined to answer",
                      elapsed=elapsed)
    return Result(True, "ok", label, role, data=value,
                  confidence=confidence, elapsed=elapsed)


# --------------------------------------------------------------------------- #
# Writing a result back into the IR
# --------------------------------------------------------------------------- #

def completed(region: dict[str, Any], role: str, field_name: str) -> bool:
    """Whether a provider already finished this region's `role` work.

    Resume rests on this. A region whose current value is exactly what a
    successful provider call wrote is *done* — re-reading it costs an API call
    to be told the same thing, and risks a different answer overwriting a good
    one. A value a person changed afterwards no longer matches, so the region
    correctly stops looking complete and gets looked at again.
    """
    existing = (region.get(field_name) or "").strip()
    if not existing:
        return False
    for record in reversed(region.get("provenance", []) or []):
        if record.get("role") != role:
            continue
        if record.get("outcome") == "applied" and record.get("wrote") == existing:
            return True
    return False


def apply(region: dict[str, Any], field_name: str, result: Result, *,
          min_confidence: float = 0.0) -> str:
    """Put a provider's answer into one region, or explain why it was not.

    Returns what happened: ``applied``, ``unchanged``, ``locked``, ``failed`` or
    ``needs_review``. The rules that matter:

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

    existing = (region.get(field_name) or "").strip()
    locked = bool(region.get("locked"))

    # **A provider fills a hole; it never replaces content, and a locked field
    # is not a hole.** That single rule covers locking, resume and disagreement
    # at once. A value already in the field came from somewhere — a person, the
    # reading model, or an earlier provider run — and a second opinion does not
    # get to overwrite any of those. It gets recorded so somebody can compare.
    #
    # Without this, rerunning the stage silently replaced its own previous
    # answer, which is the opposite of resumable: two runs of the same command
    # could leave two different documents.
    #
    # `locked` is asked here rather than inside the branch below, because a
    # field a person locked while it was *empty* — an unreadable scribble, a
    # balloon that is silent — is a decision too, and consulting `locked` only
    # once there was content to protect made that decision indistinguishable
    # from one nobody had reached yet. The provider filled it.
    if existing or locked:
        outcome = "locked" if locked else "unchanged"
        if text and text != existing:
            provenance.append({**result.as_provenance(),
                               "outcome": "disagreed", "read": text})
            held = "locked" if locked else "existing"
            kept = repr(existing) if existing else "empty"
            note = (f"{result.provider} read this as {text!r}; the {held} "
                    f"value {kept} was kept")
            if note not in region.get("review", []):
                region.setdefault("review", []).append(note)
            return "needs_review"
        provenance.append({**result.as_provenance(), "outcome": outcome})
        return outcome

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
    # The text is recorded beside the outcome so a later run can tell its own
    # earlier work from a human's, which is what makes resume meaningful.
    provenance.append({**result.as_provenance(), "outcome": "applied",
                       "wrote": text})
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
    payload: Any = None
    fail: str = ""

    def describe(self, image_path: str, regions: list[dict[str, Any]]):
        if self.fail == "raise":
            raise RuntimeError("the fake was told to fail")
        # Whatever it returns, unchanged. A vision answer is as often a sentence
        # as a structure, and coercing it to a dict broke on the common case.
        return self.payload


register("ocr", "fake-ocr", FakeOCR)
register("translation", "fake-translation", FakeTranslation)
register("image_edit", "fake-image-edit", FakeImageEdit)
register("visual_qa", "fake-visual-qa", FakeVisualQA)
register("vision", "fake-vision", FakeVision)
