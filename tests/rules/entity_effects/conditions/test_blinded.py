"""Tests for the Blinded condition entity effect.

Verifies that a blinded entity's attack rolls receive disadvantage
and that attack rolls against a blinded entity receive advantage.
"""

import os
from unittest.mock import patch

from src.models import Entity, Damage, DamageType
from src.combat import EventBus, EventType
from src.loaders import StatBlockLoader
from src.rules import RuleEngine, RuleLoader

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "examples")
CONDITIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "rules", "entity_effects", "conditions")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def load_fighter() -> Entity:
    sb = StatBlockLoader.load_from_json(os.path.join(EXAMPLES_DIR, "creatures/characters/fighter.json"))
    return Entity(sb)


def load_goblin() -> Entity:
    sb = StatBlockLoader.load_from_json(os.path.join(EXAMPLES_DIR, "creatures/goblin.json"))
    return Entity(sb)


def setup_engine(*entities):
    """Create a RuleEngine with entity effect support."""
    entity_list = list(entities)
    bus = EventBus()
    engine = RuleEngine(bus, entities_getter=lambda: entity_list)
    return bus, engine


def apply_blinded(engine, entity):
    """Load and apply the blinded entity effect to an entity."""
    rule = RuleLoader.load(os.path.join(CONDITIONS_DIR, "blinded.json"))
    engine.apply_effect(entity, rule)
    return rule


def get_action(entity: Entity, name: str):
    return next(a for a in entity.stat_block.actions if a.name == name)


# ── Blinded attacker gets disadvantage ────────────────────────────────────────

class TestBlindedAttackerDisadvantage:

    def test_blinded_attacker_gets_disadvantage(self):
        """A blinded entity attacking should have disadvantage set on the event."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_blinded(engine, fighter)

        action = get_action(fighter, "Longsword")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=fighter, defender=goblin, action=action)

        assert event.data.get("disadvantage") is True
        assert event.data.get("advantage", False) is False

    def test_blinded_attacker_disadvantage_used_in_resolve_attack(self):
        """resolve_attack should call roll_with_disadvantage for a blinded attacker."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_blinded(engine, fighter)

        from src.combat.combat_system import CombatSystem
        combat = CombatSystem()
        combat.event_bus = bus

        action = get_action(fighter, "Longsword")
        with patch("src.combat.attack_resolver.roll_with_disadvantage", return_value=10) as mock_dis, \
             patch("src.combat.attack_resolver.roll_d20") as mock_d20:
            combat.resolve_attack(fighter, goblin, action)
            mock_dis.assert_called_once()
            mock_d20.assert_not_called()


# ── Blinded defender gives advantage to attacker ──────────────────────────────

class TestBlindedDefenderAdvantage:

    def test_blinded_defender_gives_advantage(self):
        """Attacking a blinded entity should have advantage set on the event."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_blinded(engine, goblin)

        action = get_action(fighter, "Longsword")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=fighter, defender=goblin, action=action)

        assert event.data.get("advantage") is True
        assert event.data.get("disadvantage", False) is False

    def test_blinded_defender_advantage_used_in_resolve_attack(self):
        """resolve_attack should call roll_with_advantage when defender is blinded."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_blinded(engine, goblin)

        from src.combat.combat_system import CombatSystem
        combat = CombatSystem()
        combat.event_bus = bus

        action = get_action(fighter, "Longsword")
        with patch("src.combat.attack_resolver.roll_with_advantage", return_value=15) as mock_adv, \
             patch("src.combat.attack_resolver.roll_d20") as mock_d20:
            combat.resolve_attack(fighter, goblin, action)
            mock_adv.assert_called_once()
            mock_d20.assert_not_called()


# ── Both combatants blinded — cancels out ─────────────────────────────────────

class TestBlindedBothCancelOut:

    def test_both_blinded_cancels_to_normal_roll(self):
        """When both attacker and defender are blinded, advantage and disadvantage
        cancel out per D&D 5e rules — a normal d20 should be rolled."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_blinded(engine, fighter)
        apply_blinded(engine, goblin)

        action = get_action(fighter, "Longsword")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=fighter, defender=goblin, action=action)

        assert event.data.get("advantage") is True
        assert event.data.get("disadvantage") is True

    def test_both_blinded_uses_normal_roll_in_resolve(self):
        """resolve_attack should call plain roll_d20 when both flags are set."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_blinded(engine, fighter)
        apply_blinded(engine, goblin)

        from src.combat.combat_system import CombatSystem
        combat = CombatSystem()
        combat.event_bus = bus

        action = get_action(fighter, "Longsword")
        with patch("src.combat.attack_resolver.roll_d20", return_value=12) as mock_d20, \
             patch("src.combat.attack_resolver.roll_with_advantage") as mock_adv, \
             patch("src.combat.attack_resolver.roll_with_disadvantage") as mock_dis:
            combat.resolve_attack(fighter, goblin, action)
            mock_d20.assert_called_once()
            mock_adv.assert_not_called()
            mock_dis.assert_not_called()


# ── Uninvolved entity ────────────────────────────────────────────────────────

class TestBlindedDoesNotAffectOthers:

    def test_blinded_third_party_does_not_affect_attack(self):
        """Blinded applied to a bystander should not affect an attack between
        two other entities."""
        fighter = load_fighter()
        goblin = load_goblin()
        bystander = load_fighter()
        bus, engine = setup_engine(fighter, goblin, bystander)
        apply_blinded(engine, bystander)

        action = get_action(fighter, "Longsword")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=fighter, defender=goblin, action=action)

        assert event.data.get("advantage", False) is False
        assert event.data.get("disadvantage", False) is False
