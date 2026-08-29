"""The block evaluator — the two public entry points for resolving a spell.

Builds the top-level :class:`Invocation`(s) and runs the program:

- ``resolve`` — a per-target program for one caster/target pair.
- ``resolve_program`` — the fan-out entry: a set-consuming program (a top-level
  iterator) is run once on a root invocation that fans over the target set; a flat
  per-target program is run once per target.

Actually *running* a program lives in :mod:`.runner` (``run_target`` /
``run_program``), which block handlers reuse without importing this module — the
evaluator imports the blocks package to register the catalogue, so keeping the
run primitives out of here is what avoids an import cycle.
"""

from __future__ import annotations

from typing import Any, List, Optional

from . import blocks as _blocks  # noqa: F401  (import registers the built-in blocks)
from .block import Block
from .contract import TargetArity
from .context import Invocation, InvocationResult, seed_context
from .lint import lint_program
from .registry import BlockRegistry, REGISTRY
from .runner import run_program, run_target


def _has_set_consumer(program: List[Block], registry: BlockRegistry) -> bool:
    """True if the program's top level consumes a target set (an iterator block).

    Set-consuming programs own their own fan-out (an iterator loops the set);
    everything else is a per-target program the harness runs once per target.
    """
    return any(
        registry.get(b.type).contract.target_arity is TargetArity.SET for b in program
    )


def _new_invocation(
    caster: Any,
    target: Any,
    action: Any,
    *,
    event_bus: Any,
    damage_processor: Any,
    rule_engine: Any,
    slot_level: int,
    targets: Optional[List[Any]] = None,
) -> Invocation:
    return Invocation(
        caster=caster,
        target=target,
        action=action,
        event_bus=event_bus,
        damage_processor=damage_processor,
        rule_engine=rule_engine,
        slot_level=slot_level,
        context=seed_context(slot_level),
        targets=list(targets) if targets else [],
    )


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
    inv = _new_invocation(
        caster, target, action,
        event_bus=event_bus, damage_processor=damage_processor,
        rule_engine=rule_engine, slot_level=slot_level,
    )
    return run_target(inv, program, registry)


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

    # One cast-scoped invocation carries the caster/action/collaborators; it spawns
    # a child per target (flat) or is the root an iterator fans from (set). Its own
    # `target` is a caster placeholder no block reads (the lint guarantees only a
    # set-consuming iterator can run at the root, and iterators read `targets`).
    root = _new_invocation(
        caster, caster, action,
        event_bus=event_bus, damage_processor=damage_processor,
        rule_engine=rule_engine, slot_level=slot_level, targets=targets,
    )
    if not set_consumer:
        return [run_target(root.child(target=t), program, registry) for t in targets]

    run_program(program, root, registry)
    return root.results
