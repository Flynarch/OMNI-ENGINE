"""Runtime queue hints for intent v2 multi-step plans (deterministic meta only)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from engine.core.action_intent import apply_step_to_action_ctx


def _steps(action_ctx: dict[str, Any]) -> List[dict[str, Any]]:
    plan = action_ctx.get("intent_plan") if isinstance(action_ctx.get("intent_plan"), dict) else {}
    raw = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    return [s for s in raw if isinstance(s, dict)]


def _step_by_id(steps: List[dict[str, Any]], sid: str) -> Optional[dict[str, Any]]:
    for s in steps:
        if str(s.get("step_id", "") or "").strip() == sid:
            return s
    return None


def _roll_tri_state(roll_pkg: dict[str, Any]) -> Optional[bool]:
    """True success, False failure, None inconclusive / no-roll."""
    if bool(roll_pkg.get("ffci_feasibility_block")) or bool(roll_pkg.get("intent_plan_blocked")):
        return None
    oc = str(roll_pkg.get("outcome", "") or "").lower()
    if "no roll" in oc:
        return None
    if "fail" in oc or "auto fail" in oc:
        return False
    if "success" in oc or "critical" in oc:
        return True
    return None


def sync_plan_runtime_start(state: dict[str, Any], action_ctx: dict[str, Any], *, source: str) -> None:
    if int(action_ctx.get("intent_version", 1) or 1) != 2:
        return
    plan = action_ctx.get("intent_plan") if isinstance(action_ctx.get("intent_plan"), dict) else {}
    pid = str(plan.get("plan_id", "") or "").strip() or "plan"
    sid = str(action_ctx.get("step_now_id", "") or "").strip()
    if not sid:
        return
    meta = state.setdefault("meta", {})
    rt = meta.get("intent_runtime")
    if not isinstance(rt, dict):
        rt = {}
    prev_pid = str(rt.get("plan_id", "") or "")
    attempt = int(rt.get("attempt_count", 0) or 0) + 1 if prev_pid == pid else 1
    meta["intent_runtime"] = {
        "plan_id": pid[:80],
        "active_step_id": sid[:80],
        "status": "running",
        "source_turn": int(meta.get("turn", 0) or 0),
        "attempt_count": attempt,
        "last_failure_reason": str(rt.get("last_failure_reason", "") or "")[:120],
        "source": source[:40],
        "plan_snapshot": {
            "plan_id": pid[:80],
            "steps": deepcopy(_steps(action_ctx))[:8],
        },
    }


def advance_plan_runtime_after_roll(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    meta = state.setdefault("meta", {})
    rt = meta.get("intent_runtime")
    if not isinstance(rt, dict):
        return
    if str(rt.get("status", "")) != "running":
        return
    sid = str(rt.get("active_step_id", "") or "").strip()
    snap = rt.get("plan_snapshot")
    if not isinstance(snap, dict):
        return
    steps = snap.get("steps") if isinstance(snap.get("steps"), list) else []
    steps = [s for s in steps if isinstance(s, dict)]
    step = _step_by_id(steps, sid)
    if not step:
        return
    tri = _roll_tri_state(roll_pkg if isinstance(roll_pkg, dict) else {})
    if tri is None:
        meta["intent_runtime"] = rt
        return
    raw_links = step.get("on_success") if tri is True else step.get("on_failure")
    links = raw_links if isinstance(raw_links, list) else []
    if tri is False and not links:
        rt["last_failure_reason"] = "STEP_FAILED"
        rt["status"] = "blocked"
        rt["pending_next_step_id"] = ""
        meta["intent_runtime"] = rt
        return
    nxt = ""
    for ln in links[:6]:
        if not isinstance(ln, dict):
            continue
        when = str(ln.get("when", "always") or "always").lower()
        if tri is True and when not in ("always", "if_possible"):
            continue
        if tri is False and when not in ("always", "if_failed_roll", "if_blocked"):
            continue
        nxt = str(ln.get("next", "") or "").strip()
        if nxt:
            break
    if tri is True:
        if nxt and _step_by_id(steps, nxt):
            rt["pending_next_step_id"] = nxt[:80]
            rt["active_step_id"] = nxt[:80]
            rt["status"] = "pending"
            rt["last_failure_reason"] = ""
        else:
            rt["pending_next_step_id"] = ""
            rt["status"] = "done"
    else:
        if nxt and _step_by_id(steps, nxt):
            rt["pending_next_step_id"] = nxt[:80]
            rt["active_step_id"] = nxt[:80]
            rt["status"] = "pending"
            rt["last_failure_reason"] = str(rt.get("last_failure_reason", "") or "STEP_FAILED")[:120]
        else:
            rt["pending_next_step_id"] = ""
            rt["status"] = "blocked"
            rt["last_failure_reason"] = "STEP_FAILED"
    meta["intent_runtime"] = rt


def apply_pending_runtime_step(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    """If parser path but runtime pending, overlay queued step fields onto action_ctx."""
    meta = state.setdefault("meta", {})
    rt = meta.get("intent_runtime")
    if not isinstance(rt, dict):
        return
    if str(rt.get("status", "")) != "pending":
        return
    pend = str(rt.get("pending_next_step_id", "") or "").strip()
    if not pend:
        return
    snap = rt.get("plan_snapshot")
    if not isinstance(snap, dict):
        return
    steps = snap.get("steps") if isinstance(snap.get("steps"), list) else []
    steps = [s for s in steps if isinstance(s, dict)]
    st = _step_by_id(steps, pend)
    if not st:
        return
    action_ctx["intent_version"] = 2
    action_ctx["intent_plan"] = {"plan_id": snap.get("plan_id", "plan"), "steps": steps}
    action_ctx["step_now_id"] = pend
    apply_step_to_action_ctx(action_ctx, st)
    rt["status"] = "running"
    rt["active_step_id"] = pend
    meta["intent_runtime"] = rt
