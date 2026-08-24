"""Roll / gate blocks: attack_roll and saving_throw."""

from __future__ import annotations

from src.combat.events import EventType
from src.combat.event_data import (
    AttackDeclaredData,
    AttackRolledData,
    AttackHitData,
    SavingThrowDeclaredData,
)
from src.utils.dice import roll_d20, roll_with_advantage, roll_with_disadvantage
from src.utils.saving_throw import roll_saving_throw

from ..contract import BlockContract, TargetArity
from ..context import Invocation
from ..block import Block
from ..registry import REGISTRY


def _roll_d20(advantage: bool, disadvantage: bool) -> int:
    """d20 honouring advantage/disadvantage (both present cancel to normal)."""
    if advantage and disadvantage:
        return roll_d20()
    if advantage:
        return roll_with_advantage()
    if disadvantage:
        return roll_with_disadvantage()
    return roll_d20()


def attack_roll(block: Block, inv: Invocation) -> None:
    """Emit ATTACK_DECLARED, roll to hit, emit ATTACK_ROLLED/ATTACK_HIT.

    Writes hit / attack_roll / attack_total / critical_hit / critical_miss to the
    context. Mirrors the legacy pipeline's attack-roll step exactly (same events,
    same rolls) so the two engines stay in parity.
    """
    caster, defender, action = inv.caster, inv.target, inv.action
    ctx = inv.context

    declared = inv.event_bus.emit(
        EventType.ATTACK_DECLARED,
        AttackDeclaredData(attacker=caster, defender=defender, action=action),
    )
    if declared.cancelled:
        ctx["hit"] = False
        ctx["attack_roll"] = 0
        ctx["attack_total"] = 0
        ctx["attack_cancelled"] = True
        return

    has_adv = declared.data.get("advantage", False)
    has_dis = declared.data.get("disadvantage", False)
    ctx["had_advantage"] = has_adv
    ctx["had_disadvantage"] = has_dis

    bonus_spec = block.get("attack_bonus", 0)
    bonus = caster.spell_attack_bonus if bonus_spec == "use_caster_bonus" else int(bonus_spec)

    roll = _roll_d20(has_adv, has_dis)
    total = roll + bonus
    ctx["attack_roll"] = roll
    ctx["attack_total"] = total

    rolled = inv.event_bus.emit(
        EventType.ATTACK_ROLLED,
        AttackRolledData(attacker=caster, defender=defender, action=action,
                         roll=roll, total=total),
    )
    crit_hit = rolled.data.get("critical_hit", False)
    crit_miss = rolled.data.get("critical_miss", False)
    ctx["critical_hit"] = crit_hit
    ctx["critical_miss"] = crit_miss

    hit = True if crit_hit else False if crit_miss else total >= defender.ac
    ctx["hit"] = hit
    if hit:
        inv.event_bus.emit(
            EventType.ATTACK_HIT,
            AttackHitData(attacker=caster, defender=defender, action=action, roll=total),
        )


REGISTRY.register(
    "attack_roll",
    attack_roll,
    BlockContract(
        writes=("hit", "attack_roll", "attack_total", "critical_hit", "critical_miss"),
        target_arity=TargetArity.SINGLE,
        is_gate=True,
    ),
)


def saving_throw(block: Block, inv: Invocation) -> None:
    """Roll the current target's saving throw; write save_roll/save_dc/save_success.

    Emits SAVING_THROW_DECLARED so effects (e.g. Restrained → disadvantage on DEX
    saves) can flag advantage/disadvantage before the roll. Mirrors the legacy
    pipeline's saving-throw step.
    """
    caster, defender = inv.caster, inv.target
    ctx = inv.context

    attribute = block.get("attribute", "")
    dc_spec = block.get("dc", 0)
    effective_dc = caster.spell_save_dc if dc_spec == "use_caster_dc" else int(dc_spec)

    if effective_dc > 0 and attribute:
        declared = inv.event_bus.emit(
            EventType.SAVING_THROW_DECLARED,
            SavingThrowDeclaredData(defender=defender, ability=attribute, dc=effective_dc),
        )
        has_adv = declared.data.get("advantage", False)
        has_dis = declared.data.get("disadvantage", False)
        save_roll, save_success = roll_saving_throw(
            defender, attribute, effective_dc,
            advantage=has_adv, disadvantage=has_dis,
        )
    else:
        save_roll, save_success = None, True

    ctx["save_roll"] = save_roll
    ctx["save_dc"] = effective_dc
    ctx["save_success"] = save_success


REGISTRY.register(
    "saving_throw",
    saving_throw,
    BlockContract(
        writes=("save_roll", "save_dc", "save_success"),
        target_arity=TargetArity.SINGLE,
        is_gate=True,
    ),
)
