# OMNI-ENGINE v6.9

**Sandbox simulasi deterministik dengan narator AI** — satu karakter, aksi bebas dalam batas logika dunia.  
Python menghitung waktu, ekonomi, roll, konsekuensi; LLM hanya mengubah *state yang sama* menjadi narasi konsisten.

Kalau kamu cari “sandbox dewasa” di mana tindakan punya dampak sistemik dan persisten (bukan parser kata kunci), ini inti mesinnya.

---

## Apa yang bikin beda

| Aspek | Perilaku |
|--------|----------|
| **Determinisme** | State + input yang sama ⇒ hasil roll dan simulasi yang sama (bisa diuji ulang). |
| **Intent hybrid** | LLM merangkai niat pemain jadi JSON terstruktur; Python menegakkan aturan + fallback parser. |
| **Dunia persisten** | Lokasi, fraksi, ekonomi, NPC, quest, ripple, dan intel tidak “reset” seenaknya. |
| **Intel terstruktur** | Berita & ripple dibatasi, didedup, dan menyebar lewat jalur yang masuk akal (lokal / kontak / siaran). |

---

## Fitur utama (ringkas)

### Simulasi & waktu
- **Turn & jam dunia** berjalan; biaya waktu otomatis untuk mikro-aksi inventori.
- **Cuaca deterministik** memengaruhi travel dan modifier (stealth/evasion) per lokasi.
- **Restriksi lokasi** (`police_sweep`, `corporate_lockdown`) dengan dampak nyata.

### Sosial & NPC
- Emosi primer (Plutchik) + turunan, decay, keyakinan & memori singkat dengan sumber/kepercayaan.
- Gossip organik saat interaksi sosial (rate-limited).

### Jejak digital, ekonomi, fraksi
- **Trace** naik turun dengan status perhatian (Ghost → … → Manhunt).
- **Hacking heat** per target + tooling inventori.
- **Ekonomi reaktif**: baseline global → negara → kota; tekanan geopolitik + restriksi lokal.
- **Ripple** terstruktur sesuai dampak & stealth.

### Akomodasi, bank, toko, penyamaran
- **Shop / bank / prepaid stay** (hotel / kost / suite) terintegrasi ke `world_notes` dan audit turn.
- **Disguise** persona; **safehouse** sewa/stash/trace decay.
- **Skill XP** per domain setelah roll; decay saat jarang dipakai.

### Bahasa & konten
- Pembelajaran bahasa, barrier komunikasi, dan preset kota **Earth-only** (`data/locations/`).
- **Content packs** (`data/packs/`) untuk item/role/service — validasi dengan skrip.

---

## Yang baru di v6.9

- **Lapisan HTTP LLM bersama** (`ai/llm_http.py`): retry + backoff untuk **narasi (streaming)** dan **intent (JSON)** — env `LLM_HTTP_RETRIES`.
- **Baris “fakta berubah turn ini”** di paket narasi (`ai/turn_prompt.py`) + **`commerce_notes`** di `meta.last_turn_audit` (Shop / Bank / Stay).
- **Perintah hygiene**: `SHOWER` / `HYGIENE` / `MANDI` (reset jam hygiene, ~15 menit engine).
- **Migrasi save**: `python scripts/migrate_save.py` (backup `.bak`, merge field baru).
- **Validator**: `python scripts/validate_all.py` (packs + lokasi).
- **Data**: preset kota, seed tambahan, pack `core` (occupations), snapshot balance di save.

---

## Persyaratan

- **Python 3.11+**
- Dependensi: `pip install -r requirements.txt`

---

## Mulai cepat

```bash
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
# isi OPENROUTER_API_KEY atau GROQ_API_KEY di .env

python main.py
```

### Provider LLM

**OpenRouter (default)**

```env
OPENROUTER_API_KEY=sk-or-v1-...
# OPENROUTER_MODEL=openrouter/free
```

**Groq** (contoh: [Llama 3.3 70B](https://console.groq.com/docs/model/llama-3.3-70b-versatile))

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

Model:
- OpenRouter: https://openrouter.ai/models  
- Groq: https://console.groq.com/docs/models  

Opsional: `LLM_MAX_TOKENS`, `LLM_INTENT_MAX_TOKENS`, `LLM_HTTP_RETRIES`, tuning `BAL_*` dan bio — lihat komentar di `.env.example`.

### Save game

| File | Isi |
|------|-----|
| `save/current.json` | Sesi aktif |
| `save/previous.json` | Backup untuk `UNDO` (mode Normal) |

Keduanya di-*ignore* Git (jangan commit save pribadi).

Boot pertama: isi profil dan pilih **seed pack** (`default`, `minimal`, atau `none`).

---

## Perintah CLI (cuplikan)

| Perintah | Fungsi |
|----------|--------|
| `HELP` | Daftar perintah |
| `SHOWER` / `HYGIENE` / `MANDI` | Reset jam hygiene (engine, ~15 m) |
| `WHEREAMI` | Lokasi + ringkasan profil |
| `BANK …` / `STAY …` | Bank & prepaid menginap |
| `MARKET` / `QUEST` | Pasar lokal & quest |
| `ATLAS [negara]` / `COUNTRIES` / `CITIES [negara]` | Atlas & kota |
| `WHO` / `NPC <nama>` | NPC |
| `HEAT` / `OFFERS` | Hacking heat & penawaran NPC |
| `DISGUISE …` / `SAFEHOUSE …` / `WEATHER` / `SKILLS` | Penyamaran, safehouse, cuaca, skill |
| `MODE NORMAL\|IRONMAN` / `UNDO` | Mode & undo |

---

## Seed packs & data

- **Seeds**: `data/seeds/<nama>.json` — merge aman ke state (tidak menimpa profil boot inti).
- **Lokasi**: `data/locations/<kota>.json` — preset NPC/item/tag per kota.
- **Packs**: `data/packs/<id>/` — konten modding; jalankan `validate_packs.py` sebelum PR.

---

## Pengembangan & kualitas

```bash
# Smoke + determinisme + skenario regresi
python scripts/verify.py

# Validasi konten (packs + semua preset lokasi)
python scripts/validate_all.py

# Migrasi save lama ke skema terbaru (in-place + .bak)
python scripts/migrate_save.py
python scripts/migrate_save.py path/ke/save.json
```

---

## Struktur repo

| Path | Peran |
|------|--------|
| `main.py` | Loop REPL, intent, pipeline, autosave |
| `engine/` | Simulasi: waktu, dunia, ekonomi, quest, trace, NPC, bio, balance, … |
| `ai/` | Klien LLM, resolver intent, paket turn / sistem prompt |
| `display/` | UI terminal (Rich) |
| `data/` | Template state, seeds, lokasi, packs |
| `scripts/` | `verify`, `validate_*`, `migrate_save` |

---

## Roadmap (ikut minat)

- UX waktu: breakdown biaya waktu per turn (apa yang otomatis jalan).
- Kedalaman kota: distrik, travel intra-kota, layanan lokal.
- Diffusi sosial NPC→NPC lebih kaya (siapa ke siapa, distorsi).
- Modding lebih aman: skema pack + validator CI.

---

## Lisensi

[MIT](LICENSE) — Copyright (c) 2026 Flynarch.

---

*OMNI-ENGINE: sistem dulu, cerita mengikuti state.*
