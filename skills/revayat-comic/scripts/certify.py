"""Do the bytes about to be packaged come from the run that claims them?

Provenance, not content. Nothing here reads Persian, measures a balloon or
judges a repair — `qa` does that. These three questions are narrower and none
of them could be answered from the document alone:

* **is this page allowed to ship the file it is about to ship?** `export`
  resolves the most finished version that EXISTS, and that fallback is silent.
* **is the finished render the one `typeset` committed?**
* **is the cleaned page the one `clean` produced?**

The third is why this module exists as its own file. Delivery hashes were
written during typesetting, so a chapter that legitimately never reaches
typesetting — a watermark-removal job, where there is no Persian to draw —
shipped uncertified bytes with every region reporting `clean_status: cleaned`.
A success status recorded by an earlier run is not evidence about the file on
disk now.

Each function takes the caller's findings sink rather than importing `qa`, so
the gate owns severities and this module owns evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pageir as ir

#: Written by every build that signs its output. A record missing one of these
#: is not a record from an older build — those have no record at all — so it is
#: rebuilt by re-running the stage rather than accepted as partly verified.
DELIVERY_FIELDS = ("final", "clean", "writable")
CLEANING_FIELDS = ("source", "mask", "clean")


def certify_artifact(findings: Any, root: Path, page: dict[str, Any]) -> None:
    """Is this page allowed to ship the file it is about to ship?

    The gate asked this about Persian only. An erasure had no equivalent, so
    deleting a cleaned page promoted the original — watermark intact, the
    reader's approved erasure undone — into an approved edition, counted as an
    untouched page and reported as nothing at all.
    """
    found = ir.shipped_artifact(root, page)
    if found is None:
        findings.add("page-missing", page["id"],
                     "this page has no image on disk at all")
        return
    shipping = found[1]
    required = ir.required_artifact(page)
    if ir.ARTIFACT_ORDER.index(shipping) <= ir.ARTIFACT_ORDER.index(required):
        return
    if required == "final":
        findings.add(
            "page-not-rendered", page["id"],
            "this page carries Persian that has never been drawn onto "
            "it; run `typeset` before calling the chapter finished")
    else:
        findings.add(
            "page-not-cleaned", page["id"],
            f"the cleaner repaired this page and the repaired image is gone, "
            f"so it would ship as `{shipping}` — with everything that was "
            f"erased still on it. Re-run `clean`, or restore the file")


def certify_delivery(findings: Any, root: Path, page: dict[str, Any],
                     final: str) -> None:
    """Are the bytes on disk the ones the render committed?

    `typeset` signs the finished page, the writable mask it drew inside and the
    cleaned page it drew onto. This re-reads all three. A page swapped for its
    own cleaned copy, a mask rebuilt under a finished render, a hand-edited PNG
    dropped in afterwards: every one of them changes a hash and none of them
    changes a status.
    """
    delivery = page.get("delivery") or {}
    if not delivery:
        # Rendered by a build that did not sign its output. A warning, for the
        # same reason `stage-unverified` is one: a chapter finished by an older
        # build is not evidence of anything wrong, and making people re-render
        # to satisfy new bookkeeping would be a defect of the upgrade.
        findings.add(
            "delivery-unverified", page["id"],
            "this page was rendered before finished pages were signed, so "
            "there is nothing to check the file against. Re-run `typeset` to "
            "certify it")
        return

    _size(findings, page, delivery, "the render")
    named = {"final": final, "clean": page.get("clean"),
             "writable": page.get("writable")}
    _verify(findings, root, page, delivery, DELIVERY_FIELDS, named,
            "the render", "typeset")


def certify_cleaning(findings: Any, root: Path, page: dict[str, Any]) -> None:
    """Is the cleaned page the one `clean` produced, from the same inputs?

    Reached by every chapter, including one that never renders. Without it the
    only evidence an erasure had happened was `clean_status` on each region,
    which an earlier run wrote and nothing since has re-examined.
    """
    cleaned = page.get("clean")
    record = page.get("cleaning") or {}
    if not record:
        if cleaned:
            findings.add(
                "delivery-unverified", page["id"],
                "this page was cleaned before cleaned pages were signed, so "
                "there is nothing to check the file against. Re-run `clean` "
                "to certify it")
        return

    _size(findings, page, record, "the cleaning")
    named = {"source": page.get("image"), "mask": page.get("mask"),
             "clean": cleaned}
    _verify(findings, root, page, record, CLEANING_FIELDS, named,
            "the cleaning", "clean")


def _size(findings: Any, page: dict[str, Any], record: dict[str, Any],
          subject: str) -> None:
    recorded = list(record.get("size") or ())
    if recorded == [page["width"], page["height"]]:
        return
    findings.add(
        "delivery-mismatch", page["id"],
        f"{subject} was committed at "
        f"{'x'.join(str(number) for number in recorded or ('?', '?'))} and "
        f"the page is now {page['width']}x{page['height']}")


def _verify(findings: Any, root: Path, page: dict[str, Any],
            record: dict[str, Any], fields: tuple[str, ...],
            named: dict[str, str | None], subject: str, stage: str) -> None:
    """Every field of a certificate, against the file the document names.

    A missing field used to be skipped — `if not recorded: continue` — so
    deleting one line of the certificate bought exemption from the check that
    line existed to make. An absent field is now the record failing to cover
    something, repaired by running the stage again rather than by trusting what
    is left of the record.
    """
    for name in fields:
        relative = named.get(name)
        if name not in record:
            findings.add(
                "delivery-mismatch", page["id"],
                f"{subject} certificate says nothing about the {name} page, "
                f"so there is no way to check it. Re-run `{stage}`")
            continue
        recorded = record[name]
        if recorded is None:
            # Legitimately absent when the stage ran — `typeset` signs a `clean`
            # of `None` for a page it drew straight onto the original. The
            # document naming one NOW means the file appeared afterwards, which
            # is a different page from the one that was signed.
            if relative:
                findings.add(
                    "delivery-mismatch", page["id"],
                    f"{subject} was committed with no {name} page and the "
                    f"document names {relative} now. Re-run `{stage}`")
            continue
        if not relative:
            findings.add(
                "delivery-mismatch", page["id"],
                f"{subject} committed a {name} page and the document no "
                f"longer names one. Re-run `{stage}`")
            continue
        path = root / relative
        if not path.exists():
            findings.add(
                "delivery-mismatch", page["id"],
                f"{relative} was part of {subject} and is gone")
        elif ir.sha256_file(path) != recorded:
            findings.add(
                "delivery-mismatch", page["id"],
                f"{relative} is not the file this page was finished with — "
                f"it was replaced after `{stage}` ran. Re-run `{stage}`, or "
                f"restore the file it used")
