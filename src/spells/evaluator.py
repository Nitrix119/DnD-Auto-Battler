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

from typing import Any, Dict, List, Optional

from src.combat.events import EventType
from src.combat.event_data import SpellHitData, DamageDealtData
from src.rules.expressions import evaluate

from . import blocks as _blocks  # noqa: F401  (import registers the built-in blocks)
from .block import Block
from .contract import TargetArity
from .context import Invocation, InvocationResult, eval_context, seed_context
from .lint import lint_program
from .registry import BlockRegistry, REGISTRY


def _condition_passes(block: Block, inv: Invocation) -> bool:
    """Evaluate a block's optional ``condition`` guard.

    Returns True when there is no condition. A condition that evaluates falsy —
    or raises — skips the block (matching the legacy pipeline's fail-safe skip).
    """
    condition = block.get("condition")
    if condition is None:
        return True
    try:
        return bool(evaluate(condition, eval_context(inv)))
    except Exception:
        return False


def run_block(
    block: Block, inv: Invocation, registry: BlockRegistry = REGISTRY
) -> None:
    """Dispatch one block to its handler, honouring its ``condition`` guard."""
    reg = registry.get(block.type)
    if not _condition_passes(block, inv):
        return
    reg.handler(block, inv)


def run_program(
    program: List[Block], inv: Invocation, registry: BlockRegistry = REGISTRY
) -> None:
    """Run a sub-program: dispatch each block in order. Used for ``then`` bodies."""
    for block in program:
        run_block(block, inv, registry)


def _has_set_consumer(program: List[Block], registry: BlockRegistry) -> bool:
    """True if the program's top level consumes a target set (an iterator block).

    Set-consuming programs own their own fan-out (an iterator loops the set);
    everything else is a per-target program the harness runs once per target.
    """
    return any(
        registry.get(b.type).contract.target_arity is TargetArity.SET for b in program
    )


def _run_one_target(
    caster: Any,
    target: Any,
    action: Any,
    program: List[Block],
    *,
    event_bus: Any,
    damage_processor: Any,
    rule_engine: Any = None,
    slot_level: Optional[int] = None,
    shared_rolls: Optional[Dict[int, int]] = None,
    registry: BlockRegistry = REGISTRY,
) -> InvocationResult:
    """Run a per-target program over one caster/target pair, with the same
    ``SPELL_HIT`` / ``DAMAGE_DEALT`` event orchestration the legacy pipeline
    performs. The single execution primitive shared by the flat single-target
    path and each element of an iterator.

    ``shared_rolls`` seeds pre-rolled ``roll_once`` totals (keyed by ``id(block)``)
    an iterator computed once for the whole set — see :mod:`.blocks.iterators`.
    """
    inv = Invocation(
        caster=caster,
        target=target,
        action=action,
        event_bus=event_bus,
        damage_processor=damage_processor,
        rule_engine=rule_engine,
        slot_level=slot_level,
        context=seed_context(slot_level or 0),
    )
    if shared_rolls:
        inv.context["_shared_rolls"] = shared_rolls

    for block in program:
        reg = registry.get(block.type)
        # Emit SPELL_HIT once, just before the first non-gate (effect) block —
        # by block category, independent of whether that block is condition-skipped
        # (matches the legacy pipeline's emission point).
        if not reg.contract.is_gate and not inv.spell_hit_emitted:
            _emit_spell_hit(inv)
        run_block(block, inv, registry)

    if not inv.spell_hit_emitted:
        _emit_spell_hit(inv)

    if not inv.damage_dealt_emitted and inv.context["damage_dealt"] > 0:
        _emit_damage_dealt(inv)

    return InvocationResult.from_invocation(inv)


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
    """Resolve a per-target block program for one caster/target pair.

    Returns an :class:`InvocationResult` (field-compatible with the legacy
    ``PipelineResult``). For set-targeted spells (AoE, multi-target) use
    :func:`resolve_program`, which fans out over the target set.
    """
    if slot_level is None:
        slot_level = getattr(action, "spell_level", 0) or 0
    return _run_one_target(
        caster,
        target,
        action,
        program,
        event_bus=event_bus,
        damage_processor=damage_processor,
        rule_engine=rule_engine,
        slot_level=slot_level,
        registry=registry,
    )


def resolve_program(
    caster: Any,
    targets: List[Any],
    action: Any,
    program: List[Block],
    *,
    event_bus: Any,
    damage_processor: Any,
    rule_engine: Any = None,
    slot_level: Optional[int] = None,
    registry: BlockRegistry = REGISTRY,
) -> List[InvocationResult]:
    """Resolve a program over a whole target set — the fan-out entry point.

    - A **set-consuming** program (top-level iterator, e.g. ``for_each_target``)
      is run once on a root invocation; the iterator fans over ``targets`` and
      collects one result per element (rolling any shared ``roll_once`` total once).
    - A **per-target** program (flat single-target) is run once per target here.

    Returns one :class:`InvocationResult` per resolved target, in order.
    """
    if slot_level is None:
        slot_level = getattr(action, "spell_level", 0) or 0

    set_consumer = _has_set_consumer(program, registry)
    lint_program(program, target_is_set=set_consumer, registry=registry)

    if not set_consumer:
        return [
            _run_one_target(
                caster,
                t,
                action,
                program,
                event_bus=event_bus,
                damage_processor=damage_processor,
                rule_engine=rule_engine,
                slot_level=slot_level,
                registry=registry,
            )
            for t in targets
        ]

    # The root's `target` is a placeholder (the caster): no block reads it — the
    # lint above guarantees only a set-consuming iterator runs here, and iterators
    # fan over `targets`. Each element gets its own real per-target invocation.
    root = Invocation(
        caster=caster,
        target=caster,
        action=action,
        event_bus=event_bus,
        damage_processor=damage_processor,
        rule_engine=rule_engine,
        slot_level=slot_level,
        context=seed_context(slot_level),
        targets=list(targets),
    )
    run_program(program, root, registry)
    return root.results


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
