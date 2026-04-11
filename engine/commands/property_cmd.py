from __future__ import annotations

from typing import Any

from rich.table import Table

from display.renderer import console


def handle_property(state: dict[str, Any], cmd: str) -> bool:
    up = cmd.strip().upper()
    if not up.startswith("PROPERTY"):
        return False

    import engine.systems.property as prop

    prop.ensure_player_assets(state)
    parts = cmd.split()
    n = len(parts)

    if n == 1 or (n >= 2 and parts[1].upper() in ("LIST", "HELP", "STATUS")):
        t = Table(title="PROPERTY / ASSETS (W2-10)", header_style="bold cyan")
        t.add_column("id")
        t.add_column("kind")
        t.add_column("city")
        t.add_column("notes")
        for raw in prop.list_asset_entries(state):
            if not isinstance(raw, dict):
                continue
            aid = str(raw.get("asset_id", "-") or "-")
            kind = str(raw.get("kind", "-") or "-")
            city = str(raw.get("city", "-") or "-")
            if bool(raw.get("rental")):
                note = f"sewa ~${raw.get('rent_daily_usd', 0)}/d"
            else:
                note = f"own maint ~${raw.get('maintenance_daily_usd', 0)}/d"
            t.add_row(aid[:18], kind, city, note[:40])
        console.print(t)
        loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
        if loc:
            console.print(
                f"[dim]Quotes @{loc}: apt ${prop.quote_apartment_buy_usd(state, loc)} | "
                f"house ${prop.quote_house_buy_usd(state, loc)} | car_std ~${prop.quote_vehicle_price_usd(state, loc, 'car_standard')}[/dim]"
            )
        console.print(
            "[dim]PROPERTY PRICES <city> | BUY APARTMENT|HOUSE|BUSINESS <city> | RENT APARTMENT <city> | SELL <asset_id> | BUY VEHICLE <id>[/dim]"
        )
        return True

    if n >= 2 and parts[1].upper() == "PRICES" and n >= 3:
        city = parts[2].strip().lower()
        console.print(
            f"[cyan]{city}[/cyan]: apt ${prop.quote_apartment_buy_usd(state, city)} | "
            f"house ${prop.quote_house_buy_usd(state, city)} | "
            f"rent ~${prop.quote_rent_daily_usd(state, city)}/d | "
            f"car_std ~${prop.quote_vehicle_price_usd(state, city, 'car_standard')}"
        )
        return True

    if n >= 4 and parts[1].upper() == "BUY" and parts[2].upper() == "APARTMENT":
        r = prop.buy_apartment(state, parts[3], rental=False)
        console.print(f"[green]{r}[/green]" if r.get("ok") else f"[yellow]{r}[/yellow]")
        return True
    if n >= 4 and parts[1].upper() == "RENT" and parts[2].upper() == "APARTMENT":
        r = prop.buy_apartment(state, parts[3], rental=True)
        console.print(f"[green]{r}[/green]" if r.get("ok") else f"[yellow]{r}[/yellow]")
        return True
    if n >= 4 and parts[1].upper() == "BUY" and parts[2].upper() == "HOUSE":
        r = prop.buy_house(state, parts[3])
        console.print(f"[green]{r}[/green]" if r.get("ok") else f"[yellow]{r}[/yellow]")
        return True
    if n >= 4 and parts[1].upper() == "BUY" and parts[2].upper() == "BUSINESS":
        r = prop.buy_small_business(state, parts[3])
        console.print(f"[green]{r}[/green]" if r.get("ok") else f"[yellow]{r}[/yellow]")
        return True
    if n >= 4 and parts[1].upper() == "BUY" and parts[2].upper() == "VEHICLE":
        vid = parts[3].strip().lower()
        r = prop.buy_vehicle_city_priced(state, vid)
        console.print(f"[green]{r}[/green]" if r.get("ok") else f"[yellow]{r}[/yellow]")
        return True
    if n >= 3 and parts[1].upper() == "SELL":
        r = prop.sell_asset(state, parts[2])
        console.print(f"[green]{r}[/green]" if r.get("ok") else f"[yellow]{r}[/yellow]")
        return True

    console.print("[yellow]PROPERTY: subcommand tidak dikenal. Ketik PROPERTY untuk bantuan.[/yellow]")
    return True
