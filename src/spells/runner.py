"""Block execution — dispatch a program of blocks over an invocation.

The low layer under the evaluator, kept separate so that block handlers which run
sub-programs (an iterator's ``then``, a lifetime's ``then``, a trigger's ``then``)
can import it **without** importing the evaluator — the evaluator imports the
blocks package (to register the catalogue), so a block that needed the evaluator
would close an import cycle. Everything here dispatches through the registry only.

- ``run_block`` / ``run_program`` — pure dispatch, honouring each block's
  install-time ``condition`` guard, recursing into ``then`` via the handlers.
- ``run_target`` — runs a program over one already-built invocation with the
  ``SPELL_HIT`` / ``DAMAGE_DEALT`` event orchestration the legacy pipeline
  performs (emitted here, not smeared across blocks, so both engines agree). The
  single per-target execution primitive shared by the flat path, each iterator
  element, and — minus the orchestration — trigger firings.
"""

from __future__ import annotations

from typing import List

from src.combat.events import EventType
from src.combat.event_data import SpellHitData, DamageDealtData
from src.rules.expressions import evaluate

from .block import Block
from .context import Invocation, InvocationResult, eval_context
from .registry import BlockRegistry, REGISTRY


def _condition_passes(block: Block, inv: Invocation) -> bool:
    """Evaluate a block's optional install-time ``condition`` guard.

    Returns True when there is no condition. A condition that evaluates falsy — or
    raises — skips the block (matching the legacy pipeline's fail-safe skip).
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


def run_target(
    inv: Invocation, program: List[Block], registry: BlockRegistry = REGISTRY
) -> InvocationResult:
    """Run a per-target ``program`` over *inv*, with SPELL_HIT/DAMAGE_DEALT ordering.

    ``SPELL_HIT`` is emitted once just before the first non-gate (effect) block —
    by block category, independent of whether that block is condition-skipped —
    and ``DAMAGE_DEALT`` after, if any damage landed; matching the legacy
    pipeline's emission points so entity-effect subscribers behave identically.
    """
    for block in program:
        reg = registry.get(block.type)
        if not reg.contract.is_gate and not inv.spell_hit_emitted:
            _emit_spell_hit(inv)
        run_block(block, inv, registry)

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
