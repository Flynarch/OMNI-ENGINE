from __future__ import annotations

from typing import Any

from engine.news import push_news
from engine.ripple_queue import enqueue_ripple


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
    sh = ensure_safehouses(state)
    here = get_here_key(state)
    sh.setdefault(
        here,
        {
            "status": "none",  # none|rent|own
            "rent_per_day": 25,
            "security_level": 1,
            "stash": [],
            "delinquent_days": 0,
        },
    )
    row = sh.get(here)
    if not isinstance(row, dict):
        row = {"status": "none", "rent_per_day": 25, "security_level": 1, "stash": [], "delinquent_days": 0}
        sh[here] = row
    row.setdefault("status", "none")
    row.setdefault("rent_per_day", 25)
    row.setdefault("security_level", 1)
    row.setdefault("stash", [])
    row.setdefault("delinquent_days", 0)
    return row


def rent_here(state: dict[str, Any], *, rent_per_day: int = 25) -> bool:
    row = ensure_safehouse_here(state)
    if row.get("status") in ("rent", "own"):
        return True
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    if cash < 50:
        return False
    econ["cash"] = cash - 50  # deposit
    row["status"] = "rent"
    row["rent_per_day"] = int(rent_per_day)
    row["delinquent_days"] = 0
    push_news(state, text=f"Kamu sewa safehouse di {get_here_key(state)} (deposit 50, rent {rent_per_day}/d).", source="contacts")
    return True


def buy_here(state: dict[str, Any], *, price: int = 600) -> bool:
    row = ensure_safehouse_here(state)
    if row.get("status") == "own":
        return True
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    if cash < price:
        return False
    econ["cash"] = cash - price
    row["status"] = "own"
    row["rent_per_day"] = 0
    row["delinquent_days"] = 0
    push_news(state, text=f"Kamu beli safehouse di {get_here_key(state)} (price {price}).", source="contacts")
    return True


def upgrade_security(state: dict[str, Any]) -> bool:
    row = ensure_safehouse_here(state)
    if row.get("status") == "none":
        return False
    lvl = int(row.get("security_level", 1) or 1)
    cost = 120 * lvl
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    if cash < cost:
        return False
    econ["cash"] = cash - cost
    row["security_level"] = min(5, lvl + 1)
    push_news(state, text=f"Safehouse security naik ke L{row['security_level']} (cost {cost}).", source="contacts")
    return True


def apply_lay_low_bonus(state: dict[str, Any]) -> None:
    """Called on rest/sleep: bonus trace decay if at a safehouse."""
    row = ensure_safehouse_here(state)
    if row.get("status") == "none":
        return
    tr = state.setdefault("trace", {})
    tp = int(tr.get("trace_pct", 0) or 0)
    lvl = int(row.get("security_level", 1) or 1)
    dec = 2 + lvl  # 3..7
    tr["trace_pct"] = max(0, tp - dec)
    state.setdefault("world_notes", []).append(f"[Safehouse] Lay low bonus: trace -{dec}")


def process_daily_rent(state: dict[str, Any]) -> None:
    """Daily rent handling. If delinquent, landlord may report."""
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
        due = int(row.get("rent_per_day", 25) or 25)
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
            if dd >= 2:
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
                        "impact": {"trace_delta": +3},
                    },
                )

