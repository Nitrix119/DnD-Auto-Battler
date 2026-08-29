"""Trigger blocks: reactive riders bound to events, scoped to a lifetime (§4.3a).

A trigger subscribes its ``then`` sub-program to a combat event; when the event
fires it runs against a fresh invocation carrying the event's data. Bound inside a
``lifetime`` block, the subscription is owned by the scope — teardown unsubscribes
it. See :mod:`src.spells.blocks.triggers`.
"""

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.models.damage import Damage, DamageType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks
import src.spells.blocks.triggers as triggers_mod


def _caster(hp=30):
    sb = StatBlock(
        name="Warlock",
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 16),
        hit_points_max=hp, armor_class=12,
        proficiency_bonus=2, spellcasting_ability="charisma",
    )
    e = Entity(sb)
    e.refill_resources()
    return e


def _foe(hp=40):
    sb = StatBlock(name="Foe", ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
                   hit_points_max=hp, armor_class=10)
    return Entity(sb)


def _wound(e, amount):
    if amount:
        e.take_damage(Damage(DamageType.GENERIC, amount))


def _establish(caster, program_dicts, bus):
    """Run a program that installs triggers (and/or a lifetime) on *bus*."""
    action = SpellAction(name="Vampiric Touch", description="", spell_level=3)
    resolve_blocks(caster, caster, action, parse_program(program_dicts),
                   event_bus=bus, damage_processor=DamageProcessor(bus))


# A Vampiric-Touch-style heal rider: when the caster deals damage, heal the caster
# for half. Authored as a trigger — the shape §4.3b's fold will produce.
_HEAL_RIDER = {
    "block": "trigger",
    "event": "DAMAGE_DEALT",
    "when": "event.source == entity",
    "then": [
        {"block": "healing", "target": "caster", "amount": "event.total // 2"},
    ],
}


def test_trigger_fires_and_runs_then():
    caster = _caster()
    _wound(caster, 20)  # room to heal
    bus = EventBus()
    _establish(caster, [_HEAL_RIDER], bus)

    before = caster.hp
    bus.emit(EventType.DAMAGE_DEALT, defender=_foe(), source=caster,
             total=10, damage_list=[])
    assert caster.hp == before + 5  # healed event.total // 2


def test_trigger_condition_gates_out_other_sources():
    caster = _caster()
    _wound(caster, 20)
    bus = EventBus()
    _establish(caster, [_HEAL_RIDER], bus)

    before = caster.hp
    # Damage dealt by someone else — condition (source == caster) is false.
    bus.emit(EventType.DAMAGE_DEALT, defender=_foe(), source=_foe(),
             total=10, damage_list=[])
    assert caster.hp == before  # did not fire


def test_trigger_unsubscribes_when_its_lifetime_is_disposed():
    caster = _caster()
    _wound(caster, 25)
    bus = EventBus()
    # The rider lives inside a concentration lifetime.
    _establish(caster, [{
        "block": "lifetime", "kind": "concentration", "source": "Vampiric Touch",
        "then": [_HEAL_RIDER],
    }], bus)
    assert caster.has_concentration

    before = caster.hp
    bus.emit(EventType.DAMAGE_DEALT, defender=_foe(), source=caster,
             total=8, damage_list=[])
    assert caster.hp == before + 4  # fired while concentrating

    # Concentration ends → the scope disposes → the rider unsubscribes.
    caster.end_concentration()
    mid = caster.hp
    bus.emit(EventType.DAMAGE_DEALT, defender=_foe(), source=caster,
             total=8, damage_list=[])
    assert caster.hp == mid  # no further healing — rider gone


def test_trigger_depth_is_balanced_after_firing():
    # The re-entrancy guard must not leak depth: after a fire it returns to 0.
    caster = _caster()
    _wound(caster, 20)
    bus = EventBus()
    _establish(caster, [_HEAL_RIDER], bus)
    assert triggers_mod._depth_by_bus.get(bus, 0) == 0
    bus.emit(EventType.DAMAGE_DEALT, defender=_foe(), source=caster,
             total=6, damage_list=[])
    assert triggers_mod._depth_by_bus.get(bus, 0) == 0


def test_trigger_depth_guard_blocks_at_the_cap():
    # At maximum re-entrancy depth the guard refuses to run a further rider,
    # bounding retaliation chains (design §6.4). The depth is tracked per bus, so
    # simulate this bus being at the cap.
    caster = _caster()
    _wound(caster, 20)
    bus = EventBus()
    _establish(caster, [_HEAL_RIDER], bus)

    triggers_mod._depth_by_bus[bus] = triggers_mod._MAX_TRIGGER_DEPTH
    before = caster.hp
    bus.emit(EventType.DAMAGE_DEALT, defender=_foe(), source=caster,
             total=10, damage_list=[])
    assert caster.hp == before  # guard blocked the rider at the cap
