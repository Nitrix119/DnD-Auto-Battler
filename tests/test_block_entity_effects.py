"""Duration-bound / removable entity effects install on the block engine.

`apply_entity_rule` installs a reactive rule's trigger blocks on the shared bus
(`install_entity_effect`), owned by a `LifetimeScope` on the entity — so a
`duration_rounds` rule expires on the holder's turn (via `tick_lifetimes`) and
`remove_effect` disposes it by name. Proven here with a poison DoT
(TURN_START → 1d6, 3 rounds).
"""

from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.combat.lifetime_clock import install_lifetime_clock
from src.rules import RuleLoader
from src.spells.rules import apply_entity_rule
from src.rules.effect_registry import EffectRegistry

# A duration-bound entity-effect DoT: on the holder's TURN_START, 1d6 poison for
# 3 rounds. Built inline rather than depending on a shipped rule.
_NATIVE_POISON = {
    "name": "poison_dot",
    "duration_rounds": 3,
    "program": [
        {
            # `damage` has no target selector — the enclosing trigger decides who is
            # targeted (here the holder, via `target: "event.entity"`).
            "block": "trigger", "event": "TURN_START", "holder": "caster",
            "when": "event.entity == entity", "target": "event.entity",
            "then": [
                {"block": "damage", "formula": "1d6", "damage_type": "POISON"},
            ],
        },
    ],
}


def _ent(name="E", hp=40):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=10,
    )
    return Entity(sb)


def _wire(*entities):
    bus = EventBus()
    install_lifetime_clock(bus)  # drives duration expiry on TURN_END
    dp = DamageProcessor(bus)
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    return bus, dp


def _poison(bus, dp, entity):
    apply_entity_rule(entity, RuleLoader.from_dict(dict(_NATIVE_POISON)),
                      event_bus=bus, damage_processor=dp)


class TestBlockInstall:

    def test_installed_as_a_scope_owned_rider(self):
        victim = _ent("Victim")
        _bus, dp = _wire(victim)
        _poison(_bus if 'bus' not in dir() else bus, dp, victim)
        assert [s.source for s in victim.lifetimes] == ["poison_dot"]

    def test_fires_on_turn_start(self):
        victim, other = _ent("Victim"), _ent("Other")
        bus, dp = _wire(victim, other)
        _poison(_bus if 'bus' not in dir() else bus, dp, victim)
        hp0 = victim.hp
        with patch("src.spells.blocks.damage.roll_formula", return_value=4):
            bus.emit(EventType.TURN_START, entity=victim, round_num=1)
            assert hp0 - victim.hp == 4               # 1d6 poison to the holder
            # Not on anyone else's turn.
            hp1 = victim.hp
            bus.emit(EventType.TURN_START, entity=other, round_num=1)
            assert victim.hp == hp1

    def test_expires_after_duration(self):
        victim = _ent("Victim", hp=100)
        bus, dp = _wire(victim)
        _poison(_bus if 'bus' not in dir() else bus, dp, victim)
        hp0 = victim.hp
        with patch("src.spells.blocks.damage.roll_formula", return_value=4):
            for rnd in range(1, 4):                   # rounds 1-3: fires, then ticks down
                bus.emit(EventType.TURN_START, entity=victim, round_num=rnd)
                bus.emit(EventType.TURN_END, entity=victim, round_num=rnd)
            assert hp0 - victim.hp == 12              # 3 × 4
            bus.emit(EventType.TURN_START, entity=victim, round_num=4)
            assert hp0 - victim.hp == 12              # expired: no further damage
        assert victim.lifetimes == []

    def test_remove_effect_disposes_the_rider(self):
        victim = _ent("Victim")
        bus, dp = _wire(victim)
        _poison(_bus if 'bus' not in dir() else bus, dp, victim)
        victim.remove_effect("poison_dot")
        assert victim.lifetimes == []
        with patch("src.spells.blocks.damage.roll_formula", return_value=4):
            hp0 = victim.hp
            bus.emit(EventType.TURN_START, entity=victim, round_num=1)
            assert victim.hp == hp0                   # rider gone → no damage
