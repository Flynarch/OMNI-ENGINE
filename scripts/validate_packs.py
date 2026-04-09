from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from engine.core.content_packs import PACKS_DIR, PackError, _load_pack_extras, load_pack

    if not PACKS_DIR.exists():
        print(f"[packs] directory not found: {PACKS_DIR}")
        return 1

    failures: list[str] = []
    pack_dirs = [p for p in PACKS_DIR.iterdir() if p.is_dir()]
    if not pack_dirs:
        print(f"[packs] no packs found under: {PACKS_DIR}")
        return 1

    for d in sorted(pack_dirs, key=lambda p: p.name.lower()):
        pid = d.name
        try:
            pack = load_pack(pid)
            _load_pack_extras(pid)
            items = len(pack.get("items", []) or [])
            roles = len(pack.get("roles", []) or [])
            svcs = len(pack.get("services", []) or [])
            print(f"[ok] pack={pid} v{pack.get('version')} items={items} roles={roles} services={svcs}")
        except PackError as e:
            failures.append(f"{pid}: {e}")
        except Exception as e:
            failures.append(f"{pid}: unexpected error: {e}")

    if failures:
        print("\n[packs] VALIDATION FAILED")
        for f in failures:
            print(f"- {f}")
        return 2

    print("\n[packs] VALIDATION OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

