"""Spell resolution."""

import logging
from typing import List, Optional, Tuple

from src.models.entity import Entity
from src.models.action import SpellAction
from .event_bus import EventBus
from .event_data import SpellCastData
from .events import EventType
from .damage_processor import DamageProcessor

logger = logging.getLogger(__name__)


class SpellResolver:
    """Resolves spell actions against one or more targets."""

    def __init__(
        self,
        event_bus: EventBus,
        damage_processor: DamageProcessor,
        rule_engine=None,
    ) -> None:
        self._event_bus = event_bus
        self._damage_processor = damage_processor
        self.rule_engine = rule_engine

    def resolve(
        self,
        caster: Entity,
        defenders: List[Entity],
        action: SpellAction,
        *,
        origin=None,
        slot_level: Optional[int] = None,
    ) -> List[Tuple[bool, int, str, Optional[dict]]]:
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
            SpellCastData(
                caster=caster, defenders=defenders, action=action, origin=origin
            ),
        )

        if slot_level is None:
            slot_level = action.spell_level

        # One resolution path: the block engine. A spell's ``program`` is validated at
        # load (``src.spells.validate.validate_program``) and runs directly. A spell
        # with no program has nothing to resolve — an authoring error we raise on
        # rather than silently doing nothing.
        if not action.program:
            raise ValueError(
                f"Spell {action.name!r} has no block program to resolve."
            )
        return self._resolve_via_blocks(caster, defenders, action, slot_level)

    def _resolve_via_blocks(
        self,
        caster: Entity,
        defenders: List[Entity],
        action: SpellAction,
        slot_level: Optional[int],
    ) -> List[Tuple[bool, int, str, Optional[dict], int, Optional[Entity]]]:
        """Resolve via the block evaluator (one invocation per defender).

        The spell's ``program`` runs directly (``parse_program``). Imported lazily to
        avoid an import cycle (combat → spells → combat).

        Fan-out (including AoE ``roll_once`` sharing) lives in the program: the
        evaluator is called once with the whole defender set and returns one
        result per defender, in order.
        """
        from src.spells.evaluator import resolve_program
        from src.spells.block import parse_program

        program = parse_program(action.program)
        results = resolve_program(
            caster,
            defenders,
            action,
            program,
            event_bus=self._event_bus,
            damage_processor=self._damage_processor,
            rule_engine=self.rule_engine,
            slot_level=slot_level,
        )
        return [
            self._format_result(caster, defender, action, result)
            for defender, result in zip(defenders, results)
        ]

    def _format_result(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        result,
    ) -> Tuple[bool, int, str, Optional[dict], int, Optional[Entity]]:
        """Format an engine result (legacy or block) into the per-defender tuple."""
        damage_dealt = result.damage_dealt
        hit = result.hit
        healing_total = result.healing_total
        healed_entity = result.healed_entity

        if result.attack_roll is not None:
            hit_str = f"Hit! Damage: {damage_dealt}" if hit else "Miss!"
            roll_mode = ""  # advantage/disadvantage label already logged by pipeline
            log_msg = (
                f"cast {action.name} at {defender.name}. "
                f"Spell attack{roll_mode}: {result.attack_roll}+...={result.attack_total}"
                f" vs AC {defender.ac}. {hit_str}"
            )
            roll_detail: Optional[dict] = {
                "d20": result.attack_roll,
                "total": result.attack_total,
                "ac": defender.ac,
            }

        elif result.save_roll is not None:
            result_word = "success" if result.save_success else "failure"
            log_msg = (
                f"cast {action.name} at {defender.name}. "
                f"Damage: {damage_dealt} (save {result.save_roll}: {result_word})"
            )
            roll_detail = {
                "total": result.save_roll,
                "dc": result.save_dc,
                "save_success": result.save_success,
            }
        else:
            log_msg = f"cast {action.name} at {defender.name}. Damage: {damage_dealt}"
            roll_detail = None

        return hit, damage_dealt, log_msg, roll_detail, healing_total, healed_entity
