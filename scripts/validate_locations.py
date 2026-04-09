from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from engine.location_presets import LocationPresetError, load_location_preset

    loc_dir = ROOT / "data" / "locations"
    if not loc_dir.exists():
        print(f"[locations] directory not found: {loc_dir}")
        return 1

    files = sorted(loc_dir.glob("*.json"), key=lambda p: p.name.lower())
    if not files:
        print(f"[locations] no presets found under: {loc_dir}")
        return 1

    failures: list[str] = []
    for p in files:
        lk = p.stem.strip().lower()
        try:
            preset = load_location_preset(lk)
            if not isinstance(preset, dict):
                failures.append(f"{p.name}: load returned non-dict")
                continue
            npcs = preset.get("npcs", {}) or {}
            items = preset.get("nearby_items", []) or []
            tags = preset.get("tags", []) or []
            print(f"[ok] preset={lk} npcs={len(npcs) if isinstance(npcs, dict) else '?'} items={len(items) if isinstance(items, list) else '?'} tags={len(tags) if isinstance(tags, list) else 0}")
        except LocationPresetError as e:
            failures.append(f"{p.name}: {e}")
        except Exception as e:
            failures.append(f"{p.name}: unexpected error: {e}")

    if failures:
        print("\n[locations] VALIDATION FAILED")
        for f in failures:
            print(f"- {f}")
        return 2

    print("\n[locations] VALIDATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

