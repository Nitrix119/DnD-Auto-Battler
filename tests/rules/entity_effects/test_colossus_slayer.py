"""Tests for Colossus Slayer bonus damage injection.

Verifies that Colossus Slayer adds a 1d8 bonus damage entry to the triggering
attack's bonus_damage list (using the weapon's primary damage type), rather than
firing a separate DAMAGE_DEALT event.
"""

import os
import pytest

from src.models import Entity, Damage, DamageType
from src.combat import EventBus, EventType
from src.loaders import StatBlockLoader
from src.rules import RuleEngine, RuleLoader

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples")
ENTITY_EFFECTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "rules", "entity_effects")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def load_ranger() -> Entity:
    sb = StatBlockLoader.load_from_json(os.path.join(EXAMPLES_DIR, "ranger.json"))
    return Entity(sb)


def load_golem() -> Entity:
    sb = StatBlockLoader.load_from_json(os.path.join(EXAMPLES_DIR, "stone_golem.json"))
    return Entity(sb)


def setup_engine(ranger: Entity, golem: Entity):
    """Create a RuleEngine with Colossus Slayer applied to the ranger."""
    entities = [ranger, golem]
    bus = EventBus()
    engine = RuleEngine(bus, entities_getter=lambda: entities)
    rule = RuleLoader.load(os.path.join(ENTITY_EFFECTS_DIR, "colossus_slayer.json"))
    engine.apply_effect(ranger, rule)
    return bus, engine


def get_action(ranger: Entity, name: str):
    return next(a for a in ranger.stat_block.actions if a.name == name)


# ── JSON loading ───────────────────────────────────────────────────────────────

class TestFixtureLoading:

    def test_stone_golem_loads(self):
        golem = load_golem()
        assert golem.name == "Stone Golem"
        assert golem.max_hp == 178
        assert golem.stat_block.armor_class == 17

    def test_ranger_loads(self):
        ranger = load_ranger()
        assert ranger.name == "Hunter Ranger"
        assert ranger.max_hp == 38

    def test_ranger_has_all_three_weapons(self):
        ranger = load_ranger()
        names = {a.name for a in ranger.stat_block.actions}
        assert {"Club", "Shortsword", "Shortbow"} <= names

    def test_weapon_damage_types(self):
        ranger = load_ranger()
        club = get_action(ranger, "Club")
        sword = get_action(ranger, "Shortsword")
        bow = get_action(ranger, "Shortbow")
        assert club.damage[0].damage_type == DamageType.BLUDGEONING
        assert sword.damage[0].damage_type == DamageType.SLASHING
        assert bow.damage[0].damage_type == DamageType.PIERCING


# ── Colossus Slayer bonus damage injection ────────────────────────────────────

class TestColossusSlayerDamageInheritance:

    def _hit_with_weapon(self, weapon_name: str):
        """
        Pre-wounds the golem, fires an ATTACK_HIT event for the named weapon,
        and returns (golem, action) with bonus_damage populated by the effect.
        """
        ranger = load_ranger()
        golem = load_golem()
        # Pre-wound so hp < max_hp (triggers Colossus Slayer condition).
        golem.take_damage(Damage(DamageType.BLUDGEONING, 10))

        bus, _ = setup_engine(ranger, golem)
        action = get_action(ranger, weapon_name)
        bus.emit(EventType.ATTACK_HIT, attacker=ranger, defender=golem, action=action)
        return golem, action

    def test_colossus_slayer_adds_one_bonus_damage_entry(self):
        """ATTACK_HIT with a wounded target adds exactly one entry to bonus_damage."""
        _, action = self._hit_with_weapon("Shortbow")
        assert len(action.damage) == 1       # original weapon die unchanged
        assert len(action.bonus_damage) == 1  # CS bonus die injected

    def test_club_produces_bludgeoning(self):
        _, action = self._hit_with_weapon("Club")
        assert action.bonus_damage[0].damage_type == DamageType.BLUDGEONING

    def test_shortsword_produces_slashing(self):
        _, action = self._hit_with_weapon("Shortsword")
        assert action.bonus_damage[0].damage_type == DamageType.SLASHING

    def test_shortbow_produces_piercing(self):
        _, action = self._hit_with_weapon("Shortbow")
        assert action.bonus_damage[0].damage_type == DamageType.PIERCING

    def test_bonus_damage_formula_is_1d8(self):
        _, action = self._hit_with_weapon("Shortbow")
        assert action.bonus_damage[0].formula == "1d8"

    def test_roll_damage_returns_two_entries(self):
        """roll_damage() includes both weapon and CS bonus die."""
        _, action = self._hit_with_weapon("Shortbow")
        rolled = action.roll_damage()
        assert len(rolled) == 2

    def test_bonus_damage_consumed_after_roll(self):
        """bonus_damage is cleared by roll_damage() so it doesn't persist."""
        _, action = self._hit_with_weapon("Shortbow")
        action.roll_damage()
        assert len(action.bonus_damage) == 0

    def test_does_not_fire_at_full_hp(self):
        """Colossus Slayer must not fire if the target is at full HP."""
        ranger = load_ranger()
        golem = load_golem()  # NOT pre-wounded
        bus, _ = setup_engine(ranger, golem)

        action = get_action(ranger, "Shortbow")
        bus.emit(EventType.ATTACK_HIT, attacker=ranger, defender=golem, action=action)

        assert len(action.bonus_damage) == 0
        assert golem.hp == golem.max_hp
