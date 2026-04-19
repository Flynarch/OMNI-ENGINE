from __future__ import annotations

from engine.core.error_taxonomy import log_swallowed_exception
from engine.core.player_language_levels import player_language_proficiency
from dataclasses import dataclass
from typing import Any

from engine.world.atlas import ensure_location_profile
from engine.world.time_model import sim_year_from_state, tech_epoch_for_year


def _split_lang(s: str) -> list[str]:
    raw = str(s or "").strip().lower()
    if not raw:
        return []
    parts: list[str] = []
    for chunk in raw.replace("/", "+").split("+"):
        c = chunk.strip().lower()
        if c:
            parts.append(c)
    # de-dupe stable
    out: list[str] = []
    for p in parts:
        if p not in out:
            out.append(p)
    return out


@dataclass(frozen=True)
class LanguageCtx:
    sim_year: int
    tech_epoch: str
    local_lang: str
    local_langs: list[str]
    player_langs: list[str]
    shared: bool
    translator_level: str  # none|lowtech|basic|good|advanced
    quality: int  # 0..100
    penalty: int  # negative modifier applied to social roll
    reason: str


def _inventory_item_ids(state: dict[str, Any]) -> list[str]:
    inv = state.get("inventory", {}) or {}
    toks: list[str] = []
    for key in ("r_hand", "l_hand", "worn"):
        v = inv.get(key)
        if isinstance(v, str) and v.strip() and v.strip() != "-":
            toks.append(v.strip().lower())
    for key in ("pocket_contents", "bag_contents"):
        arr = inv.get(key) or []
        if isinstance(arr, list):
            for x in arr[:60]:
                if isinstance(x, str):
                    toks.append(x.lower())
                elif isinstance(x, dict):
                    toks.append(str(x.get("id", x.get("name", "")) or "").lower())
    return [t for t in toks if t]


def _translator_from_inventory(state: dict[str, Any]) -> str:
    """Return best translator level implied by inventory + content tags."""
    world = state.get("world", {}) or {}
    idx = (world.get("content_index", {}) or {}) if isinstance(world, dict) else {}
    items_idx = idx.get("items", {}) if isinstance(idx, dict) else {}
    inv_ids = _inventory_item_ids(state)

    best = "none"
    for iid in inv_ids:
        tags: list[str] = []
        row = items_idx.get(iid)
        if isinstance(row, dict) and isinstance(row.get("tags"), list):
            tags = [str(x).lower() for x in row.get("tags", []) if isinstance(x, str)]
        else:
            tags = []
        if "translator_advanced" in tags:
            return "advanced"
        if "translator_good" in tags:
            best = "good"
        if "translator_basic" in tags and best not in ("good", "advanced"):
            best = "basic"
        if "translator_lowtech" in tags and best == "none":
            best = "lowtech"
    return best


def resolve_local_language(state: dict[str, Any], loc: str) -> tuple[str, list[str]]:
    prof = ensure_location_profile(state, loc)
    lang = str((prof.get("language") if isinstance(prof, dict) else "") or "en").lower()
    langs = _split_lang(lang)
    return (lang, langs or ["en"])


def communication_quality(state: dict[str, Any], action_ctx: dict[str, Any]) -> LanguageCtx:
    meta = state.get("meta", {}) or {}
    try:
        sim_year = int(meta.get("sim_year", 0) or 0)
    except Exception as _omni_sw_113:
        log_swallowed_exception('engine/core/language.py:113', _omni_sw_113)
        sim_year = 0
    if sim_year <= 0:
        sim_year = sim_year_from_state(state)

    world = state.get("world", {}) or {}
    try:
        tech_progress = float((world.get("tech_progress", 0.0) if isinstance(world, dict) else 0.0) or 0.0)
    except Exception as _omni_sw_123:
        log_swallowed_exception('engine/core/language.py:123', _omni_sw_123)
        tech_progress = 0.0
    epoch = tech_epoch_for_year(sim_year, tech_progress=tech_progress)

    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    local_lang, local_langs = resolve_local_language(state, loc) if loc else ("en", ["en"])
    pl = player_language_proficiency(state)
    player_langs = sorted([k for k, v in pl.items() if int(v) >= 40])

    shared = any(l in pl and int(pl.get(l, 0)) >= 40 for l in local_langs)

    inv_trans = _translator_from_inventory(state)

    # Translator availability by epoch (real-world leaning).
    tl = "none"
    if inv_trans == "advanced":
        tl = "advanced"
    elif inv_trans == "good":
        tl = "good" if epoch.translator_level in ("good", "advanced") else "basic"
    elif inv_trans == "basic":
        tl = "basic" if epoch.translator_level != "none" else "none"
    elif inv_trans == "lowtech":
        tl = "lowtech"

    # Quality model
    if shared:
        quality = 92
        penalty = 0
        reason = "shared_language"
    else:
        base_q = 10
        if tl == "lowtech":
            base_q = 18
        elif tl == "basic":
            base_q = max(base_q, epoch.translator_quality)
        elif tl == "good":
            base_q = max(base_q, epoch.translator_quality + 12)
        elif tl == "advanced":
            base_q = max(base_q, epoch.translator_quality + 20)
        quality = max(0, min(95, base_q))
        # Penalty scaling: low quality hurts more.
        if quality >= 75:
            penalty = -4
        elif quality >= 55:
            penalty = -10
        elif quality >= 35:
            penalty = -18
        else:
            penalty = -28
        reason = "translator" if tl != "none" else "no_shared_language"

    return LanguageCtx(
        sim_year=int(sim_year),
        tech_epoch=str(epoch.name),
        local_lang=str(local_lang),
        local_langs=list(local_langs),
        player_langs=list(player_langs),
        shared=bool(shared),
        translator_level=str(tl),
        quality=int(quality),
        penalty=int(penalty),
        reason=str(reason),
    )


def is_high_stakes_social(action_ctx: dict[str, Any]) -> bool:
    # Explicit conflict is always high stakes.
    if str(action_ctx.get("social_mode", "") or "").lower() == "conflict":
        return True
    norm = str(action_ctx.get("normalized_input", "") or "").lower()
    # Payment/contract/negotiation keywords.
    return any(
        k in norm
        for k in (
            "negosiasi",
            "negotiate",
            "contract",
            "kontrak",
            "deal",
            "bayar",
            "payment",
            "utang",
            "debt",
            "blackmail",
            "peras",
            "ancam",
            "intimidasi",
            "transfer",
        )
    )

