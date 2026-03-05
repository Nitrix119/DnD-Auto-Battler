"""Spell resolution."""

from typing import List, Tuple

from src.models.entity import Entity
from src.models.action import SpellAction
from src.models.damage import Damage
from .event_bus import EventBus
from .event_data import AttackDeclaredData, SpellCastData, SpellHitData
from .events import EventType
from .damage_processor import DamageProcessor
from .attack_resolver import AttackResolver


class SpellResolver:
    """Resolves spell actions against one or more targets."""

    def __init__(
        self,
        event_bus: EventBus,
        damage_processor: DamageProcessor,
        attack_resolver: AttackResolver,
    ) -> None:
        self._event_bus = event_bus
        self._damage_processor = damage_processor
        self._attack_resolver = attack_resolver

    def resolve(
        self,
        caster: Entity,
        defenders: List[Entity],
        action: SpellAction,
    ) -> List[Tuple[bool, int, str]]:
        """Resolve a spell action against one or more targets.

        Damage is rolled once and applied to every target, matching D&D rules
        (e.g. Fireball rolls 8d6 once and deals that total to each creature
        in the area).

        Spell attack rolls are made per-target when the spell uses them.
        Saving throws are not yet implemented (see TODO below).

        Returns:
            List of (hit, damage_dealt, log_message) per defender, in the same
            order as defenders.
        """
        self._event_bus.emit(
            EventType.SPELL_CAST,
            SpellCastData(caster=caster, defenders=defenders, action=action),
        )

        # Roll damage once — the same total applies to every target
        rolled_damages = action.roll_damage()

        # TODO: Implement saving throws (action.save_dc > 0).  Currently all
        #       targets with a save DC are treated as if they failed the save
        #       and take full damage.

        results: List[Tuple[bool, int, str]] = []
        for defender in defenders:
            if action.spell_attack_bonus != 0 and action.save_dc == 0:
                result = self._resolve_spell_attack(
                    caster, defender, action, rolled_damages,
                )
            else:
                result = self._resolve_auto_hit(
                    caster, defender, action, rolled_damages,
                )
            results.append(result)

        return results

    def _resolve_spell_attack(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        rolled_damages: List[Damage],
    ) -> Tuple[bool, int, str]:
        """Spell with attack roll (e.g. Fire Bolt, Chromatic Orb)."""
        spell_declared = self._event_bus.emit(
            EventType.ATTACK_DECLARED,
            AttackDeclaredData(attacker=caster, defender=defender, action=action),
        )
        if spell_declared.cancelled:
            return False, 0, ""

        attack_roll = AttackResolver._resolve_attack_roll(spell_declared)
        attack_total = attack_roll + action.spell_attack_bonus
        hit = attack_total >= defender.ac
        roll_mode = AttackResolver._roll_mode_label(spell_declared)

        damage_dealt = 0
        if hit:
            self._event_bus.emit(
                EventType.SPELL_HIT,
                SpellHitData(caster=caster, defender=defender,
                             action=action, roll=attack_total),
            )
            target_damages = [Damage(d.damage_type, d.amount) for d in rolled_damages]
            damage_dealt = self._damage_processor.apply_damage(
                defender, target_damages, source=caster,
            )

        hit_str = f"Hit! Damage: {damage_dealt}" if hit else "Miss!"
        log_msg = (
            f"cast {action.name} at {defender.name}. "
            f"Spell attack{roll_mode}: {attack_roll}+{action.spell_attack_bonus}"
            f"={attack_total} vs AC {defender.ac}. {hit_str}"
        )
        return hit, damage_dealt, log_msg

    def _resolve_auto_hit(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        rolled_damages: List[Damage],
    ) -> Tuple[bool, int, str]:
        """Spell with no attack roll — auto-hit (saving throws via TODO above)."""
        self._event_bus.emit(
            EventType.SPELL_HIT,
            SpellHitData(caster=caster, defender=defender, action=action, roll=None),
        )
        target_damages = [Damage(d.damage_type, d.amount) for d in rolled_damages]
        damage_dealt = self._damage_processor.apply_damage(
            defender, target_damages, source=caster,
        )
        log_msg = (
            f"cast {action.name} at {defender.name}. "
            f"Damage: {damage_dealt}"
        )
        return True, damage_dealt, log_msg
