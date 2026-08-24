"""Spell resolution."""

import logging
from typing import Dict, List, Optional, Tuple

from src.models.entity import Entity
from src.models.action import SpellAction
from src.utils.dice import roll_formula
from .event_bus import EventBus
from .event_data import SpellCastData
from .events import EventType
from .damage_processor import DamageProcessor
from .effect_pipeline import EffectPipeline

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
            SpellCastData(caster=caster, defenders=defenders, action=action, origin=origin),
        )

        seed_damages = self._preroll_pipeline_damage(action)
        results: List[Tuple[bool, int, str, Optional[dict]]] = []
        for defender in defenders:
            results.append(
                self._run_pipeline_spell(caster, defender, action, seed_damages)
            )
        return results

    def _preroll_pipeline_damage(self, action: SpellAction) -> Dict[int, int]:
        """Pre-roll damage for any ``roll_once: true`` steps before the target loop.

        This ensures all targets of an AoE spell receive the same damage total,
        matching D&D 5e rules (e.g. Fireball rolls 8d6 once for every creature
        in the blast).

        Returns:
            Dict mapping step index → pre-rolled amount.
        """
        seed: Dict[int, int] = {}
        for i, step in enumerate(action.pipeline_effects):
            if step.get("type") == "damage" and step.get("roll_once"):
                seed[i] = roll_formula(step["formula"])
        return seed

    def _run_pipeline_spell(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        seed_damages: Dict[int, int],
    ) -> Tuple[bool, int, str, Optional[dict], int, Optional[Entity]]:
        """Execute the effect pipeline for one caster/defender pair and format the result."""
        pipeline = EffectPipeline(self._event_bus, self._damage_processor, self.rule_engine)
        result = pipeline.run(caster, defender, action, seed_damages=seed_damages)

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
