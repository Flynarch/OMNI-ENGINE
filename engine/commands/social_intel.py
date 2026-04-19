from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from typing import Any


def handle_social_intel(state: dict[str, Any], cmd: str, *, console: Any, table_cls: Any) -> bool:
    up = cmd.upper()
    if up == "HEAT":
        world = state.get("world", {}) or {}
        hh = world.get("hacking_heat", {}) or {}
        loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        tbl = table_cls(title="HEAT (per target @ lokasi)")
        tbl.add_column("target", no_wrap=True)
        tbl.add_column("heat", justify="right")
        tbl.add_column("noise", justify="right")
        tbl.add_column("signal", justify="right")
        tbl.add_column("rekomendasi")
        rows = 0
        if isinstance(hh, dict):
            for k, v in hh.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    continue
                if loc and not k.startswith(loc + "|"):
                    continue
                target = k.split("|", 1)[1] if "|" in k else k
                try:
                    heat = int(v.get("heat", 0) or 0)
                except Exception as _omni_sw_28:
                    log_swallowed_exception('engine/commands/social_intel.py:28', _omni_sw_28)
                    heat = 0
                try:
                    noise = int(v.get("noise", 0) or 0)
                except Exception as _omni_sw_32:
                    log_swallowed_exception('engine/commands/social_intel.py:32', _omni_sw_32)
                    noise = 0
                try:
                    signal = int(v.get("signal", 0) or 0)
                except Exception as _omni_sw_36:
                    log_swallowed_exception('engine/commands/social_intel.py:36', _omni_sw_36)
                    signal = 0
                rec = "OK"
                if heat >= 75 or signal >= 75:
                    rec = "COVER TRACKS / jeda / stealth"
                elif heat >= 45 or noise >= 45:
                    rec = "stealth / jeda"
                tbl.add_row(str(target), str(heat), str(noise), str(signal), rec)
                rows += 1
        if rows == 0:
            console.print("[yellow]HEAT: tidak ada data untuk lokasi ini.[/yellow]")
        else:
            console.print(tbl)
        return True
    if up == "OFFERS" or up.startswith("OFFERS "):
        parts = cmd.split(maxsplit=2)
        want_role = parts[1].strip().lower() if len(parts) >= 2 else ""
        econ = (state.get("world", {}) or {}).get("npc_economy", {}) or {}
        offers = econ.get("offers", {}) if isinstance(econ, dict) else {}
        if not isinstance(offers, dict) or not offers:
            console.print("[yellow]OFFERS: tidak ada offer aktif.[/yellow]")
            return True
        meta = state.get("meta", {}) or {}
        day = int(meta.get("day", 1) or 1)
        out: list[str] = []
        for k in sorted(list(offers.keys())):
            v = offers.get(k)
            if not isinstance(v, dict):
                continue
            role = str(v.get("role", "") or "").strip().lower()
            if want_role and role != want_role:
                continue
            npc = str(v.get("npc", k))
            svc = str(v.get("service", "offer"))
            try:
                exp = int(v.get("expires_day", day) or day)
            except Exception as _omni_sw_72:
                log_swallowed_exception('engine/commands/social_intel.py:72', _omni_sw_72)
                exp = day
            ttl = max(0, exp - day)
            out.append(f"- {npc} ({role}): {svc} (ttl {ttl}d)")
        if not out:
            console.print(f"[yellow]OFFERS: tidak ada offer untuk role '{want_role}'.[/yellow]")
        else:
            console.print(f"[bold]OFFERS{' ' + want_role if want_role else ''}[/bold]")
            for line in out[:25]:
                console.print(line)
        return True
    return False

