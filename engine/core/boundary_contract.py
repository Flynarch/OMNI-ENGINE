"""OMNI-ENGINE layer boundary contract (Interpreter → Engine → Narrator).

D1: The LLM intent resolver only proposes structured intent; it MUST NOT mutate save state.
D2: The deterministic engine (pipeline, modifiers, systems) is the sole authority for
    rolls, outcomes, economy, trace, inventory, and NPC mechanical updates.
D3: The narrator LLM consumes `build_turn_package` facts only; prose MUST NOT invent
    mechanical results or contradict the roll package / action_ctx.
D4: Renderer (`display/renderer.py`) shows numeric HUD; narration avoids raw stat dumps
    per architecture skill.
D5: Feature evolution is offline (proposal → patch → verify → review), never runtime
    self-modifying code in player sessions.
"""
