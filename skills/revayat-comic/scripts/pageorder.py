"""Panel membership shared by detection and explicit box corrections."""

from __future__ import annotations

from typing import Any

import pageir as ir


def assign_panel(page: dict[str, Any], region: dict[str, Any]) -> None:
    region["panel"] = next((panel["id"] for panel in page.get("panels", [])
                            if ir.bbox_contains(panel["bbox"], region["bbox"], slack=0.6)), None)
