"""Tests for the Charmed condition entity effect.

Verifies that a charmed entity cannot attack the entity that charmed it,
while attacks against all other entities proceed normally.  Also verifies
that instance_fields are independent when the same rule is applied to
multiple entities with different charmers.
"""

import os

from src.models import Entity
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


def apply_charmed(engine, target, charmer):
    """Load and apply the charmed entity effect, binding the charmer."""
    rule = RuleLoader.load(os.path.join(CONDITIONS_DIR, "charmed.json"))
    engine.apply_effect(target, rule, instance_fields={"charmer": charmer})
    return rule


def get_action(entity: Entity, name: str):
    return next(a for a in entity.stat_block.actions if a.name == name)


# ── Charmed entity cannot attack the charmer ──────────────────────────────────

class TestCharmedCannotAttackCharmer:

    def test_attack_against_charmer_is_cancelled(self):
        """A charmed entity's attack targeting the charmer should be cancelled."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        apply_charmed(engine, goblin, charmer=fighter)

        action = get_action(goblin, "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=fighter, action=action)

        assert event.cancelled is True

    def test_attack_against_other_is_not_cancelled(self):
        """A charmed entity's attack targeting a non-charmer should proceed normally."""
        fighter = load_fighter()
        goblin = load_goblin()
        bystander = load_fighter()
        bus, engine = setup_engine(fighter, goblin, bystander)
        apply_charmed(engine, goblin, charmer=fighter)

        action = get_action(goblin, "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=bystander, action=action)

        assert event.cancelled is False

    def test_uncharmed_entity_can_attack_charmer(self):
        """An entity that is not charmed should be able to attack anyone freely."""
        fighter = load_fighter()
        goblin = load_goblin()
        bus, engine = setup_engine(fighter, goblin)
        # goblin is charmed, but fighter is not — fighter should attack freely
        apply_charmed(engine, goblin, charmer=fighter)

        action = get_action(fighter, "Longsword")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=fighter, defender=goblin, action=action)

        assert event.cancelled is False


# ── Instance fields are independent per application ───────────────────────────

class TestCharmedInstanceIndependence:

    def test_each_charmed_entity_tracks_own_charmer(self):
        """Two entities charmed by different charmers each block only their own charmer."""
        wizard = load_fighter()
        fighter = load_fighter()
        goblin = load_goblin()
        bystander = load_goblin()
        bus, engine = setup_engine(wizard, fighter, goblin, bystander)

        # goblin is charmed by wizard; bystander is charmed by fighter
        apply_charmed(engine, goblin, charmer=wizard)
        apply_charmed(engine, bystander, charmer=fighter)

        action_goblin = get_action(goblin, "Scimitar")
        action_bystander = get_action(bystander, "Scimitar")

        # goblin cannot attack wizard (its charmer)
        event1 = bus.emit(EventType.ATTACK_DECLARED,
                          attacker=goblin, defender=wizard, action=action_goblin)
        assert event1.cancelled is True

        # goblin CAN attack fighter (not its charmer)
        event2 = bus.emit(EventType.ATTACK_DECLARED,
                          attacker=goblin, defender=fighter, action=action_goblin)
        assert event2.cancelled is False

        # bystander cannot attack fighter (its charmer)
        event3 = bus.emit(EventType.ATTACK_DECLARED,
                          attacker=bystander, defender=fighter, action=action_bystander)
        assert event3.cancelled is True

        # bystander CAN attack wizard (not its charmer)
        event4 = bus.emit(EventType.ATTACK_DECLARED,
                          attacker=bystander, defender=wizard, action=action_bystander)
        assert event4.cancelled is False

    def test_same_rule_applied_twice_independent_duration(self):
        """Two applications of the charmed rule to different entities have
        independent duration counters — ticking one does not affect the other."""
        fighter = load_fighter()
        goblin = load_goblin()
        charmer = load_fighter()
        bus, engine = setup_engine(fighter, goblin, charmer)

        rule = RuleLoader.load(os.path.join(CONDITIONS_DIR, "charmed.json"))
        rule.duration_rounds = 2

        engine.apply_effect(fighter, rule, instance_fields={"charmer": charmer})
        engine.apply_effect(goblin, rule, instance_fields={"charmer": charmer})

        # Both entities should have their own EffectInstance with duration 2
        fighter_instance = fighter.active_effects["attack_declared"][0]
        goblin_instance = goblin.active_effects["attack_declared"][0]
        assert fighter_instance is not goblin_instance
        assert fighter_instance.duration_remaining == 2
        assert goblin_instance.duration_remaining == 2

        # Tick fighter's turn — only fighter's instance should decrement
        bus.emit(EventType.TURN_END, entity=fighter)
        assert fighter_instance.duration_remaining == 1
        assert goblin_instance.duration_remaining == 2
