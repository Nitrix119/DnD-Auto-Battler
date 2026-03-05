"""Attack roll resolution."""

from typing import Tuple

from src.models.entity import Entity
from src.models.action import AttackAction
from src.utils.dice import roll_d20, roll_with_advantage, roll_with_disadvantage
from .event_bus import EventBus, CombatEvent
from .event_data import AttackDeclaredData, AttackHitData, AttackMissData
from .events import EventType
from .damage_processor import DamageProcessor


class AttackResolver:
    """Resolves melee/ranged attack actions."""

    def __init__(self, event_bus: EventBus, damage_processor: DamageProcessor) -> None:
        self._event_bus = event_bus
        self._damage_processor = damage_processor

    @staticmethod
    def _roll_mode_label(declared: CombatEvent) -> str:
        """Return a log-friendly label like ' (advantage)' from event flags."""
        has_adv = declared.data.get("advantage", False)
        has_dis = declared.data.get("disadvantage", False)
        if has_adv and not has_dis:
            return " (advantage)"
        if has_dis and not has_adv:
            return " (disadvantage)"
        return ""

    @staticmethod
    def _resolve_attack_roll(declared: CombatEvent) -> int:
        """Roll d20 with advantage/disadvantage based on event flags.

        Entity effects (e.g. Blinded) set ``advantage`` / ``disadvantage``
        flags on the ATTACK_DECLARED event data.  Per D&D 5e, if both are
        present they cancel out to a normal roll.
        """
        has_adv = declared.data.get("advantage", False)
        has_dis = declared.data.get("disadvantage", False)
        if has_adv and has_dis:
            return roll_d20()
        if has_adv:
            return roll_with_advantage()
        if has_dis:
            return roll_with_disadvantage()
        return roll_d20()

    def resolve(
        self,
        attacker: Entity,
        defender: Entity,
        action: AttackAction,
    ) -> Tuple[bool, int, str]:
        """Resolve an attack roll and damage.

        Returns:
            Tuple of (hit, total_damage, log_message).
            log_message is empty string if the attack was cancelled.
        """
        declared = self._event_bus.emit(
            EventType.ATTACK_DECLARED,
            AttackDeclaredData(attacker=attacker, defender=defender, action=action),
        )
        if declared.cancelled:
            return False, 0, ""

        attack_roll = self._resolve_attack_roll(declared)
        attack_total = attack_roll + action.bonus_to_hit
        roll_mode = self._roll_mode_label(declared)

        hit = attack_total >= defender.ac

        total_damage = 0
        if hit:
            # ATTACK_HIT fires *before* roll_damage() so that handlers like
            # AddDamage can append to action.bonus_damage (consumed by
            # roll_damage).  Do not reorder these calls.
            self._event_bus.emit(
                EventType.ATTACK_HIT,
                AttackHitData(attacker=attacker, defender=defender,
                              action=action, roll=attack_total),
            )
            rolled_damages = action.roll_damage()
            total_damage = self._damage_processor.apply_damage(
                defender, rolled_damages, source=attacker,
            )
            log_msg = (
                f"attacked {defender.name} with {action.name}. "
                f"Attack{roll_mode}: {attack_roll}+{action.bonus_to_hit}={attack_total} "
                f"vs AC {defender.ac}. Hit! Damage: {total_damage}"
            )
        else:
            self._event_bus.emit(
                EventType.ATTACK_MISS,
                AttackMissData(attacker=attacker, defender=defender,
                               action=action, roll=attack_total),
            )
            log_msg = (
                f"attacked {defender.name} with {action.name}. "
                f"Attack{roll_mode}: {attack_roll}+{action.bonus_to_hit}={attack_total} "
                f"vs AC {defender.ac}. Miss!"
            )

        return hit, total_damage, log_msg
