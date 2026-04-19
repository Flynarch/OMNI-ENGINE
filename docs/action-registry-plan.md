# Action Registry — rencana arsitektur (data-driven intent)

## Tujuan

Menggantikan rantai `if / elif` tanpa akhir di `parse_action_intent` dengan model:

**Input pemain (NL)** → **satu `action_id` terdaftar** + **parameter** → **engine Python** mengeksekusi mekanik → **AI** hanya menarasikan.

Yang _tidak_ berubah: **Python memegang kebenaran** (RNG, state, roll); AI tidak memutuskan hasil.

## Status sinkron dengan repo (ringkas)

| Area                                  | Kode utama                                                                                                                                                                                                                                                      | Catatan                                                                    |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Loader + JSON                         | `data/action_registry/registry_v1.json`, `action_registry.py`                                                                                                                                                                                                   | Cache setelah load.                                                        |
| Combat NL                             | `_registry_try_combat` + `_registry_try_combat_keyword_fallback`                                                                                                                                                                                                | Sinonim dari JSON; tanpa `elif combat_terms`.                              |
| Hedge NL                              | `instant.nl_hedge_uncertainty` + `_registry_apply_nl_hedge_flags`                                                                                                                                                                                               | Keyword di JSON; boleh overlay trivial.                                    |
| Tidur jam / default                   | `sleep.nl_duration_hours` + `parse_sleep_hours_from_nl`                                                                                                                                                                                                         | Handler di `action_registry_handlers`.                                     |
| Akomodasi (hotel semalam)             | `economy.nl_accommodation_stay` + `parse_accommodation_intent_from_nl`                                                                                                                                                                                          | Handler `apply_accommodation_nl`.                                          |
| Smartphone (telepon/SMS/dark web)     | `other.nl_smartphone_w2` + `try_parse_smartphone_nl`                                                                                                                                                                                                            | Regex di handlers.                                                         |
| Travel                                | `_registry_try_travel` + `_registry_try_travel_keyword_fallback`                                                                                                                                                                                                | Keyword + heuristik menit/destinasi/kendaraan: `_apply_travel_heuristics`. |
| Skill domain                          | `_registry_try_skill_domain` + `_registry_first_keywords_any_hit_apply` (urutan `hacking` → `medical` → `driving` → `stealth`)                                                                                                                                  | Satu sumber keyword: JSON.                                                 |
| Sosial                                | `match_registry_action_prefixed("social.")` + fallback `social.nl_dialogue` / `social.nl_scan_crowd` + suplemen `cari` + `_PEOPLE_WORDS` untuk scan                                                                                                             |                                                                            |
| Negosiasi                             | `social.nl_negotiation` memakai `match.keywords_any` di JSON; menang lewat `_registry_try_social_nl` (prioritas 48)                                                                                                                                             | Tanpa `elif` khusus di Python.                                             |
| Konflik ke orang                      | `social.nl_conflict` + `get_registry_action_by_id`                                                                                                                                                                                                              | AND: `_SOCIAL_CONFLICT_WORDS` + `_PEOPLE_WORDS` (tetap kode).              |
| Trivial / mustahil / clear jam / STOP | `instant.*` + `iter_registry_matches_by_prefix`                                                                                                                                                                                                                 | Lihat Fase 2.                                                              |
| FFCI / LLM                            | `registry_action_id_hint` divalidasi; setelah `normalize_resolved_intent`, field mekanis yang ada di `ctx_patch` entri hint di-**overlay** ke v1 / step0 v2 (LLM tidak boleh kontradiksi registry pada key itu) + anchor + `registry_hint_alignment` / mismatch | Fase 3 (parsial).                                                          |

Dokumen di bawah menjelaskan **arsitektur**; tandai **(selesai di kode)** = perilaku utama sudah di `main` + `action_intent` + `verify.py` (regresi).

## Konsep inti

| Elemen                   | Fungsi                                                                                                                                    |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Registry** (JSON / DB) | Daftar `action_id` yang valid: kata kunci, prioritas, patch ke `action_ctx`, atau rujukan _handler_ kode.                                 |
| **Resolver**             | Memilih **satu** `action_id` (urutan prioritas + match pertama / skor).                                                                   |
| **Dispatcher / handler** | Memetakan `action_id` → fungsi Python yang mengisi `action_ctx` dan memicu pipeline yang sudah ada (`update_timers`, combat gates, dll.). |
| **LLM (opsional, FFCI)** | Hanya mengembalikan **`registry_action_id_hint`** dari **himpunan terbatas** (`allowed_registry_action_ids`); unknown dibuang.            |

## Skema registry (v1)

Minimal per entri:

- `id` (string stabil, mis. `sleep.default`, `combat.ranged_attempt`)
- `version` / `priority` (integer, lebih kecil = dievaluasi lebih dulu jika perlu)
- `match`: salah satu atau kombinasi
  - `keywords_any`: list substring / kata
  - `regex` (opsional, hati-hati performa)
- `ctx_patch`: objek parsial yang di-merge ke `action_ctx` (hanya field yang sudah dipakai engine)
- `handler` (opsional): nama simbol di Python — untuk logika yang tidak bisa diekspresikan statis.

Versi berikutnya bisa menambah: `preconditions`, `requires_scene`, `mutually_exclusive_group`.

## Fase migrasi

### Fase 0 — Kontrak ✅

- Dokumen ini + modul loader + `data/action_registry/registry_v1.json` + tes load.

### Fase 1 — Dual path (aman) ✅

- **Tidur NL** dari registry: `parse_action_intent` memanggil `_registry_try_sleep` lalu **`_registry_try_sleep_hours_nl`** (**setelah** cabang akomodasi); parser jam ada di **`parse_sleep_hours_from_nl`** (handler registry).
- `meta["resolved_action_id"]` + `meta["intent_resolution"] = "registry"` diset di `main.py` bila `action_ctx["registry_action_id"]` ada.

### Fase 1b — Combat NL (registry-first) ✅ (parsial)

- `_registry_try_combat` **sebelum** cabang combat legacy (`combat_terms`): match `combat.*` di JSON + `registry_action_id`.
- Input yang tidak match registry tetap jatuh ke **legacy** `elif combat_terms`.

### Fase 1c — Travel NL (registry-first) ✅

- `_registry_try_travel` (match global `travel.*`) lalu **`_registry_try_travel_keyword_fallback`** — keyword dari **`travel.nl_generic`** di JSON (bukan tuple Python).
- Heuristik menit / destinasi / kendaraan: **`_apply_travel_heuristics`** (dipakai kedua jalur).

### Fase 1d — Domain skill (registry-first) ✅

- `_registry_try_skill_domain` + fallback keyword dari JSON untuk `hacking.*` … `stealth.*` — **tanpa** tuple legacy di Python.

### Fase 1e — Sosial & trivial (registry-first) ✅

- `match_registry_action_prefixed(text, "social.")` untuk urutan prioritas dalam keluarga sosial.
- Fallback: **`_registry_try_social_nl_dialogue_fallback`** (`social.nl_dialogue`), **`_registry_try_social_nl_scan_crowd_fallback`** (`social.nl_scan_crowd` + suplemen `cari` + orang).
- **`_registry_try_instant_trivial`**: hanya **`instant.nl_trivial`** (+ fallback substring selaras JSON).

### Fase 1f — Inquiry sosial + anchor LLM ✅ (parsial)

- `_registry_try_social_inquiry_nl` dengan prefiks **`social.inquiry.`**
- Merge FFCI: `apply_parser_registry_anchor_after_llm`, `merge_intent_into_action_ctx`, mismatch gate.

### Fase 1g — Handler + inquiry tunggal ✅

- **`handler`** di JSON → `action_registry_handlers.apply_registry_handler`.
- **`inquiry_phrases_match`** + **`_is_social_inquiry`** memakai keyword inquiry dari data.

### Fase 1h — Handler inquiry + audit keyword ✅

- **`social.inquiry.nl_keywords`** + **`ensure_social_inquiry_shape`**.
- **Tumpang-tindih diketahui**: substring **`siapa `** di inquiry dapat mengalahkan frasa scan yang overlap; `lihat sekitar` / `lihat orang` hanya di scan.

### Fase 1i — Allowlist intent + snapshot FFCI ✅

- **`allowed_registry_action_ids()`**; prompt intent menyertakan blok `[REGISTRY_ACTION_IDS]`.

### Fase 1j — Hint registry dari LLM ✅

- **`registry_action_id_hint`** → **`sanitize_registry_action_id_hint`** → **`action_ctx["llm_registry_action_id_hint"]`**.

### Fase 1k — Telemetri hint vs parser ✅

- **`registry_hint_alignment`**; mirror di `main.py`.

### Fase 1l — Handler travel + flag mismatch ✅

- **`ensure_travel_registry_shape`** untuk `travel.nl_generic`.
- **`meta["registry_hint_mismatch"]`** bila parser vs hint tidak cocok.

### Fase 1m — Narration + mechanical gate (alignment) ✅

- Mirror alignment ke `action_ctx`; **`turn_prompt._fmt_action_ctx`**; **`strip_llm_intent_overlay_on_registry_hint_mismatch`**.
- Renderer: `[INTENT]` / `hint_mismatch`.

### Fase 2 — Cabang utama → data + helper ✅ **dimaksimalkan (selesai praktis)**

Seluruh item migrasi NL ke registry / helper untuk **travel, skill domain, sosial (termasuk negosiasi), rest, intimacy, inquiry, trivial/clear jam/mustahil/STOP** sudah di kode + **`verify.py`**.

**Perluasan terakhir (maksimalisasi):**

- **Combat**: tuple **`combat_terms`** + cabang ranged/melee manual dihapus; fallback **`_registry_try_combat_keyword_fallback`** memakai keyword **`combat.nl_ranged_attempt`** lalu **`combat.nl_melee`** dari JSON (sama urutan prioritas), plus **`nl_attempt`** lewat **`_NL_ATTEMPT_MARKERS`**. Frasa hanya menyebut senjata tanpa verba serangan tetap **tidak** memicu combat (mitigasi false positive).
- **Hedge ketidakpastian**: entri **`instant.nl_hedge_uncertainty`** di JSON; **`_registry_apply_nl_hedge_flags`** menggantikan literal Python (tetap bisa menimpa trivial); **`registry_action_id`** di-set hanya bila belum ada id lain.

**Logika parser di Python** (tetap deterministik; sebagian disatukan lewat **id registry + handler**):

- Pola **jam tidur** dari teks NL: `parse_sleep_hours_from_nl` + handler `apply_sleep_duration_from_nl` di `action_registry_handlers.py`, id `sleep.nl_duration_hours`.
- **Akomodasi semalam / hotel**: `parse_accommodation_intent_from_nl` + `apply_accommodation_nl` (`economy.nl_accommodation_stay`).
- **Smartphone NL**: `try_parse_smartphone_nl` di `action_registry_handlers`; id `other.nl_smartphone_w2`.
- **Social inquiry**: cabang manual `elif _is_social_inquiry` diganti `_registry_try_social_inquiry_nl_legacy_fallback` → `social.inquiry.nl_keywords` + `ensure_social_inquiry_shape` bila prefixed NL lewat tetapi heuristik inquiry tetap True (jaga drift / konsistensi `registry_action_id`).
- Penyesuaian risiko sosial setelah hedge: `apply_social_post_hedge_risk_rules` di `action_registry_handlers` (dialogue/scan/inquiry, kata konflik, default `social_mode`).
- **`_SOCIAL_CONFLICT_WORDS`** + **`_PEOPLE_WORDS`** untuk **`social.nl_conflict`** (AND).

Penambahan sinonim combat/hedge baru → **edit `registry_v1.json`**.

### Fase 3 — LLM terikat registry ✅ (parsial; dilanjutkan)

**Sudah ada:**

- Snapshot **`[REGISTRY_ACTION_IDS]`** dari **`allowed_registry_action_ids()`**.
- **`registry_action_id_hint`** harus ∈ allowlist; invalid dibuang (**`sanitize_registry_action_id_hint`**).
- **`normalize_resolved_intent`** (v1 flat dan v2 langkah pertama): jika hint valid, **`ctx_patch`** entri registry di-merge ke field mekanis yang overlap (**`ai/intent_resolver.py`** — registry menang atas LLM untuk key seperti `action_type`, `domain`, `combat_style`, …).
- Overlay diperluas ke field tambahan dari JSON (mis. `rested_minutes`, `sleep_duration_h`, flag trivial / mustahil / `instant_minutes`, `visibility`, …) lewat **`_registry_overlay_merge_key`**; merge ke **`action_ctx`** lewat **`INTENT_MERGE_FIELD_KEYS`** + flatten v2.
- **Stub registry-first:** `version: 3` + `intent_schema_version: 3` + hint valid → keluaran berbentuk v1 (**`_normalize_registry_stub_v3`**; `version` output tetap 1). Objek **`params`** (opsional) di-merge setelah `ctx_patch` dengan allowlist yang sama dengan overlay + `suggested_dc` / `targets` / `travel_destination` / `inventory_ops`.
- **Payload minimal alat:** satu id lewat `registry_action_id` atau `registry_action_id_hint` atau `action_id` (+ `params`, dll.) **tanpa** kunci `version` / `intent_schema_version` / `plan` / `action_type` / `domain` di root → **`normalize_resolved_intent`** → **`_normalize_minimal_registry_intent_payload`** (dua alias berbeda nilai → ditolak).
- `params` stub: `smartphone_op` (disanitasi), `accommodation_intent` (dict dangkal: maks 24 kunci, hanya bool/int/float/string, nilai non-primitif dibuang). Helper **`parse_and_normalize_intent_json`** (`ai/intent_resolver.py`) untuk string JSON → `normalize_resolved_intent`.
- Prompt menjelaskan hint + overlay mekanik + stub v3 + satu baris format JSON alat tanpa `version`.

**Belum / roadmap:**

- (Opsional) Skema lebih kaya untuk `accommodation_intent` (field wajib / enum) bila ekonomi mengikat ke model terstruktur.

### Fase 4 — Penyederhanaan

- Kurangi duplikasi antara `action_intent.py` dan registry; sinonim baru **utamanya** lewat JSON.
- Lanjutkan pengujian di **`scripts/verify.py`** tiap penggeseran cabang (mis. scan/inquiry/dialogue: `registry_action_id` + `risk_level` setelah hedge + `apply_social_post_hedge_risk_rules`).

## Risiko & mitigasi

| Risiko                                 | Mitigasi                                                                 |
| -------------------------------------- | ------------------------------------------------------------------------ |
| Regresi perilaku                       | Fallback legacy tempat berisiko; `verify.py` untuk cabang yang disentuh. |
| JSON tidak cukup untuk logika kompleks | Field `handler` + fungsi Python kecil, deterministik.                    |
| LLM di luar registry                   | Validasi hint; mismatch gate mengembalikan snapshot parser.              |
| Performa                               | Match keyword dulu; cache registry di memori setelah load.               |

## Kriteria selesai (“seperti database”)

- Menambah perilaku baru yang **murni data** (sinonim + `ctx_patch`) **tanpa** `if` baru di `action_intent.py` — **hampir** tercapai untuk jalur yang sudah dipindah; cabang hedge/combat legacy masih boleh menyentuh Python.
- LLM tidak mengusulkan **hint** id di luar allowlist (**tercapai** untuk hint).

## File terkait

- `data/action_registry/registry_v1.json`
- `engine/core/action_registry.py`
- `engine/core/action_registry_handlers.py`
- `engine/core/action_intent.py`
- `ai/intent_resolver.py`, `main.py`, `display/renderer.py`, `scripts/verify.py`

## Catatan OMNI-ENGINE

Crafting, shop, travel engine, dll. sudah **data-driven** di modul masing-masing; registry menyatukan lapisan **“apa maksud input pemain ini?”** agar konsisten dengan pola tersebut.
