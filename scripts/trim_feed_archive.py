#!/usr/bin/env python3
"""Trim ``world_notes`` / ``news_feed`` inside ``save/archive.json`` for smaller publishable bundles.

Keeps the **most recent** entries (list tail), same semantics as in-game archive tail cap.

Examples (from repo root)::

    python scripts/trim_feed_archive.py --dry-run
    python scripts/trim_feed_archive.py --keep 400 --backup
    python scripts/trim_feed_archive.py save/archive.json -o publish/archive_trimmed.json --redact-metadata

Exit codes: 0 ok (including nothing to change), 1 error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("archive root must be a JSON object")
    raw.setdefault("version", 1)
    wn = raw.setdefault("world_notes", [])
    nf = raw.setdefault("news_feed", [])
    if not isinstance(wn, list):
        raw["world_notes"] = []
    if not isinstance(nf, list):
        raw["news_feed"] = []
    return raw


def _tail(lst: list[Any], keep: int) -> tuple[list[Any], int]:
    if keep < 0:
        raise SystemExit("--keep / per-list limits must be >= 0")
    if keep == 0:
        return [], len(lst)
    if len(lst) <= keep:
        return lst, 0
    removed = len(lst) - keep
    return lst[-keep:], removed


def main() -> int:
    ap = argparse.ArgumentParser(description="Trim feed archive JSON for publishing.")
    ap.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=ROOT / "save" / "archive.json",
        help="Path to archive.json (default: save/archive.json under repo root)",
    )
    ap.add_argument(
        "--keep",
        type=int,
        default=500,
        metavar="N",
        help="Keep last N entries for both lists when --notes-keep/--news-keep omitted (default: 500)",
    )
    ap.add_argument("--notes-keep", type=int, default=None, metavar="N", help="Override keep for world_notes only")
    ap.add_argument("--news-keep", type=int, default=None, metavar="N", help="Override keep for news_feed only")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Write here instead of overwriting input")
    ap.add_argument("--dry-run", action="store_true", help="Print plan only; do not write files")
    ap.add_argument("--backup", action="store_true", help="Before overwrite, copy input to input + .bak")
    ap.add_argument(
        "--redact-metadata",
        action="store_true",
        help="Remove last_pruned_* keys before writing (cleaner for public share)",
    )
    args = ap.parse_args()

    inp = args.input.resolve()
    if not inp.exists():
        print(f"[trim] missing file: {inp}", file=sys.stderr)
        return 1

    data = _load(inp)
    wn: list[Any] = list(data.get("world_notes") or [])
    nf: list[Any] = list(data.get("news_feed") or [])
    nk = int(args.notes_keep) if args.notes_keep is not None else int(args.keep)
    fk = int(args.news_keep) if args.news_keep is not None else int(args.keep)

    wn2, rw = _tail(wn, nk)
    nf2, rn = _tail(nf, fk)

    out_path = args.output.resolve() if args.output is not None else inp
    if args.redact_metadata:
        for k in ("last_pruned_meta_day", "last_pruned_at_utc"):
            data.pop(k, None)

    data["world_notes"] = wn2
    data["news_feed"] = nf2
    data["archive_trimmed_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data["archive_trimmed_removed_counts"] = {"world_notes": rw, "news_feed": rn}

    print(
        f"[trim] input={inp}\n"
        f"       world_notes: {len(wn)} -> {len(wn2)} (removed {rw})\n"
        f"       news_feed:   {len(nf)} -> {len(nf2)} (removed {rn})\n"
        f"       output={out_path if args.output else inp}{' (dry-run)' if args.dry_run else ''}"
    )

    if rw == 0 and rn == 0 and not args.redact_metadata:
        print("[trim] nothing to change")
        return 0

    if args.dry_run:
        return 0

    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"[trim] wrote {out_path}")
        return 0

    if args.backup:
        bak = inp.with_suffix(inp.suffix + ".bak")
        shutil.copyfile(inp, bak)
        print(f"[trim] backup -> {bak}")

    inp.write_text(text, encoding="utf-8")
    print(f"[trim] wrote {inp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
