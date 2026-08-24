"""The block evaluator — runs a program of blocks over an invocation.

Two layers:

- ``run_program`` / ``run_block`` — pure block execution: dispatch each block to
  its registered handler by name (no ``if/elif``), recursing into ``then``
  sub-programs. Reused by iterator/trigger blocks (later slices).
- ``resolve`` — top-level spell resolution: seeds the invocation, runs the
  program with the ``SPELL_HIT`` / ``DAMAGE_DEALT`` event orchestration the
  legacy pipeline performs, and returns an :class:`InvocationResult`.

The event ordering (SPELL_HIT before the first non-gate block; DAMAGE_DEALT after
damage) is reproduced here so entity-effect subscribers behave identically to the
old engine — this is the parity target, kept in the evaluator rather than smeared
across blocks.
"""

from __future__ import annotations

from typing import Any, List, Optional

from src.combat.events import EventType
from src.combat.event_data import SpellHitData, DamageDealtData

from . import blocks as _blocks  # noqa: F401  (import registers the built-in blocks)
from .block import Block
from .context import Invocation, InvocationResult, seed_context
from .registry import BlockRegistry, REGISTRY


def run_block(block: Block, inv: Invocation, registry: BlockRegistry = REGISTRY) -> None:
    """Dispatch one block to its registered handler."""
    registry.get(block.type).handler(block, inv)


def run_program(
    program: List[Block], inv: Invocation, registry: BlockRegistry = REGISTRY
) -> None:
    """Run a sub-program: dispatch each block in order. Used for ``then`` bodies."""
    for block in program:
        run_block(block, inv, registry)


def resolve(
    caster: Any,
    target: Any,
    action: Any,
    program: List[Block],
    *,
    event_bus: Any,
    damage_processor: Any,
    rule_engine: Any = None,
    slot_level: Optional[int] = None,
    registry: BlockRegistry = REGISTRY,
) -> InvocationResult:
    """Resolve a block program for one caster/target pair.

    Returns an :class:`InvocationResult` (field-compatible with the legacy
    ``PipelineResult``).
    """
    if slot_level is None:
        slot_level = getattr(action, "spell_level", 0) or 0

    inv = Invocation(
        caster=caster,
        target=target,
        action=action,
        event_bus=event_bus,
        damage_processor=damage_processor,
        rule_engine=rule_engine,
        slot_level=slot_level,
        context=seed_context(slot_level),
    )

    for block in program:
        reg = registry.get(block.type)
        # Emit SPELL_HIT once, just before the first non-gate (effect) block.
        if not reg.contract.is_gate and not inv.spell_hit_emitted:
            _emit_spell_hit(inv)
        reg.handler(block, inv)

    if not inv.spell_hit_emitted:
        _emit_spell_hit(inv)

    if not inv.damage_dealt_emitted and inv.context["damage_dealt"] > 0:
        _emit_damage_dealt(inv)

    return InvocationResult.from_invocation(inv)


def _emit_spell_hit(inv: Invocation) -> None:
    inv.event_bus.emit(
        EventType.SPELL_HIT,
        SpellHitData(
            caster=inv.caster,
            defender=inv.target,
            action=inv.action,
            roll=inv.context["attack_total"],
            save_success=inv.context["save_success"],
            save_roll=inv.context["save_roll"],
        ),
    )
    inv.spell_hit_emitted = True


def _emit_damage_dealt(inv: Invocation) -> None:
    inv.event_bus.emit(
        EventType.DAMAGE_DEALT,
        DamageDealtData(
            defender=inv.target,
            damage_list=inv.dealt_damages,
            total=inv.context["damage_dealt"],
            source=inv.caster,
            action_name=getattr(inv.action, "name", None),
        ),
    )
    inv.damage_dealt_emitted = True
