"""Stable locations for document-owned worksheet references."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def worksheet_folder(doc_path: Path | str, doc: dict[str, Any],
                     override: str | Path | None = None) -> Path:
    """Resolve an invocation path once, or a recorded path beside the document.

    Historical working-directory-relative records cannot reveal their original
    invocation directory. An operator supplies an explicit override to reconcile
    those records without moving or guessing at their files.
    """
    if override:
        return Path(override).expanduser().resolve()
    recorded = (doc.get("meta") or {}).get("worksheets")
    folder = Path(recorded).expanduser() if recorded else Path("worksheets")
    return folder if folder.is_absolute() else Path(doc_path).resolve().parent / folder
