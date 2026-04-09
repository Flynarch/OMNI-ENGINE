from __future__ import annotations

import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


MOVED: dict[str, str] = {
    # npc
    "engine.npcs": "engine.npc.npcs",
    "engine.npc_combat_ai": "engine.npc.npc_combat_ai",
    "engine.npc_emotions": "engine.npc.npc_emotions",
    "engine.npc_sim": "engine.npc.npc_sim",
    "engine.npc_targeting": "engine.npc.npc_targeting",
    "engine.npc_rumor_system": "engine.npc.npc_rumor_system",
    # world
    "engine.world": "engine.world.world",
    "engine.atlas": "engine.world.atlas",
    "engine.weather": "engine.world.weather",
    "engine.time_model": "engine.world.time_model",
    "engine.timers": "engine.world.timers",
    "engine.districts": "engine.world.districts",
    "engine.location_presets": "engine.world.location_presets",
    "engine.casefile": "engine.world.casefile",
    "engine.heat": "engine.world.heat",
    # player
    "engine.bio": "engine.player.bio",
    "engine.skills": "engine.player.skills",
    "engine.inventory": "engine.player.inventory",
    "engine.inventory_ops": "engine.player.inventory_ops",
    "engine.economy": "engine.player.economy",
    "engine.banking": "engine.player.banking",
    "engine.market": "engine.player.market",
    "engine.boot_economy": "engine.player.boot_economy",
    "engine.language_learning": "engine.player.language_learning",
    # systems
    "engine.combat": "engine.systems.combat",
    "engine.hacking": "engine.systems.hacking",
    "engine.intimacy": "engine.systems.intimacy",
    "engine.shop": "engine.systems.shop",
    "engine.safehouse": "engine.systems.safehouse",
    "engine.safehouse_raid": "engine.systems.safehouse_raid",
    "engine.safehouse_stash": "engine.systems.safehouse_stash",
    "engine.search_conceal": "engine.systems.search_conceal",
    "engine.scenes": "engine.systems.scenes",
    "engine.quests": "engine.systems.quests",
    "engine.occupation": "engine.systems.occupation",
    "engine.vehicles": "engine.systems.vehicles",
    "engine.weapon_kit": "engine.systems.weapon_kit",
    "engine.ammo": "engine.systems.ammo",
    "engine.illegal_trade": "engine.systems.illegal_trade",
    "engine.disguise": "engine.systems.disguise",
    "engine.encounter_router": "engine.systems.encounter_router",
    "engine.encounter_scheduler": "engine.systems.encounter_scheduler",
    "engine.accommodation": "engine.systems.accommodation",
    # social
    "engine.ripples": "engine.social.ripples",
    "engine.ripple_queue": "engine.social.ripple_queue",
    "engine.social_diffusion": "engine.social.social_diffusion",
    "engine.police_check": "engine.social.police_check",
    "engine.suspicion_ui": "engine.social.suspicion_ui",
    "engine.news": "engine.social.news",
    "engine.informants": "engine.social.informants",
    "engine.informant_ops": "engine.social.informant_ops",
    "engine.investigation_chains": "engine.social.investigation_chains",
    # core
    "engine.state": "engine.core.state",
    "engine.seeds": "engine.core.seeds",
    "engine.rng": "engine.core.rng",
    "engine.modifiers": "engine.core.modifiers",
    "engine.trace": "engine.core.trace",
    "engine.reload": "engine.core.reload",
    "engine.action_intent": "engine.core.action_intent",
    "engine.errors": "engine.core.errors",
    "engine.language": "engine.core.language",
    "engine.content_packs": "engine.core.content_packs",
    "engine.balance": "engine.core.balance",
    "engine.factions": "engine.core.factions",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # skip caches + venv
        dn = set(dirnames)
        for x in [".git", "__pycache__", ".venv", "venv", "node_modules"]:
            if x in dn:
                dirnames.remove(x)
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath) / fn)
    return out


def _rewrite(text: str) -> tuple[str, int]:
    n = 0
    # Replace dotted module paths in import statements. Keep it conservative: only engine.<name> tokens.
    for src, dst in MOVED.items():
        # from engine.mod import ...
        pat_from = re.compile(rf"(^\s*from\s+){re.escape(src)}(\s+import\s+)", re.M)
        text2, c1 = pat_from.subn(rf"\1{dst}\2", text)
        if c1:
            text = text2
            n += c1
        # import engine.mod (possibly with as)
        pat_imp = re.compile(rf"(^\s*import\s+){re.escape(src)}(\s*(?:as\s+\w+)?\s*$)", re.M)
        text2, c2 = pat_imp.subn(rf"\1{dst}\2", text)
        if c2:
            text = text2
            n += c2
        # import engine.mod, engine.other  (simple list)
        pat_imp_list = re.compile(rf"(^\s*import\s+)([^\n#]*\b{re.escape(src)}\b[^\n#]*)(\s*$)", re.M)
        if pat_imp_list.search(text):
            def _fix(m: re.Match) -> str:
                body = m.group(2)
                body = re.sub(rf"\b{re.escape(src)}\b", dst, body)
                return m.group(1) + body + m.group(3)
            text2, c3 = pat_imp_list.subn(_fix, text)
            if c3:
                text = text2
                n += c3
    return text, n


def main() -> int:
    changed_files = 0
    changed_imports = 0
    for p in _iter_py_files():
        try:
            before = p.read_text(encoding="utf-8")
        except Exception:
            continue
        after, n = _rewrite(before)
        if n and after != before:
            p.write_text(after, encoding="utf-8")
            changed_files += 1
            changed_imports += n
    print(f"[refactor_engine_imports] files_changed={changed_files} imports_rewritten={changed_imports}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

