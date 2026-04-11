from __future__ import annotations

from typing import Any

from rich.table import Table

from display.renderer import console


def handle_career(state: dict[str, Any], cmd: str) -> bool:
    up = cmd.strip().upper()
    if not up.startswith("CAREER"):
        return False
    from engine.systems.occupation import (
        career_daily_salary_usd,
        career_title_for_level,
        clear_permanent_career_stain,
        ensure_career,
        list_career_paths,
        promote_career,
        set_active_career_track,
        set_career_break,
    )

    ensure_career(state)
    parts = cmd.split()
    n = len(parts)

    if n == 1 or (n == 2 and parts[1].upper() == "HELP"):
        paths = list_career_paths(state)
        c = state.get("player", {}).get("career", {}) or {}
        at = str(c.get("active_track", "-") or "-")
        t = Table(title="CAREER (W2-9)", show_header=True, header_style="bold cyan")
        t.add_column("track")
        t.add_column("lvl")
        t.add_column("title")
        t.add_column("rep")
        t.add_column("active")
        tracks = (c.get("tracks", {}) or {}) if isinstance(c, dict) else {}
        for p in paths:
            pid = str(p.get("id", "") or "")
            row = tracks.get(pid, {}) if isinstance(tracks, dict) else {}
            lvl = int((row or {}).get("level", 0) or 0) if isinstance(row, dict) else 0
            rep = int((row or {}).get("rep", 0) or 0) if isinstance(row, dict) else 0
            title = career_title_for_level(state, pid, lvl)
            mark = "*" if pid == at else ""
            t.add_row(pid, str(lvl), title[:28], str(rep), mark)
        console.print(t)
        br = "ON" if bool(c.get("on_break")) else "off"
        st = "YES" if bool(c.get("permanent_stain")) else "no"
        pay = career_daily_salary_usd(state)
        console.print(f"[dim]Break: {br} | Permanent record: {st} | Est. daily pay (if paid today): ${pay}[/dim]")
        console.print(
            "[dim]Use: CAREER PROMOTE [track] | CAREER TRACK <id> | CAREER BREAK ON|OFF | CAREER STAIN CLEAR (denied if set)[/dim]"
        )
        return True

    if up.startswith("CAREER STAIN CLEAR") or up.startswith("CAREER CLEAR STAIN"):
        ok = clear_permanent_career_stain(state)
        c2 = state.get("player", {}).get("career", {}) or {}
        if bool(c2.get("permanent_stain")):
            console.print("[yellow]Noda permanen (rekam buronan/penjara) tidak bisa dihapus lewat perintah.[/yellow]")
        else:
            console.print("[dim]Tidak ada noda permanen tercatat.[/dim]")
        _ = ok
        return True

    if up.startswith("CAREER BREAK"):
        if up in ("CAREER BREAK ON", "CAREER BREAK TRUE", "CAREER BREAK 1"):
            set_career_break(state, True)
            console.print("[green]Career break: ON — gaji berhenti; reputasi per jalur akan merosot perlahan per hari.[/green]")
            return True
        if up in ("CAREER BREAK OFF", "CAREER BREAK FALSE", "CAREER BREAK 0"):
            set_career_break(state, False)
            console.print("[green]Career break: OFF — kembali aktif (gaji harian jika memenuhi syarat).[/green]")
            return True
        console.print("[yellow]Usage: CAREER BREAK ON | CAREER BREAK OFF[/yellow]")
        return True

    if up.startswith("CAREER TRACK "):
        tid = cmd.split(maxsplit=2)[2].strip().lower() if len(cmd.split(maxsplit=2)) > 2 else ""
        r = set_active_career_track(state, tid)
        if not r.get("ok"):
            console.print(f"[red]Track tidak dikenal: {tid}[/red]")
            return True
        console.print(f"[green]Jalur aktif: {r.get('active_track')}[/green]")
        return True

    if up.startswith("CAREER PROMOTE"):
        tok = cmd.split(maxsplit=2)
        track_arg = tok[2].strip().lower() if len(tok) > 2 else None
        r = promote_career(state, track_arg)
        if r.get("ok"):
            console.print(f"[green]Promosi OK: {r.get('title')} ({r.get('track')})[/green]")
        else:
            detail = {k: v for k, v in r.items() if k != "ok"}
            console.print(f"[yellow]Promosi ditolak: {detail}[/yellow]")
        return True

    console.print("[yellow]Unknown CAREER subcommand. Try CAREER HELP[/yellow]")
    return True
