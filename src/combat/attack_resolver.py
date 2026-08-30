"""Attack resolution on the block engine (Phase 3 — one path for weapons and spells).

A weapon attack compiles to the same ``[attack_roll, damage…]`` steps a spell does,
so it resolves on the block engine exactly like an attack-roll spell — the block
``attack_roll`` mirrors the legacy pipeline's attack step line for line. Reactive
riders (Colossus Slayer's on-hit bonus die) ride the shared EventBus as block
triggers, so there is no longer a legacy fallback: every attack runs on the block
engine.
"""

from typing import Optional, Tuple, List, Dict, Any

from src.models.entity import Entity
from src.models.action import AttackAction
from src.models.spell_properties import TargetingType
from .event_bus import EventBus
from .damage_processor import DamageProcessor


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
    """Resolves melee/ranged attack actions on the block engine."""

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
        """Resolve an attack roll and damage.

        Returns:
            Tuple of (hit, total_damage, log_message, roll_detail).
            log_message is empty string if the attack was cancelled.
            roll_detail is None when the attack was cancelled.
        """
        result = self._resolve_via_blocks(attacker, defender, action)

        if result.attack_cancelled:
            return False, 0, "", None
        return self._format(attacker, defender, action, result)

    def _resolve_via_blocks(self, attacker, defender, action):
        """The block-engine path — the same ``[attack_roll, damage…]`` as a spell.

        Imported lazily to avoid a ``combat → spells → combat`` import cycle (as in
        ``SpellResolver._resolve_via_blocks``).
        """
        from src.spells.evaluator import resolve as resolve_blocks
        from src.spells.adapter import to_program

        program = to_program(_build_pipeline_effects(action), TargetingType.SINGLE_TARGET)
        return resolve_blocks(
            attacker, defender, action, program,
            event_bus=self._event_bus,
            damage_processor=self._damage_processor,
            rule_engine=self.rule_engine,
        )

    def _format(self, attacker, defender, action, result):
        """Build the (hit, damage, log_msg, roll_detail) tuple from a resolver result.

        ``InvocationResult`` (block engine) and ``PipelineResult`` (legacy) are
        field-compatible, so this formats either identically.
        """
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
