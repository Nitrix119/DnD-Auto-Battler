"""Upcasting: slot_level in context + a `scaling` modifier on damage steps.

Design stage 2 (SPELL_SYSTEM_DESIGN.md §6.7 / §0 D4): a spell cast with a higher
slot deals more damage, expressed as a declared `scaling` modifier
(`{"per_slot_above": N, "add_dice": "1d6"}`) rather than a dice formula that is
itself an expression. `slot_level` is exposed in the pipeline context so
expressions can read it too.
"""

from unittest.mock import patch

import pytest

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.spell_resolver import SpellResolver
from src.spells.scaling import effective_damage_formula
from src.combat import CombatSystem
from src.spells.context import CONTEXT_KEYS
from src.spells.validate import validate_program


# ── The pure formula helper ─────────────────────────────────────────────────────

class TestEffectiveDamageFormula:

    STEP = {"type": "damage", "damage_type": "FIRE", "formula": "8d6",
            "scaling": {"per_slot_above": 3, "add_dice": "1d6"}}

    def test_no_scaling_returns_base(self):
        step = {"formula": "8d6"}
        assert effective_damage_formula(step, 5) == "8d6"

    def test_slot_at_threshold_returns_base(self):
        assert effective_damage_formula(self.STEP, 3) == "8d6"

    def test_slot_below_threshold_returns_base(self):
        assert effective_damage_formula(self.STEP, 1) == "8d6"

    def test_slot_none_returns_base(self):
        assert effective_damage_formula(self.STEP, None) == "8d6"

    def test_slot_above_adds_scaled_dice(self):
        # 5 - 3 = 2 extra levels -> +2d6
        assert effective_damage_formula(self.STEP, 5) == "8d6+2d6"

    def test_one_level_above_adds_one(self):
        assert effective_damage_formula(self.STEP, 4) == "8d6+1d6"


# ── slot_level is part of the context vocabulary ────────────────────────────────

def test_slot_level_is_a_valid_context_key():
    assert "slot_level" in CONTEXT_KEYS
    # An expression referencing it must validate clean.
    validate_program([
        {"block": "damage", "damage_type": "FIRE", "formula": "1d6",
         "condition": "context.slot_level >= 5"}
    ], spell_name="Scaler")


# ── Integration: a spell cast at a higher slot deals more damage ────────────────

def _damage_spell() -> SpellAction:
    return SpellAction(
        name="Test Blast",
        description="",
        spell_level=3,
        program=[
            {"block": "damage", "damage_type": "FIRE", "formula": "8d6",
             "scaling": {"per_slot_above": 3, "add_dice": "1d6"}},
        ],
    )


def _entity(name="E", hp=100):
    sb = StatBlock(name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
                   hit_points_max=hp, armor_class=10)
    e = Entity(sb)
    e.refill_resources()
    return e


class TestScalingInResolution:

    def test_damage_scales_with_slot_level(self):
        caster, t3, t5 = _entity("C"), _entity("T3"), _entity("T5")
        bus = EventBus()
        resolver = SpellResolver(bus, DamageProcessor(bus))
        spell = _damage_spell()

        # Each die rolls 1, so damage == number of dice: 8d6 -> 8, 8d6+2d6 -> 10.
        with patch("src.utils.dice.roll_dice", lambda n, s: n):
            resolver.resolve(caster, [t3], spell, slot_level=3)
            resolver.resolve(caster, [t5], spell, slot_level=5)

        assert t3.max_hp - t3.hp == 8
        assert t5.max_hp - t5.hp == 10

    def test_default_slot_level_is_base(self):
        caster, target = _entity("C"), _entity("T")
        bus = EventBus()
        resolver = SpellResolver(bus, DamageProcessor(bus))
        with patch("src.utils.dice.roll_dice", lambda n, s: n):
            resolver.resolve(caster, [target], _damage_spell())  # no slot_level
        assert target.max_hp - target.hp == 8  # base 8d6

    def test_roll_once_scaling_is_shared_across_aoe_targets(self):
        caster, a, b = _entity("C"), _entity("A"), _entity("B")
        bus = EventBus()
        resolver = SpellResolver(bus, DamageProcessor(bus))
        spell = SpellAction(
            name="Test Nova", description="", spell_level=3,
            program=[
                {"block": "damage", "damage_type": "FIRE", "formula": "8d6",
                 "roll_once": True,
                 "scaling": {"per_slot_above": 3, "add_dice": "1d6"}},
            ],
        )
        with patch("src.utils.dice.roll_dice", lambda n, s: n):
            resolver.resolve(caster, [a, b], spell, slot_level=6)  # +3d6 -> 11
        assert a.max_hp - a.hp == 11
        assert b.max_hp - b.hp == 11


# ── CombatSystem: upcasting spends the higher slot; guards a too-low slot ────────

def _caster_with_slots():
    sb = StatBlock(name="Wizard", ability_scores=AbilityScores(10, 10, 10, 10, 10, 16),
                   hit_points_max=30, armor_class=12,
                   spell_slot_defaults={3: 3, 5: 1},
                   resource_defaults={"actions": 1, "bonus_actions": 1, "reactions": 1, "speed": 30})
    caster = Entity(sb)
    caster.refill_resources()
    return caster


def _combat(*entities) -> CombatSystem:
    cs = CombatSystem()
    for e in entities:
        cs.add_combatant(e)
    cs.start_combat()
    return cs


class TestUpcastSlotAccounting:

    def _setup(self):
        caster = _caster_with_slots()
        target = _entity("Target", hp=100)
        combat = _combat(caster, target)
        # Ensure it's the caster's turn.
        while combat.get_current_entity() is not caster:
            combat.end_turn()
        return combat, caster, target

    def test_upcasting_spends_the_higher_slot(self):
        combat, caster, target = self._setup()
        with patch("src.utils.dice.roll_dice", lambda n, s: n):
            combat.resolve_spell(caster, [target], _damage_spell(), slot_level=5)
        assert caster.spell_slots.remaining[5] == 0   # the level-5 slot was spent
        assert caster.spell_slots.remaining[3] == 3   # level-3 slots untouched

    def test_casting_at_base_spends_base_slot(self):
        combat, caster, target = self._setup()
        with patch("src.utils.dice.roll_dice", lambda n, s: n):
            combat.resolve_spell(caster, [target], _damage_spell())  # base level 3
        assert caster.spell_slots.remaining[3] == 2
        assert caster.spell_slots.remaining[5] == 1

    def test_slot_level_below_base_is_rejected(self):
        combat, caster, target = self._setup()
        with pytest.raises(ValueError):
            combat.resolve_spell(caster, [target], _damage_spell(), slot_level=2)


# ── Schema: the scaling field is validated ──────────────────────────────────────

class TestScalingSchema:
    """`scaling` is validated at load: it is the one block arg with an internal
    shape, and a malformed one silently scales nothing at cast time."""

    def _damage(self, scaling):
        return [{"block": "damage", "damage_type": "FIRE", "formula": "8d6",
                 "scaling": scaling}]

    def test_valid_scaling_validates_clean(self):
        validate_program(self._damage({"per_slot_above": 3, "add_dice": "1d6"}),
                         spell_name="Upcaster")

    def test_missing_add_dice_is_reported(self):
        with pytest.raises(ValueError, match="add_dice"):
            validate_program(self._damage({"per_slot_above": 3}),
                             spell_name="Upcaster")

    def test_missing_per_slot_above_is_reported(self):
        with pytest.raises(ValueError, match="per_slot_above"):
            validate_program(self._damage({"add_dice": "1d6"}),
                             spell_name="Upcaster")

    def test_bad_add_dice_formula_is_reported(self):
        with pytest.raises(ValueError, match="add_dice"):
            validate_program(self._damage({"per_slot_above": 3, "add_dice": "1d"}),
                             spell_name="Upcaster")

    def test_non_int_per_slot_above_is_reported(self):
        with pytest.raises(ValueError, match="per_slot_above"):
            validate_program(self._damage({"per_slot_above": "3", "add_dice": "1d6"}),
                             spell_name="Upcaster")

    def test_unknown_scaling_subfield_is_reported(self):
        with pytest.raises(ValueError, match="per_levl"):
            validate_program(
                self._damage({"per_slot_above": 3, "add_dice": "1d6", "per_levl": 1}),
                spell_name="Upcaster")

    def test_scaling_must_be_an_object(self):
        with pytest.raises(ValueError, match="scaling"):
            validate_program(self._damage("1d6"), spell_name="Upcaster")
