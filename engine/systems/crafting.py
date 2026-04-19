from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RECIPES_PATH = ROOT / "data" / "packs" / "core" / "recipes.json"


def _qi(x: Any) -> int:
    try:
        return max(0, int(x))
    except Exception:
        return 0


def _skill_level(state: dict[str, Any], skill_id: str) -> int:
    sid = str(skill_id or "").strip().lower()
    if not sid:
        return 0
    skills = state.get("skills")
    if not isinstance(skills, dict):
        return 0
    row = skills.get(sid)
    if not isinstance(row, dict):
        return 0
    try:
        return max(0, int(row.get("level", 0) or 0))
    except Exception:
        return 0


def _parse_requires_skill(recipe: dict[str, Any]) -> tuple[str, int] | None:
    raw = recipe.get("requires_skill")
    if not isinstance(raw, dict):
        return None
    sk = str(raw.get("skill", raw.get("id", "")) or "").strip().lower()
    if not sk:
        return None
    need = _qi(raw.get("min_level", raw.get("level", 1)))
    need = max(1, min(99, need))
    return sk, need


def _recipe_cash_cost(recipe: dict[str, Any]) -> int:
    return max(0, min(500_000, _qi(recipe.get("cash_cost", 0))))


_KNOWN_WS = frozenset({"safehouse", "room", "stay", "hotel_room"})


def _parse_workstation_tokens(recipe: dict[str, Any]) -> list[str]:
    raw = recipe.get("requires_workstation") or recipe.get("requires_workstation_any") or recipe.get("workstation")
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[str] = []
        for x in raw:
            s = str(x or "").strip().lower()
            if s:
                out.append(s)
        return out
    s = str(raw).strip().lower()
    return [s] if s else []


def _format_workstation_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    labels: list[str] = []
    for t in tokens:
        t = str(t or "").strip().lower()
        if t == "safehouse":
            labels.append("safehouse")
        elif t in ("room", "stay", "hotel_room"):
            labels.append("kamar")
        else:
            labels.append(t)
    if len(labels) == 1:
        return labels[0]
    return "|".join(labels)


def _single_workstation_ok(state: dict[str, Any], token: str) -> bool:
    t = str(token or "").strip().lower()
    if t == "safehouse":
        return _has_active_safehouse_here(state)
    if t in ("room", "stay", "hotel_room"):
        return _has_active_stay_here(state)
    return False


def _has_active_stay_here(state: dict[str, Any]) -> bool:
    """Prepaid hotel/kos/suite at current location with nights remaining (see accommodation.py)."""
    try:
        from engine.systems.accommodation import get_stay_here

        row = get_stay_here(state)
    except Exception:
        row = None
    if not isinstance(row, dict):
        return False
    k = str(row.get("kind", "none") or "none").strip().lower()
    if k not in ("hotel", "kos", "suite"):
        return False
    return int(row.get("nights_remaining", 0) or 0) > 0


def _has_active_safehouse_here(state: dict[str, Any]) -> bool:
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not loc:
        return False
    world = state.get("world")
    if not isinstance(world, dict):
        return False
    sh = world.get("safehouses")
    if not isinstance(sh, dict):
        return False
    row = sh.get(loc)
    if not isinstance(row, dict):
        return False
    st = str(row.get("status", "none") or "none").strip().lower()
    return st in ("rent", "own")


def _workstation_satisfied(state: dict[str, Any], recipe: dict[str, Any]) -> tuple[bool, str]:
    tokens = _parse_workstation_tokens(recipe)
    if not tokens:
        return True, ""
    for t in tokens:
        if str(t or "").strip().lower() not in _KNOWN_WS:
            return False, "unknown_workstation"
    if any(_single_workstation_ok(state, t) for t in tokens):
        return True, ""
    has_sh = any(str(t or "").strip().lower() == "safehouse" for t in tokens)
    has_rm = any(str(t or "").strip().lower() in ("room", "stay", "hotel_room") for t in tokens)
    if has_sh and has_rm:
        return False, "need_bench"
    if has_sh:
        return False, "need_safehouse"
    return False, "need_room"


def _read_recipes_doc() -> dict[str, Any]:
    if not RECIPES_PATH.exists():
        return {"version": 1, "recipes": []}
    return json.loads(RECIPES_PATH.read_text(encoding="utf-8"))


def list_recipes() -> list[dict[str, Any]]:
    doc = _read_recipes_doc()
    raw = doc.get("recipes", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for r in raw:
        if isinstance(r, dict) and str(r.get("id", "") or "").strip():
            out.append(dict(r))
    out.sort(key=lambda x: str(x.get("id", "") or "").lower())
    return out


def get_recipe(recipe_id: str) -> dict[str, Any] | None:
    rid = str(recipe_id or "").strip().lower()
    for r in list_recipes():
        if str(r.get("id", "") or "").strip().lower() == rid:
            return r
    return None


def format_recipe_constraints(recipe: dict[str, Any]) -> str:
    bits: list[str] = []
    wst = _format_workstation_tokens(_parse_workstation_tokens(recipe))
    if wst:
        bits.append(wst)
    req = _parse_requires_skill(recipe)
    if req:
        bits.append(f"{req[0]}≥{req[1]}")
    c = _recipe_cash_cost(recipe)
    if c:
        bits.append(f"${c}")
    return " · ".join(bits) if bits else "—"


def _norm_item_ref(x: Any) -> str:
    return str(x or "").strip()


def _collect_counts(inv: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}

    def add(iid: str) -> None:
        k = str(iid or "").strip().lower()
        if not k or k == "-":
            return
        counts[k] = counts.get(k, 0) + 1

    for key in ("bag_contents", "pocket_contents"):
        lst = inv.get(key)
        if isinstance(lst, list):
            for it in lst:
                add(_norm_item_ref(it))
    for hk in ("r_hand", "l_hand"):
        add(_norm_item_ref(inv.get(hk)))
    return counts


def _stash_item_counts(state: dict[str, Any]) -> dict[str, int]:
    """Count item_id in current location safehouse stash (rent/own only)."""
    if not _has_active_safehouse_here(state):
        return {}
    try:
        from engine.systems.safehouse_stash import list_stash_here

        stash = list_stash_here(state)
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for entry in stash:
        if isinstance(entry, dict):
            iid = str(entry.get("item_id", "") or "").strip().lower()
        else:
            iid = str(entry or "").strip().lower()
        if iid:
            counts[iid] = counts.get(iid, 0) + 1
    return counts


def _collect_ingredient_availability(state: dict[str, Any]) -> dict[str, int]:
    inv = state.get("inventory")
    if not isinstance(inv, dict):
        return {}
    c = _collect_counts(inv)
    for k, v in _stash_item_counts(state).items():
        c[k] = c.get(k, 0) + v
    return c


def _remove_one(inv: dict[str, Any], item_id: str) -> bool:
    want = str(item_id or "").strip().lower()
    if not want:
        return False
    for key in ("bag_contents", "pocket_contents"):
        lst = inv.get(key)
        if not isinstance(lst, list):
            continue
        for idx, raw in enumerate(lst):
            if str(raw or "").strip().lower() == want:
                lst.pop(idx)
                return True
    for hk in ("r_hand", "l_hand"):
        if _norm_item_ref(inv.get(hk)).lower() == want:
            inv[hk] = "-"
            return True
    return False


def _remove_ingredients(inv: dict[str, Any], ingredients: dict[str, int]) -> bool:
    return _remove_ingredients_extended(inv, None, ingredients)


def _remove_one_from_stash(stash_list: list[Any], item_id: str) -> bool:
    want = str(item_id or "").strip().lower()
    if not want:
        return False
    for idx, elem in enumerate(list(stash_list)):
        if isinstance(elem, dict):
            eid = str(elem.get("item_id", "") or "").strip().lower()
        else:
            eid = str(elem or "").strip().lower()
        if eid == want:
            stash_list.pop(idx)
            return True
    return False


def _remove_one_extended(inv: dict[str, Any], stash_list: list[Any] | None, item_id: str) -> bool:
    """Take from carry first, then safehouse stash (if stash_list is a live list)."""
    if _remove_one(inv, item_id):
        return True
    if stash_list is None:
        return False
    return _remove_one_from_stash(stash_list, item_id)


def _remove_ingredients_extended(
    inv: dict[str, Any],
    stash_list: list[Any] | None,
    ingredients: dict[str, int],
) -> bool:
    for raw_id, raw_n in ingredients.items():
        iid = str(raw_id or "").strip().lower()
        n = _qi(raw_n)
        if not iid or n <= 0:
            continue
        for _ in range(n):
            if not _remove_one_extended(inv, stash_list, iid):
                return False
    return True


def _append_outputs(inv: dict[str, Any], outputs: dict[str, int]) -> bool:
    """Place crafted items into bag, then pocket. Returns False if capacity exceeded."""
    from engine.systems.shop import get_capacity_status

    for raw_id, raw_n in outputs.items():
        iid = str(raw_id or "").strip().lower()
        try:
            n = int(raw_n)
        except Exception:
            n = 0
        n = max(0, n)
        if not iid or n <= 0:
            continue
        for _ in range(n):
            inv.setdefault("bag_contents", [])
            inv.setdefault("pocket_contents", [])
            st = get_capacity_status({"inventory": inv})
            sz = _item_size_lookup(inv, iid)
            if st.bag_used + sz <= st.bag_cap:
                inv["bag_contents"].append(iid)
                continue
            if st.pocket_used + sz <= st.pocket_cap:
                inv["pocket_contents"].append(iid)
                continue
            return False
    return True


def _item_size_lookup(inv: dict[str, Any], item_id: str) -> int:
    sizes = inv.get("item_sizes") if isinstance(inv.get("item_sizes"), dict) else {}
    try:
        return max(1, min(6, int(sizes.get(item_id, 1) or 1)))
    except Exception:
        return 1


def can_craft(state: dict[str, Any], recipe_id: str) -> tuple[bool, str]:
    recipe = get_recipe(recipe_id)
    if not recipe:
        return False, "unknown_recipe"
    ing = recipe.get("ingredients")
    if not isinstance(ing, dict) or not ing:
        return False, "bad_recipe"
    inv = state.get("inventory")
    if not isinstance(inv, dict):
        return False, "no_inventory"
    ws_ok, ws_reason = _workstation_satisfied(state, recipe)
    if not ws_ok:
        return False, ws_reason or "wrong_workstation"
    req = _parse_requires_skill(recipe)
    if req is not None:
        sk, need = req
        if _skill_level(state, sk) < need:
            return False, "skill_too_low"
    cost = _recipe_cash_cost(recipe)
    if cost > 0:
        eco = state.get("economy")
        if not isinstance(eco, dict):
            return False, "not_enough_cash"
        try:
            cash = int(eco.get("cash", 0) or 0)
        except Exception:
            cash = 0
        if cash < cost:
            return False, "not_enough_cash"
    counts = _collect_ingredient_availability(state)
    for iid0, need0 in ing.items():
        iid = str(iid0 or "").strip().lower()
        need = _qi(need0)
        if counts.get(iid, 0) < need:
            return False, "missing_ingredients"
    ing_norm = {str(k).strip().lower(): _qi(v) for k, v in ing.items()}
    trial = deepcopy(inv)
    stash_trial: list[Any] | None = None
    if _has_active_safehouse_here(state):
        from engine.systems.safehouse import ensure_safehouse_here

        r = ensure_safehouse_here(state)
        raw = r.get("stash")
        stash_trial = deepcopy(raw) if isinstance(raw, list) else []
    if not _remove_ingredients_extended(trial, stash_trial, ing_norm):
        return False, "remove_failed"
    out = recipe.get("outputs")
    if not isinstance(out, dict) or not out:
        return False, "bad_recipe"
    out_norm = {str(k).strip().lower(): _qi(v) for k, v in out.items()}
    if not _append_outputs(trial, out_norm):
        return False, "no_space"
    return True, "ok"


def _apply_craft_progress(state: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    """Increment meta craft stats and award small flat XP (skill from requires_skill, else operations)."""
    meta = state.setdefault("meta", {})
    rid = str(recipe.get("id", "") or "").strip().lower()
    if rid:
        cc = meta.setdefault("craft_counts", {})
        if not isinstance(cc, dict):
            cc = {}
            meta["craft_counts"] = cc
        cc[rid] = int(cc.get(rid, 0) or 0) + 1
    try:
        meta["crafts_total"] = int(meta.get("crafts_total", 0) or 0) + 1
    except Exception:
        meta["crafts_total"] = 1
    try:
        from engine.player.skills import grant_skill_xp_flat

        req = _parse_requires_skill(recipe)
        if req is not None:
            sk, _need = req
            grant_skill_xp_flat(state, sk, amount=2)
            return {"xp_skill": sk, "xp_amount": 2}
        grant_skill_xp_flat(state, "operations", amount=1)
        return {"xp_skill": "operations", "xp_amount": 1}
    except Exception:
        return {}


def craft(state: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    ok, reason = can_craft(state, recipe_id)
    if not ok:
        return {"ok": False, "reason": reason}
    recipe = get_recipe(recipe_id)
    if not recipe:
        return {"ok": False, "reason": "unknown_recipe"}
    inv = state.setdefault("inventory", {})
    ing = recipe.get("ingredients")
    out = recipe.get("outputs")
    assert isinstance(ing, dict) and isinstance(out, dict)
    ing_norm = {str(k).strip().lower(): _qi(v) for k, v in ing.items()}
    out_norm = {str(k).strip().lower(): _qi(v) for k, v in out.items()}
    cost = _recipe_cash_cost(recipe)
    inv_snap = deepcopy(inv)
    stash_list: list[Any] | None = None
    stash_snap: list[Any] | None = None
    if _has_active_safehouse_here(state):
        from engine.systems.safehouse import ensure_safehouse_here

        row = ensure_safehouse_here(state)
        if not isinstance(row.get("stash"), list):
            row["stash"] = []
        stash_list = row["stash"]
        stash_snap = deepcopy(stash_list)
    eco = state.setdefault("economy", {})
    eco_snap = deepcopy(eco) if isinstance(eco, dict) else {}
    cash_paid = 0
    if cost > 0:
        if not isinstance(eco, dict):
            return {"ok": False, "reason": "not_enough_cash"}
        try:
            cash0 = int(eco.get("cash", 0) or 0)
        except Exception:
            cash0 = 0
        if cash0 < cost:
            return {"ok": False, "reason": "not_enough_cash"}
        eco["cash"] = max(0, cash0 - cost)
        cash_paid = cost
    if not _remove_ingredients_extended(inv, stash_list, ing_norm):
        state["inventory"] = inv_snap
        if isinstance(eco, dict) and isinstance(eco_snap, dict):
            state["economy"] = eco_snap
        if stash_list is not None and stash_snap is not None:
            stash_list.clear()
            stash_list.extend(stash_snap)
        return {"ok": False, "reason": "remove_failed"}
    if not _append_outputs(inv, out_norm):
        state["inventory"] = inv_snap
        if isinstance(eco, dict) and isinstance(eco_snap, dict):
            state["economy"] = eco_snap
        if stash_list is not None and stash_snap is not None:
            stash_list.clear()
            stash_list.extend(stash_snap)
        return {"ok": False, "reason": "no_space"}
    try:
        tmin = int(recipe.get("time_min", 5) or 5)
    except Exception:
        tmin = 5
    tmin = max(1, min(120, tmin))
    label = str(recipe.get("label", recipe.get("id", "")) or recipe_id)
    outs_flat = [f"{k}×{v}" for k, v in out_norm.items() if v > 0]
    xp_pkg = _apply_craft_progress(state, recipe)
    out: dict[str, Any] = {
        "ok": True,
        "recipe_id": str(recipe.get("id", recipe_id)),
        "label": label,
        "time_min": tmin,
        "outputs": dict(out_norm),
        "summary": ", ".join(outs_flat) or label,
        "cash_paid": cash_paid,
    }
    if xp_pkg.get("xp_skill"):
        out["xp_skill"] = xp_pkg["xp_skill"]
        out["xp_amount"] = int(xp_pkg.get("xp_amount", 0) or 0)
    return out
