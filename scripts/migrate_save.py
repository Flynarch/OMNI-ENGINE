"""
Migrate a save file to the current schema (merge defaults, balance freeze, packs).

Usage (from repo root):
  python scripts/migrate_save.py
  python scripts/migrate_save.py save/current.json
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.state import CURRENT, load_state, save_state  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate OMNI-ENGINE save JSON in place.")
    ap.add_argument(
        "path",
        nargs="?",
        default=str(CURRENT),
        help=f"Path to save JSON (default: {CURRENT})",
    )
    args = ap.parse_args()
    path = Path(args.path).resolve()
    if not path.exists():
        print(f"[migrate] file not found: {path}", file=sys.stderr)
        return 1
    bak = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copyfile(path, bak)
        print(f"[migrate] backup → {bak}")
    except Exception as e:
        print(f"[migrate] backup failed: {e}", file=sys.stderr)
        return 1
    try:
        st = load_state(path)
        save_state(st, path)
    except Exception as e:
        print(f"[migrate] failed: {e}", file=sys.stderr)
        return 1
    print(f"[migrate] ok → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
