from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.trace import get_trace_tier
import hashlib
from typing import Any

from engine.core.balance import BALANCE, get_balance_snapshot
from engine.systems.safehouse import ensure_safehouse_here
from engine.world.atlas import ensure_location_profile


def _here_key(state: dict[str, Any]) -> str:
    return str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()


def _ensure_accommodation_map(state: dict[str, Any]) -> dict[str, Any]:
    world = state.setdefault("world", {})
    acc = world.setdefault("accommodation", {})
    if not isinstance(acc, dict):
        acc = {}
        world["accommodation"] = acc
    return acc


def normalize_stay_kind(raw: str) -> str | None:
    """Map player input to internal tier: hotel | kos | suite.

    *kos* tier = shared budget room / boarding house / guesthouse dorm (Indonesian *kost/kos*).
    Aliases help players who do not know the word *kos*."""
    t = str(raw or "").strip().lower()
    if not t:
        return None
    if t in ("kos", "kost", "boarding", "board", "room", "dorm", "hostel", "guesthouse", "bedsit", "pension"):
        return "kos"
    if t in ("hotel", "inn", "motel"):
        return "hotel"
    if t in ("suite", "luxury", "penthouse", "mewah"):
        return "suite"
    return None


def stay_kind_label(kind: str, *, short: bool = False) -> str:
    """English-forward label; *kos* tier explains Indonesian slang."""
    k = str(kind or "").strip().lower()
    if k == "kos":
        if short:
            return "boarding room"
        return "Boarding room (budget / shared — Indonesian: kost)"
    if k == "hotel":
        return "Hotel (standard)"
    if k == "suite":
        return "Suite (luxury)"
    return k or "—"


def stay_help_aliases() -> str:
    return "boarding|kos|kost|dorm|hostel|guesthouse → same budget tier; hotel|suite"


def _food_price_idx(state: dict[str, Any]) -> int:
    m = (state.get("economy", {}) or {}).get("market", {}) or {}
    row = m.get("food", {}) if isinstance(m, dict) else {}
    if not isinstance(row, dict):
        return 100
    return max(50, min(300, int(row.get("price_idx", 100) or 100)))


def nightly_rate(state: dict[str, Any], kind: str) -> int:
    snap = get_balance_snapshot(state)
    k = normalize_stay_kind(kind) or str(kind or "").strip().lower()
    food = _food_price_idx(state)
    if k == "kos":
        base = int(snap.get("kos_night_base", BALANCE.kos_night_base) or BALANCE.kos_night_base)
    elif k == "suite":
        base = int(snap.get("suite_night_base", BALANCE.suite_night_base) or BALANCE.suite_night_base)
    elif k == "hotel":
        base = int(snap.get("hotel_night_base", BALANCE.hotel_night_base) or BALANCE.hotel_night_base)
    else:
        return 0
    return max(1, int(base * food / 100))


def get_stay_here(state: dict[str, Any]) -> dict[str, Any] | None:
    loc = _here_key(state)
    if not loc:
        return None
    acc = _ensure_accommodation_map(state)
    row = acc.get(loc)
    return row if isinstance(row, dict) else None


def stay_checkin(state: dict[str, Any], kind: str, nights: int) -> dict[str, Any]:
    """Prepay nights at current location (hotel / boarding tier / suite). Deterministic pricing from balance + food market."""
    k = normalize_stay_kind(kind)
    if not k:
        return {"ok": False, "reason": "invalid_kind"}
    n = int(nights)
    if n < 1 or n > 365:
        return {"ok": False, "reason": "invalid_nights"}
    loc = _here_key(state)
    if not loc:
        return {"ok": False, "reason": "no_location"}
    rate = nightly_rate(state, k)
    total = rate * n
    econ = state.setdefault("economy", {})
    cash = int(econ.get("cash", 0) or 0)
    if cash < total:
        return {"ok": False, "reason": "not_enough_cash", "need": total, "cash": cash}
    econ["cash"] = cash - total
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    acc = _ensure_accommodation_map(state)
    row = acc.setdefault(loc, {})
    prev_k = str(row.get("kind", "none") or "none")
    if prev_k == k:
        row["nights_remaining"] = int(row.get("nights_remaining", 0) or 0) + n
    else:
        row["nights_remaining"] = n
        row["checkin_day"] = day
    row["kind"] = k
    row["rate_per_night"] = rate
    if "checkin_day" not in row:
        row["checkin_day"] = day
    state.setdefault("world_notes", []).append(f"[Stay] {k} +{n}n @ {loc} rate={rate}/n total={total}")
    return {"ok": True, "kind": k, "nights_added": n, "nights_remaining": int(row["nights_remaining"]), "rate_per_night": rate, "paid": total, "cash_after": int(econ["cash"])}


def deterministic_stay_raid_roll_percent(state: dict[str, Any]) -> int:
    meta = state.get("meta", {}) or {}
    seed = str(meta.get("world_seed", "") or meta.get("seed_pack", "") or "").strip() or "seed"
    try:
        turn = int(meta.get("turn", 0) or 0)
    except Exception as _omni_sw_130:
        log_swallowed_exception('engine/systems/accommodation.py:130', _omni_sw_130)
        turn = 0
    loc = _here_key(state)
    h = hashlib.md5(f"{seed}|{turn}|{loc}|raid_trigger".encode("utf-8", errors="ignore")).hexdigest()
    return int(h[:8], 16) % 100


def maybe_trigger_stay_raid(state: dict[str, Any]) -> dict[str, Any]:
    """Before STAY time processing, deterministically trigger an immediate raid scene."""
    if isinstance(state.get("active_scene"), dict) and state.get("active_scene"):
        return {"triggered": False, "reason": "scene_active"}
    try:
        tier_id = str((get_trace_tier(state) or {}).get("tier_id", "") or "")
    except Exception as _omni_sw_145:
        log_swallowed_exception('engine/systems/accommodation.py:145', _omni_sw_145)
        tier_id = ""
    if tier_id not in ("Wanted", "Lockdown"):
        return {"triggered": False, "reason": "tier_below_wanted", "tier_id": tier_id}

    chance = 15 if tier_id == "Wanted" else 40
    roll = deterministic_stay_raid_roll_percent(state)
    if roll >= chance:
        return {"triggered": False, "reason": "miss", "roll": int(roll), "chance": int(chance), "tier_id": tier_id}

    loc = _here_key(state) or "unknown"
    try:
        prof = ensure_location_profile(state, loc)
    except Exception as _omni_sw_160:
        log_swallowed_exception('engine/systems/accommodation.py:160', _omni_sw_160)
        prof = {}
    sh_row = ((state.get("world", {}) or {}).get("safehouses", {}) or {}).get(loc, {})
    if not isinstance(sh_row, dict):
        sh_row = {}
    meta = state.get("meta", {}) or {}
    try:
        day = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_168:
        log_swallowed_exception('engine/systems/accommodation.py:168', _omni_sw_168)
        day = 1
    try:
        tmin = int(meta.get("time_min", 0) or 0)
    except Exception as _omni_sw_172:
        log_swallowed_exception('engine/systems/accommodation.py:172', _omni_sw_172)
        tmin = 0
    scene_id = hashlib.md5(f"{loc}|{day}|{tmin}|stay_safehouse_raid".encode("utf-8", errors="ignore")).hexdigest()[:10]
    state["active_scene"] = {
        "scene_id": scene_id,
        "scene_type": "safehouse_raid",
        "phase": "breach",
        "context": {
            "location": loc,
            "country": str((prof or {}).get("country", "") or "").strip().lower(),
            "law_level": str((prof or {}).get("law_level", "standard") or "standard").strip().lower(),
            "security_level": int(sh_row.get("security_level", 1) or 1),
        },
        "vars": {"wait_count": 0},
        "expires_at": {"day": int(day), "time_min": min(1439, int(tmin) + 20)},
        "next_options": ["SCENE COMPLY", "SCENE FLEE", "SCENE HIDE", "SCENE FIGHT"],
    }
    state.setdefault("world_notes", []).append("[Security] Authorities tracked your location! A tactical unit is breaching.")
    return {"triggered": True, "roll": int(roll), "chance": int(chance), "tier_id": tier_id, "scene_type": "safehouse_raid"}


def process_accommodation_daily(state: dict[str, Any]) -> None:
    """Consume one prepaid night per game day (after check-in day) while player is at that location."""
    loc = _here_key(state)
    if not loc:
        return
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    acc = _ensure_accommodation_map(state)
    row = acc.get(loc)
    if not isinstance(row, dict):
        return
    k = str(row.get("kind", "none") or "none")
    if k not in ("hotel", "kos", "suite"):
        return
    n = int(row.get("nights_remaining", 0) or 0)
    if n <= 0:
        return
    ch = int(row.get("checkin_day", day) or day)
    if day <= ch:
        return
    row["nights_remaining"] = n - 1
    if int(row["nights_remaining"]) <= 0:
        row["kind"] = "none"
        row["nights_remaining"] = 0
    state.setdefault("world_notes", []).append(f"[Stay] night used @ {loc} kind={k} remaining={row.get('nights_remaining',0)}")


def apply_accommodation_rest_bonus(state: dict[str, Any]) -> None:
    """Weaker trace relief on rest/sleep when prepaid stay active and no safehouse."""
    try:
        sh = ensure_safehouse_here(state)
        if str(sh.get("status", "none") or "none") != "none":
            return
    except Exception as _omni_sw_228:
        log_swallowed_exception('engine/systems/accommodation.py:228', _omni_sw_228)
    row = get_stay_here(state)
    if not row:
        return
    k = str(row.get("kind", "none") or "none")
    if k not in ("hotel", "kos", "suite"):
        return
    if int(row.get("nights_remaining", 0) or 0) <= 0:
        return
    snap = get_balance_snapshot(state)
    base = int(snap.get("accommodation_trace_relief_base", BALANCE.accommodation_trace_relief_base) or BALANCE.accommodation_trace_relief_base)
    if k == "suite":
        bonus = base + 2
    elif k == "hotel":
        bonus = base + 1
    else:
        bonus = max(0, base - 1)
    tr = state.setdefault("trace", {})
    tp = int(tr.get("trace_pct", 0) or 0)
    tr["trace_pct"] = max(0, tp - bonus)
    state.setdefault("world_notes", []).append(f"[Stay] rest bonus ({k}): trace -{bonus}")


def auto_stay_intent_enabled() -> bool:
    """OMNI_AUTO_STAY_INTENT=1|true|yes|on — apply `stay_checkin` when NL accommodation intent matches."""
    import os

    v = str(os.environ.get("OMNI_AUTO_STAY_INTENT", "") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def try_auto_stay_from_intent(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic prepaid stay from `accommodation_intent` (parser or merged LLM field).

    - Default tier when `kind` is missing: boarding (`kos`).
    - No-op when disabled, wrong intent, or `stay_checkin` fails (e.g. not enough cash).
    """
    if not auto_stay_intent_enabled():
        return {"applied": False, "reason": "disabled"}
    if str(action_ctx.get("intent_note", "") or "") != "accommodation_stay":
        return {"applied": False, "reason": "no_intent"}
    aim = action_ctx.get("accommodation_intent")
    if not isinstance(aim, dict):
        return {"applied": False, "reason": "no_intent"}
    nights = max(1, min(365, int(aim.get("nights") or 1)))
    raw = aim.get("kind")
    if raw is None or str(raw).strip() == "":
        k = "kos"
    else:
        nk = normalize_stay_kind(str(raw))
        k = nk if nk else "kos"
    res = stay_checkin(state, k, nights)
    if not res.get("ok"):
        return {"applied": False, "reason": str(res.get("reason", "stay_failed")), "stay": res}
    return {"applied": True, "kind": k, "nights": nights, "stay": res}
