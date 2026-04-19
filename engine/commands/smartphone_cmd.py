"""CLI: PHONE / SMARTPHONE (W2-11)."""

from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any

from display.renderer import console
from engine.systems.smartphone import ensure_smartphone, parse_phone_command


def handle_smartphone(state: dict[str, Any], cmd: str, *, run_pipeline: Any) -> bool:
    raw = str(cmd or "").strip()
    up = raw.upper()
    if not (up.startswith("PHONE") or up.startswith("SMARTPHONE")):
        return False

    parsed = parse_phone_command(raw)
    if not isinstance(parsed, dict):
        console.print("[yellow]Could not parse phone command.[/yellow]")
        return True

    if parsed.get("smartphone_cli_help"):
        console.print(
            "[cyan]PHONE / SMARTPHONE[/cyan]\n"
            "  PHONE ON | OFF | STATUS\n"
            "  PHONE CALL <name>\n"
            "  PHONE MSG <name> <text…>\n"
            "  PHONE DARKWEB\n"
            "[dim]Phone must be ON for calls, SMS, and dark web. High heat + powered phone risks daily trace drift.[/dim]"
        )
        return True

    if parsed.get("smartphone_cli_error"):
        console.print(
            "[yellow]Usage:[/yellow] PHONE ON|OFF|STATUS | PHONE CALL <name> | PHONE MSG <name> <text> | PHONE DARKWEB"
        )
        return True

    try:
        run_pipeline(state, parsed)
    except Exception as e:
        log_swallowed_exception('engine/commands/smartphone_cmd.py:42', e)
        console.print(f"[red]PHONE error: {e}[/red]")
        return True

    sr = parsed.get("smartphone_result") if isinstance(parsed.get("smartphone_result"), dict) else {}
    ok = bool(sr.get("ok"))
    msg = str(sr.get("msg", "") or "")
    if ok:
        console.print(f"[green]{msg}[/green]" if msg else "[green]OK[/green]")
    else:
        reason = str(sr.get("reason", "") or "")
        console.print(f"[yellow]{reason}: {msg}[/yellow]" if reason else f"[yellow]{msg}[/yellow]")
    ensure_smartphone(state)
    return True
