from __future__ import annotations

from typing import Any

from engine.social.news import push_news
from engine.social.ripple_queue import enqueue_ripple
from engine.core.balance import BALANCE, get_balance_snapshot


def ensure_safehouses(state: dict[str, Any]) -> dict[str, Any]:
    world = state.setdefault("world", {})
    sh = world.setdefault("safehouses", {})
    if not isinstance(sh, dict):
        sh = {}
        world["safehouses"] = sh
    return sh


def get_here_key(state: dict[str, Any]) -> str:
    return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()


def ensure_safehouse_here(state: dict[str, Any]) -> dict[str, Any]:
    snap = get_balance_snapshot(state)
    sh = ensure_safehouses(state)
    here = get_here_key(state)
    sh.setdefault(
        here,
        {
            "status": "none",  # none|rent|own
            "rent_per_day": int(snap.get("safehouse_rent_default_per_day", BALANCE.safehouse_rent_default_per_day) or BALANCE.safehouse_rent_default_per_day),
            "security_level": 1,
            "stash": [],
            "stash_ammo": {},
            "delinquent_days": 0,
        },
    )
    row = sh.get(here)
    if not isinstance(row, dict):
        row = {
            "status": "none",
            "rent_per_day": int(snap.get("safehouse_rent_default_per_day", BALANCE.safehouse_rent_default_per_day) or BALANCE.safehouse_rent_default_per_day),
            "security_level": 1,
            "stash": [],
            "stash_ammo": {},
            "delinquent_days": 0,
        }
        sh[here] = row
    row.setdefault("status", "none")
    row.setdefault("rent_per_day", int(snap.get("safehouse_rent_default_per_day", BALANCE.safehouse_rent_default_per_day) or BALANCE.safehouse_rent_default_per_day))
    row.setdefault("security_level", 1)
    row.setdefault("stash", [])
    row.setdefault("stash_ammo", {})
    row.setdefault("delinquent_days", 0)
    return row


def rent_here(state: dict[str, Any], *, rent_per_day: int = BALANCE.safehouse_rent_default_per_day) -> bool:
    snap = get_balance_snapshot(state)
    row = ensure_safehouse_here(state)
    if row.get("status") in ("rent", "own"):
        return True
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    dep = int(snap.get("safehouse_rent_deposit", BALANCE.safehouse_rent_deposit) or BALANCE.safehouse_rent_deposit)
    if cash < dep:
        return False
    econ["cash"] = cash - dep  # deposit
    row["status"] = "rent"
    if rent_per_day == BALANCE.safehouse_rent_default_per_day:
        rent_per_day = int(snap.get("safehouse_rent_default_per_day", rent_per_day) or rent_per_day)
    row["rent_per_day"] = int(rent_per_day)
    row["delinquent_days"] = 0
    push_news(
        state,
        text=f"Kamu sewa safehouse di {get_here_key(state)} (deposit {dep}, rent {rent_per_day}/d).",
        source="contacts",
    )
    return True


def buy_here(state: dict[str, Any], *, price: int = BALANCE.safehouse_buy_price) -> bool:
    snap = get_balance_snapshot(state)
    row = ensure_safehouse_here(state)
    if row.get("status") == "own":
        return True
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    if price == BALANCE.safehouse_buy_price:
        price = int(snap.get("safehouse_buy_price", price) or price)
    if cash < price:
        return False
    econ["cash"] = cash - price
    row["status"] = "own"
    row["rent_per_day"] = 0
    row["delinquent_days"] = 0
    push_news(state, text=f"Kamu beli safehouse di {get_here_key(state)} (price {price}).", source="contacts")
    return True


def upgrade_security(state: dict[str, Any]) -> bool:
    snap = get_balance_snapshot(state)
    row = ensure_safehouse_here(state)
    if row.get("status") == "none":
        return False
    lvl = int(row.get("security_level", 1) or 1)
    base_cost = int(snap.get("safehouse_upgrade_base_cost", BALANCE.safehouse_upgrade_base_cost) or BALANCE.safehouse_upgrade_base_cost)
    cost = base_cost * lvl
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    if cash < cost:
        return False
    econ["cash"] = cash - cost
    mx = int(snap.get("safehouse_security_max", BALANCE.safehouse_security_max) or BALANCE.safehouse_security_max)
    row["security_level"] = min(mx, lvl + 1)
    push_news(state, text=f"Safehouse security naik ke L{row['security_level']} (cost {cost}).", source="contacts")
    return True


def apply_lay_low_bonus(state: dict[str, Any]) -> None:
    """Called on rest/sleep: bonus trace decay if at a safehouse."""
    snap = get_balance_snapshot(state)
    row = ensure_safehouse_here(state)
    if row.get("status") == "none":
        return
    tr = state.setdefault("trace", {})
    tp = int(tr.get("trace_pct", 0) or 0)
    lvl = int(row.get("security_level", 1) or 1)
    base = int(snap.get("safehouse_lay_low_base_decay", BALANCE.safehouse_lay_low_base_decay) or BALANCE.safehouse_lay_low_base_decay)
    dec = base + lvl
    tr["trace_pct"] = max(0, tp - dec)
    state.setdefault("world_notes", []).append(f"[Safehouse] Lay low bonus: trace -{dec}")


def process_daily_rent(state: dict[str, Any]) -> None:
    """Daily rent handling. If delinquent, landlord may report."""
    snap = get_balance_snapshot(state)
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    sh = ensure_safehouses(state)
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    bank = int(econ.get("bank", 0) or 0)
    total_due = 0
    any_due = False

    for loc, row in list(sh.items())[:120]:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "none")) != "rent":
            continue
        due = int(row.get("rent_per_day", int(snap.get("safehouse_rent_default_per_day", BALANCE.safehouse_rent_default_per_day) or BALANCE.safehouse_rent_default_per_day)) or 0)
        total_due += max(0, due)
        any_due = True

    if not any_due or total_due <= 0:
        return

    # Try pay from cash then bank.
    if cash >= total_due:
        econ["cash"] = cash - total_due
        paid = True
    else:
        need = total_due - cash
        econ["cash"] = 0
        if bank >= need:
            econ["bank"] = bank - need
            paid = True
        else:
            # Can't pay fully
            econ["bank"] = 0
            econ["debt"] = int(econ.get("debt", 0) or 0) + (need - bank)
            paid = False

    if paid:
        for _loc, row in sh.items():
            if isinstance(row, dict) and str(row.get("status", "none")) == "rent":
                row["delinquent_days"] = 0
        push_news(state, text=f"Rent safehouse dibayar: {total_due}/d.", source="contacts")
        return

    # Delinquent: increment and maybe report.
    for loc, row in sh.items():
        if isinstance(row, dict) and str(row.get("status", "none")) == "rent":
            dd = int(row.get("delinquent_days", 0) or 0) + 1
            row["delinquent_days"] = dd
            rep_day = int(snap.get("safehouse_delinquent_report_day", BALANCE.safehouse_delinquent_report_day) or BALANCE.safehouse_delinquent_report_day)
            if dd >= rep_day:
                # Landlord report event as ripple + news.
                push_news(state, text=f"Pemilik safehouse di {loc} mulai curiga (tunggakan).", source="contacts")
                enqueue_ripple(
                    state,
                    {
                        "kind": "landlord_report",
                        "text": f"Landlord melapor soal tunggakan safehouse ({loc}).",
                        "triggered_day": day,
                        "surface_day": day,
                        "surface_time": min(1439, int(meta.get("time_min", 0) or 0) + 15),
                        "surfaced": False,
                        "propagation": "contacts",
                        "origin_location": str(loc),
                        "origin_faction": "police",
                        "witnesses": [],
                        "surface_attempts": 0,
                        "meta": {"location": loc, "delinquent_days": dd},
                        "impact": {"trace_delta": +int(snap.get("safehouse_landlord_report_trace_delta", BALANCE.safehouse_landlord_report_trace_delta) or BALANCE.safehouse_landlord_report_trace_delta)},
                    },
                )

