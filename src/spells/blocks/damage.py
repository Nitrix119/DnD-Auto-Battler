"""The damage block — the superset of the legacy ``damage`` step and ``DealDamage``.

Keeps every richer semantic of the pipeline ``damage`` step: ``requires_hit``
gating, slot-based ``scaling`` (stage 2), crit-doubling, ``save_result`` half/no
damage, and routing through the DamageProcessor so resistance/immunity apply.
``DealDamage``'s flat-formula case is just this block with those options omitted —
one block, not two.

(``roll_once`` AoE seeding is intentionally not here yet: it is a property of the
iterator that fans a rolled total across a target set, and lands with the
targeting/iterator blocks. Single-target and legacy-fanned damage need it not.)
"""

from __future__ import annotations

from src.models.damage import Damage, DamageType
from src.utils.dice import roll_formula, multiply_formula

# Reused pure helper (slot-based dice scaling). Moves into this package when the
# legacy pipeline is retired; imported here to keep the two engines identical.
from src.combat.effect_pipeline import effective_damage_formula

from ..contract import BlockContract, TargetArity
from ..context import Invocation
from ..block import Block
from ..registry import REGISTRY


def damage(block: Block, inv: Invocation) -> int:
    """Apply typed damage to the current target. Returns the amount dealt."""
    ctx = inv.context

    if block.get("requires_hit") and not ctx["hit"]:
        return 0

    formula = effective_damage_formula(
        {"formula": block.get("formula", ""), "scaling": block.get("scaling")},
        ctx.get("slot_level"),
    )
    if ctx["critical_hit"] and formula:
        formula = multiply_formula(formula, 2)
    amount = roll_formula(formula) if formula else 0
    ctx["damage_rolled"] = ctx.get("damage_rolled", 0) + amount

    save_result = block.get("save_result")
    if save_result and ctx["save_roll"] is not None and ctx["save_success"]:
        on_success = save_result.get("on_success")
        if on_success == "half_damage":
            amount = amount // 2
        elif on_success == "no_damage":
            amount = 0

    if amount <= 0:
        return 0

    dtype = DamageType[str(block.get("damage_type", "GENERIC")).upper()]
    dealt = inv.damage_processor.apply_damage(
        inv.target, [Damage(dtype, amount)],
        source=inv.caster, action_name=getattr(inv.action, "name", None),
        emit_dealt=False,
    )
    if dealt > 0:
        inv.dealt_damages.append(Damage(dtype, min(amount, dealt)))
    ctx["damage_dealt"] = ctx["damage_dealt"] + dealt
    return dealt


REGISTRY.register(
    "damage",
    damage,
    BlockContract(
        reads=("hit", "save_success", "save_roll", "critical_hit", "slot_level"),
        writes=("damage_dealt", "damage_rolled"),
        target_arity=TargetArity.SINGLE,
    ),
)
