"""Tests for Colossus Slayer bonus damage injection.

Verifies that Colossus Slayer injects a pipeline damage step into the triggering
action's pipeline_effects list (using the weapon's primary damage type), rather than
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
    sb = StatBlockLoader.load_from_json(os.path.join(EXAMPLES_DIR, "creatures/characters/ranger.json"))
    return Entity(sb)


def load_golem() -> Entity:
    sb = StatBlockLoader.load_from_json(os.path.join(EXAMPLES_DIR, "creatures/stone_golem.json"))
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
        and returns (golem, action, original_step_count) with pipeline_effects
        populated by the effect.
        """
        ranger = load_ranger()
        golem = load_golem()
        # Pre-wound so hp < max_hp (triggers Colossus Slayer condition).
        golem.take_damage(Damage(DamageType.BLUDGEONING, 10))

        bus, _ = setup_engine(ranger, golem)
        action = get_action(ranger, weapon_name)
        # Build pipeline_effects so CS has somewhere to inject
        from src.combat.attack_resolver import _build_pipeline_effects
        action.pipeline_effects = _build_pipeline_effects(action)
        original_step_count = len(action.pipeline_effects)
        bus.emit(EventType.ATTACK_HIT, attacker=ranger, defender=golem, action=action)
        return golem, action, original_step_count

    def test_colossus_slayer_adds_one_bonus_damage_entry(self):
        """ATTACK_HIT with a wounded target adds exactly one step to pipeline_effects."""
        _, action, original_step_count = self._hit_with_weapon("Shortbow")
        assert len(action.pipeline_effects) == original_step_count + 1

    def test_club_produces_bludgeoning(self):
        _, action, _ = self._hit_with_weapon("Club")
        assert action.pipeline_effects[-1]["damage_type"] == "BLUDGEONING"

    def test_shortsword_produces_slashing(self):
        _, action, _ = self._hit_with_weapon("Shortsword")
        assert action.pipeline_effects[-1]["damage_type"] == "SLASHING"

    def test_shortbow_produces_piercing(self):
        _, action, _ = self._hit_with_weapon("Shortbow")
        assert action.pipeline_effects[-1]["damage_type"] == "PIERCING"

    def test_bonus_damage_formula_is_1d8(self):
        _, action, _ = self._hit_with_weapon("Shortbow")
        assert action.pipeline_effects[-1]["formula"] == "1d8"

    def test_injected_step_requires_hit(self):
        """The injected pipeline step should have requires_hit=True."""
        _, action, _ = self._hit_with_weapon("Shortbow")
        assert action.pipeline_effects[-1].get("requires_hit") == True

    def test_bonus_damage_only_applies_to_ranger_not_other_attackers(self):
        """Colossus Slayer must not grant bonus damage to a non-ranger attacker."""
        ranger = load_ranger()
        golem = load_golem()
        # Pre-wound the ranger so hp < max_hp (CS condition satisfied if it were checked).
        ranger.take_damage(Damage(DamageType.BLUDGEONING, 10))

        bus, _ = setup_engine(ranger, golem)

        # Use one of the golem's actions as the attacking action.
        golem_action = golem.stat_block.actions[0]
        from src.combat.attack_resolver import _build_pipeline_effects
        golem_action.pipeline_effects = _build_pipeline_effects(golem_action)
        original_step_count = len(golem_action.pipeline_effects)
        # Golem attacks the (wounded) ranger — CS effect should not apply.
        bus.emit(EventType.ATTACK_HIT, attacker=golem, defender=ranger, action=golem_action)

        assert len(golem_action.pipeline_effects) == original_step_count

    def test_does_not_fire_at_full_hp(self):
        """Colossus Slayer must not fire if the target is at full HP."""
        ranger = load_ranger()
        golem = load_golem()  # NOT pre-wounded
        bus, _ = setup_engine(ranger, golem)

        action = get_action(ranger, "Shortbow")
        from src.combat.attack_resolver import _build_pipeline_effects
        action.pipeline_effects = _build_pipeline_effects(action)
        original_step_count = len(action.pipeline_effects)
        bus.emit(EventType.ATTACK_HIT, attacker=ranger, defender=golem, action=action)

        assert len(action.pipeline_effects) == original_step_count
        assert golem.hp == golem.max_hp
