"""Event-modifier blocks — reach back onto the in-flight ``CombatEvent``.

Every block built before this one is a *forward* effect: it writes state (damage,
healing, a condition, a grant) or subscribes a rider. Event-modifier blocks are the
one category that changes a **live** event the resolver is mid-way through emitting
— the block equivalent of the rule engine's ``ModifyDamage`` / ``GrantAdvantage`` /
``ForceCriticalHit`` / ``Cancel`` effects (``src/rules/effects.py``). They are the
last vocabulary the block catalogue lacked, and the primitive that lets the global
combat rules (``rules/global/*`` — resistance, crit, concentration) migrate off
``BUILTIN_EFFECTS`` (plan §4.7).

The contract (settled — see the plan §5, "live-event mutation contract"): an
event-modifier block fires inside a ``trigger`` block, which supplies the live
event on ``Invocation.live_event``; the block writes directly onto
``live_event.data`` (or ``live_event.cancelled``) — exactly what the legacy handler
does, so parity is line-for-line. Run outside a trigger there is no live event to
touch, so the block no-ops (a fail-safe, matching the engine's skip-don't-crash
stance). Contract flag ``mutates_event=True`` marks the category.

This module ships ``modify_damage`` first — the block behind the damage
resistance/immunity/vulnerability rules; its siblings (``grant_advantage`` /
``force_critical`` / ``cancel`` / …) land as each remaining global rule migrates.
"""

from __future__ import annotations

from src.models.damage import DamageType
from src.rules.expressions import resolve

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY


def modify_damage(block: Block, inv: Invocation) -> None:
    """Scale the amounts on the live ``DAMAGE_INCOMING`` event in place.

    The block form of ``effects.modify_damage``: multiply each entry of the
    event's ``damage_list`` by ``multiplier`` (0.5 resistance, 0 immunity, 2.0
    vulnerability). An optional ``damage_type`` name restricts the change to
    matching entries; absent, every entry is scaled (the caller's ``when`` guard
    having already decided the event qualifies).
    """
    event = inv.live_event
    if event is None:
        # No live event to reach (run outside a trigger) — nothing to modify.
        return
    multiplier = float(resolve(block.get("multiplier"), eval_context(inv)))
    filter_type = block.get("damage_type")
    ftype = (
        DamageType[str(filter_type).upper()] if filter_type is not None else None
    )
    for dmg in event.data.get("damage_list", []):
        if ftype is not None and dmg.damage_type != ftype:
            continue
        dmg.amount = int(dmg.amount * multiplier)


REGISTRY.register(
    "modify_damage",
    modify_damage,
    BlockContract(target_arity=TargetArity.SINGLE, mutates_event=True),
)
