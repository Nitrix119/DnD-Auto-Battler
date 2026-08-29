"""Lifetime block end-to-end: concentration through the real stack (Phase 2, §4.2).

Proves the lifetime-scope mechanism where it must work — a concentration program
run through the real evaluator, applied to a real Entity, and torn down by the
*actual* global concentration-break rule on real damage. Not a unit test on
hand-built scopes: the whole path from block → grant handle → caster scope →
DAMAGE_DEALT → failed CON save → dispose.
"""

from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.rules import RuleEngine, RuleLoader
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks


def _caster():
    sb = StatBlock(
        name="Cleric",
        ability_scores=AbilityScores(10, 10, 12, 10, 16, 10),
        hit_points_max=30,
        armor_class=14,
        proficiency_bonus=2,
        spellcasting_ability="wisdom",
    )
    e = Entity(sb)
    e.refill_resources()
    return e


def _target(ac=12):
    sb = StatBlock(
        name="Ally",
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=30,
        armor_class=ac,
    )
    return Entity(sb)


# Shield of Faith, expressed natively: a +2 AC modifier owned by a concentration
# lifetime. (Not yet routed from JSON — the add_entity_effect fold is §4.3 — but
# this is exactly the program that fold will produce.)
_SHIELD_OF_FAITH = [
    {
        "block": "lifetime",
        "kind": "concentration",
        "source": "Shield of Faith",
        "then": [
            {
                "block": "add_modifier",
                "target": "defender",
                "stat": "ac",
                "value": 2,
                "source": "Shield of Faith",
            },
        ],
    }
]


def _run(caster, target, program_dicts):
    bus = EventBus()
    action = SpellAction(name="Shield of Faith", description="", spell_level=1)
    resolve_blocks(
        caster,
        target,
        action,
        parse_program(program_dicts),
        event_bus=bus,
        damage_processor=DamageProcessor(bus),
    )


def test_concentration_program_applies_buff_and_opens_scope():
    caster, target = _caster(), _target(ac=12)
    _run(caster, target, _SHIELD_OF_FAITH)
    assert target.ac == 14  # +2 applied
    assert caster.has_concentration  # caster is concentrating
    assert caster.concentration_scope is not None
    assert len(caster.concentration_scope.handles) == 1


def test_new_concentration_spell_drops_the_prior_buff():
    caster, target = _caster(), _target(ac=12)
    _run(caster, target, _SHIELD_OF_FAITH)
    assert target.ac == 14
    first_scope = caster.concentration_scope

    # Cast another concentration spell (a second +2 on a different ally).
    other = _target(ac=10)
    _run(caster, other, _SHIELD_OF_FAITH)

    assert first_scope.disposed
    assert target.ac == 12  # first buff revoked atomically
    assert other.ac == 12  # new buff present
    assert caster.concentration_scope is not first_scope


def test_grant_outside_a_lifetime_is_permanent():
    # A bare add_modifier (no lifetime wrapper) is instantaneous/permanent — no
    # scope owns it, nothing to revoke. Parity with pre-4.2 behaviour.
    caster, target = _caster(), _target(ac=12)
    _run(
        caster,
        target,
        [
            {
                "block": "add_modifier",
                "target": "defender",
                "stat": "ac",
                "value": 2,
                "source": "Permanent",
            },
        ],
    )
    assert target.ac == 14
    assert not caster.has_concentration


def test_concentration_break_on_damage_revokes_the_buff_end_to_end():
    """Failed CON save from damage must dispose the scope and remove the buff."""
    caster, target = _caster(), _target(ac=12)
    _run(caster, target, _SHIELD_OF_FAITH)
    assert target.ac == 14 and caster.has_concentration

    # The real global concentration rule on a shared bus/engine.
    bus = EventBus()
    engine = RuleEngine(bus, entities_getter=lambda: [caster, target])
    engine.load_rule(
        RuleLoader.from_dict(
            {
                "name": "concentration_damage_check",
                "triggers": ["DAMAGE_DEALT"],
                "condition": "event.defender.has_concentration and event.total > 0",
                "effects": [
                    {
                        "action": "ForceConcentrationCheck",
                        "target": "event.defender",
                        "dc": "max(10, event.total // 2)",
                    }
                ],
            }
        )
    )

    # Caster takes damage and fails the CON save (rolls a 1).
    with patch("src.rules.effects.roll_d20", return_value=1):
        bus.emit(EventType.DAMAGE_DEALT, defender=caster, damage_list=[], total=20)

    assert not caster.has_concentration  # concentration lost
    assert caster.concentration_scope is None
    assert target.ac == 12  # the +2 AC buff revoked


def test_duration_lifetime_expires_via_the_real_turn_end_clock():
    """A rounds-duration lifetime disposes after N of the holder's TURN_ENDs.

    Drives the actual clock: RuleEngine._tick_durations on TURN_END calls
    Entity.tick_lifetimes. After the duration elapses the buff is revoked.
    """
    from src.rules import RuleEngine
    from src.combat.event_data import TurnEventData

    caster, target = _caster(), _target(ac=12)
    bus = EventBus()
    RuleEngine(bus, entities_getter=lambda: [caster, target])

    program = [{
        "block": "lifetime", "kind": "rounds", "duration_rounds": 2,
        "source": "Barkskin",
        "then": [{"block": "add_modifier", "target": "defender",
                  "stat": "ac", "value": 2, "source": "Barkskin"}],
    }]
    action = SpellAction(name="Barkskin", description="", spell_level=2)
    resolve_blocks(caster, target, action, parse_program(program),
                   event_bus=bus, damage_processor=DamageProcessor(bus))
    assert target.ac == 14 and len(target.lifetimes) == 1

    bus.emit(EventType.TURN_END, TurnEventData(entity=target, round_num=1, turn_num=1))
    assert target.ac == 14  # one round left
    bus.emit(EventType.TURN_END, TurnEventData(entity=target, round_num=2, turn_num=1))
    assert target.ac == 12          # expired: buff revoked
    assert target.lifetimes == []


def test_concentration_held_on_a_successful_save():
    caster, target = _caster(), _target(ac=12)
    _run(caster, target, _SHIELD_OF_FAITH)

    bus = EventBus()
    engine = RuleEngine(bus, entities_getter=lambda: [caster, target])
    engine.load_rule(
        RuleLoader.from_dict(
            {
                "name": "concentration_damage_check",
                "triggers": ["DAMAGE_DEALT"],
                "condition": "event.defender.has_concentration and event.total > 0",
                "effects": [
                    {
                        "action": "ForceConcentrationCheck",
                        "target": "event.defender",
                        "dc": "max(10, event.total // 2)",
                    }
                ],
            }
        )
    )

    with patch("src.rules.effects.roll_d20", return_value=20):  # passes the save
        bus.emit(EventType.DAMAGE_DEALT, defender=caster, damage_list=[], total=20)

    assert caster.has_concentration  # kept
    assert target.ac == 14  # buff intact
