"""The damage block — the superset of the legacy ``damage`` step and ``DealDamage``.

Keeps every richer semantic of the pipeline ``damage`` step: ``requires_hit``
gating, slot-based ``scaling`` (stage 2), crit-doubling, ``save_result`` half/no
damage, and routing through the DamageProcessor so resistance/immunity apply.
``DealDamage``'s flat-formula case is just this block with those options omitted —
one block, not two.

``roll_once`` AoE sharing is the *iterator's* property, not this block's: the
iterator (``blocks/iterators.py``) rolls the shared total once and seeds it here
via ``context["_shared_rolls"]``; this block only consumes a seeded total when one
is present. Single-target and non-shared damage roll normally.
"""

from __future__ import annotations

from src.models.damage import Damage, DamageType
from src.utils.dice import roll_formula, multiply_formula
from src.rules.expressions import evaluate

# Reused pure helper (slot-based dice scaling). Moves into this package when the
# legacy pipeline is retired; imported here to keep the two engines identical.
from src.combat.effect_pipeline import effective_damage_formula

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY


def _resolve_damage_type(raw, inv: Invocation) -> DamageType:
    """Resolve a block's ``damage_type`` to a DamageType member.

    A literal enum name (``"FIRE"``) is looked up directly — the common case, no
    expression evaluated. Anything else is treated as a sandboxed expression
    evaluated at run time against the invocation, so a rider can deal *the
    weapon's own type* (``event.action.primary_damage_type``), unknown until the
    on-hit trigger fires. Falls back to ``GENERIC`` if neither resolves.
    """
    if isinstance(raw, DamageType):
        return raw
    name = str(raw)
    try:
        return DamageType[name.upper()]
    except KeyError:
        pass
    try:
        value = evaluate(name, eval_context(inv))
    except Exception:
        return DamageType.GENERIC
    if isinstance(value, DamageType):
        return value
    try:
        return DamageType[str(value).upper()]
    except KeyError:
        return DamageType.GENERIC


def damage(block: Block, inv: Invocation) -> int:
    """Apply typed damage to the current target. Returns the amount dealt."""
    ctx = inv.context

    if block.get("requires_hit") and not ctx["hit"]:
        return 0

    # A ``roll_once`` block in an iterator's ``then`` body shares one rolled total
    # across the whole target set; the iterator pre-rolled it (with scaling) and
    # seeded it here, keyed by this block's identity. Consume the shared total as
    # given — no re-roll, no crit-doubling (an AoE save has no crit) — matching
    # the legacy pre-rolled path exactly.
    shared = ctx.get("_shared_rolls")
    if shared is not None and id(block) in shared:
        amount = shared[id(block)]
    else:
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

    dtype = _resolve_damage_type(block.get("damage_type", "GENERIC"), inv)
    dealt = inv.damage_processor.apply_damage(
        inv.target,
        [Damage(dtype, amount)],
        source=inv.caster,
        action_name=getattr(inv.action, "name", None),
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
