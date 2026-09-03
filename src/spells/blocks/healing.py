"""The healing block — the superset of the legacy ``healing`` step and ``HealTarget``.

Heals the current target (or the caster with ``target: "self"``) by either an
``amount`` expression or a ``formula`` + optional ``bonus``. Mirrors the legacy
pipeline's healing step; ``HealTarget``'s formula+bonus case is this block with
``amount`` omitted.
"""

from __future__ import annotations

from src.combat.events import EventType
from src.combat.event_data import HealingAppliedData
from src.utils.dice import roll_formula
from src.rules.expressions import resolve

from ..contract import BlockContract, Field, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY
from .targeting import TARGET_FIELD, select_target


def healing(block: Block, inv: Invocation) -> None:
    """Heal a target by an ``amount`` expression, or a ``formula`` + ``bonus``."""
    target = select_target(block, inv)
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
        # One of `amount`/`formula` is required in practice — the handler returns
        # silently when neither is present — but that is an either/or constraint
        # `Field.required` cannot express. See SPELL_SYSTEM_REMAINING §4.
        fields=(
            TARGET_FIELD,
            Field("amount", "expr",
                  description="Expression for a computed amount; takes precedence "
                              "over formula."),
            Field("formula", "formula",
                  description="Dice formula rolled at cast time."),
            Field("bonus", "expr",
                  description="Added to the formula roll (a number or an expression)."),
        ),
        reads=("damage_dealt",),
        writes=("healing_amount",),
        # SINGLE by default; a `target: "self"` instance acts on the caster and
        # is exempt from the set-cardinality check (handled when arity is enforced).
        target_arity=TargetArity.SINGLE,
    ),
)
