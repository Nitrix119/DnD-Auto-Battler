"""Tests for the Longstrider spell's per-turn movement grant (native block program).

Verifies that Longstrider grants +10 movement per turn, fires after the global
resource refill rule, only affects the targeted entity, and persists (no duration).
Longstrider is now authored as a native ``program`` (Phase 3 §5) — its rider is
installed by **casting the spell** (self-cast here), not by applying a standalone
entity-effect rule. The refill-ordering end-to-end proof lives in
``tests/test_persistent_spells.py::TestLongstriderEndToEnd``.
"""

from src.models import AbilityScores, StatBlock, Entity
from src.combat.event_bus import EventBus
from src.combat.events import EventType
from src.combat.event_data import TurnEventData
from src.combat.damage_processor import DamageProcessor
from src.combat.spell_resolver import SpellResolver
from src.combat.lifetime_clock import install_lifetime_clock
from src.spells.rules import load_rule_file
from src.rules.effect_registry import EffectRegistry
from src.loaders import StatBlockLoader

LONGSTRIDER_SPELL_PATH = "examples/spells/longstrider.json"
REFILL_RULE_PATH = "rules/global/action_economy_refill.json"


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
    """Emit a TURN_END event for *entity* (ticks lifetimes/durations)."""
    bus.emit(EventType.TURN_END, TurnEventData(
        entity=entity, round_num=round_num, turn_num=turn_num,
    ))


def _cast_longstrider_on(entity, *others):
    """Cast Longstrider (self-cast) so its native rider is installed on *entity*."""
    bus = EventBus()
    install_lifetime_clock(bus)
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    dp = DamageProcessor(bus)
    load_rule_file(REFILL_RULE_PATH, event_bus=bus, damage_processor=dp)
    resolver = SpellResolver(bus, dp, condition_rules=reg)
    resolver.resolve(entity, [entity],
                     StatBlockLoader.load_spell_from_json(LONGSTRIDER_SPELL_PATH))
    return bus, reg


def _setup(entity):
    """Cast Longstrider on *entity* and return its (bus, condition catalogue)."""
    return _cast_longstrider_on(entity)


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
        bus, engine = _cast_longstrider_on(entity_a, entity_b)

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
