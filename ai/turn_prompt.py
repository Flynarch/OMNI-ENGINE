from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from engine.systems.combat import get_active_weapon


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
        return """OMNI-ENGINE v6.9 — NARRATION LAYER (hybrid).

You are NOT the rules engine. Python already computed: time, economy, inventory, combat gates, rolls, world queues.
Your job: turn [ENGINE], [WORLD BEAT], [ROLL RESULT] into prose inside the XML sections — one coherent moment.

CONTRACT:
- Numbers in CALCULATED STATE / ROLL RESULT are FINAL. Never contradict or recalculate them.
- [PLAYER INPUT] is what the human typed — address that action first.
- If [ENGINE] says combat_blocked or lists triggered events/ripples, the story MUST reflect that (no alternate physics).
- MEMORY_HASH is the continuity channel; keep NPC lines and ripples consistent with [WORLD QUEUE] when possible.
- If travel uses a vehicle (see `vehicle_used` in action_ctx or the vehicle line), narration must reflect the chosen vehicle (noise/visibility), and must not contradict fuel/condition changes recorded by the engine.
- If a pending/triggered event `police_weapon_check` exists, treat it as a focused police stop about weapons: use `country`, `law_level`, `firearm_policy`, and the `dialog` templates (opener / ask_weapon / ask_permit / hint_consequences / reactions) to drive a natural conversation about honesty, weapon permit, and local law — never contradict whether the weapon is illegal in that jurisdiction. If payload includes `permit_doc`, incorporate whether the permit is present/valid/forged into the scene (paper check, doubt, quick glance vs deeper verification).
- If a `police_weapon_check` event triggered a scene (see `active_scene.scene_type=police_stop`), treat it as an interactive stop. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE SAY_NO`, `SCENE SHOW_PERMIT`, `SCENE BRIBE`, `SCENE RUN`). Do not resolve it in narration without player input.
- If a pending/triggered event `safehouse_raid` exists, treat it as an urgent police search of the safehouse: use its `dialog` beats (opener / announce / search / found / outcome_*) and the local `country`/`law_level` context to narrate consequences (confiscation, trace jump, restrictions). Do NOT invent confiscated items that contradict the payload/meta.
- If `safehouse_raid` triggered a scene (see `active_scene.scene_type=raid_response`), treat it as an interactive raid response. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE HIDE`, `SCENE BRIBE 500`, `SCENE FLEE`, `SCENE SHOW_PERMIT`). Do not resolve it in narration without player input.
- If a pending event `safehouse_raid` is scheduled for soon (in [WORLD QUEUE]), explicitly prompt the player with actionable options they can type: `SAFEHOUSE RAID comply`, `SAFEHOUSE RAID hide`, `SAFEHOUSE RAID bribe <amount>`, `SAFEHOUSE RAID flee`.
- If the safehouse was raided recently (see world_notes/news/ripples), remind the player that they can “burn” it: `SAFEHOUSE burn` to abandon it and clear stash.
 - If a pending/triggered event `undercover_sting` exists, treat it as a tense realization that the black-market transaction was monitored (undercover / CCTV / marked bills). It should foreshadow that a police stop can happen moments later; give the player concrete actions (leave calmly, stash, change vehicle, go to safehouse, etc.) without contradicting [ENGINE] outcomes.
 - If `undercover_sting` triggered a scene (see `active_scene.scene_type=sting_setup`), treat it as an interactive immediate-response moment. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE LAY_LOW`, `SCENE DITCH_ITEMS`, `SCENE WALK_AWAY`, `SCENE RUN`). Do not resolve it in narration without player input.
 - If `police_sweep` triggered a scene (see `active_scene.scene_type=checkpoint_sweep`), treat it as an interactive checkpoint moment. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE DETOUR`, `SCENE BRIBE 500`, `SCENE RUN`, `SCENE WAIT`). Do not resolve it in narration without player input.
 - If a travel encounter triggered a scene (`active_scene.scene_type=traffic_stop` or `vehicle_search`), treat it as an interactive roadside stop/search. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE BRIBE 200`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Do not resolve it in narration without player input.
 - If a travel encounter triggered a scene (`active_scene.scene_type=border_control`), treat it as an interactive border/ID checkpoint moment. You MUST only offer commands listed in `active_scene.next_options` (e.g. `SCENE COMPLY`, `SCENE BRIBE 500`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Do not resolve it in narration without player input.
 - If the player uses `INFORMANTS` / `INFORMANT PAY` / `INFORMANT BURN`, treat it as off-screen social maneuvering with contacts. Never invent new informants; only reflect what [ENGINE] outputs and any scheduled events (like `informant_tip` or `npc_report` backlash).
 - If a pending/triggered event `delivery_drop` exists, narrate it as a discreet handoff (dead drop) or brief courier meet. The item should appear as pickupable in `nearby_items` shortly after; remind the player they can `PICKUP <item_id>` (or equivalent) and that loitering increases risk in high-police districts.
 - If a delivery package in `nearby_items` is marked as `decoy` or `sting_on_pickup`, treat it as suspicious (wrong tape, wrong weight, too clean, someone watching). If the engine triggers a police stop afterward, connect the cause-and-effect (pickup → attention).
 - If the world/news mentions `paper_trail` / `Jejak Transaksi` / `CCTV` / `serial cash`, treat it as delayed consequences of a courier-style transaction (not magic). Make it feel like real investigation momentum (cameras, informants, bank logs), and foreshadow increased checks/raids.
 - If `active_scene` exists in [ENGINE], treat it as the primary interaction. You MUST present the current `scene_type`, `phase`, and the authoritative `next_options` as explicit commands the player can type (e.g. `SCENE APPROACH`, `SCENE TAKE`, `SCENE WAIT`). Do NOT invent options outside `next_options`. While a scene is active, do not narrate unrelated long actions as if they happened.

LANGUAGE: All narrative prose inside sections = English. XML tag names stay English. MEMORY_HASH emoji prefixes unchanged.

""" + style_line_en + """

SECTIONS (once each, in order): OMNI_MONITOR, INTERNAL_LOGIC, SENSORY_FEED, EVENT_LOG, INTERACTION_NODE, MEMORY_HASH.
Close every tag. Do not skip sections.
"""
    return """OMNI-ENGINE v6.9 — LAPIS NARASI (hybrid).

Kamu BUKAN mesin aturan. Python sudah menghitung: waktu, ekonomi, inventori, gate combat, roll, antrian dunia.
Tugasmu: jadikan [ENGINE], [BEAT DUNIA], [HASIL ROLL] menjadi prosa di section XML — satu momen utuh.

KONTRAK:
- Angka di CALCULATED STATE / HASIL ROLL bersifat FINAL. Jangan membantah atau menghitung ulang.
- [PLAYER INPUT] adalah perintah pemain — tanggapi tindakan itu dulu.
- Jika [ENGINE] menyebut combat_blocked atau event/ripple terpicu, cerita HARUS selaras (bukan fisika lain).
- MEMORY_HASH adalah saluran kontinuitas; samakan NPC/ripple dengan [ANTREAN DUNIA] bila relevan.
- Jika travel memakai kendaraan (lihat `vehicle_used` di action_ctx atau baris vehicle), narasi wajib menyebut kendaraan itu (suara/visibilitas) dan tidak boleh bertentangan dengan fuel/condition yang sudah diubah engine.
- Jika ada pending/triggered event `police_weapon_check`, anggap itu razia polisi fokus senjata: pakai `country`, `law_level`, `firearm_policy`, dan template `dialog` (opener / ask_weapon / ask_permit / hint_consequences / reaksi) untuk bikin percakapan alami soal kejujuran, weapon permit, dan hukum lokal — jangan pernah bertentangan dengan status senjata (legal/ilegal) di negara itu.
- Jika ada pending/triggered event `police_weapon_check`, anggap itu razia polisi fokus senjata: pakai `country`, `law_level`, `firearm_policy`, dan template `dialog` (opener / ask_weapon / ask_permit / hint_consequences / reaksi) untuk bikin percakapan alami soal kejujuran, weapon permit, dan hukum lokal — jangan pernah bertentangan dengan status senjata (legal/ilegal) di negara itu. Kalau payload punya `permit_doc`, masukkan detailnya (ada/tidak, valid/tidak, terindikasi palsu) sebagai “paper check” yang realistis.
- Kalau `police_weapon_check` memicu scene (lihat `active_scene.scene_type=police_stop`), anggap itu penghentian interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE SAY_NO`, `SCENE SHOW_PERMIT`, `SCENE BRIBE`, `SCENE RUN`). Jangan “menyelesaikan” razia itu di narasi tanpa input pemain.
- Jika ada pending/triggered event `safehouse_raid`, anggap itu penggeledahan safehouse oleh polisi: pakai beat `dialog` (opener / announce / search / found / outcome_*) + konteks `country`/`law_level` untuk narasikan konsekuensi (penyitaan, lonjakan trace, pembatasan area). Jangan mengarang barang yang disita kalau bertentangan dengan payload/meta.
- Kalau `safehouse_raid` memicu scene (lihat `active_scene.scene_type=raid_response`), anggap itu respons razia interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE HIDE`, `SCENE BRIBE 500`, `SCENE FLEE`, `SCENE SHOW_PERMIT`). Jangan “menyelesaikan” razia itu di narasi tanpa input pemain.
- Jika pending event `safehouse_raid` sudah terjadwal dekat (lihat [ANTREAN DUNIA]), minta pemain memilih opsi yang bisa langsung diketik: `SAFEHOUSE RAID comply`, `SAFEHOUSE RAID hide`, `SAFEHOUSE RAID bribe <jumlah>`, `SAFEHOUSE RAID flee`.
- Jika safehouse baru saja digeledah (lihat world_notes/news/ripples), ingatkan bahwa pemain bisa “burn” safehouse: `SAFEHOUSE burn` untuk meninggalkannya dan mengosongkan stash.
 - Jika ada pending/triggered event `undercover_sting`, anggap itu momen tegang saat kamu sadar transaksi black market sedang dipantau (undercover/CCTV/uang bertanda). Ini harus jadi foreshadow bahwa razia/penghentian bisa terjadi sebentar lagi; kasih opsi aksi konkret (jalan santai, ganti rute, stash, ganti kendaraan, masuk safehouse, dll.) tanpa melawan hasil [ENGINE].
 - Kalau `undercover_sting` memicu scene (lihat `active_scene.scene_type=sting_setup`), anggap itu momen respons cepat yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE LAY_LOW`, `SCENE DITCH_ITEMS`, `SCENE WALK_AWAY`, `SCENE RUN`). Jangan “menyelesaikan” sting itu di narasi tanpa input pemain.
 - Kalau `police_sweep` memicu scene (lihat `active_scene.scene_type=checkpoint_sweep`), anggap itu momen checkpoint yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE DETOUR`, `SCENE BRIBE 500`, `SCENE RUN`, `SCENE WAIT`). Jangan “menyelesaikan” sweep itu di narasi tanpa input pemain.
 - Kalau travel memicu scene (lihat `active_scene.scene_type=traffic_stop` atau `vehicle_search`), anggap itu penghentian/pengecekan di jalan yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE BRIBE 200`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Jangan “menyelesaikan” interaksi itu di narasi tanpa input pemain.
 - Kalau travel memicu scene (lihat `active_scene.scene_type=border_control`), anggap itu momen pemeriksaan perbatasan/ID yang interaktif. Kamu WAJIB hanya menawarkan perintah yang ada di `active_scene.next_options` (mis. `SCENE COMPLY`, `SCENE BRIBE 500`, `SCENE CONCEAL <item_id>`, `SCENE DUMP <item_id>`, `SCENE RUN`). Jangan “menyelesaikan” interaksi itu di narasi tanpa input pemain.
 - Kalau pemain pakai `INFORMANTS` / `INFORMANT PAY` / `INFORMANT BURN`, anggap itu manuver sosial off-screen lewat kontak. Jangan mengarang informant baru; cukup refleksikan output [ENGINE] dan event yang terjadwal (mis. `informant_tip` atau backlash `npc_report`).
 - Jika ada pending/triggered event `delivery_drop`, narasikan sebagai serah-terima discreet (dead drop) atau courier meet singkat. Item akan muncul sebagai objek yang bisa dipickup di `nearby_items` beberapa saat kemudian; ingatkan pemain bisa `PICKUP <item_id>` dan bahwa kelamaan nongkrong di distrik polisi tinggi meningkatkan risiko.
 - Jika paket delivery di `nearby_items` ditandai `decoy` atau `sting_on_pickup`, anggap itu mencurigakan (tape beda, berat aneh, terlalu rapi, ada orang ngeliatin). Kalau engine memicu razia setelahnya, jelaskan sebab-akibatnya (pickup → attention).
 - Kalau world/news menyebut `paper_trail` / `Jejak Transaksi` / `CCTV` / `serial cash`, anggap itu konsekuensi tertunda dari transaksi model courier (bukan sihir). Buat terasa seperti investigasi nyata (kamera, informan, log bank), dan foreshadow check/raid yang makin sering.
 - Kalau ada `active_scene` di [ENGINE], anggap itu interaksi utama. Kamu WAJIB menampilkan `scene_type`, `phase`, dan daftar `next_options` (authoritative) sebagai perintah yang bisa diketik pemain (mis. `SCENE APPROACH`, `SCENE TAKE`, `SCENE WAIT`). Jangan mengarang opsi di luar `next_options`. Saat scene aktif, jangan menarasikan aksi panjang lain seolah-olah sudah terjadi.

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


def _fmt_vehicle_line(state: dict[str, Any]) -> str:
    inv = state.get("inventory", {}) or {}
    if not isinstance(inv, dict):
        return "vehicle: (invalid inventory)"
    vid = str(inv.get("active_vehicle_id", "") or "").strip().lower()
    if not vid:
        return "vehicle: (none active)"
    vmap = inv.get("vehicles", {}) if isinstance(inv.get("vehicles"), dict) else {}
    row = vmap.get(vid) if isinstance(vmap, dict) else None
    if not isinstance(row, dict):
        return f"vehicle: active={vid} (missing data)"
    return f"vehicle: active={vid} fuel={int(row.get('fuel', 0) or 0)} cond={int(row.get('condition', 100) or 100)} stolen={bool(row.get('stolen', False))}"


def _fmt_cyber_alert_line(state: dict[str, Any]) -> str:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        if not loc:
            return "cyber_alert: -"
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc)
        ca = slot.get("cyber_alert") if isinstance(slot, dict) else None
        if not isinstance(ca, dict) or not ca:
            return "cyber_alert: (none)"
        return f"cyber_alert: level={ca.get('level',0)}/100 until_day={ca.get('until_day',0)} district={ca.get('district','-')}"
    except Exception:
        return "cyber_alert: (error)"


def _fmt_location_tags(state: dict[str, Any]) -> str:
    try:
        p = state.get("player", {}) or {}
        loc = str(p.get("location", "") or "").strip().lower()
        slot = ((state.get("world", {}) or {}).get("locations", {}) or {}).get(loc) if loc else None
        if isinstance(slot, dict):
            tags = slot.get("tags") or []
            if isinstance(tags, list) and tags:
                return "location_tags: " + ", ".join([str(x) for x in tags[:10]])
    except Exception:
        pass
    return "location_tags: -"


def _fmt_district_line(state: dict[str, Any]) -> str:
    p = state.get("player", {}) or {}
    loc = str(p.get("location", "") or "").strip().lower()
    did = str(p.get("district", "") or "").strip().lower()
    if not (loc and did):
        return "district: -"
    try:
        from engine.world.districts import get_district

        d = get_district(state, loc, did)
        if isinstance(d, dict):
            return (
                f"district: {d.get('name', did)} id={did} crime={d.get('crime_risk','-')}/5 "
                f"police={d.get('police_presence','-')}/5 services={','.join(d.get('services',[]) or [])}"
            )
    except Exception:
        pass
    return f"district: id={did}"


def _fmt_social_rumor_brief(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    """Give the LLM specific rumors/beliefs for the target NPC to reference."""
    if str(action_ctx.get("domain", "") or "") != "social":
        return ""
    targs = action_ctx.get("targets")
    if not (isinstance(targs, list) and targs and isinstance(targs[0], str)):
        return ""
    npc_name = str(targs[0])
    lines: list[str] = []
    # Belief summary (from ripples/news).
    npc = (state.get("npcs", {}) or {}).get(npc_name)
    if isinstance(npc, dict):
        bs = npc.get("belief_summary") or {}
        if isinstance(bs, dict):
            lines.append(f"belief_summary: suspicion={bs.get('suspicion',0)}/100 respect={bs.get('respect',50)}/100")
    # Social diffusion knowledge (gossip memory).
    try:
        from engine.social.social_diffusion import get_npc_knowledge_summary

        k = get_npc_knowledge_summary(state, npc_name)
        if isinstance(k, dict):
            cats = k.get("known_categories") if isinstance(k.get("known_categories"), dict) else {}
            if isinstance(cats, dict) and cats:
                preview = []
                for ck, cv in list(cats.items())[:3]:
                    if isinstance(cv, dict) and cv.get("latest_text"):
                        preview.append(f"{ck}:{str(cv.get('latest_text'))[:80]}")
                if preview:
                    lines.append("rumors_about_player: " + " | ".join(preview))
    except Exception:
        pass
    if not lines:
        return ""
    return "[NPC CONTEXT]\n" + "\n".join(lines)


def _fmt_npc_memories_brief(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    """Inject a small, relevant memory snippet for the target NPC only."""
    targs = action_ctx.get("targets")
    if not (isinstance(targs, list) and targs and isinstance(targs[0], str)):
        return ""
    npc_id = str(targs[0]).strip()
    if not npc_id:
        return ""
    npc = (state.get("npcs", {}) or {}).get(npc_id)
    if not isinstance(npc, dict):
        return ""
    mems = npc.get("memories", [])
    if not isinstance(mems, list) or not mems:
        return ""
    rows = [m for m in mems if isinstance(m, dict) and str(m.get("summary", "") or "").strip()]
    if not rows:
        return ""

    def _score(m: dict[str, Any]) -> tuple[int, int, int]:
        imp = int(m.get("importance", 0) or 0)
        w = m.get("when") if isinstance(m.get("when"), dict) else {}
        d = int((w or {}).get("day", 1) or 1)
        tm = int((w or {}).get("time_min", 0) or 0)
        return (imp, d, tm)

    rows.sort(key=_score, reverse=True)
    top = rows[:3]
    lines: list[str] = []
    for m in top:
        kind = str(m.get("kind", "") or "").strip()
        summ = str(m.get("summary", "") or "").strip()
        if kind:
            lines.append(f"- {kind}: {summ[:120]}")
        else:
            lines.append(f"- {summ[:120]}")
    return "[NPC_MEMORIES]\n" + "\n".join(lines)


def _fmt_npc_beliefs_brief(state: dict[str, Any], action_ctx: dict[str, Any]) -> str:
    targs = action_ctx.get("targets")
    if not (isinstance(targs, list) and targs and isinstance(targs[0], str)):
        return ""
    npc_id = str(targs[0]).strip()
    if not npc_id:
        return ""
    npc = (state.get("npcs", {}) or {}).get(npc_id)
    if not isinstance(npc, dict):
        return ""
    tags = npc.get("belief_tags", [])
    if not isinstance(tags, list) or not tags:
        return ""
    preview = ", ".join([str(x) for x in tags[:5]])
    # Add a narrative anchor hint for consistent tone.
    try:
        from engine.npc.memory import get_narrative_anchor_context

        anchor = get_narrative_anchor_context(state, npc_id)
    except Exception:
        anchor = ""
    if anchor:
        return "[NPC_BELIEFS]\n" + preview + "\n" + anchor
    return "[NPC_BELIEFS]\n" + preview
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
    aim = action_ctx.get("accommodation_intent")
    if isinstance(aim, dict):
        lines.append(f"accommodation_intent=nights={aim.get('nights')} kind_guess={aim.get('kind')}")
    if action_ctx.get("accommodation_auto_applied"):
        lines.append("accommodation_auto_applied=True")
    if action_ctx.get("vehicle_id"):
        lines.append(f"vehicle_id={action_ctx.get('vehicle_id')}")
    if action_ctx.get("vehicle_used"):
        lines.append(f"vehicle_used={action_ctx.get('vehicle_used')}")
    return "\n".join(lines)


def _fmt_accommodation_state(state: dict[str, Any], lang: str) -> str:
    loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
    if not loc:
        return "Prepaid stay (engine): (no location)" if lang == "en" else "Menginap prepaid (engine): (tanpa lokasi)"
    acc = (state.get("world", {}) or {}).get("accommodation", {}) or {}
    row = acc.get(loc) if isinstance(acc, dict) else None
    if not isinstance(row, dict):
        return "Prepaid stay (engine): none at current location" if lang == "en" else "Menginap prepaid (engine): tidak ada di lokasi ini"
    k = str(row.get("kind", "none") or "none")
    if k not in ("hotel", "kos", "suite"):
        return "Prepaid stay (engine): none at current location" if lang == "en" else "Menginap prepaid (engine): tidak ada di lokasi ini"
    return (
        f"Prepaid stay (engine): kind={k} nights_left={row.get('nights_remaining', 0)} rate/night={row.get('rate_per_night', 0)}"
        if lang == "en"
        else f"Menginap prepaid (engine): kind={k} sisa_malam={row.get('nights_remaining', 0)} rate/malam={row.get('rate_per_night', 0)}"
    )


def _fmt_accommodation_policy(action_ctx: dict[str, Any], lang: str) -> str:
    """How NL 'stay one night' relates to engine truth (for the LLM)."""
    if str(action_ctx.get("intent_note", "") or "") != "accommodation_stay":
        return ""
    if action_ctx.get("accommodation_auto_applied"):
        if lang == "en":
            return (
                "[ACCOMMODATION — NL vs ENGINE]\n"
                "Engine already applied prepaid stay this turn (OMNI_AUTO_STAY_INTENT). "
                "Narration must match `Prepaid stay (engine)` and updated cash in [CALCULATED STATE]."
            )
        return (
            "[AKOMODASI — bahasa vs ENGINE]\n"
            "Engine sudah menerapkan prepaid stay di turn ini (OMNI_AUTO_STAY_INTENT). "
            "Narasi harus selaras dengan `Menginap prepaid (engine)` dan cash di [CALCULATED STATE]."
        )
    if lang == "en":
        return (
            "[ACCOMMODATION — NL vs ENGINE]\n"
            "Player wording may imply booking a room for the night. Narrate check-in, keycard, room, noise, etc. freely.\n"
            "ECONOMY TRUTH: prepaid nights and cash only change when the engine applies `STAY <hotel|boarding|suite> <nights>` "
            "(or equivalent). If `Prepaid stay (engine)` shows no nights but the player describes paying, treat it as intent/planning "
            "unless you explicitly align with state, or mention they still need to complete payment in-system.\n"
            "Tier hints: boarding = budget/shared (ID: kost); hotel; suite = luxury."
        )
    return (
        "[AKOMODASI — bahasa vs ENGINE]\n"
        "Narasi boleh gambarkan check-in, kunci kamar, suara lorong, dll.\n"
        "FAKTA EKONOMI: malam prepaid & uang hanya berubah lewat engine (`STAY hotel|boarding|suite <n>`). "
        "Kalau teks pemain seperti bayar tapi `Menginap prepaid (engine)` kosong, anggap rencana/roleplay kecuali diselaraskan dengan state.\n"
        "Tier: boarding = murah/berbagi (kost); hotel; suite = mewah."
    )


def _fmt_weapon_line(state: dict[str, Any]) -> str:
    inv = state.get("inventory", {})
    flags = state.get("flags", {}) or {}
    w = get_active_weapon(inv)
    if not isinstance(w, dict):
        return "active_weapon: (none / unarmed)"
    mag = w.get("mag_capacity", "-")
    jam = bool(w.get("jammed")) or bool(flags.get("weapon_jammed"))
    aid = str(w.get("ammo_item_id", "") or "").strip()
    res_txt = ""
    if aid:
        iq = inv.get("item_quantities") if isinstance(inv.get("item_quantities"), dict) else {}
        if isinstance(iq, dict):
            res_txt = f" reserve_{aid}={int(iq.get(aid, 0) or 0)}"
    return (
        f"active_weapon kind={w.get('kind', '?')} ammo={w.get('ammo', '-')}/{mag} "
        f"jammed={jam} tier={w.get('condition_tier', '?')} id={inv.get('active_weapon_id') or 'legacy'}{res_txt}"
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


def _fmt_economy_detail(state: dict[str, Any], lang: str) -> str:
    eco = state.get("economy", {}) or {}
    debt = int(eco.get("debt", 0) or 0)
    aml = str(eco.get("aml_status", "CLEAR") or "CLEAR")
    thr = int(eco.get("aml_threshold", 10000) or 10000)
    if lang == "en":
        return f"Economy extra: debt={debt} | aml={aml} | aml_threshold={thr}"
    return f"Ekonomi tambahan: debt={debt} | aml={aml} | aml_threshold={thr}"


def _fmt_engine_recent_commerce(state: dict[str, Any], lang: str) -> str:
    notes = state.get("world_notes") or []
    if not isinstance(notes, list):
        return ""
    hits = [str(x) for x in notes[-14:] if isinstance(x, str) and ("[Shop]" in x or "[Bank]" in x or "[Stay]" in x)]
    if not hits:
        return ""
    tail = " | ".join(hits[-4:])
    if lang == "en":
        return f"Recent commerce (engine notes): {tail}"
    return f"Transaksi terkini (engine): {tail}"


def _fmt_skills_engine(state: dict[str, Any], lang: str) -> str:
    sk = state.get("skills", {}) or {}
    if not isinstance(sk, dict) or not sk:
        return "Skills (engine): (none)" if lang == "en" else "Skill (engine): (belum ada)"
    parts: list[str] = []
    for k in ("hacking", "social", "combat", "stealth", "evasion", "medical", "driving", "languages"):
        row = sk.get(k)
        if isinstance(row, dict):
            parts.append(f"{k} L{row.get('level', 1)} cur={row.get('current', row.get('base', 10))}")
    if not parts:
        return "Skills (engine): (none)" if lang == "en" else "Skill (engine): (belum ada)"
    return ("Skills (engine): " if lang == "en" else "Skill (engine): ") + "; ".join(parts[:8])


def _fmt_weather_engine(state: dict[str, Any], lang: str) -> str:
    try:
        from engine.world.weather import ensure_weather

        loc = str((state.get("player", {}) or {}).get("location", "") or "").strip().lower()
        day = int((state.get("meta", {}) or {}).get("day", 1) or 1)
        if not loc:
            return "Weather (engine): (no location)" if lang == "en" else "Cuaca (engine): (tanpa lokasi)"
        w = ensure_weather(state, loc, day)
        k = str((w or {}).get("kind", "-") or "-")
        return f"Weather (engine) @ {loc}: {k}" if lang == "en" else f"Cuaca (engine) @ {loc}: {k}"
    except Exception:
        return "Weather (engine): -" if lang == "en" else "Cuaca (engine): -"


def _fmt_disguise_engine(state: dict[str, Any], lang: str) -> str:
    d = (state.get("player", {}) or {}).get("disguise") or {}
    if not isinstance(d, dict) or not d.get("active"):
        return "Disguise (engine): inactive" if lang == "en" else "Disguise (engine): tidak aktif"
    if lang == "en":
        return (
            f"Disguise (engine): ACTIVE persona={d.get('persona', '?')} until D{d.get('until_day', '?')} "
            f"t={d.get('until_time', 0)} risk={d.get('risk', 0)}"
        )
    return (
        f"Disguise (engine): AKTIF persona={d.get('persona', '?')} sampai D{d.get('until_day', '?')} "
        f"t={d.get('until_time', 0)} risk={d.get('risk', 0)}"
    )


def _fmt_language_engine(state: dict[str, Any], lang: str) -> str:
    try:
        from engine.core.language import communication_quality

        lc = communication_quality(state, {"domain": "social", "normalized_input": "narration snapshot"})
        if lang == "en":
            return (
                f"Language barrier (engine): local={lc.local_lang} shared={lc.shared} "
                f"translator={lc.translator_level} quality={lc.quality} roll_penalty={lc.penalty}"
            )
        return (
            f"Hambatan bahasa (engine): lokal={lc.local_lang} shared={lc.shared} "
            f"translator={lc.translator_level} quality={lc.quality} penalty_roll={lc.penalty}"
        )
    except Exception:
        return "Language barrier (engine): -"


def _fmt_safehouse_engine(state: dict[str, Any], lang: str) -> str:
    try:
        from engine.systems.safehouse import ensure_safehouse_here

        row = ensure_safehouse_here(state)
        st = str(row.get("status", "none") or "none")
        sec = int(row.get("security_level", 1) or 1)
        if lang == "en":
            return f"Safehouse (engine): status={st} security=L{sec} delinquent={row.get('delinquent_days', 0)}"
        return f"Safehouse (engine): status={st} security=L{sec} tunggakan_hari={row.get('delinquent_days', 0)}"
    except Exception:
        return ""


def _fmt_npc_combat_brief(state: dict[str, Any], lang: str) -> str:
    npcs = state.get("npcs", {}) or {}
    if not isinstance(npcs, dict):
        return ""
    lines: list[str] = []
    for name, data in list(npcs.items())[:14]:
        if not isinstance(data, dict):
            continue
        pur = data.get("pursuit_until_day")
        posture = data.get("combat_posture")
        mor = data.get("combat_morale")
        if pur or posture or mor is not None:
            lines.append(f"- {name}: morale={mor} posture={posture} pursuit_until_day={pur}")
    if not lines:
        return ""
    head = "NPC combat AI (engine):" if lang == "en" else "NPC AI tempur (engine):"
    return head + "\n" + "\n".join(lines)


def _fmt_narration_sync_hint(lang: str) -> str:
    if lang == "en":
        return (
            "[NARRATION SYNC — use ENGINE facts]\n"
            "Naturally reflect: economy (cash/bank/debt/FICO/AML), recent Shop/Bank/Stay notes, prepaid stay, "
            "skills, weather, disguise, language barrier, NPC pursuit/surrender lines, safehouse if relevant."
        )
    return (
        "[SINKRON NARASI — pakai fakta ENGINE]\n"
        "Cerminkan: ekonomi (cash/bank/debt/FICO/AML), catatan Shop/Bank/Stay, menginap prepaid, skill, cuaca, "
        "disguise, hambatan bahasa, garis NPC kejar/menyerah, safehouse bila relevan."
    )


def _dialogue_contract(action_ctx: dict[str, Any], lang: str) -> str:
    if action_ctx.get("domain") != "social":
        return ""
    note = action_ctx.get("intent_note", "")
    if note == "intimacy_private":
        if lang == "en":
            return """[INTIMACY — FADE-TO-BLACK]
- The physical act is OFF-SCREEN. Do not write graphic sexual detail; imply time passing, then aftermath only.
- After the fade: mood, tenderness, awkwardness, or distance must align with [INTIMACY SUMMARY] and the social roll outcome.
- Post-fade dialogue is allowed if non-explicit. Respect consent + CALCULATED STATE.
"""
        return """[INTIMACY — FADE-TO-BLACK]
- Adegan fisik OFF-SCREEN; tanpa detail grafis; cukup implikasi + lompatan waktu, lalu sesudahnya.
- Setelah fade: suasana harus selaras dengan [INTIMACY SUMMARY] dan outcome roll sosial.
- Dialog sesudah fade boleh selama non-eksplisit. Hormati konsensualitas + CALCULATED STATE.
"""
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


def _fmt_turn_facts_delta(state: dict[str, Any], lang: str) -> str:
    """Compact deltas for the narrator: economy/trace/time/skill/commerce vs repeating full CALCULATED STATE."""
    meta = state.get("meta", {}) or {}
    d = meta.get("last_turn_diff")
    audit = meta.get("last_turn_audit")
    parts: list[str] = []
    if isinstance(d, dict):
        for k in ("cash", "bank", "debt", "trace"):
            try:
                dv = int(d.get(k, 0) or 0)
            except Exception:
                dv = 0
            if dv != 0:
                parts.append(f"{k}{dv:+d}")
        try:
            tel = int(d.get("time_elapsed_min", 0) or 0)
        except Exception:
            tel = 0
        if tel != 0:
            parts.append(f"time_elapsed={tel}m")
        xp = d.get("xp_delta")
        if isinstance(xp, dict):
            for sk in ("hacking", "social", "combat", "stealth", "evasion"):
                try:
                    xv = int(xp.get(sk, 0) or 0)
                except Exception:
                    xv = 0
                if xv != 0:
                    parts.append(f"xp.{sk}={xv:+d}")
        for fk in ("att_police", "att_corporate", "att_black_market"):
            ch = d.get(fk)
            if isinstance(ch, dict) and ch.get("from") != ch.get("to"):
                parts.append(f"{fk}:{ch.get('from')}→{ch.get('to')}")
        try:
            nac = int(d.get("notes_added_count", 0) or 0)
        except Exception:
            nac = 0
        if nac > 0:
            parts.append(f"world_notes+{nac}")
    if isinstance(audit, dict):
        cn = audit.get("commerce_notes")
        if isinstance(cn, list) and cn:
            joined = " | ".join(str(x) for x in cn[:5])
            if len(joined) > 320:
                joined = joined[:317] + "..."
            parts.append("commerce: " + joined)
    if not parts:
        return ""
    title = "[FACTS CHANGED THIS TURN — use for prose, do not contradict CALCULATED STATE below]" if lang == "en" else "[FAKTA BERUBAH TURN INI — untuk prosa; jangan bentrok dengan CALCULATED STATE di bawah]"
    return title + "\n" + " | ".join(parts)


def _fmt_intimacy_summary(state: dict[str, Any], lang: str) -> str:
    meta = state.get("meta", {}) or {}
    il = meta.get("intimacy_last")
    if not isinstance(il, dict):
        return ""
    try:
        cur_turn = int(meta.get("turn", 0) or 0)
        if int(il.get("turn", -1) or -1) != cur_turn:
            return ""
    except Exception:
        return ""
    partner = str(il.get("partner", "") or "-")
    try:
        sat = int(il.get("satisfaction", 0) or 0)
    except Exception:
        sat = 0
    tier = str(il.get("tier", "") or "")
    if lang == "en":
        return (
            f"[INTIMACY SUMMARY — engine, this turn]\n"
            f"partner={partner} satisfaction_roll={sat}/100 tier={tier} (use for emotional aftermath only; fade explicit acts)"
        )
    return (
        f"[INTIMACY SUMMARY — engine, turn ini]\n"
        f"partner={partner} satisfaction_roll={sat}/100 tier={tier} (untuk suasana sesudah fade; adegan eksplisit tidak ditulis)"
    )


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

    return f"""[TURN PACKAGE - OMNI-ENGINE v6.9]
[NARRATION LANGUAGE]
{lang_label} (code={lang})
[PLAYER INPUT]
{player_input}
{eng_title}
{_fmt_meta_clock(state)}
{_fmt_player_card(state)}
{_fmt_location_tags(state)}
{_fmt_district_line(state)}
{_fmt_accommodation_state(state, lang)}
{_fmt_turn_facts_delta(state, lang)}
{_fmt_economy_detail(state, lang)}
{_fmt_engine_recent_commerce(state, lang)}
{_fmt_skills_engine(state, lang)}
{_fmt_weather_engine(state, lang)}
{_fmt_disguise_engine(state, lang)}
{_fmt_safehouse_engine(state, lang)}
{_fmt_vehicle_line(state)}
{_fmt_cyber_alert_line(state)}
{_fmt_language_engine(state, lang)}
{_fmt_intimacy_summary(state, lang)}
{_fmt_npc_combat_brief(state, lang)}
{_fmt_action_ctx(action_ctx)}
{_fmt_accommodation_policy(action_ctx, lang)}
{_fmt_narration_sync_hint(lang)}
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
{_fmt_social_rumor_brief(state, action_ctx)}
{_fmt_npc_beliefs_brief(state, action_ctx)}
{_fmt_npc_memories_brief(state, action_ctx)}
[CALCULATED STATE]
Blood: {bio.get('blood_volume', 5.0)}L / {bio.get('blood_max', 5.0)}L | BP: {bio.get('bp_state', 'Stable')}
Sleep Debt: {bio.get('sleep_debt', 0)}h | Infection: {bio.get('infection_pct', 0)}%
Burnout: {bio.get('burnout', 0)}/10 | Sanity Debt: {bio.get('sanity_debt', 0)}
Cash: {eco.get('cash', 0)} | Bank: {eco.get('bank', 0)} | Debt: {eco.get('debt', 0)} | Daily Burn: {eco.get('daily_burn', 0)}
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
