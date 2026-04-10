from __future__ import annotations

from typing import Any, Callable

from rich.table import Table

from display.renderer import console


def handle_misc(
    state: dict[str, Any],
    cmd: str,
    *,
    fmt_clock: Callable[[int], str],
) -> bool:
    up = cmd.upper()
    if up == "UI FULL":
        state.setdefault("meta", {})["monitor_mode"] = "full"
        console.print("[green]Monitor: FULL (lebar).[/green]")
        return True
    if up == "UI COMPACT":
        state.setdefault("meta", {})["monitor_mode"] = "compact"
        console.print("[green]Monitor: COMPACT (ringkas).[/green]")
        return True
    if up in ("STATUS", "INFO"):
        meta = state.get("meta", {}) or {}
        tr = state.get("trace", {}) or {}
        eco = state.get("economy", {}) or {}
        try:
            gigs_done = int(meta.get("daily_gigs_done", 0) or 0)
        except Exception:
            gigs_done = 0
        try:
            hacks_attempted = int(meta.get("daily_hacks_attempted", 0) or 0)
        except Exception:
            hacks_attempted = 0
        penalty = max(0, int(hacks_attempted) * 10)
        t = Table(title="STATUS", show_header=False)
        t.add_column("k", style="bold cyan", no_wrap=True)
        t.add_column("v")
        t.add_row("Location", str((state.get("player", {}) or {}).get("location", "-") or "-"))
        t.add_row("Clock", f"Day {int(meta.get('day', 1) or 1)} {fmt_clock(int(meta.get('time_min', 0) or 0))}")
        t.add_row("Trace", f"{int(tr.get('trace_pct', 0) or 0)}%")
        t.add_row("Cash/Bank", f"${int(eco.get('cash', 0) or 0)} / ${int(eco.get('bank', 0) or 0)}")
        t.add_row("Daily Gigs", f"{max(0, gigs_done)}/2")
        t.add_row("Neural Fatigue", f"{penalty}% fail penalty")
        console.print(t)
        return True
    return False

