"""Weapon-attack resolution on the block engine (the only engine).

`AttackResolver` resolves a weapon attack through the block engine (the same
`[attack_roll, damage…]` a spell uses). These tests drive the real `AttackResolver`
with controlled rolls to pin hit / miss / multi-type damage, and that a Colossus
attacker — a native ATTACK_HIT block trigger — resolves on blocks and lands its
bonus die.
"""

from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver
from src.rules import RuleLoader
from src.spells.rules import apply_entity_rule
from src.rules.effect_registry import EffectRegistry


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


class TestWeaponAttack:
    """AttackResolver resolves a weapon attack on the block engine."""

    def _resolve(self, *, bonus, ac, damage, d20):
        bus = EventBus()
        dp = DamageProcessor(bus)
        attacker, defender = _entity("A"), _entity("D", ac=ac)
        ar = AttackResolver(bus, dp)
        with patch("src.spells.blocks.rolls.roll_d20", return_value=d20), \
             patch("src.spells.blocks.damage.roll_formula", return_value=4):
            hit, dmg, _log, _detail = ar.resolve(attacker, defender, _weapon(bonus, damage))
        return hit, dmg, defender

    def test_hit(self):
        hit, dmg, defender = self._resolve(
            bonus=10, ac=5, damage=[(DamageType.SLASHING, "1d8")], d20=10)
        assert hit and dmg == 4 and defender.hp == 196

    def test_miss(self):
        hit, dmg, defender = self._resolve(
            bonus=0, ac=40, damage=[(DamageType.SLASHING, "1d8")], d20=2)
        assert not hit and dmg == 0 and defender.hp == 200

    def test_multi_type_damage(self):
        hit, dmg, defender = self._resolve(
            bonus=10, ac=5,
            damage=[(DamageType.SLASHING, "1d8"), (DamageType.FIRE, "1d6")], d20=10)
        assert hit and dmg == 8 and defender.hp == 192  # 4 slashing + 4 fire


class TestAttackRouting:
    def test_colossus_attacker_lands_bonus_die_on_blocks(self):
        """A Colossus attacker resolves on the block engine (its rider is an
        ATTACK_HIT block trigger) and still lands the bonus die on a wounded target."""
        bus = EventBus()
        dp = DamageProcessor(bus)
        reg = EffectRegistry()
        reg.scan_directory("rules/entity_effects")
        ranger = _entity("Ranger", hp=40)
        target = _entity("Target", hp=40)
        apply_entity_rule(
            ranger, RuleLoader.load("rules/entity_effects/colossus_slayer.json"),
            event_bus=bus, damage_processor=dp)
        # Installed on the block engine, owned by a scope keyed to the rule name.
        assert [s.source for s in ranger.lifetimes] == ["colossus_slayer"]

        target.take_damage(Damage(DamageType.SLASHING, 5))  # wound so Colossus fires
        hp_before = target.hp
        ar = AttackResolver(bus, dp, condition_rules=reg)
        with patch("src.spells.blocks.rolls.roll_d20", return_value=15), \
             patch("src.spells.blocks.damage.roll_formula", return_value=3):
            hit, damage, _log, _detail = ar.resolve(ranger, target, _weapon(20, [(DamageType.SLASHING, "1d8")]))
        assert hit
        assert hp_before - target.hp == 6  # weapon 1d8 (3) + Colossus 1d8 (3)
