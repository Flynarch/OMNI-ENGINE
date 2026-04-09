from __future__ import annotations

from typing import Any


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except Exception:
        n = int(default)
    return max(int(lo), min(int(hi), int(n)))


def _norm_s(v: Any) -> str:
    return str(v or "").strip()


def process_memory_decay(
    state: dict[str, Any],
    *,
    base_importance_decay_per_day: int = 5,
    valence_cool_per_day: int = 8,
    consolidate_importance_threshold: int = 80,
    consolidate_min_age_days: int = 3,
) -> dict[str, int]:
    """Deterministic NPC memory decay + consolidation.

    - Decay: importance decreases each day; valence cools toward 0.
    - Consolidation: very high-importance memories (importance>threshold) older than N days become beliefs.
    - Hygiene: drop memories that reach importance==0; bound memory list size.

    Returns counters for debug/testing.
    """
    meta = state.get("meta", {}) or {}
    cur_day = _clamp_int(meta.get("day", 1), 1, 999999, 1)

    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return {"decayed": 0, "removed": 0, "consolidated": 0}

    decayed = 0
    removed = 0
    consolidated = 0

    for npc_id, npc in list(npcs.items()):
        if not isinstance(npc, dict):
            continue
        mems = npc.get("memories", [])
        if not isinstance(mems, list) or not mems:
            continue

        belief_tags = npc.setdefault("belief_tags", [])
        if not isinstance(belief_tags, list):
            belief_tags = []
            npc["belief_tags"] = belief_tags
        ms = npc.setdefault("memory_summary", {})
        if not isinstance(ms, dict):
            ms = {}
            npc["memory_summary"] = ms
        belief_from_mem: dict[str, Any] = ms.setdefault("belief_from_memories", {})
        if not isinstance(belief_from_mem, dict):
            belief_from_mem = {}
            ms["belief_from_memories"] = belief_from_mem

        keep: list[dict[str, Any]] = []

        for m in mems[:120]:
            if not isinstance(m, dict):
                continue
            mid = _norm_s(m.get("memory_id", ""))[:40]
            if not mid:
                continue
            imp = _clamp_int(m.get("importance", 0), 0, 100, 0)
            val = _clamp_int(m.get("valence", 0), -100, 100, 0)
            kind = str(m.get("kind", "") or "").strip().lower()[:32]
            summ = str(m.get("summary", "") or "").strip()

            when = m.get("when") if isinstance(m.get("when"), dict) else {}
            md = _clamp_int((when or {}).get("day", cur_day), 1, 999999, cur_day)
            age = max(0, int(cur_day) - int(md))

            # Consolidate into beliefs if long-lived and very important.
            if imp > int(consolidate_importance_threshold) and age >= int(consolidate_min_age_days):
                if mid not in belief_from_mem:
                    tag = "Deep_Grudge" if val <= -40 else "Eternal_Gratitude" if val >= 40 else ("Core_Belief_" + (kind or "memory"))
                    if tag not in belief_tags:
                        belief_tags.append(tag)
                    belief_from_mem[mid] = {
                        "tag": tag,
                        "kind": kind,
                        "summary": summ[:140],
                        "since_day": int(md),
                        "consolidated_day": int(cur_day),
                    }
                    consolidated += 1
                    state.setdefault("world_notes", []).append(f"[Belief] {npc_id}: consolidated {tag} from memory {mid}")
                # Drop from transient memories (now permanent via belief).
                continue

            # Normal decay
            if age >= 1:
                new_imp = max(0, imp - int(base_importance_decay_per_day))
                new_val = val
                if new_val > 0:
                    new_val = max(0, new_val - int(valence_cool_per_day))
                elif new_val < 0:
                    new_val = min(0, new_val + int(valence_cool_per_day))
                if new_imp != imp or new_val != val:
                    decayed += 1
                imp = new_imp
                val = new_val

            if imp <= 0:
                removed += 1
                continue

            m2 = dict(m)
            m2["importance"] = int(imp)
            m2["valence"] = int(val)
            keep.append(m2)

        # Bound list size: keep most important then most recent.
        try:
            def _key(x: dict[str, Any]) -> tuple[int, int]:
                w = x.get("when") if isinstance(x.get("when"), dict) else {}
                d = _clamp_int((w or {}).get("day", 1), 1, 999999, 1)
                imp = _clamp_int(x.get("importance", 0), 0, 100, 0)
                return (imp, d)

            keep.sort(key=_key, reverse=True)
            npc["memories"] = keep[:50]
        except Exception:
            npc["memories"] = keep[:50]

    return {"decayed": int(decayed), "removed": int(removed), "consolidated": int(consolidated)}

