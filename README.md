# OMNI-ENGINE v6.8

**A deterministic sandbox simulation with an AI narrator** — you control one character and can attempt *any* logical action.  
Python runs the world (state, time, economy, rolls, consequences). An LLM turns the same state into a coherent narrative.

If you want a “mature” sandbox where your actions have persistent, systemic consequences (not a keyword game), this is the core.

## What makes it different

- **Deterministic simulation**: identical state + input ⇒ identical roll outcomes (repeatable, testable).
- **Hybrid intent resolution**: LLM resolves intent into structured JSON; Python enforces the rules and fallbacks.
- **Persistent world**: locations, factions, NPC beliefs/emotions, markets, quests, and ripples persist and propagate.
- **Structured intel**: news + ripples are deduped, bounded, and gated by propagation (local/contacts/broadcast).
- **Reactive economy**: global baseline → country baseline → city market, influenced by geopolitics and local restrictions.

## Features (current)

### Core simulation
- **Time & turns**: the world advances even when you “do nothing”.
- **Inventory micro-actions**: automatic pocket/bag handling with time cost (reduces wasted turns).
- **Restrictions**: `police_sweep` and `corporate_lockdown` create real penalties and area restrictions.
- **Deterministic weather**: affects travel time and stealth/evasion modifiers per day+location.

### Social / NPCs
- **NPC psychology**: Plutchik-based primaries with decay; secondary emotions derived.
- **Beliefs & memory snippets**: NPCs remember claims with sources/bias/confidence and use them in social logic.
- **Organic gossip**: during social interactions, NPCs can surface relevant news naturally (rate-limited).

### Hacking / Trace / Factions
- **Trace escalation**: increases lead to attention states (Ghost → Flagged → Investigated → Manhunt).
- **Hacking heat + cooldown**: pressure is tracked per target, plus inventory tooling hooks.
- **Faction impacts + structured ripples**: outcomes ripple through contacts/broadcast depending on stealth/impact.

### Quests & world pressure
- **Emergent quest chains**: multi-step objectives with deadlines, failure states, and branching.
- **Remote incidents**: other cities can have events that propagate into your intel network.

### New integrated systems (v6.8)
- **Disguise/persona**: change identity to reduce trace; can be caught under police pressure for heavier consequences.
- **Safehouses**: rent/buy/upgrade + stash + daily rent pressure; bonus trace decay when laying low.
- **Skill progression**: XP/levels per domain applied after rolls; skills decay when unused.

## Quickstart (Windows)

### Requirements
- Python **3.11+**

### Install

```bash
pip install -r requirements.txt
```

### Configure LLM

Copy `.env.example` → `.env`, then choose a provider.

**OpenRouter**

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

Model lists:
- OpenRouter: `https://openrouter.ai/models`
- Groq: `https://console.groq.com/docs/models`

### Run

```bash
python main.py
```

Saves:
- Current: `save/current.json`
- Backup: `save/previous.json`

On a fresh boot you’ll fill a profile and choose a **seed pack** (`default`, `minimal`, or `none`).

## Key commands

- **`HELP`**: show command list
- **`WHEREAMI`**: current location + profile summary + known locations
- **`MARKET`**: local market snapshot (falls back to global)
- **`QUEST`**: active/completed/failed quest chains + steps/deadlines
- **`ATLAS [country]`**: geopolitics + deterministic country profiles
- **`WHO` / `NPC <name>`**: list NPCs / inspect a specific NPC
- **`HEAT`**: hacking heat/cooldowns
- **`OFFERS [role]`**: NPC economy offers
- **`NPCSIM_STATS`**: NPC simulation LOD counters
- **`DISGUISE <persona>` / `DISGUISE OFF`**
- **`SAFEHOUSE status|rent|buy|upgrade|stash put <id>|stash take <id>`**
- **`WEATHER`**
- **`SKILLS`**

## Seed packs

Seed packs live in `data/seeds/<name>.json`. They merge safely into the state (NPCs, events, ripples, notes, reputation, skills, trace, world) and do **not** overwrite your boot profile, bio, or economy.

## Verification

```bash
python scripts/verify.py
```

Runs `compileall` + smoke/stress scenarios to catch regressions (determinism, markets, quests, restrictions, atlas caching, etc.).

## Project layout

| Path | Purpose |
|------|---------|
| `main.py` | REPL loop, intent integration, pipeline, autosave |
| `engine/` | world simulation: time, factions, economy, quests, trace, NPCs |
| `ai/` | LLM client + strict turn packaging |
| `display/` | Rich-based monitor UI |
| `data/` | state template, seed packs |
| `scripts/` | verification & developer utilities |

## Roadmap (high-impact next)

- **Better action UX**: explicit “time cost breakdown” per turn (what auto-actions happened and why).
- **More location depth**: districts/venues, travel-within-city, local services and procurement.
- **NPC-to-NPC spread**: stronger social graph diffusion (who tells whom, why, and with what distortion).
- **Safer modding**: data-driven items/roles/services/events packs with validation tooling.

---

If you’re building a sandbox where *systems* tell the story, OMNI-ENGINE is the foundation.
