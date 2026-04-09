from __future__ import annotations

from typing import Any


def _clamp_int(v: object, lo: int, hi: int, default: int = 0) -> int:
    try:
        x = int(v)
    except Exception:
        x = default
    return max(lo, min(hi, x))


def bank_deposit(state: dict[str, Any], amount: int) -> dict[str, Any]:
    """Move cash → bank. Caller should pass `cash_deposit` into `update_economy` / pipeline for AML."""
    amt = _clamp_int(amount, 1, 999_999_999, 0)
    if amt <= 0:
        return {"ok": False, "reason": "invalid_amount"}
    econ = state.setdefault("economy", {})
    cash = _clamp_int(econ.get("cash", 0), 0, 10_000_000_000, 0)
    if cash < amt:
        return {"ok": False, "reason": "not_enough_cash"}
    bank = _clamp_int(econ.get("bank", 0), 0, 10_000_000_000, 0)
    econ["cash"] = cash - amt
    econ["bank"] = bank + amt
    state.setdefault("world_notes", []).append(f"[Bank] DEPOSIT {amt} cash→bank")
    return {"ok": True, "amount": amt, "cash_deposit": float(amt)}


def bank_withdraw(state: dict[str, Any], amount: int) -> dict[str, Any]:
    """Move bank → cash (no AML deposit event)."""
    amt = _clamp_int(amount, 1, 999_999_999, 0)
    if amt <= 0:
        return {"ok": False, "reason": "invalid_amount"}
    econ = state.setdefault("economy", {})
    cash = _clamp_int(econ.get("cash", 0), 0, 10_000_000_000, 0)
    bank = _clamp_int(econ.get("bank", 0), 0, 10_000_000_000, 0)
    if bank < amt:
        return {"ok": False, "reason": "not_enough_bank"}
    econ["bank"] = bank - amt
    econ["cash"] = cash + amt
    state.setdefault("world_notes", []).append(f"[Bank] WITHDRAW {amt} bank→cash")
    return {"ok": True, "amount": amt}


def bank_aml_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Read-only AML / deposit window summary for UI (mirrors economy.py window logic)."""
    econ = state.get("economy", {}) or {}
    meta = state.get("meta", {}) or {}
    day = int(meta.get("day", 1) or 1)
    t = int(meta.get("time_min", 0) or 0)
    threshold = int(econ.get("aml_threshold", 10000) or 10000)
    deposits = econ.get("deposit_log", []) or []
    window_hours = 72
    now_abs_h = day * 24 + (t // 60)
    total = 0.0
    if isinstance(deposits, list):
        for d in deposits:
            if not isinstance(d, dict):
                continue
            abs_h = int(d.get("day", 0)) * 24 + (int(d.get("time_min", 0)) // 60)
            if now_abs_h - abs_h <= window_hours:
                total += float(d.get("amount", 0))
    recent: list[dict[str, Any]] = []
    if isinstance(deposits, list):
        for d in deposits[-8:]:
            if isinstance(d, dict):
                recent.append({"day": d.get("day"), "time_min": d.get("time_min"), "amount": d.get("amount")})
    return {
        "aml_status": str(econ.get("aml_status", "CLEAR") or "CLEAR"),
        "aml_threshold": threshold,
        "deposit_window_72h_total": round(total, 2),
        "deposit_window_over_threshold": total > float(threshold),
        "recent_deposits": recent,
    }
