"""State blocks: apply_condition, add_modifier, grant_temporary_hp, add_resource.

These fold three legacy twins into one catalogue and, crucially, do the work
**directly** instead of the old pipeline's route (build a synthetic ``on_apply``
dict + a stub SPELL_HIT event, then call the rule engine's ``BUILTIN_EFFECTS``
handler). That bridge — the clearest symptom of the two-vocabulary seam — is gone
here: a state block just mutates the target and emits the same event.
"""

from __future__ import annotations

from src.models.condition import Condition, ConditionType
from src.models.stat_modifier import StatModifier
from src.combat.events import EventType
from src.combat.event_data import ConditionAddedData
from src.rules.expressions import resolve

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY


def _target(block: Block, inv: Invocation):
    return inv.caster if block.get("target") == "caster" else inv.target


def _own(inv: Invocation, handle) -> None:
    """Register a grant's revoke handle with the open lifetime scope, if any.

    Inside a ``lifetime`` block the scope takes ownership so teardown revokes the
    grant; outside one the grant is instantaneous/permanent (the handle is dropped).
    """
    if inv.active_scope is not None:
        inv.active_scope.add(handle)


def apply_condition(block: Block, inv: Invocation) -> None:
    """Add a status condition to the target, emitting CONDITION_ADDED."""
    target = _target(block, inv)
    ctype = ConditionType[str(block.get("condition_type", "")).upper()]
    raw_duration = block.get("duration")
    duration = resolve(raw_duration, eval_context(inv)) if raw_duration is not None else None
    condition = Condition(
        condition_type=ctype,
        duration_rounds=duration,
        source=str(block.get("source", "")),
        effect_name=str(block.get("effect_name", "")),
    )
    _own(inv, target.add_condition(condition))
    inv.event_bus.emit(
        EventType.CONDITION_ADDED,
        ConditionAddedData(entity=target, condition=condition),
    )


def add_modifier(block: Block, inv: Invocation) -> None:
    """Attach a labeled StatModifier to the target."""
    target = _target(block, inv)
    ec = eval_context(inv)
    mod = StatModifier(
        stat=str(block.get("stat", "")),
        value=int(resolve(block.get("value", 0), ec)),
        source=str(block.get("source", "")),
        effect_name=str(block.get("effect_name", "")),
    )
    _own(inv, target.add_stat_modifier(mod))


def grant_temporary_hp(block: Block, inv: Invocation) -> None:
    """Grant temporary hit points to the target (non-stacking, keeps the higher)."""
    target = _target(block, inv)
    try:
        amount = int(resolve(block.get("amount", 0), eval_context(inv)))
    except Exception:
        amount = 0
    if amount > 0:
        _own(inv, target.add_temporary_hp(amount))
        inv.context["temp_hp_granted"] = amount


def add_resource(block: Block, inv: Invocation) -> None:
    """Add to a per-turn resource (movement, actions, …) on the target.

    A *transient* grant, not a durable one: it is re-applied each turn by a
    ``TURN_START`` rider and wiped by the next turn's refill, so it registers **no**
    revoke handle — when the rider's lifetime ends it simply stops being re-added
    (matching the legacy ``AddResource`` entity effect).
    """
    target = _target(block, inv)
    resource = str(block.get("resource", ""))
    try:
        amount = int(resolve(block.get("amount", 0), eval_context(inv)))
    except Exception:
        return
    if resource and amount:
        target.add_resource(resource, amount)


REGISTRY.register(
    "apply_condition", apply_condition,
    BlockContract(target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "add_modifier", add_modifier,
    BlockContract(target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "grant_temporary_hp", grant_temporary_hp,
    BlockContract(writes=("temp_hp_granted",), target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "add_resource", add_resource,
    BlockContract(target_arity=TargetArity.SINGLE),
)
