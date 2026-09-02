"""Tests for the Armor of Agathys spell and entity effect.

Verifies that casting Armor of Agathys grants temporary HP, deals cold
retaliation damage when the warded entity is hit by an attack while temp
HP remain, and that the effect self-terminates when temp HP are depleted.
"""

from unittest.mock import patch

import pytest

from src.models import AbilityScores, StatBlock, Entity, DamageType
from src.models.damage import Damage
from src.combat.event_bus import EventBus
from src.combat.events import EventType
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver
from src.combat.spell_resolver import SpellResolver
from src.loaders.stat_block_loader import StatBlockLoader
from src.rules.rule_engine import RuleEngine
from src.rules.effect_registry import EffectRegistry
from pathlib import Path

SPELLS_DIR = Path(__file__).parent.parent.parent.parent / "examples" / "spells"


# -- Helpers ------------------------------------------------------------------

def _make_entity(name="Fighter", hp=30, ac=15, speed=30, actions=None):
    abilities = AbilityScores(14, 14, 14, 10, 10, 10)
    sb = StatBlock(
        name=name, ability_scores=abilities,
        hit_points_max=hp, armor_class=ac,
    )
    if actions:
        sb.actions = actions
    sb.resource_defaults["speed"] = speed
    entity = Entity(sb)
    entity.refill_resources()
    return entity


def _make_attacker(name="Goblin"):
    """Create an entity with a melee attack action."""
    from src.models.action import AttackAction, ActionType
    scimitar = AttackAction(
        name="Scimitar", description="Melee weapon attack",
        bonus_to_hit=4,
        damage=[Damage(DamageType.SLASHING, formula="1d6+2")],
    )
    abilities = AbilityScores(10, 14, 10, 10, 10, 10)
    sb = StatBlock(
        name=name, ability_scores=abilities,
        hit_points_max=20, armor_class=13,
        actions=[scimitar],
    )
    return Entity(sb)


def _setup(*entities):
    """Wire up EventBus, RuleEngine, DamageProcessor, and resolvers."""
    bus = EventBus()
    damage_proc = DamageProcessor(bus)
    registry = EffectRegistry()
    registry.scan_directory("rules/entity_effects")
    engine = RuleEngine(
        bus,
        damage_processor=damage_proc,
        effect_registry=registry,
    )
    attack_res = AttackResolver(bus, damage_proc)
    spell_res = SpellResolver(bus, damage_proc, rule_engine=engine)
    return bus, engine, damage_proc, attack_res, spell_res


def _load_spell():
    return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "armor_of_agathys.json"))


# -- Loading tests ------------------------------------------------------------

class TestArmorOfAgathysLoading:

    def test_loads_native_program(self):
        """Armor of Agathys is a native program: a lifetime granting temp HP with a
        retaliation trigger (its effect is inline, not a separate entity-effect file)."""
        spell = _load_spell()
        assert spell.program
        life = spell.program[0]
        assert life["block"] == "lifetime"
        inner = [b["block"] for b in life["then"]]
        assert inner[0] == "grant_temporary_hp"
        assert "trigger" in inner  # the on-hit cold retaliation rider

    def test_no_save_no_attack_roll(self):
        spell = _load_spell()

        def walk(blocks):
            for b in blocks:
                yield b.get("block", b.get("type"))
                yield from walk(b.get("then", []))

        types = set(walk(spell.program))
        assert "saving_throw" not in types
        assert "attack_roll" not in types

    def test_spell_level_1_no_concentration(self):
        spell = _load_spell()
        assert spell.spell_level == 1
        assert spell.duration.concentration is False


# -- Temp HP grant tests ------------------------------------------------------

class TestArmorOfAgathysTempHP:

    def test_grants_temp_hp_on_cast(self):
        """Casting Armor of Agathys should grant 5 temp HP to the caster."""
        caster = _make_entity()
        bus, engine, dp, ar, spell_res = _setup(caster)

        spell_res.resolve(caster, [caster], _load_spell())

        assert caster.temporary_hp == 5

    def test_does_not_lower_existing_higher_temp_hp(self):
        """Non-stacking: if the caster already has more temp HP, keep the higher."""
        caster = _make_entity()
        caster.add_temporary_hp(10)
        bus, engine, dp, ar, spell_res = _setup(caster)

        spell_res.resolve(caster, [caster], _load_spell())

        assert caster.temporary_hp == 10

    def test_replaces_lower_temp_hp(self):
        """If the caster has fewer temp HP, the spell's grant wins."""
        caster = _make_entity()
        caster.add_temporary_hp(2)
        bus, engine, dp, ar, spell_res = _setup(caster)

        spell_res.resolve(caster, [caster], _load_spell())

        assert caster.temporary_hp == 5


# -- Retaliation tests --------------------------------------------------------

class TestArmorOfAgathysRetaliation:

    def test_attacker_takes_cold_damage_on_hit(self):
        """A creature that hits the warded entity should take 5 cold damage."""
        caster = _make_entity()
        attacker = _make_attacker()
        bus, engine, dp, ar, spell_res = _setup(caster, attacker)

        spell_res.resolve(caster, [caster], _load_spell())

        attacker_hp_before = attacker.hp
        action = attacker.stat_block.actions[0]
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            ar.resolve(attacker, caster, action)

        assert attacker.hp == attacker_hp_before - 5

    def test_no_retaliation_when_temp_hp_already_gone(self):
        """No cold damage if the caster's temp HP were cleared before the hit."""
        caster = _make_entity()
        attacker = _make_attacker()
        bus, engine, dp, ar, spell_res = _setup(caster, attacker)

        spell_res.resolve(caster, [caster], _load_spell())
        caster.clear_temporary_hp()

        attacker_hp_before = attacker.hp
        action = attacker.stat_block.actions[0]
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            ar.resolve(attacker, caster, action)

        assert attacker.hp == attacker_hp_before

    def test_no_retaliation_on_miss(self):
        """No retaliation when the attack misses."""
        caster = _make_entity()
        attacker = _make_attacker()
        bus, engine, dp, ar, spell_res = _setup(caster, attacker)

        spell_res.resolve(caster, [caster], _load_spell())

        attacker_hp_before = attacker.hp
        action = attacker.stat_block.actions[0]
        with patch("src.spells.blocks.rolls.roll_d20", return_value=1):
            ar.resolve(attacker, caster, action)

        assert attacker.hp == attacker_hp_before

    def test_retaliation_fires_before_damage_applied(self):
        """Retaliation fires on ATTACK_HIT (before damage), so temp HP are still up."""
        caster = _make_entity()
        attacker = _make_attacker()
        bus, engine, dp, ar, spell_res = _setup(caster, attacker)

        spell_res.resolve(caster, [caster], _load_spell())

        # Record the sequence: retaliation should happen while temp HP > 0
        retaliation_fired = []
        original_take_damage = attacker.take_damage

        def spy_take_damage(damage):
            if damage.damage_type == DamageType.COLD:
                retaliation_fired.append(caster.temporary_hp)
            return original_take_damage(damage)

        attacker.take_damage = spy_take_damage

        action = attacker.stat_block.actions[0]
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            ar.resolve(attacker, caster, action)

        # The cold retaliation damage was dealt while caster still had temp HP
        assert len(retaliation_fired) == 1
        assert retaliation_fired[0] == 5  # temp HP were still 5 at retaliation time


# -- Self-termination tests ---------------------------------------------------

class TestArmorOfAgathysSelfTermination:

    def test_effect_removed_when_temp_hp_depleted_by_attack(self):
        """The effect should auto-remove when temp HP reach 0 from attack damage."""
        caster = _make_entity()
        attacker = _make_attacker()
        bus, engine, dp, ar, spell_res = _setup(caster, attacker)

        spell_res.resolve(caster, [caster], _load_spell())

        # Verify the effect is present: a lifetime scope on the warded entity.
        assert len(caster.lifetimes) == 1 and not caster.lifetimes[0].disposed

        # Attack with enough damage to deplete temp HP.
        # Patch roll_formula at both import sites: action.roll_damage() and
        # effects.deal_damage() use their own imported copies.
        action = attacker.stat_block.actions[0]
        mock_roll = lambda f: 5 if f == "5" else 10
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.spells.blocks.damage.roll_formula", side_effect=mock_roll):
            ar.resolve(attacker, caster, action)

        assert caster.temporary_hp == 0
        # The effect self-terminated: its lifetime scope was disposed.
        assert caster.lifetimes[0].disposed

    def test_effect_removed_when_temp_hp_depleted_by_non_attack(self):
        """Non-attack damage that depletes temp HP should also remove the effect."""
        caster = _make_entity()
        bus, engine, dp, ar, spell_res = _setup(caster)

        spell_res.resolve(caster, [caster], _load_spell())

        # Direct damage through damage processor (e.g. environmental)
        dp.apply_damage(caster, [Damage(DamageType.FIRE, 10)])

        assert caster.temporary_hp == 0
        assert caster.lifetimes[0].disposed  # self-terminated

    def test_effect_persists_while_temp_hp_remain(self):
        """The effect stays if temp HP are only partially consumed."""
        caster = _make_entity()
        bus, engine, dp, ar, spell_res = _setup(caster)

        spell_res.resolve(caster, [caster], _load_spell())

        dp.apply_damage(caster, [Damage(DamageType.BLUDGEONING, 3)])

        assert caster.temporary_hp == 2
        assert len(caster.lifetimes) == 1 and not caster.lifetimes[0].disposed

    def test_full_combat_flow(self):
        """End-to-end: goblin hits warded caster, takes cold damage, temp HP deplete."""
        caster = _make_entity(hp=50)
        attacker = _make_attacker()
        bus, engine, dp, ar, spell_res = _setup(caster, attacker)

        spell_res.resolve(caster, [caster], _load_spell())
        assert caster.temporary_hp == 5

        attacker_hp_before = attacker.hp
        action = attacker.stat_block.actions[0]

        # Force hit, scimitar deals 8 damage (> 5 temp HP)
        mock_roll = lambda f: 5 if f == "5" else 8
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.spells.blocks.damage.roll_formula", side_effect=mock_roll):
            ar.resolve(attacker, caster, action)

        # Attacker took 5 cold retaliation
        assert attacker.hp == attacker_hp_before - 5

        # Caster's temp HP gone, real HP took overflow (8 - 5 = 3)
        assert caster.temporary_hp == 0
        assert caster.hp == 50 - 3

        # Effect auto-removed: its lifetime scope has been disposed.
        assert all(s.disposed for s in caster.lifetimes)

        # Second attack: no retaliation since effect is gone
        attacker_hp_now = attacker.hp
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            ar.resolve(attacker, caster, action)
        assert attacker.hp == attacker_hp_now
