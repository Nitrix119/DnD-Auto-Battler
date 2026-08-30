"""Weapon-attack parity: the block engine resolves an attack like the legacy one.

`AttackResolver` now routes weapon attacks through the block engine (the same
`[attack_roll, damage…]` a spell uses), keeping a legacy fallback only for an
attacker carrying a pipeline-injecting effect (Colossus Slayer). These tests
dual-run a weapon attack on both engines under one seed and assert identical
outcomes, and pin the routing: ordinary attackers go to blocks; a Colossus
attacker stays on legacy and still lands its bonus die.
"""

from copy import copy
from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver, _build_pipeline_effects
from src.combat.effect_pipeline import EffectPipeline
from src.combat.reactive_guard import caster_has_injection_effect
from src.models.spell_properties import TargetingType
from src.rules import RuleEngine, RuleLoader
from src.rules.effect_registry import EffectRegistry
import src.utils.dice as dice


def _entity(name="E", ac=10, hp=200):
    sb = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=ac,
    )
    return Entity(sb)


def _weapon(bonus, damage):
    return AttackAction(
        name="Sword", description="",
        bonus_to_hit=bonus,
        damage=[Damage(dt, 0, formula=f) for dt, f in damage],
    )


def _legacy_result(attacker, defender, action, bus, dp):
    ac = copy(action)
    ac.pipeline_effects = _build_pipeline_effects(action)
    return EffectPipeline(bus, dp).run(attacker, defender, ac)


def _block_result(attacker, defender, action, bus, dp):
    from src.spells.evaluator import resolve as resolve_blocks
    from src.spells.adapter import to_program

    program = to_program(_build_pipeline_effects(action), TargetingType.SINGLE_TARGET)
    return resolve_blocks(attacker, defender, action, program,
                          event_bus=bus, damage_processor=dp)


def _run(engine_fn, seed, *, bonus, ac, damage):
    """Resolve one weapon attack on a fresh, seeded battle; return the outcome tuple."""
    dice.seed_rng(seed)
    attacker = _entity("A")
    defender = _entity("D", ac=ac)
    bus = EventBus()
    dp = DamageProcessor(bus)
    result = engine_fn(attacker, defender, _weapon(bonus, damage), bus, dp)
    return (result.hit, result.damage_dealt, result.attack_roll,
            result.attack_total, defender.hp)


class TestWeaponAttackParity:
    """The block path matches the legacy pipeline field-for-field under one seed."""

    def _assert_parity(self, **kw):
        for seed in (1, 7, 42, 1000):
            legacy = _run(_legacy_result, seed, **kw)
            block = _run(_block_result, seed, **kw)
            assert block == legacy, f"seed={seed}: {block} != {legacy}"

    def test_hit(self):
        self._assert_parity(bonus=10, ac=5, damage=[(DamageType.SLASHING, "1d8")])

    def test_miss(self):
        # High AC, low bonus — the attack misses on both engines, no damage.
        self._assert_parity(bonus=0, ac=40, damage=[(DamageType.SLASHING, "1d8")])

    def test_multi_type_damage(self):
        self._assert_parity(
            bonus=10, ac=5,
            damage=[(DamageType.SLASHING, "1d8"), (DamageType.FIRE, "1d6")],
        )


class TestAttackRouting:
    def test_ordinary_attacker_has_no_injection_effect(self):
        # No injection effect → AttackResolver.resolve takes the block path.
        assert caster_has_injection_effect(_entity("A")) is False

    def test_colossus_attacker_stays_on_legacy_with_bonus_die(self):
        """A Colossus attacker keeps the legacy path (guard) and lands the bonus die."""
        bus = EventBus()
        dp = DamageProcessor(bus)
        reg = EffectRegistry()
        reg.scan_directory("rules/entity_effects")
        ranger = _entity("Ranger", hp=40)
        target = _entity("Target", hp=40)
        engine = RuleEngine(bus, entities_getter=lambda: [ranger, target],
                            damage_processor=dp, effect_registry=reg)
        engine.apply_effect(ranger, RuleLoader.load("rules/entity_effects/colossus_slayer.json"))
        assert caster_has_injection_effect(ranger) is True  # routes to legacy

        target.take_damage(Damage(DamageType.SLASHING, 5))  # wound so Colossus fires
        hp_before = target.hp
        ar = AttackResolver(bus, dp, rule_engine=engine)
        with patch("src.combat.effect_pipeline.roll_d20", return_value=15), \
             patch("src.combat.effect_pipeline.roll_formula", return_value=3):
            hit, damage, _log, _detail = ar.resolve(ranger, target, _weapon(20, [(DamageType.SLASHING, "1d8")]))
        assert hit
        assert hp_before - target.hp == 6  # weapon 1d8 (3) + Colossus 1d8 (3)
