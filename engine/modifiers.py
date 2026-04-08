from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILLS_TABLE_PATH = ROOT / "data" / "skills_table.json"

# Fallback if JSON missing or invalid (v6.8 C1)
_BASE_FALLBACK: dict[str, tuple[int, int]] = {
    "social": (60, 25),
    "combat": (55, 20),
    "hacking": (55, 15),
    "medical": (55, 20),
    "driving": (65, 30),
    "stealth": (55, 30),
    "evasion": (50, 50),
}

_cached_base: dict[str, tuple[int, int]] | None = None


def _load_base_thresholds() -> dict[str, tuple[int, int]]:
    global _cached_base
    if _cached_base is not None:
        return _cached_base
    out = dict(_BASE_FALLBACK)
    if SKILLS_TABLE_PATH.exists():
        try:
            raw = json.loads(SKILLS_TABLE_PATH.read_text(encoding="utf-8"))
            table = raw.get("base_thresholds", {})
            if isinstance(table, dict):
                for key, row in table.items():
                    if not isinstance(row, dict):
                        continue
                    tr, un = row.get("trained"), row.get("unskilled")
                    if isinstance(tr, (int, float)) and isinstance(un, (int, float)):
                        out[str(key)] = (int(tr), int(un))
        except Exception:
            pass
    _cached_base = out
    return out


def base_pair(domain: str) -> tuple[int, int]:
    b = _load_base_thresholds()
    return b.get(domain, b["evasion"])


def compute_roll_package(state: dict[str, Any], action_ctx: dict[str, Any]) -> dict[str, Any]:
    domain = action_ctx.get("domain", "evasion")
    trained = bool(action_ctx.get("trained", True))
    pair = base_pair(domain)
    base = pair[0 if trained else 1]
    mods: list[tuple[str, int]] = []
    act_type = str(action_ctx.get("action_type", "") or "")

    bio = state.get("bio", {})
    # Ordered modifier stack (v6.8 deterministic order).
    # 1. Skill decay
    decay_pen = int(action_ctx.get("skill_decay_penalty", 0))
    if decay_pen != 0:
        mods.append(("Skill decay", decay_pen))
    # 2. Trauma debuff
    if bool(action_ctx.get("trauma_debuff", False)):
        mods.append(("Trauma debuff", -10))
    # 3. Mastery bonus
    if bool(action_ctx.get("mastery_active", False)):
        mods.append(("Mastery bonus", +10))
    # 4. Acute stress
    if bool(bio.get("acute_stress", False)):
        mods.append(("Acute stress precision", -20))
    # 5. Burnout
    if int(bio.get("burnout", 0)) >= 5:
        mods.append(("Burnout", -20))
    # 6. Blood loss
    if bio.get("bp_state") == "Low" and domain == "combat":
        mods.append(("Blood loss low", -20))
    if bio.get("bp_state") == "Critical":
        mods.append(("Blood loss critical", -25))
    # 7. Permanent injuries
    perm_pen = int(action_ctx.get("permanent_injury_penalty", 0))
    if perm_pen != 0:
        mods.append(("Permanent injury", perm_pen))
    # 8. Environmental
    env_pen = int(action_ctx.get("environment_penalty", 0))
    env_bonus = int(action_ctx.get("environment_bonus", 0))
    if env_pen != 0:
        mods.append(("Environment penalty", env_pen))
    if env_bonus != 0:
        mods.append(("Environment bonus", env_bonus))

    # Location-specific restrictions (deterministic, no new scheduling).
    try:
        cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
        day = int((state.get("meta", {}) or {}).get("day", 1) or 1)
        world = state.get("world", {}) or {}
        locs = world.get("locations", {}) or {}
        slot = (locs.get(cur_loc) if isinstance(locs, dict) and cur_loc else None) if True else None
        restr = (slot.get("restrictions", {}) if isinstance(slot, dict) else {}) or {}

        # Police sweep: stealth/evasion + travel becomes harder in affected city.
        if domain in ("stealth", "evasion") or act_type == "travel":
            try:
                until_ps = int(restr.get("police_sweep_until_day", 0) or 0) if isinstance(restr, dict) else 0
            except Exception:
                until_ps = 0
            if until_ps >= day:
                # Evasion/stealth gets punished; travel gets a little punished even if no roll (threshold still matters for UI).
                mods.append(("Police sweep", -8 if domain in ("stealth", "evasion") else -5))

        # Corporate lockdown: corporate hacking becomes harder in affected city.
        if domain == "hacking":
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            if isinstance(restr, dict):
                try:
                    until = int(restr.get("corporate_lockdown_until_day", 0) or 0)
                except Exception:
                    until = 0
                if until >= day:
                    norm = str(action_ctx.get("normalized_input", "") or "").lower()
                    # Only apply when player is targeting corporate-ish systems.
                    if any(t in norm for t in ("corp", "corporate", "perusahaan", "kantor pusat", "hq")):
                        mods.append(("Corporate lockdown", -10))

        # Area-level restrictions (simple districts): add a small penalty if player targets restricted districts by text.
        try:
            if isinstance(slot, dict):
                areas = slot.get("areas", {}) or {}
                if isinstance(areas, dict) and areas:
                    norm = str(action_ctx.get("normalized_input", "") or "").lower()
                    day2 = day
                    # If player mentions a restricted area name, apply penalty (movement/stealth/hacking most affected).
                    for area_name, arow in list(areas.items())[:20]:
                        if not isinstance(area_name, str) or not isinstance(arow, dict):
                            continue
                        if not bool(arow.get("restricted", False)):
                            continue
                        try:
                            until_a = int(arow.get("until_day", 0) or 0)
                        except Exception:
                            until_a = 0
                        if until_a < day2:
                            continue
                        if area_name.lower() in norm:
                            if domain in ("stealth", "evasion", "hacking"):
                                mods.append((f"Restricted area ({area_name})", -6))
                            else:
                                mods.append((f"Restricted area ({area_name})", -3))
                            break
        except Exception:
            pass
    except Exception:
        pass

    # Weather modifier (stealth/evasion mostly).
    try:
        from engine.weather import ensure_weather, stealth_bonus

        if domain in ("stealth", "evasion"):
            meta2 = state.get("meta", {}) or {}
            day2 = int(meta2.get("day", 1) or 1)
            cur_loc = str(state.get("player", {}).get("location", "") or "").strip().lower()
            if cur_loc:
                w = ensure_weather(state, cur_loc, day2)
                b = stealth_bonus(str((w or {}).get("kind", "") or ""))
                if b:
                    mods.append(("Weather", b))
    except Exception:
        pass
    # 9. Hygiene tax
    if bio.get("hygiene_tax_active") and domain == "social":
        mods.append(("Hygiene tax", -30))

    # Social non-conflict: tidak perlu roll, tapi tetap terjadi (AI harus buat dialog/beat).
    if domain == "social" and action_ctx.get("social_mode") == "non_conflict":
        net = max(0, min(100, base + sum(v for _, v in mods)))
        return {
            "base": base,
            "mods": mods + [("Social non-conflict", +0)],
            "net_threshold": net,
            "roll": None,
            "outcome": "No Roll (Social Non-Conflict)",
            "net_threshold_locked": True,
        }

    # Social conflict: apply social_stats from state (looks/outfit/hygiene/speaking).
    if domain == "social":
        stats = state.get("player", {}).get("social_stats", {}) or {}
        if isinstance(stats, dict):
            total = 0
            for k in ("looks", "outfit", "hygiene", "speaking"):
                try:
                    v = int(stats.get(k, 0) or 0)
                except Exception:
                    v = 0
                total += max(-20, min(20, v))
            total = max(-25, min(25, total))
            if total != 0:
                mods.append(("Social stats", total))

        # NPC belief modifier (only meaningful for conflict rolls with a concrete target).
        if action_ctx.get("social_mode") == "conflict":
            targs = action_ctx.get("targets")
            if isinstance(targs, list) and targs:
                t0 = targs[0]
                npcs = state.get("npcs", {}) or {}
                if isinstance(t0, str) and isinstance(npcs, dict) and isinstance(npcs.get(t0), dict):
                    bs = (npcs.get(t0) or {}).get("belief_summary", {}) or {}
                    if isinstance(bs, dict):
                        try:
                            suspicion = int(bs.get("suspicion", 0) or 0)
                        except Exception:
                            suspicion = 0
                        try:
                            respect = int(bs.get("respect", 50) or 50)
                        except Exception:
                            respect = 50
                        # suspicion makes social harder; respect makes it easier.
                        sus_mod = -min(20, max(0, int((suspicion - 30) / 3)))
                        rep_mod = min(10, max(-10, int((respect - 50) / 5)))
                        if sus_mod != 0:
                            mods.append(("NPC suspicion", sus_mod))
                        if rep_mod != 0:
                            mods.append(("NPC respect", rep_mod))

                    # Relationship edge modifier (player <-> NPC) from world.social_graph
                    world = state.get("world", {}) or {}
                    g = world.get("social_graph", {}) or {}
                    if isinstance(g, dict):
                        p = g.get("__player__", {}) or {}
                        if isinstance(p, dict):
                            edge = p.get(t0)
                            if isinstance(edge, dict):
                                et = str(edge.get("type", "neutral") or "neutral").lower()
                                try:
                                    strength = int(edge.get("strength", 50) or 50)
                                except Exception:
                                    strength = 50
                                # Relationship makes it easier/harder depending on type and strength.
                                rel_mod = 0
                                if et in ("ally", "lover", "friend"):
                                    rel_mod = min(12, max(0, int((strength - 50) / 4)))
                                elif et in ("handler",):
                                    # Handler is a leverage relationship: mild bonus but capped.
                                    rel_mod = min(8, max(-6, int((strength - 50) / 6)))
                                elif et in ("rival", "enemy", "informant"):
                                    rel_mod = -min(18, max(0, int((strength - 50) / 3)))
                                elif et in ("debt", "debtor"):
                                    rel_mod = -min(22, max(0, int((strength - 40) / 3)))
                                if rel_mod != 0:
                                    mods.append(("Relationship", rel_mod))

    # Combat gate (ammo / broken / no weapon for ranged) — sebelum roll
    if domain == "combat":
        blocked = action_ctx.get("combat_blocked")
        if blocked:
            labels = {
                "no_weapon": "No weapon for ranged",
                "out_of_ammo": "Out of ammo",
                "broken": "Weapon broken",
            }
            reason = labels.get(str(blocked), str(blocked))
            return {
                "base": base,
                "mods": mods + [(f"Combat blocked ({reason})", -100)],
                "net_threshold": 0,
                "roll": None,
                "outcome": f"Auto Fail ({reason})",
                "net_threshold_locked": True,
            }

    # CC threshold gate for social actions (fail-fast context gating).
    if domain == "social":
        cc = int(state.get("player", {}).get("cc", 0) or 0)
        social_context = action_ctx.get("social_context", "standard")
        if social_context == "formal" and cc <= 20:
            return {
                "base": base,
                "mods": mods + [("CC gate formal fail", -100)],
                "net_threshold": 0,
                "roll": None,
                "outcome": "Auto Fail (CC Gate)",
                "net_threshold_locked": True,
            }

    net = max(0, min(100, base + sum(v for _, v in mods)))
    if action_ctx.get("physically_impossible"):
        return {
            "base": base,
            "mods": mods + [("Impossible action", -100)],
            "net_threshold": 0,
            "roll": None,
            "outcome": "Auto Fail (Impossible)",
            "net_threshold_locked": True,
        }

    if action_ctx.get("trivial_action"):
        return {
            "base": base,
            "mods": mods,
            "net_threshold": net,
            "roll": None,
            "outcome": "Auto Success (Trivial)",
            "net_threshold_locked": True,
        }

    # Non-combat low stakes: jangan pakai roll untuk aksi yang sederhana.
    stakes = str(action_ctx.get("stakes", "") or "").lower()
    if domain != "combat" and stakes in ("none", "low") and not (
        domain == "social" and action_ctx.get("social_mode") == "conflict"
    ):
        return {
            "base": base,
            "mods": mods + [("Low stakes (no roll)", +0)],
            "net_threshold": net,
            "roll": None,
            "outcome": "No Roll (Low stakes)",
            "net_threshold_locked": True,
        }

    should_roll = bool(action_ctx.get("uncertain", True) and action_ctx.get("has_stakes", True))
    if not should_roll:
        return {"base": base, "mods": mods, "net_threshold": net, "roll": None, "outcome": "No Roll", "net_threshold_locked": True}
    # Deterministic roll for replayability/debuggability (no hidden RNG drift).
    try:
        from engine.rng import roll_for_action

        roll = int(roll_for_action(state, action_ctx, salt="roll_pkg"))
    except Exception:
        roll = random.randint(1, 100)
    success = roll <= net
    if roll <= 5:
        outcome = "Critical Failure"
    elif success and roll >= 91:
        outcome = "Critical Success"
    elif success:
        outcome = "Success"
    else:
        outcome = "Failure"
    return {"base": base, "mods": mods, "net_threshold": net, "roll": roll, "outcome": outcome, "net_threshold_locked": True}


def stop_sequence_check(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    t1 = bool(action_ctx.get("irreversible_decision"))
    t2 = bool(action_ctx.get("new_zone"))
    t3 = bool(action_ctx.get("blood_loss_single_event_over_30"))
    flags = state.setdefault("flags", {})
    flags["stop_sequence_active"] = t1 or t2 or t3
    flags["stop_sequence_trigger"] = (
        "irreversible_decision" if t1 else "new_zone" if t2 else "critical_blood_loss" if t3 else ""
    )

