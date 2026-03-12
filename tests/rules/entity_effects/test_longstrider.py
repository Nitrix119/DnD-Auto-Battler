"""Tests for the Longstrider entity effect.

Verifies that Longstrider grants +10 movement per turn, fires after the global
resource refill rule, and only affects the targeted entity.
"""

import pytest

from src.models import AbilityScores, StatBlock, Entity, ACTION_COST
from src.combat.event_bus import EventBus
from src.combat.events import EventType
from src.combat.event_data import TurnEventData
from src.rules.rule_engine import RuleEngine
from src.rules.rule_loader import RuleLoader

LONGSTRIDER_RULE_PATH = "rules/entity_effects/longstrider.json"
REFILL_RULE_PATH = "rules/action_economy_refill.json"


# -- Helpers ------------------------------------------------------------------

def _make_entity(name="Fighter", hp=30, ac=15, speed=30):
    abilities = AbilityScores(14, 14, 14, 10, 10, 10)
    sb = StatBlock(name=name, ability_scores=abilities, hit_points_max=hp, armor_class=ac)
    sb.resource_defaults["speed"] = speed
    entity = Entity(sb)
    entity.refill_resources()
    return entity


def _emit_turn(bus, entity, round_num=1, turn_num=1):
    """Emit a TURN_START event for *entity*."""
    bus.emit(EventType.TURN_START, TurnEventData(
        entity=entity, round_num=round_num, turn_num=turn_num,
    ))


def _emit_turn_end(bus, entity, round_num=1, turn_num=1):
    """Emit a TURN_END event for *entity* (ticks durations)."""
    bus.emit(EventType.TURN_END, TurnEventData(
        entity=entity, round_num=round_num, turn_num=turn_num,
    ))


def _setup(entity):
    """Wire up an EventBus + RuleEngine with refill rule and longstrider applied."""
    bus = EventBus()
    engine = RuleEngine(
        bus,
        entities_getter=lambda: [entity],
        damage_processor=None,
    )
    engine.load_from_file(REFILL_RULE_PATH)
    longstrider_rule = RuleLoader.load(LONGSTRIDER_RULE_PATH)
    engine.apply_effect(entity, longstrider_rule)
    return bus, engine


# -- Tests --------------------------------------------------------------------

class TestLongstrider:
    def test_grants_extra_movement_after_refill(self):
        """Longstrider adds +10 movement on top of the refilled default."""
        entity = _make_entity()
        bus, _ = _setup(entity)

        # Spend all movement first
        entity.resources.movement = 0

        _emit_turn(bus, entity, round_num=2)
        # Refill restores to 30, then longstrider adds 10 -> 40 total
        assert entity.resources.movement == 40

    def test_does_not_affect_other_resources(self):
        """Longstrider only adds movement, not actions or other resources."""
        entity = _make_entity()
        bus, _ = _setup(entity)

        _emit_turn(bus, entity, round_num=2)
        assert entity.resources.movement == 40
        assert entity.resources.actions == 1
        assert entity.resources.bonus_actions == 1
        assert entity.resources.reactions == 1

    def test_only_affects_targeted_entity(self):
        """Longstrider on entity A does not give extra movement to entity B."""
        entity_a = _make_entity("Enchanted Fighter")
        entity_b = _make_entity("Normal Fighter")
        bus = EventBus()
        all_entities = [entity_a, entity_b]
        engine = RuleEngine(
            bus,
            entities_getter=lambda: all_entities,
            damage_processor=None,
        )
        engine.load_from_file(REFILL_RULE_PATH)
        longstrider_rule = RuleLoader.load(LONGSTRIDER_RULE_PATH)
        engine.apply_effect(entity_a, longstrider_rule)

        # Entity B's turn -- should get normal movement only
        _emit_turn(bus, entity_b, round_num=1)
        assert entity_b.resources.movement == 30

        # Entity A's turn -- should get the longstrider bonus
        _emit_turn(bus, entity_a, round_num=1, turn_num=2)
        assert entity_a.resources.movement == 40

    def test_stacks_with_higher_base_speed(self):
        """An entity with 40 base speed gets 50 with longstrider."""
        entity = _make_entity(speed=40)
        bus, _ = _setup(entity)

        _emit_turn(bus, entity, round_num=2)
        assert entity.resources.movement == 50

    def test_persists_across_rounds(self):
        """Longstrider has no duration_rounds, so it persists indefinitely."""
        entity = _make_entity()
        bus, _ = _setup(entity)

        for r in range(1, 6):
            _emit_turn(bus, entity, round_num=r)
            assert entity.resources.movement == 40, f"Round {r}: should still have longstrider"
            _emit_turn_end(bus, entity, round_num=r)

        # Still active after many rounds
        _emit_turn(bus, entity, round_num=6)
        assert entity.resources.movement == 40
