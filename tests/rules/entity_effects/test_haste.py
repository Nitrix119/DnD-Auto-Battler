"""Tests for the Haste spell's per-turn action grant (native block program).

Verifies that Haste grants +1 action per turn, fires after the global resource
refill rule, and expires correctly after its duration. Haste is now authored as a
native ``program`` (Phase 3 §5) — its rider is installed by **casting the spell**
(self-cast here), not by applying a standalone entity-effect rule. The block-native
end-to-end coverage on a targeted ally lives in
``tests/test_entity_effect_fold.py::TestHasteFold``.
"""

from src.models import AbilityScores, StatBlock, Entity, ACTION_COST
from src.combat.event_bus import EventBus
from src.combat.events import EventType
from src.combat.event_data import TurnEventData
from src.combat.damage_processor import DamageProcessor
from src.combat.spell_resolver import SpellResolver
from src.combat.lifetime_clock import install_lifetime_clock
from src.rules.rule_engine import RuleEngine
from src.rules.effect_registry import EffectRegistry
from src.loaders import StatBlockLoader

HASTE_SPELL_PATH = "examples/spells/haste.json"
REFILL_RULE_PATH = "rules/global/action_economy_refill.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_entity(name="Fighter", hp=30, ac=15):
    abilities = AbilityScores(14, 14, 14, 10, 10, 10)
    sb = StatBlock(name=name, ability_scores=abilities, hit_points_max=hp, armor_class=ac)
    return Entity(sb)


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


def _engine(bus, entities):
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    engine = RuleEngine(bus, entities_getter=lambda: list(entities),
                        damage_processor=DamageProcessor(bus), effect_registry=reg)
    engine.load_from_file(REFILL_RULE_PATH)
    return engine


def _cast_haste_on(entity, *others):
    """Cast Haste (self-cast) so its native rider is installed on *entity*."""
    bus = EventBus()
    install_lifetime_clock(bus)  # ticks the concentration duration on TURN_END
    engine = _engine(bus, [entity, *others])
    resolver = SpellResolver(bus, engine._damage_processor, rule_engine=engine)
    resolver.resolve(entity, [entity],
                     StatBlockLoader.load_spell_from_json(HASTE_SPELL_PATH))
    return bus, engine


def _setup(entity):
    """Cast Haste on *entity* and return its (bus, engine)."""
    return _cast_haste_on(entity)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestHaste:
    def test_grants_extra_action_after_refill(self):
        """Haste adds +1 action on top of the refilled default."""
        entity = _make_entity()
        bus, _ = _setup(entity)

        entity.spend_resources(ACTION_COST)
        assert entity.resources.actions == 0

        _emit_turn(bus, entity, round_num=2)
        # Refill restores to 1, then haste adds 1 → 2 total
        assert entity.resources.actions == 2

    def test_does_not_affect_other_resources(self):
        """Haste only adds actions, not bonus actions or reactions."""
        entity = _make_entity()
        bus, _ = _setup(entity)

        _emit_turn(bus, entity, round_num=2)
        assert entity.resources.actions == 2
        assert entity.resources.bonus_actions == 1
        assert entity.resources.reactions == 1

    def test_only_affects_hasted_entity(self):
        """Haste on entity A does not give extra actions to entity B."""
        entity_a = _make_entity("Hasted Fighter")
        entity_b = _make_entity("Normal Fighter")
        bus, engine = _cast_haste_on(entity_a, entity_b)

        # Entity B's turn — should get normal resources only
        _emit_turn(bus, entity_b, round_num=1)
        assert entity_b.resources.actions == 1

        # Entity A's turn — should get the haste bonus
        _emit_turn(bus, entity_a, round_num=1, turn_num=2)
        assert entity_a.resources.actions == 2

    def test_stacks_with_overfill(self):
        """If entity already has 2 base actions, haste adds a third."""
        entity = _make_entity()
        entity.stat_block.resource_defaults["actions"] = 2
        entity.refill_resources()
        bus, _ = _setup(entity)

        _emit_turn(bus, entity, round_num=2)
        assert entity.resources.actions == 3

    def test_expires_after_duration(self):
        """After 10 TURN_END ticks, haste no longer grants the bonus."""
        entity = _make_entity()
        bus, _ = _setup(entity)

        # Simulate 10 rounds of turns (haste lasts 10 rounds)
        for r in range(1, 11):
            _emit_turn(bus, entity, round_num=r)
            assert entity.resources.actions == 2, f"Round {r}: should still have haste"
            _emit_turn_end(bus, entity, round_num=r)

        # Round 11: haste has expired
        _emit_turn(bus, entity, round_num=11)
        assert entity.resources.actions == 1
