from __future__ import annotations

from typing import Any, Callable

from display.renderer import format_data_table
from engine.core.error_taxonomy import log_swallowed_exception

_EDIBLE_TAGS = {"food", "ration", "snack", "meal", "drink", "water"}


def _shop_item_row(state: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    world = state.get("world", {}) or {}
    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items = idx.get("items", {}) if isinstance(idx, dict) else {}
    if not isinstance(items, dict):
        return None
    row = items.get(str(item_id or "").strip())
    return row if isinstance(row, dict) else None


def _item_tags(row: dict[str, Any]) -> list[str]:
    tags = row.get("tags", [])
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for t in tags[:40]:
        if isinstance(t, str) and t.strip():
            s = t.strip().lower()
            if s not in out:
                out.append(s)
    return out


def _is_edible_tags(tags: list[str]) -> bool:
    return any(t in _EDIBLE_TAGS for t in tags)


def _is_food_item(state: dict[str, Any], item_id: str) -> bool:
    row = _shop_item_row(state, item_id)
    if not isinstance(row, dict):
        return False
    tags = _item_tags(row)
    return _is_edible_tags(tags)


def _food_restore_value(state: dict[str, Any], item_id: str) -> float:
    row = _shop_item_row(state, item_id)
    if not isinstance(row, dict):
        return 20.0
    tags = _item_tags(row)
    try:
        calories = float(row.get("calories", 0) or 0)
    except Exception as _omni_sw_50:
        log_swallowed_exception('engine/commands/commerce.py:50', _omni_sw_50)
        calories = 0.0
    if calories > 0:
        return max(8.0, min(50.0, round(calories / 16.0, 2)))
    if "meal" in tags:
        return 35.0
    if "ration" in tags:
        return 30.0
    if "snack" in tags:
        return 18.0
    if "drink" in tags or "water" in tags:
        return 10.0
    return 22.0


def _remove_item_once_from_inventory(state: dict[str, Any], item_id: str) -> bool:
    inv = state.setdefault("inventory", {})
    if not isinstance(inv, dict):
        return False
    iid = str(item_id or "").strip()
    if not iid:
        return False
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key)
        if isinstance(arr, list):
            for i, x in enumerate(arr):
                if str(x) == iid:
                    del arr[i]
                    return True
    return False


def _apply_hunger_reduction(state: dict[str, Any], amount: float) -> tuple[float, float, str]:
    bio = state.setdefault("bio", {})
    try:
        before = float(bio.get("hunger", 0.0) or 0.0)
    except Exception as _omni_sw_86:
        log_swallowed_exception('engine/commands/commerce.py:86', _omni_sw_86)
        before = 0.0
    after = max(0.0, min(100.0, round(before - max(0.0, amount), 2)))
    if after <= 20.0:
        label = "full"
    elif after <= 40.0:
        label = "okay"
    elif after <= 65.0:
        label = "hungry"
    elif after <= 85.0:
        label = "starving"
    else:
        label = "critical"
    bio["hunger"] = after
    bio["hunger_label"] = label
    return before, after, label


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
    run_pipeline: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> bool:
    up = cmd.upper()
    if up == "EAT" or up.startswith("EAT "):
        parts = cmd.split(maxsplit=1)
        want_iid = parts[1].strip() if len(parts) >= 2 else ""
        inv = state.get("inventory", {}) or {}
        pocket = inv.get("pocket_contents", []) if isinstance(inv, dict) else []
        bag = inv.get("bag_contents", []) if isinstance(inv, dict) else []
        candidates: list[str] = []
        if isinstance(pocket, list):
            candidates.extend([str(x) for x in pocket if isinstance(x, str)])
        if isinstance(bag, list):
            candidates.extend([str(x) for x in bag if isinstance(x, str)])
        food_in_inv = [iid for iid in candidates if _is_food_item(state, iid)]
        chosen = ""
        source = ""
        buy_fail_reason = ""

        def _buy_fail_text(res: dict[str, Any]) -> str:
            reason = str(res.get("reason", "error") or "error")
            if reason == "not_enough_cash":
                return f"cash kurang (need={res.get('need')}, cash={res.get('cash')})"
            if reason == "no_capacity":
                return "kapasitas inventory penuh"
            if reason == "sold_out":
                return "stok habis"
            if reason == "unknown_item":
                return "item tidak dikenal"
            return reason

        if want_iid:
            if any(iid == want_iid for iid in food_in_inv):
                chosen = want_iid
                source = "inventory"
            else:
                q = quote_item(state, want_iid)
                if q and bool(q.available) and _is_food_item(state, want_iid):
                    b = buy_item(state, want_iid, prefer="pocket", delivery="counter")
                    if bool(b.get("ok")):
                        chosen = want_iid
                        source = "market"
                    else:
                        buy_fail_reason = _buy_fail_text(b if isinstance(b, dict) else {})
                elif q and not bool(q.available):
                    buy_fail_reason = "stok habis"
                elif q:
                    buy_fail_reason = "item bukan makanan/minuman"
                else:
                    buy_fail_reason = "item tidak ditemukan"
        else:
            if food_in_inv:
                chosen = food_in_inv[0]
                source = "inventory"
            else:
                for q in list_shop_quotes(state, limit=20):
                    if not bool(q.available):
                        continue
                    if not _is_food_item(state, str(q.item_id)):
                        continue
                    if bool(q.available):
                        b = buy_item(state, q.item_id, prefer="pocket", delivery="counter")
                        if bool(b.get("ok")):
                            chosen = q.item_id
                            source = "market"
                            break
                        buy_fail_reason = _buy_fail_text(b if isinstance(b, dict) else {})
        if not chosen:
            if buy_fail_reason:
                console.print(f"[yellow]EAT gagal: {buy_fail_reason}.[/yellow]")
            else:
                console.print("[yellow]EAT: tidak ada makanan di inventory/market.[/yellow]")
            return True
        if not _remove_item_once_from_inventory(state, chosen):
            if source == "market":
                console.print("[red]EAT failed: makanan tidak masuk inventory setelah pembelian.[/red]")
            else:
                console.print("[red]EAT failed: item tidak ditemukan di inventory.[/red]")
            return True
        restore = _food_restore_value(state, chosen)
        before, after, hlabel = _apply_hunger_reduction(state, restore)
        state.setdefault("world_notes", []).append(
            f"[Bio] Ate {chosen} source={source} hunger {before:.2f}->{after:.2f} ({hlabel})."
        )
        console.print(
            f"[green]EAT OK[/green] {chosen} ({source}) hunger {before:.1f} -> {after:.1f} [{hlabel}]"
        )
        if callable(run_pipeline):
            try:
                run_pipeline(
                    state,
                    {
                        "action_type": "instant",
                        "domain": "other",
                        "normalized_input": f"eat {chosen}",
                        "instant_minutes": 0,
                        "stakes": "low",
                    },
                )
            except Exception as _omni_sw_216:
                log_swallowed_exception('engine/commands/commerce.py:216', _omni_sw_216)
        return True
    if up == "MARKET":
        eco = state.get("economy", {}) or {}
        mkt = eco.get("market", {}) or {}
        try:
            loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
            if isinstance(slot, dict) and isinstance(slot.get("market"), dict) and slot.get("market"):
                mkt = slot.get("market") or mkt
        except Exception as _omni_sw_227:
            log_swallowed_exception('engine/commands/commerce.py:227', _omni_sw_227)
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
            except Exception as _omni_sw_276:
                log_swallowed_exception('engine/commands/commerce.py:276', _omni_sw_276)
                console.print("[red]SHOP roles error.[/red]")
            return True

        def _parse_page_token(tok: str) -> int | None:
            t = str(tok or "").strip().lower()
            if t.startswith("page"):
                try:
                    n = int(t.replace("page", "").strip() or "0")
                    return n if n >= 1 else None
                except Exception as _omni_sw_286:
                    log_swallowed_exception('engine/commands/commerce.py:286', _omni_sw_286)
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
        except Exception as _omni_sw_344:
            log_swallowed_exception('engine/commands/commerce.py:344', _omni_sw_344)
        try:
            eco = state.get("economy", {}) or {}
            cash = int((eco.get("cash", 0) if isinstance(eco, dict) else 0) or 0)
            cap = get_capacity_status(state)
            console.print(f"[dim]cash={cash} | pocket={cap.pocket_used}/{cap.pocket_cap} | bag={cap.bag_used}/{cap.bag_cap}[/dim]")
        except Exception as _omni_sw_351:
            log_swallowed_exception('engine/commands/commerce.py:351', _omni_sw_351)
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
            rows: list[list[str]] = []
            for i, q in enumerate(quotes, start=1):
                stock = "OK" if q.available else "SOLD OUT"
                rows.append([str(i), str(q.item_id), str(q.name), str(q.category), str(stock), str(q.buy_price), str(q.sell_price)])
            console.print(format_data_table(title, ["#", "item_id", "name", "cat", "stock", "buy", "sell"], rows, theme="default"))
        except Exception as _omni_sw_370:
            log_swallowed_exception('engine/commands/commerce.py:370', _omni_sw_370)
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
        console.print("[dim]Use: SHOP [role] [tag <x>] [available] [page N] | BUY <item_id> [xN] [bag|pocket] [counter|dead_drop|courier] | SELL <item_id> [ALL] | PRICE <item_id> | EAT [item_id][/dim]")
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
                except Exception as _omni_sw_416:
                    log_swallowed_exception('engine/commands/commerce.py:416', _omni_sw_416)
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
            except Exception as _omni_sw_476:
                log_swallowed_exception('engine/commands/commerce.py:476', _omni_sw_476)
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

