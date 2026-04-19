from __future__ import annotations

from typing import Any

from display.renderer import render_faction_report


def handle_faction_report(state: dict[str, Any], cmd: str) -> bool:
    up = str(cmd or "").strip().upper()
    if up == "FACTION_REPORT":
        render_faction_report(state, full=False)
        return True
    if up == "FACTION_REPORT FULL":
        render_faction_report(state, full=True)
        return True
    return False
