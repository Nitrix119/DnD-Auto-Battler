"""Colossus Slayer as a native block-engine ATTACK_HIT trigger (Phase 3 §2).

Colossus Slayer used to be a legacy *pipeline injection* — an ATTACK_HIT handler that
appended a damage step to the running attack's ``pipeline_effects``. It is now an
ordinary ``ATTACK_HIT`` block ``trigger`` installed on the shared event bus by
``RuleEngine.apply_effect`` (which folds a permanent reactive rider onto the block
engine). These tests resolve a real weapon attack through ``AttackResolver`` (the
block path) and assert the *outcome*: the bonus die lands only on a wounded target,
only for the effect's own attacker, once per attack, and is dealt as a **separate**
contribution from the weapon's own damage. Crit-doubling of an on-hit rider's die is
proven generally in ``tests/test_block_trigger_context.py``.
"""

import os

from unittest.mock import patch

from src.models import (
    AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType,
)
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver
from src.loaders import StatBlockLoader
from src.rules import RuleEngine, RuleLoader
from src.rules.effect_registry import EffectRegistry

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples")
COLOSSUS_JSON = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "rules", "entity_effects",
    "colossus_slayer.json",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _entity(name="E", ac=10, hp=40):
    sb = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=ac,
    )
    return Entity(sb)


def _weapon(bonus=20, dtype=DamageType.SLASHING, formula="1d8"):
    return AttackAction(
        name="Sword", description="", bonus_to_hit=bonus,
        damage=[Damage(dtype, 0, formula=formula)],
    )


def _setup(*entities, colossus_on=None):
    """Wire an EventBus + DamageProcessor + RuleEngine + AttackResolver.

    ``colossus_on`` gets Colossus Slayer applied; ``apply_effect`` installs it as a
    block trigger on the shared bus, owned by a lifetime scope on the holder.
    """
    bus = EventBus()
    dp = DamageProcessor(bus)
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    engine = RuleEngine(
        bus,
        damage_processor=dp, effect_registry=reg,
    )
    if colossus_on is not None:
        engine.apply_effect(colossus_on, RuleLoader.load(COLOSSUS_JSON))
    return bus, dp, engine, AttackResolver(bus, dp, rule_engine=engine)


def _hit(ar, attacker, defender, weapon=None):
    """Resolve a guaranteed hit with fixed rolls; return (hit, reported_damage)."""
    with patch("src.spells.blocks.rolls.roll_d20", return_value=15), \
         patch("src.spells.blocks.damage.roll_formula", return_value=3):
        hit, dmg, _log, _detail = ar.resolve(attacker, defender, weapon or _weapon())
    return hit, dmg


# ── Fixture loading (unchanged general creature-loading coverage) ─────────────

class TestFixtureLoading:

    def test_rule_json_is_a_native_program(self):
        """The rider's events live inside its program's trigger blocks."""
        rule = RuleLoader.load(COLOSSUS_JSON)
        assert rule.name == "colossus_slayer"
        assert rule.program and rule.program[0]["event"] == "ATTACK_HIT"
        assert rule.duration_rounds is None
        assert rule.source == "Colossus Slayer"

    def test_ranger_loads_with_three_weapons(self):
        sb = StatBlockLoader.load_from_json(
            os.path.join(EXAMPLES_DIR, "creatures/characters/ranger.json")
        )
        ranger = Entity(sb)
        assert ranger.name == "Hunter Ranger"
        names = {a.name for a in ranger.stat_block.actions}
        assert {"Club", "Shortsword", "Shortbow"} <= names

    def test_weapon_damage_types(self):
        sb = StatBlockLoader.load_from_json(
            os.path.join(EXAMPLES_DIR, "creatures/characters/ranger.json")
        )
        ranger = Entity(sb)
        by_name = {a.name: a for a in ranger.stat_block.actions}
        assert by_name["Club"].damage[0].damage_type == DamageType.BLUDGEONING
        assert by_name["Shortsword"].damage[0].damage_type == DamageType.SLASHING
        assert by_name["Shortbow"].damage[0].damage_type == DamageType.PIERCING


# ── Colossus Slayer as a block trigger ────────────────────────────────────────

class TestColossusSlayerBonusDie:

    def test_bonus_die_lands_on_a_wounded_target(self):
        ranger = _entity("Ranger")
        target = _entity("Target", hp=40)
        target.take_damage(Damage(DamageType.BLUDGEONING, 5))  # wound → CS fires

        _bus, _dp, _engine, ar = _setup(ranger, target, colossus_on=ranger)
        hp_before = target.hp
        hit, reported = _hit(ar, ranger, target)

        assert hit
        # Weapon 1d8 (3) + Colossus 1d8 (3), the bonus die dealt as a separate
        # contribution from the weapon's own damage block.
        assert hp_before - target.hp == 6
        # AttackResolver reports the weapon attack's own damage only; the rider's
        # die reaches the target through its own trigger invocation.
        assert reported == 3

    def test_no_bonus_die_at_full_hp(self):
        ranger = _entity("Ranger")
        target = _entity("Target", hp=40)  # full HP → CS condition false

        _bus, _dp, _engine, ar = _setup(ranger, target, colossus_on=ranger)
        hp_before = target.hp
        hit, _reported = _hit(ar, ranger, target)

        assert hit
        assert hp_before - target.hp == 3  # weapon only

    def test_no_bonus_die_for_a_different_attacker(self):
        ranger = _entity("Ranger")
        other = _entity("Other")
        target = _entity("Target", hp=40)
        target.take_damage(Damage(DamageType.BLUDGEONING, 5))  # wounded

        # Colossus is on the ranger; the *other* creature attacks.
        _bus, _dp, _engine, ar = _setup(ranger, other, target, colossus_on=ranger)
        hp_before = target.hp
        hit, _reported = _hit(ar, other, target)

        assert hit
        assert hp_before - target.hp == 3  # ranger's CS does not fire for `other`

    def test_repeated_attacks_do_not_compound_the_bonus_die(self):
        ranger = _entity("Ranger")
        target = _entity("Target", hp=100)
        target.take_damage(Damage(DamageType.BLUDGEONING, 5))  # wounded

        _bus, _dp, _engine, ar = _setup(ranger, target, colossus_on=ranger)
        for _ in range(3):
            hp_before = target.hp
            _hit(ar, ranger, target)
            assert hp_before - target.hp == 6  # exactly one bonus die each attack

    def test_bonus_die_does_not_leak_across_targets(self):
        ranger = _entity("Ranger")
        t1 = _entity("T1", hp=100)
        t2 = _entity("T2", hp=100)
        t1.take_damage(Damage(DamageType.BLUDGEONING, 5))
        t2.take_damage(Damage(DamageType.BLUDGEONING, 5))

        _bus, _dp, _engine, ar = _setup(ranger, t1, t2, colossus_on=ranger)
        b1, b2 = t1.hp, t2.hp
        _hit(ar, ranger, t1)
        _hit(ar, ranger, t2)
        assert b1 - t1.hp == 6
        assert b2 - t2.hp == 6

    def test_installed_as_a_scope_owned_bus_subscription(self):
        """apply_effect installs the rider on the block engine, owned by a lifetime
        scope on the holder keyed to the rule name — so removal can dispose it."""
        ranger = _entity("Ranger")
        _bus, _dp, _engine, _ar = _setup(ranger, colossus_on=ranger)
        assert [s.source for s in ranger.lifetimes] == ["colossus_slayer"]
