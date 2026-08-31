"""Duration-bound / removable entity effects install on the block engine (§3).

`RuleEngine.apply_effect` routes a cleanly-foldable reactive rule onto the block
engine (`install_entity_effect`) when a damage_processor is wired. Beyond the
permanent Colossus rider, this now covers **duration-bound** effects: the rule's
triggers are owned by a `LifetimeScope` on the entity, so a `duration_rounds` rule
expires on the holder's turn (via `tick_lifetimes`) and `remove_effect` disposes it
by name. Proven here with the spider-bite poison DoT (TURN_START → 1d6, 3 rounds).
Without a damage_processor the effect still falls back to the legacy dispatch.
"""

from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.combat.lifetime_clock import install_lifetime_clock
from src.rules import RuleEngine, RuleLoader
from src.rules.effect_registry import EffectRegistry

POISON = "rules/entity_effects/conditions/spider_bite_poison.json"


def _ent(name="E", hp=40):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=10,
    )
    return Entity(sb)


def _wire(*entities, with_dp=True):
    bus = EventBus()
    install_lifetime_clock(bus)  # drives duration expiry on TURN_END
    dp = DamageProcessor(bus) if with_dp else None
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    engine = RuleEngine(
        bus, entities_getter=lambda: list(entities),
        damage_processor=dp, effect_registry=reg,
    )
    return bus, engine


def _poison(engine, entity):
    engine.apply_effect(entity, RuleLoader.load(POISON))


class TestBlockInstall:

    def test_installed_on_blocks_not_active_effects(self):
        victim = _ent("Victim")
        _bus, engine = _wire(victim)
        _poison(engine, victim)
        assert victim.get_effects_for_trigger("turn_start") == []   # not legacy-filed
        assert len(victim.lifetimes) == 1                            # owned by a scope

    def test_fires_on_turn_start(self):
        victim, other = _ent("Victim"), _ent("Other")
        bus, engine = _wire(victim, other)
        _poison(engine, victim)
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
        bus, engine = _wire(victim)
        _poison(engine, victim)
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
        bus, engine = _wire(victim)
        _poison(engine, victim)
        engine.remove_effect(victim, "spider_bite_poison")
        assert victim.lifetimes == []
        with patch("src.spells.blocks.damage.roll_formula", return_value=4):
            hp0 = victim.hp
            bus.emit(EventType.TURN_START, entity=victim, round_num=1)
            assert victim.hp == hp0                   # rider gone → no damage

    def test_without_damage_processor_falls_back_to_legacy(self):
        victim = _ent("Victim")
        _bus, engine = _wire(victim, with_dp=False)
        _poison(engine, victim)
        # No block install without a damage_processor → filed for legacy dispatch.
        assert victim.get_effects_for_trigger("turn_start") != []
        assert victim.lifetimes == []
