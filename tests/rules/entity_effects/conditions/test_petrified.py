"""Tests for the Petrified condition entity effect.

Petrified has two riders: the petrified creature cannot act (its declared attack is
cancelled) while attacks against it have advantage, and it takes half damage.

The damage-resistance half was mechanically dead: its DAMAGE_INCOMING trigger guarded
on ``event.attacker``, a field that event does not carry, so the guard raised
AttributeError and was swallowed as "did not fire" — indistinguishable from a
legitimate miss. Caught at load once `validate_program` checked event references
against the trigger's declared event (E6, rule side).
"""

import os

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType
from src.combat import EventBus, EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleLoader
from src.spells.rules import apply_entity_rule

CONDITIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..",
    "rules", "entity_effects", "conditions",
)
PETRIFIED_JSON = os.path.join(CONDITIONS_DIR, "petrified.json")


def _entity(name="Statue", hp=40):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=10,
    )
    return Entity(sb)


def _wire():
    bus = EventBus()
    return bus, DamageProcessor(bus)


def _petrify(bus, dp, entity):
    apply_entity_rule(entity, RuleLoader.load(PETRIFIED_JSON),
                      event_bus=bus, damage_processor=dp)


class TestPetrifiedDamageResistance:

    def test_petrified_creature_takes_half_damage(self):
        victim = _entity()
        bus, dp = _wire()
        _petrify(bus, dp, victim)

        hp0 = victim.hp
        dp.apply_damage(victim, [Damage(DamageType.SLASHING, 10)])
        assert hp0 - victim.hp == 5  # halved

    def test_damage_to_others_is_untouched(self):
        victim, bystander = _entity("Statue"), _entity("Bystander")
        bus, dp = _wire()
        _petrify(bus, dp, victim)

        hp0 = bystander.hp
        dp.apply_damage(bystander, [Damage(DamageType.SLASHING, 10)])
        assert hp0 - bystander.hp == 10  # full


class TestPetrifiedIncapacitation:

    def test_petrified_creature_cannot_attack(self):
        victim, other = _entity("Statue"), _entity("Other")
        bus, dp = _wire()
        _petrify(bus, dp, victim)

        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=victim, defender=other, action=None)
        assert event.cancelled is True

    def test_attacks_against_a_petrified_creature_have_advantage(self):
        victim, other = _entity("Statue"), _entity("Other")
        bus, dp = _wire()
        _petrify(bus, dp, victim)

        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=other, defender=victim, action=None)
        assert event.data.get("advantage") is True
        assert event.cancelled is False
