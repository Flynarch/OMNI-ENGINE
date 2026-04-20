"""W2-12: judicial / incarceration state — sentence timer, seized inventory snapshot, daily release."""
from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
import hashlib
from typing import Any


def ensure_judicial(state: dict[str, Any]) -> dict[str, Any]:
    j = state.setdefault("judicial", {})
    if not isinstance(j, dict):
        j = {}
        state["judicial"] = j
    j.setdefault("phase", "free")
    j.setdefault("sentence_days_total", 0)
    j.setdefault("release_day", 0)
    j.setdefault("case_id", "")
    snap = j.get("seized_bag_snapshot")
    if not isinstance(snap, list):
        j["seized_bag_snapshot"] = []
    return j


def is_incarcerated(state: dict[str, Any]) -> bool:
    j = ensure_judicial(state)
    ph = str(j.get("phase", "free") or "free").strip().lower()
    return ph in ("custody", "sentenced", "incarcerated")


def fmt_judicial_brief(state: dict[str, Any]) -> str:
    j = ensure_judicial(state)
    ph = str(j.get("phase", "free") or "free")
    if ph == "free":
        return "judicial: free"
    rd = int(j.get("release_day", 0) or 0)
    return f"judicial: phase={ph} release_day={rd} case={j.get('case_id','')}"


def _case_id(meta: dict[str, Any], day: int) -> str:
    seed = str(meta.get("seed_pack", "") or meta.get("world_seed", "") or "")
    h = hashlib.md5(f"{seed}|{day}|case".encode("utf-8", errors="ignore")).hexdigest()
    return h[:12]


def apply_arrest_sentence(
    state: dict[str, Any],
    *,
    sentence_days: int = 3,
    bribery_attempt: bool = False,
) -> dict[str, Any]:
    """Attach sentence + seize contraband bag (hands already cleared by arrest)."""
    meta = state.setdefault("meta", {})
    try:
        d = int(meta.get("day", 1) or 1)
    except Exception as _omni_sw_54:
        log_swallowed_exception('engine/systems/judicial.py:54', _omni_sw_54)
        d = 1
    j = ensure_judicial(state)
    sd = max(1, min(30, int(sentence_days)))
    if bribery_attempt:
        sd += 1
    j["phase"] = "sentenced"
    j["sentence_days_total"] = int(sd)
    j["release_day"] = int(d + sd)
    j["case_id"] = _case_id(meta, d)

    inv = state.setdefault("inventory", {})
    if not isinstance(inv, dict):
        inv = {}
        state["inventory"] = inv
    bag = inv.get("bag_contents", [])
    if isinstance(bag, list) and bag:
        j["seized_bag_snapshot"] = list(bag)
        inv["bag_contents"] = []
    else:
        j["seized_bag_snapshot"] = []
    state["judicial"] = j
    return {"ok": True, "release_day": int(j["release_day"]), "sentence_days": int(sd), "seized_n": len(j["seized_bag_snapshot"])}


def tick_judicial_daily(state: dict[str, Any], *, day: int) -> None:
    """Call once per calendar day (after day rollover)."""
    j = ensure_judicial(state)
    if str(j.get("phase", "free") or "free").strip().lower() == "free":
        return
    try:
        rd = int(j.get("release_day", 0) or 0)
    except Exception as _omni_sw_86:
        log_swallowed_exception('engine/systems/judicial.py:86', _omni_sw_86)
        rd = 0
    if rd and int(day) >= rd:
        j["phase"] = "free"
        j["sentence_days_total"] = 0
        j["release_day"] = 0
        j["case_id"] = ""
        inv = state.setdefault("inventory", {})
        if not isinstance(inv, dict):
            inv = {}
            state["inventory"] = inv
        bag = inv.setdefault("bag_contents", [])
        if not isinstance(bag, list):
            bag = []
        snap = j.get("seized_bag_snapshot", [])
        if isinstance(snap, list):
            cap = 12
            try:
                cap = int(inv.get("bag_capacity", 12) or 12)
            except Exception as _omni_sw_105:
                log_swallowed_exception('engine/systems/judicial.py:105', _omni_sw_105)
                cap = 12
            for it in snap:
                if len(bag) >= cap:
                    break
                bag.append(it)
        inv["bag_contents"] = bag
        j["seized_bag_snapshot"] = []
        state["judicial"] = j
        state.setdefault("world_notes", []).append("[Judicial] Sentence served. Personal effects returned (what fits in your bag).")


def block_travel_if_incarcerated(state: dict[str, Any]) -> str | None:
    if is_incarcerated(state):
        return "Travel blocked: you are serving a sentence / in custody."
    return None


def block_action_if_incarcerated(state: dict[str, Any], *, surface: str) -> str | None:
    """Central incarceration policy for command surfaces."""
    if not is_incarcerated(state):
        return None
    s = str(surface or "").strip().lower()
    if s == "underworld":
        return "Underworld action blocked: you are serving a sentence / in custody."
    if s == "economy":
        return "Economy action blocked: you are serving a sentence / in custody."
    if s == "scene":
        return "Scene action blocked: you are serving a sentence / in custody."
    return "Action blocked: you are serving a sentence / in custody."
