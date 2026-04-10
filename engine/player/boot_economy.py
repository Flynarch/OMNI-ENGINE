from __future__ import annotations

import hashlib
import re
from typing import Any

# Kata kunci pekerjaan / latar (id + en) — klasifikasi kasar untuk startup ekonomi.
_TIER_HIGH = (
    "ceo", "cto", "cfo", "coo", "director", "executive", "vp ", "vice president",
    "dokter", "doctor", "surgeon", "lawyer", "pengacara", "partner",
    "investor", "consultant", "konsultan", "banker", "bank",
    "senior", "principal", "lead ", "manager", "manajer", "head of",
    "engineer", "insinyur", "architect", "developer", "pilot",
)
_TIER_LOW = (
    "unemployed", "penganggur", "jobless", "buruh", "waiter", "pelayan",
    "cashier", "kasir", "cleaner", "pembersih", "janitor", "security guard",
    "gig", "ojek", "driver", "kurir", "student", "mahasiswa", "pelajar",
    "intern", "magang", "part-time", "part time", "freelance",
)


def _stable_seed(s: str) -> int:
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest()[:12], 16)


def _span(lo: int, hi: int, seed: int) -> int:
    if hi <= lo:
        return lo
    return lo + (seed % (hi - lo + 1))


def _parse_year(raw: Any) -> int:
    if isinstance(raw, (int, float)):
        y = int(raw)
        return max(1980, min(2060, y))
    s = str(raw or "").strip()
    m = re.search(r"(19|20)\d{2}", s)
    if m:
        return max(1980, min(2060, int(m.group(0))))
    try:
        return max(1980, min(2060, int(s)))
    except ValueError:
        return 2025


def _year_factor(year: int) -> float:
    """Skala nominal biaya vs era (1990 murah, 2025 baseline, 2050 lebih mahal)."""
    y = max(1990, min(2050, year))
    if y <= 2025:
        return 0.72 + (y - 1990) / 35 * 0.28
    return min(1.22, 1.0 + (y - 2025) / 25 * 0.15)


def _tier(occupation: str, background: str) -> str:
    blob = f"{occupation} {background}".lower()
    hi = sum(1 for k in _TIER_HIGH if k in blob)
    lo = sum(1 for k in _TIER_LOW if k in blob)
    if hi > lo and hi >= 1:
        return "high"
    if lo > hi and lo >= 1:
        return "low"
    if hi >= 1 and lo == 0:
        return "high"
    if lo >= 1 and hi == 0:
        return "low"
    return "mid"


def preview_economy_tier(occupation: str, background: str) -> str:
    """Same rules as startup economy tier (keyword scan on occupation + background)."""
    return _tier(occupation, background)


def format_boot_economy_preview(occupation: str, background: str, year: Any) -> str:
    """
    Human-readable tier + approximate numeric ranges after year scaling.
    Final cash/bank/etc. still use name|occ|bg seed inside apply_boot_economy — this is indicative only.
    """
    tier = _tier(occupation, background)
    factor = _year_factor(_parse_year(year))
    if tier == "high":
        cash_r, bank_r, burn_r, cc_r, fico_r = (2500, 8000), (12000, 50000), (150, 350), (72, 95), (680, 780)
    elif tier == "low":
        cash_r, bank_r, burn_r, cc_r, fico_r = (200, 800), (500, 2000), (40, 80), (22, 48), (520, 600)
    else:
        cash_r, bank_r, burn_r, cc_r, fico_r = (800, 2500), (3000, 12000), (80, 180), (45, 70), (600, 680)

    def scaled(lo: int, hi: int) -> tuple[int, int]:
        return int(lo * factor), int(hi * factor)

    c0, c1 = scaled(*cash_r)
    b0, b1 = scaled(*bank_r)
    br0, br1 = scaled(*burn_r)
    # burn has max(15, ...) in apply — show scaled range as hint
    br0 = max(15, br0)
    lines = [
        f"Tier ekonomi awal (preview): [bold]{tier}[/bold]",
        f"  Cash ~ {c0}-{c1}  |  Bank ~ {b0}-{b1}  |  Burn/hari ~ {br0}-{br1}",
        f"  CC ~ {cc_r[0]}-{cc_r[1]}  |  FICO ~ {fico_r[0]}-{fico_r[1]}  (skala tahun x{factor:.2f})",
        "[dim]Angka final ditentukan saat start (seed nama+teks); ini hanya rentang tier.[/dim]",
    ]
    return "\n".join(lines)


def apply_boot_economy(state: dict[str, Any]) -> None:
    """
    Set cash, bank, daily_burn, fico, dan player.cc dari occupation/background/year.
    Hanya untuk karakter baru (dipanggil dari initialize_state).
    """
    player = state.setdefault("player", {})
    econ = state.setdefault("economy", {})
    occ = str(player.get("occupation", "") or "")
    bg = str(player.get("background", "") or "")
    name = str(player.get("name", "") or "")
    seed = _stable_seed(f"{name}|{occ}|{bg}")
    year = _parse_year(player.get("year"))
    factor = _year_factor(year)
    tier = _tier(occ, bg)
    player["econ_tier"] = tier

    if tier == "high":
        cash_r, bank_r, burn_r, cc_r, fico_r = (2500, 8000), (12000, 50000), (150, 350), (72, 95), (680, 780)
    elif tier == "low":
        cash_r, bank_r, burn_r, cc_r, fico_r = (200, 800), (500, 2000), (40, 80), (22, 48), (520, 600)
    else:
        cash_r, bank_r, burn_r, cc_r, fico_r = (800, 2500), (3000, 12000), (80, 180), (45, 70), (600, 680)

    cash = int(_span(*cash_r, seed) * factor)
    bank = int(_span(*bank_r, seed >> 8) * factor)
    daily_burn = max(15, int(_span(*burn_r, seed >> 16) * factor))
    cc = _span(*cc_r, seed >> 24)
    fico = _span(*fico_r, seed >> 32)

    econ["cash"] = cash
    econ["bank"] = bank
    econ["debt"] = 0
    econ["daily_burn"] = daily_burn
    econ["fico"] = fico
    econ.setdefault("aml_status", "CLEAR")
    econ.setdefault("aml_threshold", 10000)
    econ.setdefault("deposit_log", [])
    econ["last_economic_cycle_day"] = int(state.get("meta", {}).get("day", 1))

    player["cc"] = cc
