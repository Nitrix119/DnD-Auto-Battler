"""Tests for critical hit (natural 20) and critical miss (natural 1) rules.

Natural 1  → always miss, regardless of attack bonus vs AC.
Natural 20 → always hit, regardless of AC vs attack total.
            + deal double the base damage *dice* (modifiers are added once).

Both weapon attacks (AttackResolver) and spell attacks (the block evaluator)
resolve on the block engine; the nat-1/nat-20 crit rules ride the shared bus.
"""

import os
from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType
from src.models.action import SpellAction
from src.models.spell_properties import TargetingType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver
from src.rules import RuleEngine

GLOBAL_RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules", "global")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_entity(name: str, ac: int = 10, hp: int = 100) -> Entity:
    sb = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
    )
    return Entity(sb)


def _make_resolver():
    bus = EventBus()
    dp = DamageProcessor(bus)
    engine = RuleEngine(bus)
    engine.load_from_directory(GLOBAL_RULES_DIR)
    return AttackResolver(bus, dp), dp


def _resolve_spell(caster, defender, spell):
    """Resolve a spell attack on the block engine, with the crit rules on the bus."""
    from src.spells.evaluator import resolve as resolve_blocks
    from src.spells.adapter import to_program

    bus = EventBus()
    dp = DamageProcessor(bus)
    engine = RuleEngine(bus)
    engine.load_from_directory(GLOBAL_RULES_DIR)  # subscribes nat-20/nat-1 on the bus
    program = to_program(spell.pipeline_effects, TargetingType.SINGLE_TARGET)
    return resolve_blocks(caster, defender, spell, program,
                          event_bus=bus, damage_processor=dp)


def _sword(bonus_to_hit: int = 0, die_sides: int = 8) -> AttackAction:
    """A simple 1dN weapon attack with the given to-hit bonus."""
    return AttackAction(
        name="Sword",
        description="A basic sword swing",
        bonus_to_hit=bonus_to_hit,
        damage=[Damage(DamageType.SLASHING, 0, formula=f"1d{die_sides}")],
    )


def _attack_spell(die_sides: int = 8) -> SpellAction:
    """A minimal attack-roll spell that deals 1dN force damage on hit."""
    return SpellAction(
        name="Force Bolt",
        description="A test spell attack",
        pipeline_effects=[
            {
                "type": "attack_roll",
                "attack_bonus": 0,
            },
            {
                "type": "damage",
                "formula": f"1d{die_sides}",
                "damage_type": "FORCE",
                "requires_hit": True,
            },
        ],
    )


# ---------------------------------------------------------------------------
# Natural 1 – weapon attacks
# ---------------------------------------------------------------------------

class TestNatural1WeaponAttack:
    """A natural 1 on a weapon attack roll must always be a miss."""

    def test_nat_1_misses_even_with_high_bonus(self):
        """bonus_to_hit=+20 against AC 5: total 21 ≥ 5 normally, but nat 1 → miss."""
        attacker = _make_entity("Attacker", ac=10)
        defender = _make_entity("Defender", ac=5)  # trivially low AC
        resolver, _ = _make_resolver()
        sword = _sword(bonus_to_hit=20)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=1):
            hit, damage, _log, _detail = resolver.resolve(attacker, defender, sword)

        assert not hit, "Natural 1 must always be a miss regardless of attack bonus"

    def test_nat_1_deals_no_damage(self):
        attacker = _make_entity("Attacker")
        defender = _make_entity("Defender", ac=5)
        resolver, _ = _make_resolver()
        sword = _sword(bonus_to_hit=20)
        initial_hp = defender.hp

        with patch("src.spells.blocks.rolls.roll_d20", return_value=1):
            resolver.resolve(attacker, defender, sword)

        assert defender.hp == initial_hp, "Natural 1 miss must deal no damage"


# ---------------------------------------------------------------------------
# Natural 20 – weapon attacks
# ---------------------------------------------------------------------------

class TestNatural20WeaponAttack:
    """A natural 20 on a weapon attack roll must always hit and double damage dice."""

    def test_nat_20_hits_even_against_impossible_ac(self):
        """bonus_to_hit=0 against AC 30: total 20 < 30 normally, but nat 20 → hit."""
        attacker = _make_entity("Attacker")
        defender = _make_entity("Defender", ac=30, hp=200)
        resolver, _ = _make_resolver()
        sword = _sword(bonus_to_hit=0)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            hit, damage, _log, _detail = resolver.resolve(attacker, defender, sword)

        assert hit, "Natural 20 must always be a hit regardless of AC"

    def test_nat_20_deals_damage(self):
        attacker = _make_entity("Attacker")
        defender = _make_entity("Defender", ac=30, hp=200)
        resolver, _ = _make_resolver()
        sword = _sword(bonus_to_hit=0)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            hit, damage, _log, _detail = resolver.resolve(attacker, defender, sword)

        assert damage > 0, "Natural 20 hit must deal damage"

    def test_nat_20_doubles_damage_dice(self):
        """Crit should roll 2d8 instead of 1d8 (dice doubled, no flat modifiers here).

        We pin roll_dice to always return 4 per die.
        Normal hit  → 1d8 → roll_dice(1, 8) → 4 total damage.
        Critical hit → 2d8 → roll_dice(2, 8) → 8 total damage.
        """
        attacker = _make_entity("Attacker")
        defender = _make_entity("Defender", ac=1, hp=200)  # AC 1 so any roll hits
        resolver, _ = _make_resolver()
        sword = _sword(bonus_to_hit=0, die_sides=8)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.utils.dice.roll_dice", side_effect=lambda n, _s: n * 4):
            _hit, damage, _log, _detail = resolver.resolve(attacker, defender, sword)

        assert damage == 8, (
            f"Critical hit with 1d8 (pinned to 4/die) should deal 8 (2d8), got {damage}"
        )


# ---------------------------------------------------------------------------
# Natural 1 – spell attack roll
# ---------------------------------------------------------------------------

class TestNatural1SpellAttack:
    """A natural 1 on a spell attack roll must always be a miss."""

    def test_nat_1_spell_misses_even_with_high_bonus(self):
        """Spell with +20 bonus vs AC 5: total 21 normally hits, but nat 1 → miss."""
        caster = _make_entity("Caster")
        defender = _make_entity("Defender", ac=5)
        spell = _attack_spell()
        spell.pipeline_effects[0]["attack_bonus"] = 20

        with patch("src.spells.blocks.rolls.roll_d20", return_value=1):
            result = _resolve_spell(caster, defender, spell)

        assert not result.hit, "Natural 1 spell attack must always miss"

    def test_nat_1_spell_deals_no_damage(self):
        caster = _make_entity("Caster")
        defender = _make_entity("Defender", ac=5)
        spell = _attack_spell()
        spell.pipeline_effects[0]["attack_bonus"] = 20

        with patch("src.spells.blocks.rolls.roll_d20", return_value=1):
            result = _resolve_spell(caster, defender, spell)

        assert result.damage_dealt == 0, "Natural 1 spell miss must deal no damage"


# ---------------------------------------------------------------------------
# Natural 20 – spell attack roll
# ---------------------------------------------------------------------------

class TestNatural20SpellAttack:
    """A natural 20 on a spell attack roll must always hit and double damage dice."""

    def test_nat_20_spell_hits_even_against_impossible_ac(self):
        """Spell +0 vs AC 30: total 20 < 30 normally, but nat 20 → hit."""
        caster = _make_entity("Caster")
        defender = _make_entity("Defender", ac=30, hp=200)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            result = _resolve_spell(caster, defender, _attack_spell())

        assert result.hit, "Natural 20 spell attack must always hit regardless of AC"

    def test_nat_20_spell_deals_damage(self):
        caster = _make_entity("Caster")
        defender = _make_entity("Defender", ac=30, hp=200)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            result = _resolve_spell(caster, defender, _attack_spell())

        assert result.damage_dealt > 0, "Natural 20 spell hit must deal damage"

    def test_nat_20_spell_doubles_damage_dice(self):
        """Crit spell should roll 2d8 instead of 1d8.

        Pins roll_dice to return 4 per die.
        Normal hit  → roll_dice(1, 8) → 4.
        Critical hit → roll_dice(2, 8) → 8.
        """
        caster = _make_entity("Caster")
        defender = _make_entity("Defender", ac=1, hp=200)

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.utils.dice.roll_dice", side_effect=lambda n, _s: n * 4):
            result = _resolve_spell(caster, defender, _attack_spell(die_sides=8))

        assert result.damage_dealt == 8, (
            f"Critical spell hit with 1d8 (pinned to 4/die) should deal 8 (2d8), "
            f"got {result.damage_dealt}"
        )
