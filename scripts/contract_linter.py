"""Lightweight integration contract checks (CI-friendly)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "engine" / "core"

REQUIRED = (
    CORE / "domain_vocab.py",
    CORE / "boundary_contract.py",
    CORE / "integration_hooks.py",
    CORE / "mutation_gateway.py",
)


def main() -> int:
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.exists()]
    if missing:
        print("[contract_linter] FAILED missing:")
        for m in missing:
            print(f"  - {m}")
        return 2
    print("[contract_linter] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
