# OMNI-ENGINE v6.9

**A deterministic sandbox simulation with an AI narrator** — one character, free-form actions within the world’s logic.  
Python computes time, economy, rolls, and consequences; the LLM only turns that **same state** into coherent prose.

If you want a “grown-up” sandbox where actions have persistent, systemic consequences (not a keyword parser), this is the core engine.

---

## What sets it apart

| Aspect | Behavior |
|--------|----------|
| **Determinism** | Same state + input ⇒ same rolls and simulation (replayable, testable). |
| **Hybrid intent** | An LLM maps player intent to structured JSON; Python enforces rules + a fallback parser. |
| **Persistent world** | Locations, factions, economy, NPCs, quests, ripples, and intel do not reset on a whim. |
| **Structured intel** | News and ripples are bounded, deduped, and propagate through plausible channels (local / contacts / broadcast). |

---

## Features (summary)

### Simulation & time
- **Turns and world clock** advance; automatic time cost for inventory micro-actions.
- **Deterministic weather** affects travel and stealth/evasion modifiers per location.
- **Location restrictions** (`police_sweep`, `corporate_lockdown`) with real penalties.

### Social & NPCs
- Primary emotions (Plutchik) + derived emotions, decay, beliefs and short memory with source/confidence.
- Organic gossip during social interactions (rate-limited).

### Trace, economy, factions
- **Trace** scales with attention states (Ghost → … → Manhunt).
- **Hacking heat** per target + inventory tooling hooks.
- **Reactive economy**: global → country → city baselines; geopolitical pressure + local restrictions.
- **Structured ripples** tied to impact and stealth.
- **Underworld consequences**: Black Market sting ambush scenes, arrest outcomes, and faction heat escalation from targeted hacks.

### Lodging, bank, shop, disguise
- **Shop / bank / prepaid stay** (hotel / boarding / suite) wired into `world_notes` and turn audit.
- **Disguise** personas; **safehouses** rent/stash/trace decay.
- **Skill XP** per domain after rolls; decay when skills go unused.

### Language & content
- Language learning, communication barriers, and **Earth-only** city presets (`data/locations/`).
- **Content packs** (`data/packs/`) for items/roles/services — validate with the bundled scripts.

---

## What’s new in v6.9

- **Shared LLM HTTP layer** (`ai/llm_http.py`): retries + backoff for **narration (streaming)** and **intent (JSON)** — see `LLM_HTTP_RETRIES`.
- **Intent schema v2 (plan-based)**: the LLM can return `version=2` with `plan.steps[]` + `preconditions`. The engine selects the first valid step for this turn (not always `steps[0]`) and overlays it into `action_ctx` for execution.
- **“Facts changed this turn”** line in the narration package (`ai/turn_prompt.py`) + **`commerce_notes`** in `meta.last_turn_audit` (Shop / Bank / Stay).
- **Hygiene commands**: `SHOWER` / `HYGIENE` / `MANDI` (reset hygiene clock, ~15 engine minutes).
- **Phase 3.5 systems integration**:
  - Security scene chain: `police_stop`, `safehouse_raid`, `sting_operation` with deterministic outcomes.
  - Underworld economy: `BLACKMARKET` + `BUY_DARK` with deterministic daily stock and sting risk.
  - Targeted hacking command: `HACK atm|corp_server|police_archive` with faction heat impact.
  - Daily attrition balancing: `daily_gigs_done` cap and `daily_hacks_attempted` fatigue penalty (resets on day rollover).
  - HUD polish: `[CONDITION]` monitor line + `STATUS` / `INFO` capacity indicators.
  - Master E2E verification path in `scripts/verify.py` covering gigs, hacking, stay rollover reset, and black market purchase.
- **Save migration**: `python scripts/migrate_save.py` (writes `.bak`, merges new fields).
- **Validators**: `python scripts/validate_all.py` (packs + all location presets).
- **Data**: city presets, extra seeds, `core` pack (occupations), balance snapshot in saves.

---

## Requirements

- **Python 3.11+**
- Dependencies: `pip install -r requirements.txt`

---

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
# Set OPENROUTER_API_KEY or GROQ_API_KEY in .env

python main.py
```

### LLM providers

**OpenRouter (default)**

```env
OPENROUTER_API_KEY=sk-or-v1-...
# OPENROUTER_MODEL=openrouter/free
```

**Groq** (example: [Llama 3.3 70B](https://console.groq.com/docs/model/llama-3.3-70b-versatile))

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
```

Model directories:
- OpenRouter: https://openrouter.ai/models  
- Groq: https://console.groq.com/docs/models  

Optional: `LLM_MAX_TOKENS`, `LLM_INTENT_MAX_TOKENS`, `LLM_HTTP_RETRIES`, `BAL_*` and bio tuning — see `.env.example`.

### Save files

| File | Role |
|------|------|
| `save/current.json` | Active session |
| `save/previous.json` | Backup for `UNDO` (Normal mode) |

Both are gitignored — do not commit personal saves.

On first boot you fill a profile and pick a **seed pack** (`default`, `minimal`, or `none`).

---

## CLI commands (sample)

| Command | Purpose |
|---------|---------|
| `HELP` | Full command list |
| `SHOWER` / `HYGIENE` / `MANDI` | Reset hygiene clock (engine, ~15 min) |
| `STATUS` / `INFO` | Current condition: daily gigs cap + hack fatigue penalty |
| `WHEREAMI` | Location + short profile |
| `BANK …` / `STAY …` | Banking & prepaid lodging |
| `MARKET` / `BLACKMARKET` / `BUY_DARK …` / `QUEST` | Legal + underworld market and quests |
| `ATLAS [country]` / `COUNTRIES` / `CITIES [country]` | Atlas & cities |
| `WHO` / `NPC <name>` | NPCs |
| `HEAT` / `OFFERS` | Hacking heat & NPC offers |
| `GIGS` / `WORK <gig_id>` / `HACK <target>` | Contracts and targeted hacking loop |
| `DISGUISE …` / `SAFEHOUSE …` / `WEATHER` / `SKILLS` | Disguise, safehouse, weather, skills |
| `MODE NORMAL\|IRONMAN` / `UNDO` | Mode & undo |

---

## Seed packs & data

- **Seeds**: `data/seeds/<name>.json` — safe merge into state (does not overwrite core boot profile).
- **Locations**: `data/locations/<city>.json` — NPC/item/tag presets per city.
- **Packs**: `data/packs/<id>/` — modding content; run `validate_packs.py` before large PRs.

---

## Development & quality

```bash
# Compile check + smoke + regression scenarios (determinism, markets, quests, etc.)
python scripts/verify.py

# Validate content (packs + every location preset)
python scripts/validate_all.py

# Migrate an older save to the latest schema (in-place + .bak)
python scripts/migrate_save.py
python scripts/migrate_save.py path/to/save.json
```

---

## Repository layout

| Path | Role |
|------|------|
| `main.py` | REPL loop, intent, pipeline, autosave |
| `engine/` | Simulation: time, world, economy, quests, trace, NPCs, bio, balance, … |
| `ai/` | LLM client, intent resolver, turn package / system prompts |
| `display/` | Terminal UI (Rich) |
| `data/` | State template, seeds, locations, packs |
| `scripts/` | `verify`, `validate_*`, `migrate_save` |

---

## Roadmap (directional)

- Time UX: per-turn time breakdown (what ran automatically).
- Deeper cities: districts, intra-city travel, local services.
- Richer NPC→NPC social diffusion (who tells whom, with distortion).
- Safer modding: pack schema + CI validators.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Flynarch.

---

*OMNI-ENGINE: systems first; the story follows the state.*
