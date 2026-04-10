from __future__ import annotations

from typing import Any, Callable

from display.renderer import console


def handle_scene_commands(
    state: dict[str, Any],
    cmd: str,
    *,
    run_pipeline: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    scene_blocks_command: Callable[[dict[str, Any], str], bool],
) -> bool:
    up = cmd.upper()
    if scene_blocks_command(state, up):
        console.print("[yellow]Scene active. Use: SCENE | SCENE OPTIONS | SCENE <action>[/yellow]")
        return True

    if up == "SCENE" or up.startswith("SCENE "):
        parts = cmd.split(maxsplit=2)
        sub = parts[1].strip().lower() if len(parts) >= 2 else "status"
        sc = state.get("active_scene")
        if not isinstance(sc, dict) or not sc:
            console.print("[yellow]SCENE: (none active)[/yellow]")
            return True
        if sub in ("status", "info"):
            console.print("[bold]SCENE[/bold]")
            console.print(f"- type={sc.get('scene_type','-')} phase={sc.get('phase','-')}")
            exp = sc.get("expires_at") if isinstance(sc.get("expires_at"), dict) else {}
            if isinstance(exp, dict) and exp:
                console.print(f"- deadline: day{exp.get('day','?')} t{exp.get('time_min','?')}")
            return True
        if sub in ("options", "opts"):
            opts = sc.get("next_options") or []
            if not isinstance(opts, list) or not opts:
                console.print("[yellow]SCENE OPTIONS: (none)[/yellow]")
                return True
            console.print("[bold]SCENE OPTIONS[/bold]")
            for o in opts[:12]:
                if isinstance(o, str):
                    console.print(f"- {o}")
            return True

        act = sub
        from engine.systems.scenes import advance_scene

        action_ctx: dict[str, Any] = {
            "action_type": "instant",
            "domain": "other",
            "normalized_input": f"scene {act}",
            "instant_minutes": 2,
            "stakes": "low",
            "scene_action": act,
        }
        if len(parts) >= 3 and isinstance(parts[2], str) and parts[2].strip():
            action_ctx["scene_arg"] = parts[2].strip()
            if act in ("bribe",):
                try:
                    action_ctx["bribe_amount"] = int(parts[2].strip())
                except Exception:
                    action_ctx["bribe_amount"] = 0
        res = advance_scene(state, action_ctx)
        if not bool(res.get("ok")):
            console.print(f"[red]SCENE failed[/red] {res.get('reason','error')}")
            return True
        if act in ("wait",) and bool(res.get("ok")):
            action_ctx["instant_minutes"] = 5
        try:
            run_pipeline(state, action_ctx)
        except Exception:
            pass
        if bool(res.get("ended")):
            console.print("[green]SCENE resolved[/green]")
        else:
            console.print(f"[green]SCENE OK[/green] phase={res.get('phase_after', '-')}")
        for m in (res.get("messages") or [])[:4]:
            if isinstance(m, str) and m.strip():
                console.print(f"[dim]- {m}[/dim]")
        return True

    return False

