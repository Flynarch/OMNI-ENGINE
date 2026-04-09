"""
Run all static validators (content packs + location presets).

Usage: python scripts/validate_all.py
Exit code: 0 if all pass, else first non-zero sub-exit or 1.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> int:
    scripts = [
        ROOT / "scripts" / "validate_packs.py",
        ROOT / "scripts" / "validate_locations.py",
    ]
    code = 0
    for s in scripts:
        if not s.exists():
            print(f"[validate_all] missing: {s}", file=sys.stderr)
            return 1
        r = subprocess.call([PY, str(s)])
        if r != 0:
            code = r if code == 0 else code
    return code


if __name__ == "__main__":
    raise SystemExit(main())
