from __future__ import annotations

from typing import Any, Callable


def handle_commerce(
    state: dict[str, Any],
    cmd: str,
    *,
    console: Any,
    table_cls: Any,
    list_shop_quotes: Callable[..., Any],
    buy_item: Callable[..., dict[str, Any]],
    sell_item: Callable[..., dict[str, Any]],
    sell_item_all: Callable[..., dict[str, Any]],
    sell_item_n: Callable[..., dict[str, Any]],
    quote_item: Callable[..., Any],
    get_capacity_status: Callable[[dict[str, Any]], Any],
) -> bool:
    up = cmd.upper()
    if up == "MARKET":
        eco = state.get("economy", {}) or {}
        mkt = eco.get("market", {}) or {}
        try:
            loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
            if isinstance(slot, dict) and isinstance(slot.get("market"), dict) and slot.get("market"):
                mkt = slot.get("market") or mkt
        except Exception:
            pass
        mi = (state.get("meta", {}) or {}).get("market_index") or {}
        if not isinstance(mkt, dict) or not mkt:
            console.print("[yellow]MARKET: data market kosong.[/yellow]")
            return True
        tbl = table_cls(title="MARKET")
        tbl.add_column("category", no_wrap=True)
        tbl.add_column("price_idx", justify="right")
        tbl.add_column("scarcity", justify="right")
        if isinstance(mi, dict) and mi:
            tbl.caption = f"idx_avg price={mi.get('price_avg','-')} (Δ{mi.get('d_price','0')}) | scarcity={mi.get('scarcity_avg','-')} (Δ{mi.get('d_scarcity','0')})"
        for cat in ("electronics", "medical", "weapons", "food", "transport"):
            row = mkt.get(cat) if isinstance(mkt.get(cat), dict) else {}
            if not isinstance(row, dict):
                continue
            tbl.add_row(cat, str(row.get("price_idx", "-")), str(row.get("scarcity", "-")))
        console.print(tbl)
        return True
    if up == "SHOP" or up.startswith("SHOP "):
        parts = cmd.split(maxsplit=5)
        arg1 = parts[1].strip().lower() if len(parts) >= 2 else ""
        arg2 = parts[2].strip().lower() if len(parts) >= 3 else ""
        arg3 = parts[3].strip().lower() if len(parts) >= 4 else ""
        arg4 = parts[4].strip().lower() if len(parts) >= 5 else ""
        arg5 = parts[5].strip().lower() if len(parts) >= 6 else ""
        role = ""
        only_avail = False
        page = 1
        tag = ""
        if arg1 == "roles":
            try:
                loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
                slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
                roles_here: list[str] = []
                if isinstance(slot, dict):
                    npcs = slot.get("npcs") or {}
                    if isinstance(npcs, dict):
                        for _nm, row in list(npcs.items())[:120]:
                            if not isinstance(row, dict):
                                continue
                            rr = str(row.get("role", "") or "").strip().lower()
                            if rr and rr not in roles_here:
                                roles_here.append(rr)
                if roles_here:
                    console.print("[bold]SHOP roles[/bold]")
                    console.print("- " + ", ".join(roles_here))
                else:
                    console.print("[yellow]SHOP roles: tidak ada role NPC di lokasi ini (preset belum ada atau belum diaplikasikan).[/yellow]")
            except Exception:
                console.print("[red]SHOP roles error.[/red]")
            return True

        def _parse_page_token(tok: str) -> int | None:
            t = str(tok or "").strip().lower()
            if t.startswith("page"):
                try:
                    n = int(t.replace("page", "").strip() or "0")
                    return n if n >= 1 else None
                except Exception:
                    return None
            return None

        p2 = _parse_page_token(arg2)
        p3 = _parse_page_token(arg3)
        p4 = _parse_page_token(arg4)
        p5 = _parse_page_token(arg5)
        if p2 is not None:
            page = p2
        if p3 is not None:
            page = p3
        if p4 is not None:
            page = p4
        if p5 is not None:
            page = p5
        if arg1 == "tag" and arg2:
            tag = arg2
            role = ""
        elif arg2 == "tag" and arg3:
            tag = arg3
        elif arg3 == "tag" and arg4:
            tag = arg4
        elif arg4 == "tag" and arg5:
            tag = arg5
        if arg1 in ("available", "avail", "in_stock"):
            only_avail = True
        else:
            if arg1 and arg1 != "tag":
                role = arg1
        if arg2 in ("available", "avail", "in_stock"):
            only_avail = True
        if arg3 in ("available", "avail", "in_stock"):
            only_avail = True
        if arg4 in ("available", "avail", "in_stock"):
            only_avail = True
        if arg5 in ("available", "avail", "in_stock"):
            only_avail = True
        offset = max(0, (page - 1) * 12)
        quotes = list_shop_quotes(state, limit=12, role=(role or None), offset=offset, tag=(tag or None))
        if not quotes:
            console.print("[yellow]SHOP: tidak ada item (content pack belum ter-load).[/yellow]")
            return True
        try:
            loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
            slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
            roles_here: list[str] = []
            if isinstance(slot, dict):
                npcs = slot.get("npcs") or {}
                if isinstance(npcs, dict):
                    for _nm, row in list(npcs.items())[:80]:
                        if not isinstance(row, dict):
                            continue
                        rr = str(row.get("role", "") or "").strip().lower()
                        if rr and rr not in roles_here:
                            roles_here.append(rr)
            if roles_here:
                console.print("[dim]roles here: " + ", ".join(roles_here[:10]) + "[/dim]")
        except Exception:
            pass
        try:
            eco = state.get("economy", {}) or {}
            cash = int((eco.get("cash", 0) if isinstance(eco, dict) else 0) or 0)
            cap = get_capacity_status(state)
            console.print(f"[dim]cash={cash} | pocket={cap.pocket_used}/{cap.pocket_cap} | bag={cap.bag_used}/{cap.bag_cap}[/dim]")
        except Exception:
            pass
        if only_avail:
            quotes = [q for q in quotes if q.available]
        title = f"SHOP ({role})" if role else "SHOP"
        if only_avail:
            title += " [available]"
        if tag:
            title += f" [tag={tag}]"
        if page > 1:
            title += f" [page {page}]"
        try:
            from display.renderer import format_data_table

            rows: list[list[str]] = []
            for i, q in enumerate(quotes, start=1):
                stock = "OK" if q.available else "SOLD OUT"
                rows.append([str(i), str(q.item_id), str(q.name), str(q.category), str(stock), str(q.buy_price), str(q.sell_price)])
            console.print(format_data_table(title, ["#", "item_id", "name", "cat", "stock", "buy", "sell"], rows, theme="default"))
        except Exception:
            tbl = table_cls(title=title)
            tbl.add_column("#", justify="right", no_wrap=True)
            tbl.add_column("item_id", no_wrap=True)
            tbl.add_column("name")
            tbl.add_column("cat", no_wrap=True)
            tbl.add_column("stock", no_wrap=True)
            tbl.add_column("buy", justify="right")
            tbl.add_column("sell", justify="right")
            for i, q in enumerate(quotes, start=1):
                stock = "OK" if q.available else "SOLD OUT"
                tbl.add_row(str(i), q.item_id, q.name, q.category, stock, str(q.buy_price), str(q.sell_price))
            console.print(tbl)
        console.print("[dim]Use: SHOP [role] [tag <x>] [available] [page N] | BUY <item_id> [xN] [bag|pocket] [counter|dead_drop|courier] | SELL <item_id> [ALL] | PRICE <item_id>[/dim]")
        return True
    if up == "PRICE" or up.startswith("PRICE "):
        parts = cmd.split(maxsplit=2)
        if len(parts) < 2:
            console.print("[yellow]Usage: PRICE <item_id>[/yellow]")
            return True
        q = quote_item(state, parts[1].strip())
        if q is None:
            console.print("[red]Unknown item_id.[/red]")
            return True
        console.print(f"[bold]PRICE[/bold] {q.item_id} ({q.name})")
        console.print(f"- cat={q.category} base={q.base_price} price_idx={q.price_idx} scarcity={q.scarcity}")
        console.print(f"- buy={q.buy_price} sell={q.sell_price}")
        if q.available:
            console.print("- stock=OK")
        else:
            console.print(f"- stock=SOLD OUT ({q.sold_out_reason})")
        return True
    if up == "BUY" or up.startswith("BUY "):
        parts = cmd.split(maxsplit=5)
        if len(parts) < 2:
            console.print("[yellow]Usage: BUY <item_id> [xN] [bag|pocket] [counter|dead_drop|courier][/yellow]")
            return True
        iid = parts[1].strip()
        qty = 1
        prefer = "bag"
        delivery = "counter"
        for tok in parts[2:]:
            t = str(tok).strip().lower()
            if t.startswith("x") and len(t) >= 2:
                try:
                    qty = max(1, min(50, int(t[1:])))
                except Exception:
                    qty = 1
            elif t in ("bag", "pocket"):
                prefer = t
            elif t in ("counter", "dead_drop", "deaddrop", "dead", "drop", "courier", "meet"):
                delivery = t
        bought = 0
        last_err = None
        last_res = None
        for _ in range(qty):
            res = buy_item(state, iid, prefer=prefer, delivery=delivery)
            last_res = res
            if not bool(res.get("ok")):
                last_err = res
                break
            bought += 1
        if bought <= 0:
            res = last_err or last_res or {}
            reason = res.get("reason", "error")
            detail = res.get("detail")
            if reason == "sold_out":
                console.print(f"[red]BUY failed: SOLD OUT[/red] ({detail})")
            elif reason == "not_enough_cash":
                console.print(f"[red]BUY failed: not enough cash[/red] need={res.get('need')} cash={res.get('cash')}")
            elif reason == "no_capacity":
                console.print("[red]BUY failed: no capacity[/red] " f"size={res.get('size')} pocket={res.get('pocket_used')}/{res.get('pocket_cap')} bag={res.get('bag_used')}/{res.get('bag_cap')}")
            else:
                console.print(f"[red]BUY failed: {reason}[/red]")
            return True
        q = (last_res or {}).get("quote")
        cash_after = (last_res or {}).get("cash_after")
        placed = (last_res or {}).get("placed_to", prefer)
        if placed == "delivery_pending":
            d = (last_res or {}).get("delivery", "?")
            due = (last_res or {}).get("delivery_due_in_min", "?")
            fee = (last_res or {}).get("delivery_fee", 0)
            console.print(f"[yellow]Delivery scheduled[/yellow] via={d} fee={fee} due~{due}min (pickup required)")
        if bought == 1 and q:
            console.print(f"[green]BUY OK[/green] {q.item_id} price={q.buy_price} cash={cash_after} to={placed}")
        elif q:
            console.print(f"[green]BUY OK[/green] {q.item_id} x{bought} cash={cash_after} (last_to={placed})")
            if last_err:
                console.print(f"[yellow]Stopped early: {last_err.get('reason','error')}[/yellow]")
        else:
            console.print(f"[green]BUY OK[/green] x{bought}")
        return True
    if up == "SELL" or up.startswith("SELL "):
        parts = cmd.split(maxsplit=3)
        if len(parts) < 2:
            console.print("[yellow]Usage: SELL <item_id> [ALL][/yellow]")
            return True
        iid = parts[1].strip()
        tok = parts[2].strip() if len(parts) >= 3 else ""
        all_mode = tok.upper() == "ALL"
        qty_mode = tok.lower().startswith("x") and len(tok) >= 2
        if all_mode:
            res = sell_item_all(state, iid)
        elif qty_mode:
            try:
                n = int(tok[1:])
            except Exception:
                n = 1
            res = sell_item_n(state, iid, n=n)
        else:
            res = sell_item(state, iid)
        if not bool(res.get("ok")):
            console.print(f"[red]SELL failed: {res.get('reason','error')}[/red]")
            return True
        q = res.get("quote")
        if q:
            if all_mode:
                console.print(f"[green]SELL ALL OK[/green] {q.item_id} n={res.get('count',0)} unit={q.sell_price} gain={res.get('gain',0)} cash={res.get('cash_after')}")
            elif qty_mode:
                console.print(f"[green]SELL x OK[/green] {q.item_id} n={res.get('count',0)} unit={q.sell_price} gain={res.get('gain',0)} cash={res.get('cash_after')}")
            else:
                console.print(f"[green]SELL OK[/green] {q.item_id} price={q.sell_price} cash={res.get('cash_after')}")
        else:
            console.print("[green]SELL OK[/green]")
        return True
    return False

