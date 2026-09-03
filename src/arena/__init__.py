"""Agent Arena — a headless harness for agent-controlled combatants.

This package lets an autonomous agent (an LLM, or a scripted policy) drive an
entity through the existing :class:`~src.combat.combat_system.CombatSystem`
referee: it reads an *observation* of the battle, sees its *legal actions*, and
issues chosen actions that the engine validates and applies.

It is a **driver over the engine, not a second engine** — nothing here resolves
combat itself; it assembles what an agent may know and may do, then calls the
same ``CombatSystem`` methods the web layer uses. See ``docs/AGENT_ARENA_PLAN.md``.
"""
