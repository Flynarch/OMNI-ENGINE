"""W2-2: numeric reputation lanes drive access (black market tier, informant premium), not just labels."""
from __future__ import annotations

from typing import Any

LANES = ("criminal", "corporate", "political", "street", "underground")


def ensure_reputation_lanes(state: dict[str, Any]) -> dict[str, Any]:
    rep = state.setdefault("reputation", {})
    if not isinstance(rep, dict):
        rep = {}
        state["reputation"] = rep
    scores = rep.get("scores")
    if not isinstance(scores, dict):
        scores = {}
        rep["scores"] = scores
    for lane in LANES:
        if lane not in scores:
            scores[lane] = 50
        try:
            scores[lane] = max(0, min(100, int(scores[lane])))
        except Exception:
            scores[lane] = 50
    rep["scores"] = scores
    return rep


def lane_score(state: dict[str, Any], lane: str) -> int:
    ensure_reputation_lanes(state)
    rep = state.get("reputation", {}) or {}
    scores = rep.get("scores", {}) if isinstance(rep.get("scores"), dict) else {}
    lk = str(lane or "").strip().lower()
    try:
        return max(0, min(100, int(scores.get(lk, 50) or 50)))
    except Exception:
        return 50


def bump_lane(state: dict[str, Any], lane: str, delta: int) -> int:
    ensure_reputation_lanes(state)
    rep = state.setdefault("reputation", {})
    scores = rep.setdefault("scores", {})
    lk = str(lane or "").strip().lower()
    if lk not in LANES:
        return 50
    cur = lane_score(state, lk)
    nv = max(0, min(100, cur + int(delta)))
    scores[lk] = nv
    return nv


def dominant_lane(state: dict[str, Any]) -> str:
    ensure_reputation_lanes(state)
    rep = state.get("reputation", {}) or {}
    scores = rep.get("scores", {}) if isinstance(rep.get("scores"), dict) else {}
    best = -1
    best_l = "street"
    for lane in LANES:
        try:
            v = int(scores.get(lane, 50) or 50)
        except Exception:
            v = 50
        if v > best or (v == best and lane < best_l):
            best = v
            best_l = lane
    return best_l


def black_market_access_tier(state: dict[str, Any]) -> int:
    """0..3 — higher unlocks more catalog tiers (underworld + criminal standing)."""
    ensure_reputation_lanes(state)
    u = lane_score(state, "underground")
    c = lane_score(state, "criminal")
    m = max(u, c)
    if m >= 75:
        return 3
    if m >= 50:
        return 2
    if m >= 28:
        return 1
    return 0


def black_market_price_percent(state: dict[str, Any]) -> int:
    """Percentage multiplier for BM checkout (100 = baseline). Dominant lane adjusts markup/discount."""
    dom = dominant_lane(state)
    u = lane_score(state, "underground")
    cr = lane_score(state, "criminal")
    co = lane_score(state, "corporate")
    po = lane_score(state, "political")
    pct = 100
    if dom in ("underground", "criminal"):
        pct -= min(12, (u + cr) // 18)
    elif dom in ("corporate", "political"):
        pct += min(10, (co + po) // 20)
    return max(88, min(118, int(pct)))


def black_market_item_required_tier(item_id: str) -> int:
    try:
        from engine.systems.black_market import ITEM_REPUTATION_TIER

        return int(ITEM_REPUTATION_TIER.get(str(item_id or "").strip().lower(), 0))
    except Exception:
        return 0


def can_buy_black_market_item(state: dict[str, Any], item_id: str) -> dict[str, Any]:
    iid = str(item_id or "").strip().lower()
    need = black_market_item_required_tier(iid)
    have = black_market_access_tier(state)
    if have >= need:
        return {"ok": True, "need_tier": need, "your_tier": have}
    return {
        "ok": False,
        "reason": "reputation_gate",
        "message": "Vendor trust too low for this listing. Raise underground/criminal standing or find a fixer introduction.",
        "need_tier": need,
        "your_tier": have,
    }


def premium_informant_unlocked(state: dict[str, Any]) -> bool:
    """Premium intel roster — street cred or political access."""
    ensure_reputation_lanes(state)
    return lane_score(state, "political") >= 38 or lane_score(state, "street") >= 42


def premium_intel_pay_cap(state: dict[str, Any]) -> int:
    """Max single PAY that counts as premium intel (soft gate)."""
    return 2500 if premium_informant_unlocked(state) else 800
