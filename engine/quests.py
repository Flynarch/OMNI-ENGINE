from __future__ import annotations

import hashlib
from typing import Any


def _event_exists(state: dict[str, Any], event_type: str, *, day: int) -> bool:
    for ev in state.get("pending_events", []) or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("event_type") == event_type and int(ev.get("due_day", 99999)) >= day and not ev.get("triggered"):
            return True
    return False


def _add_event(
    state: dict[str, Any],
    *,
    event_type: str,
    title: str,
    due_day: int,
    due_time: int,
    payload: dict[str, Any] | None = None,
) -> None:
    state.setdefault("pending_events", []).append(
        {
            "event_type": event_type,
            "title": title,
            "due_day": due_day,
            "due_time": due_time,
            "triggered": False,
            "payload": payload or {},
        }
    )


def _ensure_loc_slot(state: dict[str, Any], loc: str) -> dict[str, Any]:
    world = state.setdefault("world", {})
    store = world.setdefault("locations", {})
    if not isinstance(store, dict):
        store = {}
        world["locations"] = store
    key = str(loc or "").strip().lower()
    if not key:
        key = str(state.get("player", {}).get("location", "") or "").strip().lower()
    store.setdefault(key, {})
    slot = store.get(key)
    if not isinstance(slot, dict):
        slot = {}
        store[key] = slot
    slot.setdefault("restrictions", {})
    slot.setdefault("market", {})  # local market snapshot (optional)
    return slot


def _ensure_local_market_from_global(state: dict[str, Any], loc: str) -> dict[str, dict[str, int]]:
    slot = _ensure_loc_slot(state, loc)
    m = slot.get("market") or {}
    if not isinstance(m, dict):
        m = {}
        slot["market"] = m
    if m:
        return m  # type: ignore[return-value]
    base = (state.get("economy", {}) or {}).get("market", {}) or {}
    if isinstance(base, dict):
        for k in ("electronics", "medical", "weapons", "food", "transport"):
            row = base.get(k) if isinstance(base.get(k), dict) else {"price_idx": 100, "scarcity": 0}
            m[k] = {"price_idx": int((row or {}).get("price_idx", 100) or 100), "scarcity": int((row or {}).get("scarcity", 0) or 0)}
    else:
        for k in ("electronics", "medical", "weapons", "food", "transport"):
            m[k] = {"price_idx": 100, "scarcity": 0}
    slot["market"] = m
    return m  # type: ignore[return-value]


def _ensure_quests(state: dict[str, Any]) -> dict[str, Any]:
    q = state.setdefault("quests", {"active": [], "completed": [], "failed": [], "last_id": 0})
    if not isinstance(q, dict):
        q = {"active": [], "completed": [], "failed": [], "last_id": 0}
        state["quests"] = q
    q.setdefault("active", [])
    q.setdefault("completed", [])
    q.setdefault("failed", [])
    q.setdefault("last_id", 0)
    return q


def _new_quest_id(state: dict[str, Any]) -> str:
    q = _ensure_quests(state)
    try:
        n = int(q.get("last_id", 0) or 0) + 1
    except Exception:
        n = 1
    q["last_id"] = n
    return f"Q{n:04d}"


def _has_active_quest(state: dict[str, Any], kind: str, *, origin_location: str | None = None) -> bool:
    q = state.get("quests", {}) or {}
    active = q.get("active") if isinstance(q, dict) else []
    if not isinstance(active, list):
        return False
    k = str(kind or "").strip().lower()
    ol = str(origin_location or "").strip().lower()
    for it in active[-40:]:
        if not isinstance(it, dict):
            continue
        if str(it.get("kind", "") or "").strip().lower() != k:
            continue
        if it.get("status") not in ("active", "overdue"):
            continue
        if ol:
            if str(it.get("origin_location", "") or "").strip().lower() != ol:
                continue
        return True
    return False


def _inv_has(inv: dict[str, Any], item_id: str) -> bool:
    iid = str(item_id)
    for key in ("r_hand", "l_hand", "worn"):
        if str(inv.get(key, "") or "") == iid:
            return True
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key) or []
        if isinstance(arr, list):
            if iid in [str(x) for x in arr]:
                return True
    return False


def _inv_remove(inv: dict[str, Any], item_id: str) -> None:
    iid = str(item_id)
    for key in ("r_hand", "l_hand", "worn"):
        if str(inv.get(key, "") or "") == iid:
            inv[key] = "-"
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key) or []
        if isinstance(arr, list):
            inv[key] = [x for x in arr if str(x) != iid]


def create_black_market_delivery_quest(state: dict[str, Any], *, origin_location: str, bm_power: int, bm_stability: int) -> dict[str, Any]:
    """Create a multi-step quest chain instance (v1)."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    seed = str(meta.get("seed_pack", "") or "")
    qid = _new_quest_id(state)

    origin = str(origin_location or "").strip().lower() or str(state.get("player", {}).get("location", "") or "").strip().lower()
    # Pick a deterministic drop location (different if possible).
    locs = (state.get("world", {}) or {}).get("locations", {}) or {}
    keys = [str(k).strip().lower() for k in (locs.keys() if isinstance(locs, dict) else [])]
    keys = [k for k in keys if k and k != origin]
    drop = "london" if origin != "london" else "jakarta"
    if keys:
        drop = keys[(_det_roll_1_100(seed, day, qid, "drop") - 1) % len(keys)]

    contact = "Broker_Shade"
    package_id = f"pkg_{qid}"
    # Place package in origin scene (persisted location slot + live nearby if player is there).
    slot = _ensure_loc_slot(state, origin)
    ni = slot.setdefault("nearby_items", [])
    if not isinstance(ni, list):
        ni = []
        slot["nearby_items"] = ni
    ni.append({"id": package_id, "name": f"Package {qid}"})
    slot["nearby_items"] = ni[-30:]
    if str(state.get("player", {}).get("location", "") or "").strip().lower() == origin:
        world = state.setdefault("world", {})
        wni = world.setdefault("nearby_items", [])
        if not isinstance(wni, list):
            wni = []
            world["nearby_items"] = wni
        wni.append({"id": package_id, "name": f"Package {qid}"})
        world["nearby_items"] = wni[-30:]

    # Ensure inventory knows package size (small).
    inv = state.setdefault("inventory", {})
    inv.setdefault("item_sizes", {})
    if isinstance(inv.get("item_sizes"), dict):
        inv["item_sizes"].setdefault(package_id, 2)

    quest = {
        "id": qid,
        "kind": "bm_delivery",
        "status": "active",
        "origin_location": origin,
        "step": 0,
        "deadline_day": day + 2,
        "data": {"contact": contact, "package_id": package_id, "pickup_loc": origin, "drop_loc": drop, "bm_power": bm_power, "bm_stability": bm_stability},
        "reward": {"cash": 250, "trace_delta": -5, "bm_respect": +2},
        "failure": {"trace_delta": +6},
        "steps": [
            {"name": "meet_contact", "desc": f"Temui {contact} (pasar gelap) dan konfirmasi kerja."},
            {"name": "pickup", "desc": f"Ambil paket {qid} di {origin}."},
            {"name": "deliver", "desc": f"Antar paket ke drop di {drop} sebelum hari {day+2}."},
        ],
        "created_day": day,
    }
    q = _ensure_quests(state)
    (q.get("active") if isinstance(q.get("active"), list) else []).append(quest)
    return quest


def create_trace_cleanup_quest(state: dict[str, Any], *, origin_location: str, trace_snapshot: int) -> dict[str, Any]:
    """Quest chain: reduce trace pressure (cover tracks + lay low)."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    origin = str(origin_location or "").strip().lower() or str(state.get("player", {}).get("location", "") or "").strip().lower()
    if _has_active_quest(state, "trace_cleanup", origin_location=origin):
        return {}
    qid = _new_quest_id(state)
    quest = {
        "id": qid,
        "kind": "trace_cleanup",
        "status": "active",
        "origin_location": origin,
        "step": 0,
        "deadline_day": day + 2,
        "data": {"trace_snapshot": int(trace_snapshot), "cooldown_done": False},
        "reward": {"trace_delta": -8},
        "failure": {"trace_delta": +5},
        "steps": [
            {"name": "cover_tracks", "desc": "Hapus jejak / cover tracks (burner, ganti SIM, bersihkan metadata)."},
            {"name": "lay_low", "desc": "Low profile 1 hari (rest/sleep) atau hindari aksi berisiko."},
        ],
        "created_day": day,
    }
    q = _ensure_quests(state)
    q["active"].append(quest)
    state.setdefault("world_notes", []).append(f"[Quest] New: {qid} trace_cleanup (deadline D{day+2}).")
    return quest


def create_corp_infiltration_quest(state: dict[str, Any], *, origin_location: str) -> dict[str, Any]:
    """Quest chain: respond to corporate lockdown via infiltration + hack."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    origin = str(origin_location or "").strip().lower() or str(state.get("player", {}).get("location", "") or "").strip().lower()
    if _has_active_quest(state, "corp_infiltration", origin_location=origin):
        return {}
    qid = _new_quest_id(state)
    quest = {
        "id": qid,
        "kind": "corp_infiltration",
        "status": "active",
        "origin_location": origin,
        "step": 0,
        "deadline_day": day + 3,
        "data": {"has_badge": False, "site": "corporate_district"},
        "reward": {"cash": 180, "trace_delta": -2},
        "failure": {"trace_delta": +4},
        "steps": [
            {"name": "get_badge", "desc": "Dapatkan akses/badge (sosial/stealth) untuk corporate district."},
            {"name": "infiltrate", "desc": "Masuk ke corporate_district (stealth/evasion)."},
            {"name": "hack", "desc": "Hack sistem corporate (butuh fokus, risiko)."},
            {"name": "exfil", "desc": "Keluar dengan aman (travel/stealth)."},
        ],
        "created_day": day,
    }
    q = _ensure_quests(state)
    q["active"].append(quest)
    state.setdefault("world_notes", []).append(f"[Quest] New: {qid} corp_infiltration (deadline D{day+3}).")
    return quest


def create_debt_repayment_quest(state: dict[str, Any]) -> dict[str, Any]:
    """Quest chain: repay part of debt to reduce pressure."""
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    origin = str(state.get("player", {}).get("location", "") or "").strip().lower()
    if _has_active_quest(state, "debt_repayment", origin_location=origin):
        return {}
    econ = state.get("economy", {}) or {}
    try:
        debt = int(econ.get("debt", 0) or 0)
    except Exception:
        debt = 0
    qid = _new_quest_id(state)
    target = min(200, max(50, int(debt * 0.25))) if debt > 0 else 100
    quest = {
        "id": qid,
        "kind": "debt_repayment",
        "status": "active",
        "origin_location": origin,
        "step": 0,
        "deadline_day": day + 4,
        "data": {"target_payment": target, "paid": 0},
        "reward": {"fico_delta": +10, "trace_delta": -1},
        "failure": {"daily_burn_delta": +2, "trace_delta": +2},
        "steps": [
            {"name": "raise_cash", "desc": f"Kumpulkan uang untuk cicilan (target {target})."},
            {"name": "pay", "desc": "Bayar utang (ketik: bayar utang / pay debt)."},
        ],
        "created_day": day,
    }
    q = _ensure_quests(state)
    q["active"].append(quest)
    state.setdefault("world_notes", []).append(f"[Quest] New: {qid} debt_repayment (target {target}).")
    return quest


def tick_quest_chains(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """Advance quest chains based on player actions + time. Deterministic and bounded."""
    q = _ensure_quests(state)
    active = q.get("active") if isinstance(q.get("active"), list) else []
    if not isinstance(active, list) or not active:
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    inv = state.get("inventory", {}) or {}
    world_notes = state.setdefault("world_notes", [])

    new_active: list[dict[str, Any]] = []
    for quest in active[:30]:
        if not isinstance(quest, dict) or quest.get("status") not in ("active", "overdue"):
            continue
        qid = str(quest.get("id", "") or "")
        deadline = int(quest.get("deadline_day", 99999) or 99999)
        # Branching failure: allow a short overdue grace window for delivery quests.
        if day > deadline and quest.get("kind") == "bm_delivery":
            # Allow 1-day grace as OVERDUE (reward reduced, extra heat).
            if day <= deadline + 1:
                quest["status"] = "overdue"
                quest.setdefault("data", {})
                if isinstance(quest.get("data"), dict):
                    quest["data"].setdefault("overdue_marked_day", day)
                world_notes.append(f"[Quest] {qid} is OVERDUE (reward reduced).")
            else:
                quest["status"] = "failed"
                # Apply failure consequence (trace up).
                try:
                    tr = state.setdefault("trace", {})
                    tp = int(tr.get("trace_pct", 0) or 0)
                    tp = max(0, min(100, tp + int((quest.get("failure") or {}).get("trace_delta", 0) or 0)))
                    tr["trace_pct"] = tp
                except Exception:
                    pass
                q.setdefault("failed", []).append(quest)
                world_notes.append(f"[Quest] {qid} FAILED (deadline passed).")
                continue

        # Generic deadline failure for non-bm_delivery quests.
        kind = str(quest.get("kind", "") or "")
        if kind != "bm_delivery" and day > deadline:
            quest["status"] = "failed"
            # Apply failure consequences (if any).
            fail = quest.get("failure") if isinstance(quest.get("failure"), dict) else {}
            try:
                tr = state.setdefault("trace", {})
                tp = int(tr.get("trace_pct", 0) or 0)
                tp = max(0, min(100, tp + int((fail or {}).get("trace_delta", 0) or 0)))
                tr["trace_pct"] = tp
            except Exception:
                pass
            try:
                econ = state.setdefault("economy", {})
                if "daily_burn_delta" in (fail or {}):
                    econ["daily_burn"] = int(econ.get("daily_burn", 0) or 0) + int((fail or {}).get("daily_burn_delta", 0) or 0)
            except Exception:
                pass
            q.setdefault("failed", []).append(quest)
            world_notes.append(f"[Quest] {qid} FAILED (deadline passed).")
            continue

        # Branch: trace cleanup quest.
        if kind == "trace_cleanup":
            step = int(quest.get("step", 0) or 0)
            norm = str(action_ctx.get("normalized_input", "") or "").lower()
            act_type = str(action_ctx.get("action_type", "") or "")
            if step == 0:
                if any(x in norm for x in ("cover tracks", "hapus jejak", "bersihkan jejak", "burner", "ganti sim")):
                    quest["step"] = 1
                    world_notes.append(f"[Quest] {qid}: step 1/2 complete (cover tracks).")
                new_active.append(quest)
                continue
            if step == 1:
                if act_type in ("rest", "sleep"):
                    # Reward: reduce trace.
                    rew = quest.get("reward") if isinstance(quest.get("reward"), dict) else {}
                    try:
                        tr = state.setdefault("trace", {})
                        tp = int(tr.get("trace_pct", 0) or 0)
                        tp = max(0, min(100, tp + int((rew or {}).get("trace_delta", 0) or 0)))
                        tr["trace_pct"] = tp
                    except Exception:
                        pass
                    quest["status"] = "completed"
                    q.setdefault("completed", []).append(quest)
                    world_notes.append(f"[Quest] {qid} COMPLETED (trace reduced).")
                    continue
                new_active.append(quest)
                continue

        # Branch: corporate infiltration quest.
        if kind == "corp_infiltration":
            step = int(quest.get("step", 0) or 0)
            data = quest.get("data") if isinstance(quest.get("data"), dict) else {}
            norm = str(action_ctx.get("normalized_input", "") or "").lower()
            act_type = str(action_ctx.get("action_type", "") or "")
            site = str((data or {}).get("site", "corporate_district")).lower()
            if step == 0:
                if any(x in norm for x in ("badge", "keycard", "akses", "id card", "curi")):
                    if isinstance(quest.get("data"), dict):
                        quest["data"]["has_badge"] = True
                    quest["step"] = 1
                    world_notes.append(f"[Quest] {qid}: step 1/4 complete (badge acquired).")
                new_active.append(quest)
                continue
            if step == 1:
                # Player explicitly mentions entering the district, or stealth in that area.
                if site in norm or (action_ctx.get("domain") in ("stealth", "evasion") and site in norm):
                    quest["step"] = 2
                    world_notes.append(f"[Quest] {qid}: step 2/4 complete (infiltrated).")
                new_active.append(quest)
                continue
            if step == 2:
                if action_ctx.get("domain") == "hacking" and any(x in norm for x in ("corp", "corporate", "perusahaan", "server", "system", "sistem")):
                    quest["step"] = 3
                    world_notes.append(f"[Quest] {qid}: step 3/4 complete (hack done).")
                new_active.append(quest)
                continue
            if step == 3:
                if act_type == "travel" or any(x in norm for x in ("kabur", "keluar", "exfil", "leave")):
                    # Reward: cash + small trace down.
                    rew = quest.get("reward") if isinstance(quest.get("reward"), dict) else {}
                    try:
                        econ = state.setdefault("economy", {})
                        econ["cash"] = int(econ.get("cash", 0) or 0) + int((rew or {}).get("cash", 0) or 0)
                    except Exception:
                        pass
                    try:
                        tr = state.setdefault("trace", {})
                        tp = int(tr.get("trace_pct", 0) or 0)
                        tp = max(0, min(100, tp + int((rew or {}).get("trace_delta", 0) or 0)))
                        tr["trace_pct"] = tp
                    except Exception:
                        pass
                    quest["status"] = "completed"
                    q.setdefault("completed", []).append(quest)
                    world_notes.append(f"[Quest] {qid} COMPLETED (corp job).")
                    continue
                new_active.append(quest)
                continue

        # Branch: debt repayment quest.
        if kind == "debt_repayment":
            step = int(quest.get("step", 0) or 0)
            data = quest.get("data") if isinstance(quest.get("data"), dict) else {}
            norm = str(action_ctx.get("normalized_input", "") or "").lower()
            econ = state.get("economy", {}) or {}
            try:
                cash = int(econ.get("cash", 0) or 0)
            except Exception:
                cash = 0
            try:
                debt = int(econ.get("debt", 0) or 0)
            except Exception:
                debt = 0
            target = int((data or {}).get("target_payment", 100) or 100)
            paid = int((data or {}).get("paid", 0) or 0)
            if step == 0:
                if cash >= min(target, max(50, target // 2)):
                    quest["step"] = 1
                    world_notes.append(f"[Quest] {qid}: step 1/2 ready (enough cash to pay).")
                new_active.append(quest)
                continue
            if step == 1:
                if "bayar utang" in norm or "pay debt" in norm or "cicil" in norm:
                    pay = min(debt, cash, max(50, target - paid))
                    if pay > 0:
                        econ2 = state.setdefault("economy", {})
                        econ2["cash"] = int(econ2.get("cash", 0) or 0) - pay
                        econ2["debt"] = max(0, int(econ2.get("debt", 0) or 0) - pay)
                        if isinstance(quest.get("data"), dict):
                            quest["data"]["paid"] = paid + pay
                        world_notes.append(f"[Quest] {qid}: paid {pay} toward debt.")
                    # Complete if target reached or debt cleared.
                    paid2 = int(((quest.get("data") or {}).get("paid", 0) if isinstance(quest.get("data"), dict) else 0) or 0)
                    if paid2 >= target or int((state.get("economy", {}) or {}).get("debt", 0) or 0) <= 0:
                        rew = quest.get("reward") if isinstance(quest.get("reward"), dict) else {}
                        try:
                            econ3 = state.setdefault("economy", {})
                            econ3["fico"] = int(econ3.get("fico", 600) or 600) + int((rew or {}).get("fico_delta", 0) or 0)
                        except Exception:
                            pass
                        try:
                            tr = state.setdefault("trace", {})
                            tp = int(tr.get("trace_pct", 0) or 0)
                            tp = max(0, min(100, tp + int((rew or {}).get("trace_delta", 0) or 0)))
                            tr["trace_pct"] = tp
                        except Exception:
                            pass
                        quest["status"] = "completed"
                        q.setdefault("completed", []).append(quest)
                        world_notes.append(f"[Quest] {qid} COMPLETED (debt pressure eased).")
                        continue
                new_active.append(quest)
                continue

        if kind != "bm_delivery":
            new_active.append(quest)
            continue

        data = quest.get("data") if isinstance(quest.get("data"), dict) else {}
        contact = str((data or {}).get("contact", "Broker_Shade"))
        pkg = str((data or {}).get("package_id", ""))
        pickup_loc = str((data or {}).get("pickup_loc", "") or "").strip().lower()
        drop_loc = str((data or {}).get("drop_loc", "") or "").strip().lower()
        step = int(quest.get("step", 0) or 0)
        norm = str(action_ctx.get("normalized_input", "") or "").lower()
        act_type = str(action_ctx.get("action_type", "") or "")

        # If traveling with the package during a police sweep, mark as "spotted" -> requires cleanup before delivery.
        try:
            if act_type == "travel" and pkg and _inv_has(inv, pkg):
                world = state.get("world", {}) or {}
                slot = ((world.get("locations", {}) or {}).get(loc) if isinstance((world.get("locations", {}) or {}), dict) else None)
                restr = (slot.get("restrictions", {}) if isinstance(slot, dict) else {}) or {}
                until_ps = int(restr.get("police_sweep_until_day", 0) or 0) if isinstance(restr, dict) else 0
                if until_ps >= day:
                    if isinstance(quest.get("data"), dict):
                        quest["data"]["spotted"] = True
                        quest["data"]["spotted_day"] = day
        except Exception:
            pass

        if step == 0:
            # Meet/contact confirmation: social action with contact keyword.
            if action_ctx.get("domain") == "social" and ("black market" in norm or "pasar gelap" in norm or contact.lower() in norm):
                quest["step"] = 1
                world_notes.append(f"[Quest] {qid}: step 1/3 complete (met contact).")
            new_active.append(quest)
            continue

        if step == 1:
            # Pickup: player must have the package, OR be at pickup_loc and attempt pickup.
            if pkg and _inv_has(inv, pkg):
                quest["step"] = 2
                world_notes.append(f"[Quest] {qid}: step 2/3 complete (package acquired).")
                new_active.append(quest)
                continue
            if pkg and loc == pickup_loc and ("ambil" in norm or "pickup" in norm or "ambil paket" in norm):
                # Auto-grant to bag if missing (QoL, deterministic quest progression).
                bag = inv.setdefault("bag_contents", [])
                if isinstance(bag, list):
                    bag.append(pkg)
                    inv["bag_contents"] = bag[-40:]
                quest["step"] = 2
                world_notes.append(f"[Quest] {qid}: step 2/3 complete (package acquired).")
            new_active.append(quest)
            continue

        if step == 2:
            # Deliver: at drop_loc + has pkg + player indicates delivery; then remove item and reward.
            if pkg and loc == drop_loc and _inv_has(inv, pkg) and ("antar" in norm or "deliver" in norm or "kirim" in norm or "serahkan" in norm):
                # If spotted, require a "cover tracks" action first.
                if isinstance(quest.get("data"), dict) and bool(quest["data"].get("spotted", False)):
                    world_notes.append(f"[Quest] {qid}: kamu merasa diawasi. Cover tracks dulu sebelum delivery.")
                    new_active.append(quest)
                    continue
                was_overdue = str(quest.get("status", "") or "").lower() == "overdue"
                _inv_remove(inv, pkg)
                rew = quest.get("reward") if isinstance(quest.get("reward"), dict) else {}
                try:
                    econ = state.setdefault("economy", {})
                    cash_add = int(rew.get("cash", 0) or 0)
                    if was_overdue:
                        cash_add = max(0, int(rew.get("cash", 0) or 0) // 2)
                    econ["cash"] = int(econ.get("cash", 0) or 0) + cash_add
                except Exception:
                    pass
                try:
                    tr = state.setdefault("trace", {})
                    tp = int(tr.get("trace_pct", 0) or 0)
                    trace_delta = int(rew.get("trace_delta", 0) or 0)
                    if was_overdue:
                        trace_delta = max(trace_delta, +2)
                    tp = max(0, min(100, tp + trace_delta))
                    tr["trace_pct"] = tp
                except Exception:
                    pass
                # Local market reward: slightly reduce weapons scarcity at drop location.
                try:
                    lm = _ensure_local_market_from_global(state, drop_loc)
                    if isinstance(lm.get("weapons"), dict):
                        lm["weapons"]["scarcity"] = _clamp_int(int(lm["weapons"].get("scarcity", 0) or 0) - 2, 0, 100)
                except Exception:
                    pass
                quest["status"] = "completed"
                q.setdefault("completed", []).append(quest)
                world_notes.append(f"[Quest] {qid} COMPLETED.")
                continue
            # Cover-tracks step (branch): if spotted, allow clearing it via hacking/stealth flavored input.
            if isinstance(quest.get("data"), dict) and bool(quest["data"].get("spotted", False)):
                if ("cover tracks" in norm) or ("hapus jejak" in norm) or ("bersihkan jejak" in norm) or ("burner" in norm) or ("buang hp" in norm):
                    quest["data"]["spotted"] = False
                    world_notes.append(f"[Quest] {qid}: cover tracks OK. Delivery sekarang lebih aman.")
            new_active.append(quest)
            continue

        new_active.append(quest)

    q["active"] = new_active

def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _det_roll_1_100(*parts: Any) -> int:
    s = "|".join([str(p) for p in parts])
    h = hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()
    return (int(h[:8], 16) % 100) + 1


def _push_news(state: dict[str, Any], *, text: str, source: str, day: int) -> None:
    from engine.news import push_news

    push_news(state, text=text, source=source, day=day)


def _add_ripple_dict(state: dict[str, Any], rp: dict[str, Any]) -> None:
    if not isinstance(rp, dict):
        return
    from engine.ripple_queue import enqueue_ripple

    enqueue_ripple(state, rp)


def generate_daily_news(state: dict[str, Any]) -> None:
    """Auto news feed (rate-limited) that reflects world state.

    Goal: player gets a small number of meaningful headlines without spam.
    """
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    world = state.setdefault("world", {})
    last = int(world.get("last_news_day", 0) or 0)
    if last >= day:
        return
    world["last_news_day"] = day

    factions = world.get("factions", {}) or {}
    statuses = world.get("faction_statuses", {}) or {}
    police_att = str(statuses.get("police", "idle") or "idle").lower()
    corp = factions.get("corporate", {}) if isinstance(factions.get("corporate"), dict) else {}
    bm = factions.get("black_market", {}) if isinstance(factions.get("black_market"), dict) else {}

    corp_st = int(corp.get("stability", 50) or 50)
    bm_pw = int(bm.get("power", 50) or 50)

    # Max 2 headlines/day.
    headlines: list[tuple[str, str]] = []
    if police_att in ("investigated", "manhunt"):
        headlines.append(
            (
                "Polisi meningkatkan operasi penyisiran & checkpoint (tekanan naik)."
                if police_att == "manhunt"
                else "Polisi memperluas penyelidikan (patroli & razia meningkat).",
                "broadcast",
            )
        )
    if corp_st <= 30:
        headlines.append(("Korporasi memperketat keamanan sistem & akses (lockdown internal).", "broadcast"))
    if bm_pw >= 75:
        headlines.append(("Pasar gelap bergerak agresif: suplai & jaringan makin kuat.", "faction_network"))

    # Deterministic shuffle/pick based on seed+day to keep stable.
    seed = str(meta.get("seed_pack", "") or "")
    pick = _det_roll_1_100(seed, day, "news_pick")
    # Choose up to 2 unique.
    chosen: list[tuple[str, str]] = []
    if headlines:
        idx = (pick - 1) % len(headlines)
        chosen.append(headlines[idx])
        if len(headlines) > 1:
            chosen.append(headlines[(idx + 1) % len(headlines)])
    for text, src in chosen[:2]:
        _push_news(state, text=text, source=src, day=day)


def generate_faction_strikes(state: dict[str, Any], *, force: bool = False) -> None:
    """Faction-vs-faction aggression: if one is strong and the other is weak, an attack may happen.

    The result is scheduled as a pending_event + an info ripple (broadcast/network).
    """
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)
    world = state.get("world", {}) or {}
    factions = world.get("factions", {}) or {}
    if not isinstance(factions, dict) or not factions:
        return

    # Cooldown: once per day.
    gen_day = int(world.get("last_faction_strike_day", 0) or 0)
    if gen_day >= day:
        return
    world["last_faction_strike_day"] = day

    # Rival map (simple v1).
    pairs = [
        ("corporate", "black_market"),
        ("police", "black_market"),
        ("corporate", "police"),
    ]

    seed = str(meta.get("seed_pack", "") or "")
    roll = _det_roll_1_100(seed, day, str(world.get("conflict_model", "")), "strike")

    for attacker, defender in pairs:
        a = factions.get(attacker, {}) if isinstance(factions.get(attacker), dict) else {}
        d = factions.get(defender, {}) if isinstance(factions.get(defender), dict) else {}
        a_pw = int(a.get("power", 50) or 50)
        a_st = int(a.get("stability", 50) or 50)
        d_pw = int(d.get("power", 50) or 50)
        d_st = int(d.get("stability", 50) or 50)

        # Conditions: attacker strong enough + defender unstable/weak.
        if a_pw < 70 or a_st < 40:
            continue
        if d_st > 35 and d_pw > 45:
            continue

        # Probability gate (deterministic): stronger disparity => more likely.
        disparity = (a_pw - d_st) + (a_pw - d_pw)
        chance = _clamp_int(int(disparity / 3), 10, 80)  # 10..80
        if not force and roll > chance:
            continue

        et = "faction_strike"
        if _event_exists(state, et, day=day):
            return

        # Impact magnitude.
        mag = _clamp_int(int(disparity / 8), 6, 18)
        title = f"{attacker} strike vs {defender}"
        _add_event(
            state,
            event_type=et,
            title=title,
            due_day=day,
            due_time=min(1439, time_min + 120),
            payload={"attacker": attacker, "defender": defender, "magnitude": mag},
        )

        # Info ripple + immediate faction impact when surfaced.
        text = f"[World] {attacker} melancarkan operasi terhadap {defender} (eskalasi konflik)."
        propagation = "broadcast" if mag >= 12 else "faction_network"
        _add_ripple_dict(
            state,
            {
                "text": text,
                "triggered_day": day,
                "surface_day": day,
                "surface_time": min(1439, time_min + 60),
                "surfaced": False,
                "propagation": propagation,
                "origin_location": str(state.get("player", {}).get("location", "") or "").strip().lower(),
                "origin_faction": attacker,
                "witnesses": [],
                "surface_attempts": 0,
                "impact": {
                    "severity": 55 if mag >= 12 else 40,
                    "factions": {
                        attacker: {"power": +int(mag / 2), "stability": -2},
                        defender: {"stability": -mag, "power": -int(mag / 3)},
                    },
                },
            },
        )
        # Headline entry so player can see it even if ripple is network-only.
        _push_news(state, text=text.replace("[World] ", ""), source=propagation, day=day)
        return


def generate_faction_events(state: dict[str, Any]) -> None:
    """Generate low-frequency events from faction pressures.

    v1 goals:
    - Make factions feel active without overwhelming player.
    - Tie events to attention tiers + power/stability.
    """
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    time_min = int(meta.get("time_min", 0) or 0)

    world = state.get("world", {}) or {}
    factions = world.get("factions", {}) or {}
    statuses = world.get("faction_statuses", {}) or {}
    if not isinstance(factions, dict) or not isinstance(statuses, dict):
        return

    # Cooldown: once per (sim) day for global generation.
    gen_day = int(world.get("last_faction_event_day", 0) or 0)
    if gen_day >= day:
        return
    world["last_faction_event_day"] = day

    police_att = str(statuses.get("police", "idle") or "idle").lower()
    origin_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
    corp = factions.get("corporate", {}) if isinstance(factions.get("corporate"), dict) else {}
    police = factions.get("police", {}) if isinstance(factions.get("police"), dict) else {}
    bm = factions.get("black_market", {}) if isinstance(factions.get("black_market"), dict) else {}

    corp_pw = int(corp.get("power", 50) or 50)
    corp_st = int(corp.get("stability", 50) or 50)
    pol_pw = int(police.get("power", 50) or 50)
    bm_pw = int(bm.get("power", 50) or 50)
    bm_st = int(bm.get("stability", 50) or 50)

    # Police pressure events
    if police_att in ("investigated", "manhunt"):
        et = "police_sweep"
        if not _event_exists(state, et, day=day):
            title = "Police sweep in your area" if police_att == "investigated" else "Manhunt checkpoint lockdown"
            due = min(1439, time_min + (90 if police_att == "investigated" else 30))
            _add_event(
                state,
                event_type=et,
                title=title,
                due_day=day,
                due_time=due,
                payload={"attention": police_att, "police_power": pol_pw, "location": origin_loc},
            )

    # Corporate countermeasures if stability is low.
    if corp_st <= 35:
        et = "corporate_lockdown"
        if not _event_exists(state, et, day=day):
            _add_event(
                state,
                event_type=et,
                title="Corporate systems harden & access tightens",
                due_day=day,
                due_time=min(1439, time_min + 180),
                payload={"corp_power": corp_pw, "corp_stability": corp_st, "location": origin_loc},
            )

    # Black market offers when powerful + not too unstable.
    if bm_pw >= 65 and bm_st >= 35:
        et = "black_market_offer"
        if not _event_exists(state, et, day=day):
            _add_event(
                state,
                event_type=et,
                title="Black market contact offers a deal",
                due_day=day,
                due_time=min(1439, time_min + 240),
                payload={"bm_power": bm_pw, "bm_stability": bm_st, "location": origin_loc},
            )

    # New: inter-faction strikes + daily news (both rate-limited).
    try:
        generate_faction_strikes(state)
    except Exception:
        pass
    try:
        generate_daily_news(state)
    except Exception:
        pass

