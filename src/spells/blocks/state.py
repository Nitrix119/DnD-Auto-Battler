"""State blocks: apply_condition, add_modifier, grant_temporary_hp.

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
    target.add_condition(condition)
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
    target.add_stat_modifier(mod)


def grant_temporary_hp(block: Block, inv: Invocation) -> None:
    """Grant temporary hit points to the target (non-stacking, keeps the higher)."""
    target = _target(block, inv)
    try:
        amount = int(resolve(block.get("amount", 0), eval_context(inv)))
    except Exception:
        amount = 0
    if amount > 0:
        target.add_temporary_hp(amount)
        inv.context["temp_hp_granted"] = amount


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
