"""Tests for saving-throw advantage/disadvantage.

Regression coverage for a gap where `roll_saving_throw` always rolled a single
d20, so conditions like Restrained (disadvantage on DEX saves) had no effect on
saves even though they correctly imposed advantage/disadvantage on attacks.

The mechanism mirrors the attack path: `_handle_saving_throw` emits
SAVING_THROW_DECLARED before rolling, entity effects set advantage/disadvantage
flags on the event, and the flags are passed to `roll_saving_throw`.
"""

import os
from unittest.mock import patch

from src.combat.damage_processor import DamageProcessor
from src.combat.event_bus import EventBus
from src.combat.events import EventType
from src.models import Entity
from src.models.ability import AbilityScores
from src.models.action import SpellAction
from src.models.spell_properties import (
    CastingTime, CastingTimeType,
    Duration, DurationUnit,
    RangeType, SpellComponents, SpellRange,
    TargetingType,
)
from src.models.stat_block import StatBlock
from src.rules import RuleEngine, RuleLoader
from src.utils.saving_throw import roll_saving_throw

CONDITIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "rules", "entity_effects", "conditions"
)
RESTRAINED_JSON = os.path.join(CONDITIONS_DIR, "restrained.json")


def _plain_entity(name="Target") -> Entity:
    return Entity(StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=30,
        armor_class=10,
    ))


def _caster() -> Entity:
    return Entity(StatBlock(
        name="Caster",
        ability_scores=AbilityScores(10, 10, 10, 18, 10, 10),
        hit_points_max=30,
        armor_class=12,
        proficiency_bonus=3,
        spellcasting_ability="intelligence",  # spell_save_dc = 8 + 3 + 4 = 15
    ))


# ---------------------------------------------------------------------------
# Unit: roll_saving_throw honours advantage / disadvantage
# ---------------------------------------------------------------------------

class TestRollSavingThrowRollMode:
    def test_disadvantage_takes_lower_of_two(self):
        target = _plain_entity()
        with patch("src.utils.dice.roll_d20", side_effect=[18, 3]):
            total, _ = roll_saving_throw(target, "dexterity", 10, disadvantage=True)
        assert total == 3  # min(18, 3) + 0 bonus

    def test_advantage_takes_higher_of_two(self):
        target = _plain_entity()
        with patch("src.utils.dice.roll_d20", side_effect=[4, 17]):
            total, _ = roll_saving_throw(target, "dexterity", 10, advantage=True)
        assert total == 17  # max(4, 17) + 0 bonus

    def test_both_flags_cancel_to_normal_roll(self):
        target = _plain_entity()
        with patch("src.utils.saving_throw.roll_d20", return_value=11):
            total, _ = roll_saving_throw(
                target, "dexterity", 10, advantage=True, disadvantage=True
            )
        assert total == 11  # single normal roll


# ---------------------------------------------------------------------------
# Rule wiring: Restrained imposes disadvantage on DEX saves only
# ---------------------------------------------------------------------------

class TestRestrainedSaveWiring:
    def _setup(self, target):
        # Restrained is a native block rule now (§5d): apply_effect installs it on the
        # block engine, which needs a damage_processor present (the no-dp legacy path
        # cannot run a native rule — it has no legacy triggers to dispatch on).
        bus = EventBus()
        engine = RuleEngine(
            bus, damage_processor=DamageProcessor(bus)
        )
        rule = RuleLoader.load(RESTRAINED_JSON)
        engine.apply_effect(target, rule)
        return bus

    def test_dex_save_gets_disadvantage(self):
        target = _plain_entity()
        bus = self._setup(target)
        event = bus.emit(
            EventType.SAVING_THROW_DECLARED,
            defender=target, ability="dexterity", dc=15,
        )
        assert event.data.get("disadvantage") is True

    def test_non_dex_save_unaffected(self):
        target = _plain_entity()
        bus = self._setup(target)
        event = bus.emit(
            EventType.SAVING_THROW_DECLARED,
            defender=target, ability="strength", dc=15,
        )
        assert not event.data.get("disadvantage")

    def test_other_entity_save_unaffected(self):
        target = _plain_entity("Restrained")
        other = _plain_entity("Free")
        bus = EventBus()
        engine = RuleEngine(
            bus,
            damage_processor=DamageProcessor(bus),
        )
        engine.apply_effect(target, RuleLoader.load(RESTRAINED_JSON))
        event = bus.emit(
            EventType.SAVING_THROW_DECLARED,
            defender=other, ability="dexterity", dc=15,
        )
        assert not event.data.get("disadvantage")


# ---------------------------------------------------------------------------
# Integration: the block engine actually rolls the save with disadvantage
# ---------------------------------------------------------------------------

class TestBlockSaveRollMode:
    def _dex_save_spell(self) -> SpellAction:
        return SpellAction(
            name="Test Save Spell",
            description="",
            spell_range=SpellRange(RangeType.FEET, distance_ft=60),
            targeting_type=TargetingType.SINGLE_TARGET,
            casting_time=CastingTime(CastingTimeType.ACTION),
            duration=Duration(DurationUnit.INSTANTANEOUS),
            components=SpellComponents(verbal=True, somatic=False),
            program=[
                {"block": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc"},
                {"block": "damage", "damage_type": "FIRE", "formula": "10",
                 "save_result": {"on_success": "half_damage"}},
            ],
        )

    def _resolve(self, caster, target, bus):
        from src.spells.evaluator import resolve as resolve_blocks
        from src.spells.block import parse_program

        spell = self._dex_save_spell()
        program = parse_program(spell.program)
        return resolve_blocks(
            caster, target, spell, program,
            event_bus=bus, damage_processor=DamageProcessor(bus),
        )

    def test_disadvantage_flag_makes_save_use_disadvantage_roll(self):
        caster, target = _caster(), _plain_entity()
        bus = EventBus()
        bus.subscribe(
            EventType.SAVING_THROW_DECLARED,
            lambda e: e.data.__setitem__("disadvantage", True),
        )
        # Disadvantage path (min of two) returns 2; normal path would return 20.
        with patch("src.utils.saving_throw.roll_with_disadvantage", return_value=2), \
             patch("src.utils.saving_throw.roll_d20", return_value=20):
            result = self._resolve(caster, target, bus)
        assert result.save_roll == 2  # disadvantage roll was used, not the normal 20

    def test_without_flag_uses_normal_roll(self):
        caster, target = _caster(), _plain_entity()
        bus = EventBus()
        with patch("src.utils.saving_throw.roll_with_disadvantage", return_value=2), \
             patch("src.utils.saving_throw.roll_d20", return_value=20):
            result = self._resolve(caster, target, bus)
        assert result.save_roll == 20  # normal single roll
