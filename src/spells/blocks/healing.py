"""The healing block — the superset of the legacy ``healing`` step and ``HealTarget``.

Heals the current target (or the caster with ``target: "caster"``) by either an
``amount`` expression or a ``formula`` + optional ``bonus``. Mirrors the legacy
pipeline's healing step; ``HealTarget``'s formula+bonus case is this block with
``amount`` omitted.
"""

from __future__ import annotations

from src.combat.events import EventType
from src.combat.event_data import HealingAppliedData
from src.utils.dice import roll_formula
from src.rules.expressions import resolve

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY


def healing(block: Block, inv: Invocation) -> None:
    """Heal a target by an ``amount`` expression, or a ``formula`` + ``bonus``."""
    target = inv.caster if block.get("target") == "caster" else inv.target
    ec = eval_context(inv)

    amount_expr = block.get("amount")
    formula = block.get("formula")
    bonus_spec = block.get("bonus", 0)

    if amount_expr is not None:
        try:
            amount = int(resolve(amount_expr, ec))
        except Exception:
            return
    elif formula:
        amount = roll_formula(formula)
        try:
            bonus = int(resolve(bonus_spec, ec)) if isinstance(bonus_spec, str) else int(bonus_spec)
        except Exception:
            bonus = 0
        amount += bonus
    else:
        return

    if amount <= 0:
        return

    target.heal(amount)
    inv.event_bus.emit(EventType.HEALING_APPLIED, HealingAppliedData(target=target, amount=amount))
    inv.context["healing_amount"] = amount
    inv.healing_total += amount
    inv.healed_entity = target


REGISTRY.register(
    "healing",
    healing,
    BlockContract(
        reads=("damage_dealt",),
        writes=("healing_amount",),
        # SINGLE by default; a `target: "caster"` instance acts on the caster and
        # is exempt from the set-cardinality check (handled when arity is enforced).
        target_arity=TargetArity.SINGLE,
    ),
)
