from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.state import initialize_state  # type: ignore  # noqa: E402
from ai.intent_resolver import resolve_intent  # type: ignore  # noqa: E402
from engine.action_intent import parse_action_intent  # type: ignore  # noqa: E402
from engine.modifiers import compute_roll_package  # type: ignore  # noqa: E402
from engine.inventory_ops import apply_inventory_ops  # type: ignore  # noqa: E402


def run() -> None:
    state = initialize_state(
        {
            "name": "IntentSmoke",
            "age": "25",
            "location": "Kota",
            "year": "2025",
            "occupation": "freelancer",
            "background": "tester",
        },
        seed_pack="minimal",
    )
    # Provide 2 weapons for weapon-switch intent tests.
    inv = state.setdefault("inventory", {})
    inv.setdefault("weapons", {})
    inv["weapons"]["p1"] = {"name": "Pistol-1", "kind": "firearm", "ammo": 7, "condition_tier": 2}
    inv["weapons"]["p2"] = {"name": "Pistol-2", "kind": "firearm", "ammo": 6, "condition_tier": 2}
    inv["active_weapon_id"] = "p1"
    # Scene objects nearby for pickup intent tests.
    world = state.setdefault("world", {})
    world.setdefault("nearby_items", [])
    world["nearby_items"] = [{"id": "laptop1", "name": "laptop1"}]
    inv.setdefault("item_sizes", {})["laptop1"] = 5
    inv.setdefault("item_sizes", {})["phone"] = 1

    examples = [
        "aku mau bicara dengan orang sekitar",
        "tanya jam berapa sekarang ke orang yang lewat",
        "coba mencari orang sekitar, cewe terutama nya",
        "aku memaksa orang itu untuk ngomong sekarang",
        "aku menembak orang bersenjata di depan",
        "aku pukul orang yang menghalangi jalan",
        "aku lompat pagar kecil untuk masuk ke halaman",
        "aku cari pintu belakang lalu coba masuk diam-diam lewat jendela",
        "memegang pistol aku mencoba menembakan senjata yang satunya",
        "sedang di kafe dan laptop di meja aku akan balik ke kos",
    ]

    for text in examples:
        print("=== ", text)
        it = resolve_intent(state, text)
        print("intent_resolver:", it)
        ctx = parse_action_intent(text)
        if it:
            for key in (
                "action_type",
                "domain",
                "combat_style",
                "social_mode",
                "social_context",
                "intent_note",
                "targets",
                "stakes",
                "risk_level",
                "inventory_ops",
            ):
                if key in it and it[key] is not None:
                    ctx[key] = it[key]
            if isinstance(it.get("stakes"), str):
                ctx["has_stakes"] = it["stakes"] not in ("none", "low")
                if ctx.get("domain") == "social" and ctx.get("social_mode") == "conflict":
                    ctx["has_stakes"] = True
            if ctx.get("domain") == "combat" and ctx.get("action_type") != "combat":
                ctx["action_type"] = "combat"
                if str(ctx.get("intent_note", "")).strip().lower() not in ("switch_weapon", "equip_weapon_only"):
                    ctx["has_stakes"] = True
        apply_inventory_ops(state, ctx)
        print("action_ctx:", ctx)
        rp = compute_roll_package(state, ctx)
        print("roll_pkg:", rp)
        print()


if __name__ == "__main__":
    run()

