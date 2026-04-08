from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from engine.combat import get_active_weapon


def get_narration_lang(state: dict[str, Any]) -> str:
    load_dotenv()
    env = os.getenv("NARRATION_LANG", "").strip().lower()
    if env in ("id", "en"):
        return env
    if env in ("indonesia", "ina"):
        return "id"
    if env in ("english", "inggris"):
        return "en"
    raw = str(state.get("player", {}).get("language", "id")).strip().lower()
    if raw in ("en", "english", "inggris"):
        return "en"
    return "id"


def build_system_prompt(state: dict[str, Any]) -> str:
    lang = get_narration_lang(state)
    style = str(state.get("player", {}).get("narration_style", "cinematic") or "cinematic").strip().lower()
    style_line_en = "STYLE: COMPACT (short, dense, minimal) ." if style == "compact" else "STYLE: CINEMATIC (more sensory detail, but still consistent)."
    style_line_id = "GAYA: COMPACT (singkat, padat, minim) ." if style == "compact" else "GAYA: CINEMATIC (lebih imersif, namun tetap konsisten & tidak bertele-tele)."
    if lang == "en":
        return """OMNI-ENGINE v6.8 — NARRATION LAYER (hybrid).

You are NOT the rules engine. Python already computed: time, economy, inventory, combat gates, rolls, world queues.
Your job: turn [ENGINE], [WORLD BEAT], [ROLL RESULT] into prose inside the XML sections — one coherent moment.

CONTRACT:
- Numbers in CALCULATED STATE / ROLL RESULT are FINAL. Never contradict or recalculate them.
- [PLAYER INPUT] is what the human typed — address that action first.
- If [ENGINE] says combat_blocked or lists triggered events/ripples, the story MUST reflect that (no alternate physics).
- MEMORY_HASH is the continuity channel; keep NPC lines and ripples consistent with [WORLD QUEUE] when possible.

LANGUAGE: All narrative prose inside sections = English. XML tag names stay English. MEMORY_HASH emoji prefixes unchanged.

""" + style_line_en + """

SECTIONS (once each, in order): OMNI_MONITOR, INTERNAL_LOGIC, SENSORY_FEED, EVENT_LOG, INTERACTION_NODE, MEMORY_HASH.
Close every tag. Do not skip sections.
"""
    return """OMNI-ENGINE v6.8 — LAPIS NARASI (hybrid).

Kamu BUKAN mesin aturan. Python sudah menghitung: waktu, ekonomi, inventori, gate combat, roll, antrian dunia.
Tugasmu: jadikan [ENGINE], [BEAT DUNIA], [HASIL ROLL] menjadi prosa di section XML — satu momen utuh.

KONTRAK:
- Angka di CALCULATED STATE / HASIL ROLL bersifat FINAL. Jangan membantah atau menghitung ulang.
- [PLAYER INPUT] adalah perintah pemain — tanggapi tindakan itu dulu.
- Jika [ENGINE] menyebut combat_blocked atau event/ripple terpicu, cerita HARUS selaras (bukan fisika lain).
- MEMORY_HASH adalah saluran kontinuitas; samakan NPC/ripple dengan [ANTREAN DUNIA] bila relevan.

BAHASA: Semua prosa narasi dalam section = Bahasa Indonesia natural. Nama tag XML tetap Inggris. Prefix emoji MEMORY_HASH jangan diganti.

""" + style_line_id + """

SECTION (masing-masing sekali, berurutan): OMNI_MONITOR, INTERNAL_LOGIC, SENSORY_FEED, EVENT_LOG, INTERACTION_NODE, MEMORY_HASH.
Tutup setiap tag. Jangan lompat section.
"""


def _fmt_mods(mods: list[tuple[str, int]]) -> str:
    if not mods:
        return "-"
    return " | ".join([f"{k}: {v:+d}%" for k, v in mods])


def _fmt_meta_clock(state: dict[str, Any]) -> str:
    meta = state.get("meta", {})
    day = int(meta.get("day", 1))
    tm = int(meta.get("time_min", 0))
    h, m = tm // 60, tm % 60
    return f"Day {day} {h:02d}:{m:02d} | meta.turn={meta.get('turn', 0)}"


def _fmt_player_card(state: dict[str, Any]) -> str:
    p = state.get("player", {})
    return (
        f"name={p.get('name', '?')} | loc={p.get('location', '-')} | year={p.get('year', '-')} | "
        f"job={p.get('occupation', '-')} | seed={state.get('meta', {}).get('seed_pack', '-')}"
    )

def _fmt_social_stats(state: dict[str, Any]) -> str:
    stats = state.get("player", {}).get("social_stats", {}) or {}
    if not isinstance(stats, dict):
        return "social_stats: (invalid)"
    return (
        "social_stats "
        f"looks={int(stats.get('looks', 0) or 0)} "
        f"outfit={int(stats.get('outfit', 0) or 0)} "
        f"hygiene={int(stats.get('hygiene', 0) or 0)} "
        f"speaking={int(stats.get('speaking', 0) or 0)}"
    )


def _fmt_action_ctx(action_ctx: dict[str, Any]) -> str:
    lines = [
        f"action_type={action_ctx.get('action_type', 'instant')}",
        f"domain={action_ctx.get('domain', 'evasion')}",
    ]
    if action_ctx.get("combat_style"):
        lines.append(f"combat_style={action_ctx['combat_style']}")
    if action_ctx.get("combat_blocked"):
        lines.append(f"combat_blocked={action_ctx['combat_blocked']}")
    if action_ctx.get("intent_note"):
        lines.append(f"intent_note={action_ctx['intent_note']}")
    if action_ctx.get("social_context"):
        lines.append(f"social_context={action_ctx['social_context']}")
    if action_ctx.get("social_mode"):
        lines.append(f"social_mode={action_ctx['social_mode']}")
    if action_ctx.get("stakes"):
        lines.append(f"stakes={action_ctx['stakes']}")
    if action_ctx.get("time_cost_min") is not None:
        tcm = action_ctx.get("time_cost_min")
        if isinstance(tcm, (int, float, str)) and str(tcm).strip() != "":
            lines.append(f"time_cost_min={tcm}")
    ama = action_ctx.get("auto_micro_actions")
    if isinstance(ama, list) and ama:
        preview = " | ".join([str(x) for x in ama[:6]])
        lines.append(f"auto_micro_actions={preview}")
    if action_ctx.get("attempt_clear_jam"):
        lines.append("attempt_clear_jam=True")
    return "\n".join(lines)


def _fmt_weapon_line(state: dict[str, Any]) -> str:
    inv = state.get("inventory", {})
    w = get_active_weapon(inv)
    if not isinstance(w, dict):
        return "active_weapon: (none / unarmed)"
    return (
        f"active_weapon kind={w.get('kind', '?')} ammo={w.get('ammo', '-')} "
        f"tier={w.get('condition_tier', '?')} id={inv.get('active_weapon_id') or 'legacy'}"
    )


def _fmt_beat_this_turn(state: dict[str, Any], lang: str) -> str:
    trig = state.get("triggered_events_this_turn") or []
    surf = state.get("surfacing_ripples_this_turn") or []
    if not trig and not surf:
        return "(none)" if lang == "en" else "(tidak ada event/ripple baru di beat ini)"
    parts: list[str] = []
    for e in trig[:6]:
        parts.append(f"- event: {e.get('title', e.get('event_type', '?'))}")
    for r in surf[:6]:
        parts.append(f"- ripple: {r.get('text', '?')}")
    return "\n".join(parts)


def _fmt_queues(state: dict[str, Any], lang: str) -> str:
    pe = state.get("pending_events") or []
    ar = state.get("active_ripples") or []
    lines: list[str] = []
    for e in pe[:5]:
        lines.append(
            f"- pending_event: {e.get('title', e.get('event_type', '?'))} "
            f"@day{e.get('due_day', '?')} t{e.get('due_time', '?')}"
        )
    if not lines and lang == "id":
        lines.append("(tidak ada pending_event terjadwal)")
    elif not lines:
        lines.append("(no pending_event)")
    lines.append("--- ripples (belum surface) ---")
    for r in ar[:5]:
        lines.append(f"- ripple: {r.get('text', '?')} → surface day {r.get('surface_day', '?')}")
    if len(ar) == 0:
        lines.append("(empty)" if lang == "en" else "(kosong)")
    return "\n".join(lines)


def _fmt_npcs(state: dict[str, Any]) -> str:
    npcs = state.get("npcs") or {}
    if not isinstance(npcs, dict) or not npcs:
        return "(no NPCs in state)"
    out: list[str] = []
    for name, data in list(npcs.items())[:12]:
        if not isinstance(data, dict):
            continue
        lbl = data.get("disposition_label", "?")
        sc = data.get("disposition_score", "?")
        out.append(f"- {name}: [{lbl}] score={sc} {data.get('role', '')}".strip())
    return "\n".join(out)


def _fmt_world_notes(state: dict[str, Any]) -> str:
    notes = state.get("world_notes") or []
    if not notes:
        return "(empty)"
    tail = notes[-6:] if isinstance(notes, list) else []
    return "\n".join(f"- {n}" for n in tail)


def _dialogue_contract(action_ctx: dict[str, Any], lang: str) -> str:
    if action_ctx.get("domain") != "social":
        return ""
    note = action_ctx.get("intent_note", "")
    if note not in ("social_dialogue", "social_scan_crowd", "social_inquiry"):
        return ""
    if lang == "en":
        return """[DIALOGUE CONTRACT]
- Put at least one spoken line (quoted dialogue) from a passerby or NPC in SENSORY_FEED or INTERACTION_NODE.
- On Failure: awkward / dismissed / too busy — NOT "nobody exists anywhere".
- If the NPC list is non-empty, use those names as speakers.
"""
    return """[KONTRAK DIALOG]
- Wajib ada minimal satu ucapan orang (boleh pakai tanda kutip) di SENSORY_FEED atau INTERACTION_NODE.
- Jika Outcome Failure: canggung/diabaikan/orang buru-buru — BUKAN 'tidak ada manusia sama sekali'.
- Jika daftar NPC tidak kosong, gunakan nama itu sebagai pembicara.
"""


def _roll_reason_line(roll_pkg: dict[str, Any], lang: str) -> str:
    oc = str(roll_pkg.get("outcome", ""))
    if "Social Non-Conflict" in oc:
        return "Social non-conflict → no roll" if lang == "en" else "Kontak sosial non-konflik → tanpa roll"
    if "Low stakes" in oc:
        return "Low stakes → no roll" if lang == "en" else "Taruhan rendah → tanpa roll"
    if "No Roll" in oc and "Trivial" not in oc:
        return "No roll" if lang == "en" else "Tanpa roll"
    if "Trivial" in oc:
        return "Trivial → no roll" if lang == "en" else "Trivial → tanpa roll"
    if "Impossible" in oc:
        return "Impossible → auto fail" if lang == "en" else "Mustahil → auto gagal"
    if "CC Gate" in oc:
        return "CC gate → auto fail" if lang == "en" else "Gate CC → auto gagal"
    if "Auto Fail" in oc or "Combat blocked" in oc:
        return oc
    return "Uncertain + stakes" if lang == "en" else "Tak pasti + ada taruhan"


def build_turn_package(
    state: dict[str, Any],
    player_input: str,
    roll_pkg: dict[str, Any],
    action_ctx: dict[str, Any] | None = None,
) -> str:
    action_ctx = action_ctx or {}
    bio = state.get("bio", {})
    eco = state.get("economy", {})
    tr = state.get("trace", {})
    flags = state.get("flags", {})
    world = state.get("world", {}) or {}
    nearby = world.get("nearby_items", []) or []
    nearby_str = "-"
    if isinstance(nearby, list) and nearby:
        labels: list[str] = []
        for x in nearby[:10]:
            if isinstance(x, dict):
                labels.append(str(x.get("id", x.get("name", "-"))))
            else:
                labels.append(str(x))
        nearby_str = ", ".join(labels)
    lang = get_narration_lang(state)
    lang_label = "Bahasa Indonesia" if lang == "id" else "English"

    eng_title = "[ENGINE — single source for this turn]" if lang == "en" else "[ENGINE — sumber kebenaran turn ini]"
    beat_title = "[WORLD BEAT — resolved this turn]" if lang == "en" else "[BEAT DUNIA — terjadi di turn ini]"
    queue_title = "[WORLD QUEUE — background]" if lang == "en" else "[ANTREAN DUNIA — latar]"
    npc_title = "[NPCs — snapshot]" if lang == "en" else "[NPC — cuplikan]"

    return f"""[TURN PACKAGE - OMNI-ENGINE v6.8]
[NARRATION LANGUAGE]
{lang_label} (code={lang})
[PLAYER INPUT]
{player_input}
{eng_title}
{_fmt_meta_clock(state)}
{_fmt_player_card(state)}
{_fmt_action_ctx(action_ctx)}
{_fmt_weapon_line(state)}
{_fmt_social_stats(state)}
flags: weapon_jammed={flags.get('weapon_jammed')} stop_seq={flags.get('stop_sequence_active')}
{beat_title}
{_fmt_beat_this_turn(state, lang)}
{queue_title}
{_fmt_queues(state, lang)}
{npc_title}
{_fmt_npcs(state)}
Recent world_notes:
{_fmt_world_notes(state)}
[CALCULATED STATE]
Blood: {bio.get('blood_volume', 5.0)}L / {bio.get('blood_max', 5.0)}L | BP: {bio.get('bp_state', 'Stable')}
Sleep Debt: {bio.get('sleep_debt', 0)}h | Infection: {bio.get('infection_pct', 0)}%
Burnout: {bio.get('burnout', 0)}/10 | Sanity Debt: {bio.get('sanity_debt', 0)}
Cash: {eco.get('cash', 0)} | Bank: {eco.get('bank', 0)} | Daily Burn: {eco.get('daily_burn', 0)}
FICO: {eco.get('fico', 600)} | AML: {eco.get('aml_status', 'CLEAR')}
Trace: {tr.get('trace_pct', 0)}% [{tr.get('trace_status', 'Ghost')}]
CC: {state.get('player', {}).get('cc', 0)} | Econ tier: {state.get('player', {}).get('econ_tier', '-')} | Hygiene Tax: {bio.get('hygiene_tax_active', False)}
Acute Stress: {bio.get('acute_stress', False)} | Stop Sequence: {flags.get('stop_sequence_active', False)}
Hallucination: {bio.get('hallucination_type', 'none')} | Narrator Drift: {bio.get('narrator_drift_state', 'stable')}
Permanent Damage: {state.get('permanent_damage_summary', '-')}
NearbyItems: {nearby_str}
[FACTIONS]
corp st={state.get('world', {}).get('factions', {}).get('corporate', {}).get('stability', '-')} pw={state.get('world', {}).get('factions', {}).get('corporate', {}).get('power', '-')} att={state.get('world', {}).get('faction_statuses', {}).get('corporate', '-')}
police st={state.get('world', {}).get('factions', {}).get('police', {}).get('stability', '-')} pw={state.get('world', {}).get('factions', {}).get('police', {}).get('power', '-')} att={state.get('world', {}).get('faction_statuses', {}).get('police', '-')}
black st={state.get('world', {}).get('factions', {}).get('black_market', {}).get('stability', '-')} pw={state.get('world', {}).get('factions', {}).get('black_market', {}).get('power', '-')} att={state.get('world', {}).get('faction_statuses', {}).get('black_market', '-')}
[MODIFIER STACK]
{_fmt_mods(roll_pkg.get('mods', []))}
NET THRESHOLD: {roll_pkg.get('net_threshold', 0)}%
[ROLL RESULT]
Roll: {roll_pkg.get('roll', 'N/A')} / 100 vs {roll_pkg.get('net_threshold', 0)}%
Outcome: {roll_pkg.get('outcome', 'No Roll')}
Reason: {_roll_reason_line(roll_pkg, lang)}
ThresholdLocked: {roll_pkg.get('net_threshold_locked', True)}
[ACTIVE CONSTRAINTS]
Stop Sequence: {flags.get('stop_sequence_active', False)}
Stop Trigger: {flags.get('stop_sequence_trigger', '')}
Hand Slot Issue: {flags.get('hand_slot_issue', False)}
Weapon Jam: {flags.get('weapon_jammed', False)}
Equip Cost: {flags.get('equip_cost_active', False)}
Hallucination Active: {flags.get('hallucination_active', False)}
{_dialogue_contract(action_ctx, lang)}
[OUTPUT FORMAT - STRICT — tag names fixed]
<OMNI_MONITOR>...</OMNI_MONITOR>
<INTERNAL_LOGIC>...</INTERNAL_LOGIC>
<SENSORY_FEED>...</SENSORY_FEED>
<EVENT_LOG>...</EVENT_LOG>
<INTERACTION_NODE>...</INTERACTION_NODE>
<MEMORY_HASH>
🎯 ...
📜 ...
🤝 ...
🏷 ...
📍 ...
🩺 ...
🩻 ...
⏰ ...
💬 ...
🌊 ...
⚡ ...
📊 ...
🎓 ...
📚 ...
</MEMORY_HASH>
[YOUR TASK]
{f'Fill every section. Narration in {lang_label}. Respect ENGINE + WORLD BEAT + ROLL; do not invent conflicting facts.' if lang == 'en' else f'Isi semua section. Narasi {lang_label}. Hormati ENGINE + BEAT DUNIA + ROLL; jangan mengarang fakta yang bentrok.'}
"""
