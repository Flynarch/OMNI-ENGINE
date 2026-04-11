"""Print a minimal valid pack skeleton for designers (stdout JSON)."""

from __future__ import annotations

import json

SKELETON = {
    "pack_id": "example_pack",
    "version": 1,
    "pack_schema_version": 1,
    "name": "Example",
    "description": "Starter skeleton — replace content.",
    "items": [],
    "roles": [],
    "services": [],
}


def main() -> int:
    print(json.dumps(SKELETON, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
