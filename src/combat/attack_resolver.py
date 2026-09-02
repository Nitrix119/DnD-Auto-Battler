"""Attack resolution on the block engine (Phase 3 — one path for weapons and spells).

A weapon attack *is* a block program: ``[attack_roll, damage…]``, the same blocks an
attack-roll spell uses, so it resolves on the one engine. A weapon is authored in the
concise flat form (``bonus_to_hit`` + a ``damage`` list) that creature JSON has always
used, and :func:`_default_program` builds its program from that; a weapon that needs
more than the default may author a ``program`` directly, exactly as a spell does.
Reactive riders (Colossus Slayer's on-hit bonus die) ride the shared EventBus as block
triggers.
"""

from typing import Optional, Tuple, List, Dict, Any

from src.models.entity import Entity
from src.models.action import AttackAction
from .event_bus import EventBus
from .damage_processor import DamageProcessor


def _default_program(action: AttackAction) -> List[Dict[str, Any]]:
    """The block program implied by a weapon's flat ``bonus_to_hit`` + ``damage``.

    One ``attack_roll`` followed by a ``damage`` block per damage entry, each gated on
    the hit. This is a convenience constructor in the engine's own vocabulary — the
    blocks it emits are the ones a spell author would write by hand — not a
    translation from a second effect vocabulary.
    """
    blocks: List[Dict[str, Any]] = [
        {"block": "attack_roll", "attack_bonus": action.bonus_to_hit}
    ]
    for d in action.damage:
        blocks.append({
            "block": "damage",
            "formula": d.formula or str(d.amount),
            "damage_type": d.damage_type.name,
            "requires_hit": True,
        })
    return blocks


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
        from src.spells.block import parse_program

        program = parse_program(action.program or _default_program(action))
        return resolve_blocks(
            attacker, defender, action, program,
            event_bus=self._event_bus,
            damage_processor=self._damage_processor,
            rule_engine=self.rule_engine,
        )

    def _format(self, attacker, defender, action, result):
        """Build the (hit, damage, log_msg, roll_detail) tuple from an
        ``InvocationResult`` (the block engine's result type)."""
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
