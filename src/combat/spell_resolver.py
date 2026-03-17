"""Spell resolution."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.models.entity import Entity
from src.models.action import SpellAction
from src.models.damage import Damage
from src.utils.dice import roll_d20
from src.rules.expressions import build_context, evaluate, resolve
from .event_bus import CombatEvent, EventBus
from .event_data import AttackDeclaredData, SpellCastData, SpellHitData
from .events import EventType
from .damage_processor import DamageProcessor
from .attack_resolver import AttackResolver

logger = logging.getLogger(__name__)


class SpellResolver:
    """Resolves spell actions against one or more targets."""

    def __init__(
        self,
        event_bus: EventBus,
        damage_processor: DamageProcessor,
        attack_resolver: AttackResolver,
        rule_engine=None,
    ) -> None:
        self._event_bus = event_bus
        self._damage_processor = damage_processor
        self._attack_resolver = attack_resolver
        self.rule_engine = rule_engine

    def resolve(
        self,
        caster: Entity,
        defenders: List[Entity],
        action: SpellAction,
        *,
        origin=None,
    ) -> List[Tuple[bool, int, str]]:
        """Resolve a spell action against one or more targets.

        Damage is rolled once and applied to every target, matching D&D rules
        (e.g. Fireball rolls 8d6 once and deals that total to each creature
        in the area).

        Spell attack rolls are made per-target when the spell uses them.
        Saving throws are resolved per-target when the spell has a ``save_dc``
        and ``save_ability`` set; the result is available in spell effect
        conditions as ``save_success`` and ``save_roll``.

        Args:
            caster: The entity casting the spell.
            defenders: Entities the spell targets.
            action: The spell being cast.
            origin: Optional Point3D of the AoE centre/apex, forwarded to the
                SPELL_CAST event so listeners can know where the area was placed.

        Returns:
            List of (hit, damage_dealt, log_message) per defender, in the same
            order as defenders.
        """
        self._event_bus.emit(
            EventType.SPELL_CAST,
            SpellCastData(caster=caster, defenders=defenders, action=action, origin=origin),
        )

        # Roll damage once — the same total applies to every target
        rolled_damages = action.roll_damage()

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
            save_roll, save_success = self._roll_saving_throw(
                defender, action.save_ability, action.save_dc,
            ) if action.save_dc > 0 and action.save_ability else (None, True)

            self._event_bus.emit(
                EventType.SPELL_HIT,
                SpellHitData(
                    caster=caster, defender=defender, action=action,
                    roll=attack_total, save_success=save_success, save_roll=save_roll,
                ),
            )
            self._apply_spell_effects(
                caster, defender, action, attack_total, save_success, save_roll,
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
        """Spell with no attack roll — auto-hit, saving throw if applicable."""
        save_roll, save_success = self._roll_saving_throw(
            defender, action.save_ability, action.save_dc,
        ) if action.save_dc > 0 and action.save_ability else (None, True)

        self._event_bus.emit(
            EventType.SPELL_HIT,
            SpellHitData(
                caster=caster, defender=defender, action=action,
                roll=None, save_success=save_success, save_roll=save_roll,
            ),
        )
        self._apply_spell_effects(
            caster, defender, action, None, save_success, save_roll,
        )
        target_damages = [Damage(d.damage_type, d.amount) for d in rolled_damages]
        damage_dealt = self._damage_processor.apply_damage(
            defender, target_damages, source=caster,
        )
        save_str = ""
        if save_roll is not None:
            result_word = "success" if save_success else "failure"
            save_str = f" (save {save_roll}: {result_word})"
        log_msg = (
            f"cast {action.name} at {defender.name}. "
            f"Damage: {damage_dealt}{save_str}"
        )
        return True, damage_dealt, log_msg

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _roll_saving_throw(
        defender: Entity, ability: str, dc: int,
    ) -> Tuple[int, bool]:
        """Roll a saving throw and return (roll_total, success)."""
        roll = roll_d20()
        bonus = defender.stat_block.get_saving_throw_bonus(ability)
        total = roll + bonus
        return total, total >= dc

    def _apply_spell_effects(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        attack_roll: Optional[int],
        save_success: bool,
        save_roll: Optional[int],
    ) -> None:
        """Apply entity effects declared in the spell's ``effects`` list.

        Evaluates each entry's optional ``condition`` in a sandboxed context,
        then evaluates each ``instance_fields`` expression and calls
        ``rule_engine.apply_effect`` on the defender.

        Context available in expressions:
          ``event``         — SimpleNamespace with caster, defender, action,
                             roll, save_success, save_roll.
          ``save_success``  — bool shorthand.
          ``save_roll``     — int | None shorthand.
          plus SAFE_BUILTINS (max, min, abs, int, round, bool, len, hasattr).
        """
        if not action.spell_effects or self.rule_engine is None:
            return

        ctx = build_context(
            dict(caster=caster, defender=defender, action=action,
                 roll=attack_roll, save_success=save_success, save_roll=save_roll),
            save_success=save_success,
            save_roll=save_roll,
        )

        for entry in action.spell_effects:
            # Evaluate optional guard condition
            condition_expr = entry.get("condition")
            if condition_expr:
                try:
                    if not evaluate(condition_expr, ctx):
                        continue
                except Exception as exc:
                    logger.debug(
                        "Spell effect condition skipped (%s: %s)", type(exc).__name__, exc
                    )
                    continue

            # Look up the entity effect rule by name
            effect_name = entry.get("effect")
            if not effect_name:
                logger.warning("Spell effect entry missing 'effect' key: %s", entry)
                continue
            rule = self.rule_engine.effect_registry.get(effect_name)

            # Evaluate instance_fields expressions
            instance_fields: Dict[str, Any] = {}
            for field_name, expr in entry.get("instance_fields", {}).items():
                try:
                    instance_fields[field_name] = resolve(expr, ctx)
                except Exception as exc:
                    logger.debug(
                        "Spell effect instance_field '%s' evaluation failed (%s: %s)",
                        field_name, type(exc).__name__, exc,
                    )

            self.rule_engine.apply_effect(defender, rule, instance_fields=instance_fields)
            logger.info(
                "Applied spell effect '%s' to %s (save_success=%s)",
                rule.name, defender.name, save_success,
            )

            # Execute immediate on-apply effects (e.g. granting temp HP at cast time)
            for on_apply_effect in entry.get("on_apply", []):
                action_name = on_apply_effect.get("action")
                handler = self.rule_engine._effect_registry.get(action_name)
                if handler is None:
                    logger.warning("on_apply: unknown action '%s'", action_name)
                    continue
                stub_event = CombatEvent(
                    event_type=EventType.SPELL_HIT,
                    data=SpellHitData(
                        caster=caster, defender=defender, action=action,
                        roll=attack_roll, save_success=save_success,
                        save_roll=save_roll,
                    ),
                )
                handler(on_apply_effect, ctx, stub_event, self._event_bus)
