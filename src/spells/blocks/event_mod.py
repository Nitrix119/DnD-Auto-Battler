"""Event-modifier blocks — reach back onto the in-flight ``CombatEvent``.

Every block built before this one is a *forward* effect: it writes state (damage,
healing, a condition, a grant) or subscribes a rider. Event-modifier blocks are the
one category that changes a **live** event the resolver is mid-way through emitting
— ``modify_damage`` / ``grant_advantage`` / ``force_critical`` / ``cancel``. They are
the primitive the global combat rules (``rules/global/*`` — resistance, crit,
concentration) are built on.

The contract (settled — see the plan §5, "live-event mutation contract"): an
event-modifier block fires inside a ``trigger`` block, which supplies the live
event on ``Invocation.live_event``; the block writes directly onto
``live_event.data`` (or ``live_event.cancelled``) — which is what the emitter checks
after each handler. Run outside a trigger there is no live event to touch, so the
block no-ops (a fail-safe, matching the engine's skip-don't-crash stance). Contract
flag ``mutates_event=True`` marks the category.

This module ships the pure event-flag modifiers — ``modify_damage`` (damage
resistance/immunity/vulnerability rules), ``force_critical`` (nat-20/nat-1 crit
rules), and ``grant_advantage`` / ``grant_disadvantage`` / ``cancel`` (the entire
condition library: blinded, frightened, invisible, paralysed, restrained, stunned,
…). The side-effecting members (``force_concentration_check``, ``refill_resources``)
are forward effects that fire *on* an event rather than mutating it, and live in
``global_effects.py``.
"""

from __future__ import annotations

from src.models.damage import DamageType
from src.rules.expressions import resolve

from ..contract import BlockContract, Field, TargetArity
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


def force_critical(block: Block, inv: Invocation) -> None:
    """Force the in-flight attack to resolve as a critical hit (or miss).

    The block form of ``effects.force_critical_hit`` / ``force_critical_miss``
    folded into one: ``outcome: "hit"`` (default) sets ``critical_hit`` on the live
    ``ATTACK_ROLLED``/``ATTACK_DECLARED`` event, ``outcome: "miss"`` sets
    ``critical_miss`` — the flags ``CombatSystem`` reads after emitting. The caller's
    ``when`` guard decides the trigger (a nat 20, a paralysed target, …).
    """
    event = inv.live_event
    if event is None:
        return
    outcome = str(block.get("outcome", "hit")).lower()
    key = "critical_miss" if outcome == "miss" else "critical_hit"
    event.data[key] = True


def grant_advantage(block: Block, inv: Invocation) -> None:
    """Flag advantage on the live roll event (``ATTACK_DECLARED`` /
    ``SAVING_THROW_DECLARED``). The block form of ``effects.grant_advantage`` —
    how blinded/invisible/paralysed/… grant advantage to or against a creature.
    """
    event = inv.live_event
    if event is None:
        return
    event.data["advantage"] = True


def grant_disadvantage(block: Block, inv: Invocation) -> None:
    """Flag disadvantage on the live roll event (the mirror of
    :func:`grant_advantage`). Advantage and disadvantage are independent flags —
    both set, they cancel per 5e — so these are two blocks, not one parametrised.
    """
    event = inv.live_event
    if event is None:
        return
    event.data["disadvantage"] = True


def cancel(block: Block, inv: Invocation) -> None:
    """Cancel the in-flight action by setting ``cancelled`` on the live event.

    The block form of ``effects.cancel_event`` — how incapacitated/paralysed/
    stunned/… stop an action outright. Sets the flag on the ``CombatEvent``
    itself (not its ``data``), which is what the emitter checks after each handler.
    """
    event = inv.live_event
    if event is None:
        return
    event.cancelled = True


def _event_modifier(*fields: Field) -> BlockContract:
    """An event-modifier contract: mutates the live event, takes no target."""
    return BlockContract(
        fields=fields, target_arity=TargetArity.SINGLE, mutates_event=True
    )


REGISTRY.register("modify_damage", modify_damage, _event_modifier(
    # Mandatory in practice: absent, `float(resolve(None, ...))` raises.
    Field("multiplier", "expr", required=True,
          description="Scale matching damage by this (0.5 resist, 0 immune, 2 vulnerable)."),
    Field("damage_type", "enum", enum=DamageType,
          description="Only scale this damage type; omitted scales every entry."),
))
REGISTRY.register("force_critical", force_critical, _event_modifier(
    Field("outcome", "choice", choices=("hit", "miss"),
          description="Force a critical hit or a critical miss. Default 'hit'."),
))
REGISTRY.register("grant_advantage", grant_advantage, _event_modifier())
REGISTRY.register("grant_disadvantage", grant_disadvantage, _event_modifier())
REGISTRY.register("cancel", cancel, _event_modifier())
