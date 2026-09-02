"""Forward blocks the global combat rules fire.

The event-modifier blocks (``modify_damage`` / ``force_critical`` / …) *mutate* the
in-flight event; these two instead fire **on** an event and mutate an entity:

- ``force_concentration_check`` — the concentration-break rule (on ``DAMAGE_DEALT``):
  roll a CON save against a ``dc`` expression and, on a failure, end the target's
  concentration (disposing its block-engine lifetime scope identity-first).
- ``refill_resources`` — the per-turn action-economy rule (on ``TURN_START``): reset
  the target's resources to its stat-block defaults.

They are ordinary forward blocks acting on the current target; a global rule's
trigger rebinds that target to the event entity (``target: "event.defender"`` /
``"event.entity"``). Nothing about them is intrinsically "global"; they
live together here because the two global rules are their only callers today, and can
move into ``state.py`` if a spell ever reuses them.
"""

from __future__ import annotations

from src.rules.expressions import resolve
from src.utils.dice import roll_d20

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY


def _target(block: Block, inv: Invocation):
    return inv.caster if block.get("target") == "caster" else inv.target


def force_concentration_check(block: Block, inv: Invocation) -> None:
    """Force the target's CON save; on a failure, end its concentration.

    The block form of ``effects.force_concentration_check``. ``dc`` is an expression
    evaluated at fire time against the event (e.g. ``max(10, event.total // 2)``).
    ``Entity.end_concentration`` disposes a block-engine concentration scope (Shield
    of Faith, Vampiric Touch, Haste) and cleans a legacy string tag — one call covers
    both, so this drives the whole concentration teardown on the new engine.
    """
    target = _target(block, inv)
    dc = int(resolve(block.get("dc", 0), eval_context(inv)))
    con_bonus = target.stat_block.get_saving_throw_bonus("constitution")
    if roll_d20() + con_bonus < dc:
        target.end_concentration()


def refill_resources(block: Block, inv: Invocation) -> None:
    """Reset the target's action resources to its stat-block defaults."""
    _target(block, inv).refill_resources()


_FORWARD_CONTRACT = BlockContract(target_arity=TargetArity.SINGLE)

REGISTRY.register("force_concentration_check", force_concentration_check, _FORWARD_CONTRACT)
REGISTRY.register("refill_resources", refill_resources, _FORWARD_CONTRACT)
