"""Move misplaced ``log_swallowed_exception`` import below ``from __future__ import annotations``."""

from __future__ import annotations

from pathlib import Path

from engine_import_placement import compute_log_swallowed_import_insert_index

ROOT = Path(__file__).resolve().parents[1]
IMP = "from engine.core.error_taxonomy import log_swallowed_exception\n"
IMP_STRIP = IMP.strip()


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines:
        return False
    # Strip leading misplaced import(s)
    removed = False
    while lines and lines[0].strip() == IMP_STRIP:
        lines.pop(0)
        removed = True
    if not removed:
        return False
    if IMP in "".join(lines):
        # already present elsewhere
        path.write_text("".join(lines), encoding="utf-8")
        return True
    insert_at = compute_log_swallowed_import_insert_index(lines)
    lines.insert(insert_at, IMP)
    path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> None:
    n = 0
    for p in sorted((ROOT / "engine").rglob("*.py")):
        if p.is_file() and fix_file(p):
            print("fixed", p.relative_to(ROOT).as_posix())
            n += 1
    mp = ROOT / "main.py"
    if mp.is_file() and fix_file(mp):
        print("fixed main.py")
        n += 1
    print("total", n)


if __name__ == "__main__":
    main()
