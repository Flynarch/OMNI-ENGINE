from __future__ import annotations

import hashlib


def test_master_e2e_pipeline() -> None:
    """Master E2E: use top-level handlers to validate cross-system stability."""
    from engine.core.state import initialize_state
    from engine.systems.black_market import generate_black_market_inventory
    from engine.systems.jobs import generate_gigs
    from main import handle_special

    st = initialize_state({"name": "MasterE2E", "location": "london", "year": "2025", "occupation": "hacker"}, seed_pack="minimal")
    st.setdefault("meta", {}).update({"day": 3, "time_min": 8 * 60, "turn": 0})
    st.setdefault("economy", {})["cash"] = 100_000
    st.setdefault("trace", {})["trace_pct"] = 0
    st.setdefault("inventory", {}).setdefault("bag_contents", []).append("laptop_basic")
    abs_min = lambda s: int((s.get("meta", {}) or {}).get("day", 1) or 1) * 1440 + int((s.get("meta", {}) or {}).get("time_min", 0) or 0)

    assert handle_special(st, "GIGS") is True
    gigs = generate_gigs(st)
    assert isinstance(gigs, list) and gigs
    gid = str((gigs[0] or {}).get("id", "") or "")
    assert gid
    t0 = abs_min(st)
    assert handle_special(st, f"WORK {gid}") is True
    t1 = abs_min(st)
    assert t1 > t0

    assert handle_special(st, f"WORK {gid}") is True
    t2 = abs_min(st)
    assert t2 >= t1
    assert int((st.get("meta", {}) or {}).get("daily_gigs_done", 0) or 0) == 2
    assert handle_special(st, f"WORK {gid}") is True
    t3 = abs_min(st)
    assert t3 == t2
    assert any("physically and mentally exhausted" in str(x) for x in (st.get("world_notes") or []))

    h0 = int((st.get("meta", {}) or {}).get("daily_hacks_attempted", 0) or 0)
    assert handle_special(st, "HACK atm") is True
    h1 = int((st.get("meta", {}) or {}).get("daily_hacks_attempted", 0) or 0)
    assert h1 == h0 + 1

    meta = st.setdefault("meta", {})
    meta["time_min"] = 23 * 60 + 55
    d0 = int((st.get("meta", {}) or {}).get("day", 0) or 0)
    assert handle_special(st, "STAY hotel 1") is True
    d1 = int((st.get("meta", {}) or {}).get("day", 0) or 0)
    assert d1 == d0 + 1
    assert int((st.get("meta", {}) or {}).get("daily_gigs_done", -1) or 0) == 0
    assert int((st.get("meta", {}) or {}).get("daily_hacks_attempted", -1) or 0) == 0

    (st.get("meta", {}) or {})["time_min"] = 20 * 60
    assert handle_special(st, "BLACKMARKET") is True
    inv = generate_black_market_inventory(st)
    items = inv.get("items", []) or []
    assert isinstance(items, list) and items
    seed = str((st.get("meta", {}) or {}).get("world_seed", "") or (st.get("meta", {}) or {}).get("seed_pack", "") or "seed")
    day = int((st.get("meta", {}) or {}).get("day", 1) or 1)
    chosen = None
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id", "") or "")
        if not iid:
            continue
        h = hashlib.md5(f"{seed}|{day}|{iid}|sting".encode("utf-8", errors="ignore")).hexdigest()
        if int(h[:8], 16) % 100 >= 5:
            chosen = iid
            break
    if not chosen:
        chosen = str((items[0] or {}).get("id", "") or "")
    assert chosen
    assert handle_special(st, f"BUY_DARK {chosen}") is True
    bag = (st.get("inventory", {}) or {}).get("bag_contents", []) or []
    assert chosen in [str(x) for x in bag]

