"""Domain plugin hook surface (register pre-roll / post-roll adapters without forking pipeline).

Plugins are optional callables looked up by roll_domain; default registry is empty.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

PreRollFn = Callable[[dict[str, Any], dict[str, Any]], None]
PostRollFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]

_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_domain_plugin(
    domain: str,
    *,
    pre_roll: Optional[PreRollFn] = None,
    post_roll: Optional[PostRollFn] = None,
) -> None:
    key = str(domain or "").strip().lower()
    if not key:
        return
    _REGISTRY[key] = {"pre_roll": pre_roll, "post_roll": post_roll}


def run_pre_roll_plugin(state: dict[str, Any], action_ctx: dict[str, Any]) -> None:
    dom = str(action_ctx.get("roll_domain", action_ctx.get("domain", "")) or "").lower()
    plug = _REGISTRY.get(dom)
    if not plug:
        return
    fn = plug.get("pre_roll")
    if callable(fn):
        fn(state, action_ctx)


def run_post_roll_plugin(state: dict[str, Any], action_ctx: dict[str, Any], roll_pkg: dict[str, Any]) -> None:
    dom = str(action_ctx.get("roll_domain", action_ctx.get("domain", "")) or "").lower()
    plug = _REGISTRY.get(dom)
    if not plug:
        return
    fn = plug.get("post_roll")
    if callable(fn):
        fn(state, action_ctx, roll_pkg)
