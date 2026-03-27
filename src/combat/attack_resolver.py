"""Attack roll resolution via EffectPipeline."""

import copy
from typing import Optional, Tuple, List, Dict, Any

from src.models.entity import Entity
from src.models.action import AttackAction
from .event_bus import EventBus
from .damage_processor import DamageProcessor
from .effect_pipeline import EffectPipeline


def _build_pipeline_effects(action: AttackAction) -> List[Dict[str, Any]]:
    """Convert a weapon attack's flat damage/bonus_to_hit into pipeline_effects steps."""
    steps: List[Dict[str, Any]] = [
        {"type": "attack_roll", "attack_bonus": action.bonus_to_hit}
    ]
    for d in action.damage:
        steps.append({
            "type": "damage",
            "formula": d.formula or str(d.amount),
            "damage_type": d.damage_type.name,
            "requires_hit": True,
        })
    return steps


class AttackResolver:
    """Resolves melee/ranged attack actions via EffectPipeline."""

    def __init__(self, event_bus: EventBus, damage_processor: DamageProcessor, rule_engine=None) -> None:
        self._event_bus = event_bus
        self._damage_processor = damage_processor
        self.rule_engine = rule_engine

    def resolve(
        self,
        attacker: Entity,
        defender: Entity,
        action: AttackAction,
    ) -> Tuple[bool, int, str, Optional[dict]]:
        """Resolve an attack roll and damage via EffectPipeline.

        Returns:
            Tuple of (hit, total_damage, log_message, roll_detail).
            log_message is empty string if the attack was cancelled.
            roll_detail is None when the attack was cancelled.
        """
        action_copy = copy.copy(action)
        action_copy.pipeline_effects = _build_pipeline_effects(action)

        pipeline = EffectPipeline(self._event_bus, self._damage_processor, self.rule_engine)
        result = pipeline.run(attacker, defender, action_copy)

        if result.attack_cancelled:
            return False, 0, "", None

        roll_mode = ""
        if result.had_advantage and not result.had_disadvantage:
            roll_mode = " (advantage)"
        elif result.had_disadvantage and not result.had_advantage:
            roll_mode = " (disadvantage)"

        if result.hit:
            hit_str = f"Hit! Damage: {result.damage_dealt}"
        else:
            hit_str = "Miss!"

        log_msg = (
            f"attacked {defender.name} with {action.name}. "
            f"Attack{roll_mode}: {result.attack_roll}+{action.bonus_to_hit}={result.attack_total}"
            f" vs AC {defender.ac}. {hit_str}"
        )
        roll_detail = {
            "d20": result.attack_roll,
            "bonus": action.bonus_to_hit,
            "total": result.attack_total,
            "ac": defender.ac,
        }
        return result.hit, result.damage_dealt, log_msg, roll_detail
