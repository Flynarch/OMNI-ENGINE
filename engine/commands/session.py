from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any, Callable
import json
import os

from ai.parser import filter_narration_for_player_display


def handle_session(
    state: dict[str, Any],
    cmd: str,
    *,
    console: Any,
    previous_path: Any,
    load_state: Callable[[Any], dict[str, Any]],
    get_narration_lang: Callable[[dict[str, Any]], str],
    stream_response: Callable[[str, str], Any],
    build_system_prompt: Callable[[dict[str, Any]], str],
    stream_render: Callable[[str], None],
) -> bool:
    up = cmd.upper()
    if up == "UNDO":
        iron = bool((state.get("flags", {}) or {}).get("ironman_mode", False))
        if iron:
            console.print("[red]IRONMAN mode aktif: UNDO dinonaktifkan.[/red]")
            return True
        if previous_path.exists():
            try:
                restored = load_state(previous_path)
                state.clear()
                state.update(restored)
                console.print("[green]UNDO: restored previous turn.[/green]")
            except Exception as _omni_sw_32:
                log_swallowed_exception('engine/commands/session.py:32', _omni_sw_32)
                console.print("[red]UNDO gagal: previous.json tidak bisa dibaca.[/red]")
        else:
            console.print("[yellow]UNDO tidak tersedia (previous.json belum ada).[/yellow]")
        return True
    if up == "MODE" or up.startswith("MODE "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            iron = bool((state.get("flags", {}) or {}).get("ironman_mode", False))
            console.print(f"[yellow]Mode: {'IRONMAN' if iron else 'NORMAL'}[/yellow]")
            console.print("[dim]Pakai: MODE NORMAL | MODE IRONMAN[/dim]")
            return True
        mode = parts[1].strip().lower()
        if mode not in ("normal", "ironman"):
            console.print("[red]Pakai: MODE NORMAL | MODE IRONMAN[/red]")
            return True
        state.setdefault("flags", {})["ironman_mode"] = (mode == "ironman")
        console.print(f"[green]Mode set → {mode.upper()}[/green]")
        return True
    if up == "SAVE STATE":
        console.print(json.dumps(state, ensure_ascii=False, indent=2))
        return True
    if up == "WORLD_BRIEF":
        lang = get_narration_lang(state)
        if lang == "en":
            turn_package = "WORLD_BRIEF: summarize the world from the player character's POV in <=400 words."
        else:
            turn_package = "WORLD_BRIEF: rangkum dunia dari sudut pandang karakter pemain, maksimal ~400 kata, Bahasa Indonesia."
        try:
            parts: list[str] = []
            for chunk in stream_response(build_system_prompt(state), turn_package):
                parts.append(chunk)
            console.print(filter_narration_for_player_display("".join(parts)))
            console.print()
        except Exception as _omni_sw_64:
            log_swallowed_exception('engine/commands/session.py:64', _omni_sw_64)
            console.print("[red]// SIGNAL LOST //[/red]")
        return True
    if up == "LANG" or up.startswith("LANG "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            console.print(f"[yellow]Bahasa narasi: {get_narration_lang(state)} (ketik: LANG id | LANG en)[/yellow]")
            return True
        code = parts[1].lower()
        if code not in ("id", "en"):
            console.print("[red]Pakai: LANG id atau LANG en[/red]")
            return True
        state.setdefault("player", {})["language"] = code
        if os.getenv("NARRATION_LANG", "").strip():
            console.print("[dim]Catatan: NARRATION_LANG di .env menimpa — kosongkan untuk pakai LANG.[/dim]")
        console.print(f"[green]Narasi AI → {'Bahasa Indonesia' if code == 'id' else 'English'}[/green]")
        return True
    if up == "NARRATION" or up.startswith("NARRATION "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            style = str(state.get("player", {}).get("narration_style", "cinematic") or "cinematic").lower()
            console.print(f"[yellow]Narasi style: {style} (ketik: NARRATION compact | NARRATION cinematic)[/yellow]")
            return True
        style = parts[1].strip().lower()
        if style not in ("compact", "cinematic"):
            console.print("[red]Pakai: NARRATION compact | NARRATION cinematic[/red]")
            return True
        state.setdefault("player", {})["narration_style"] = style
        console.print(f"[green]Narasi style → {style}[/green]")
        return True
    return False

