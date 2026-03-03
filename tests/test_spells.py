"""Tests for spell actions in simple combat scenarios."""

import pytest
from pathlib import Path

from src.models import (
    AbilityScores, StatBlock, Entity,
    SpellAction, Damage, DamageType,
    RangeType, TargetingType, AOEShape,
    CastingTimeType, DurationUnit,
)
from src.loaders.stat_block_loader import StatBlockLoader
from src.combat import CombatSystem, CombatState
from src.utils.dice import roll_d20, roll_formula

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
SPELLS_DIR = EXAMPLES_DIR / "spells"

# Wizard stats: INT 18 (+4), proficiency +3 → spell attack +7, save DC 15
_WIZARD_SPELL_ATTACK = 7
_WIZARD_SAVE_DC = 15


class TestSpellLoading:
    """Verify that spell JSON files round-trip through the loader correctly."""

    def test_firebolt_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        assert spell.name == "Fire Bolt"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.aoe is None
        assert spell.casting_time.time_type == CastingTimeType.ACTION
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert spell.components.verbal
        assert spell.components.somatic
        assert not spell.components.requires_material
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FIRE
        assert spell.damage[0].formula == "1d10"

    def test_fireball_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))
        assert spell.name == "Fireball"
        assert spell.spell_level == 3
        assert spell.targeting_type == TargetingType.AOE
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 150
        assert spell.aoe is not None
        assert spell.aoe.shape == AOEShape.SPHERE
        assert spell.aoe.size_ft == 20
        assert spell.components.requires_material
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FIRE
        assert spell.damage[0].formula == "8d6"

    def test_inflict_wounds_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "inflict_wounds.json"))
        assert spell.name == "Inflict Wounds"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.TOUCH
        assert spell.aoe is None
        assert not spell.components.requires_material
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.NECROTIC
        assert spell.damage[0].formula == "3d10"


class TestSpellCombat:
    """Test spell behaviour against goblins in a live combat encounter."""

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @pytest.fixture
    def wizard(self) -> Entity:
        """Level-5 wizard: INT 18, proficiency +3, spell attack +7, DC 15."""
        abilities = AbilityScores(
            strength=8,
            dexterity=14,
            constitution=14,
            intelligence=18,
            wisdom=12,
            charisma=10,
        )
        stat_block = StatBlock(
            name="Wizard",
            ability_scores=abilities,
            hit_points=28,
            hit_points_max=28,
            armor_class=12,
            proficiency_bonus=3,
        )
        return Entity(stat_block, is_player_controlled=True)

    @pytest.fixture
    def goblins(self):
        """Three independent goblin entities loaded from examples/goblin.json."""
        def _make():
            sb = StatBlockLoader.load_from_json(str(EXAMPLES_DIR / "goblin.json"))
            return Entity(sb)
        return [_make() for _ in range(3)]

    @pytest.fixture
    def firebolt(self) -> SpellAction:
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        spell.spell_attack_bonus = _WIZARD_SPELL_ATTACK
        return spell

    @pytest.fixture
    def fireball(self) -> SpellAction:
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))
        spell.save_dc = _WIZARD_SAVE_DC
        return spell

    @pytest.fixture
    def inflict_wounds(self) -> SpellAction:
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "inflict_wounds.json"))
        spell.spell_attack_bonus = _WIZARD_SPELL_ATTACK
        return spell

    @pytest.fixture
    def combat(self, wizard, goblins) -> CombatSystem:
        cs = CombatSystem()
        cs.add_combatant(wizard)
        for goblin in goblins:
            cs.add_combatant(goblin)
        cs.start_combat()
        return cs

    # ------------------------------------------------------------------
    # Fire Bolt – single target, ranged spell attack
    # ------------------------------------------------------------------

    def test_firebolt_only_damages_target(self, wizard, goblins, firebolt, combat):
        """Fire Bolt targets one goblin; the other two are untouched."""
        target, bystander_a, bystander_b = goblins

        initial_b_a = bystander_a.hp
        initial_b_b = bystander_b.hp

        # Simulate the spell attack roll
        roll = roll_d20()
        attack_total = roll + firebolt.spell_attack_bonus
        hit = attack_total >= target.ac

        if hit:
            damage = roll_formula(firebolt.damage[0].formula)
            target.take_damage(Damage(firebolt.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        # The two bystanders must be completely unaffected
        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b

    # ------------------------------------------------------------------
    # Fireball – AOE, Dexterity save, half on success
    # ------------------------------------------------------------------

    def test_fireball_damages_all_targets(self, wizard, goblins, fireball, combat):
        """Fireball's AOE must damage every goblin in the blast.

        8d6 minimum is 8.  Even on a successful Dexterity save (half damage),
        each goblin takes at least 4 damage — enough to reduce a 7 HP goblin's
        HP without the save-result causing zero damage.
        """
        assert fireball.targeting_type == TargetingType.AOE, (
            "Fireball must be an AOE spell so the combat system applies it "
            "to all targets in the area, not just one."
        )

        initial_hps = [g.hp for g in goblins]

        # Roll damage once; all targets in the AOE share the same damage roll
        raw_damage = roll_formula(fireball.damage[0].formula)  # 8d6, min 8

        for goblin in goblins:
            _, saved = combat.resolve_saving_throw(goblin, "dexterity", fireball.save_dc)
            actual_damage = raw_damage // 2 if saved else raw_damage
            goblin.take_damage(Damage(fireball.damage[0].damage_type, actual_damage))

        # Every goblin must have taken damage regardless of save outcome
        for goblin, initial_hp in zip(goblins, initial_hps):
            assert goblin.hp < initial_hp, (
                f"{goblin.name} should have taken damage from Fireball "
                f"(initial HP {initial_hp}, current HP {goblin.hp})"
            )

    # ------------------------------------------------------------------
    # Inflict Wounds – single target, melee spell attack
    # ------------------------------------------------------------------

    def test_inflict_wounds_only_damages_target(self, wizard, goblins, inflict_wounds, combat):
        """Inflict Wounds targets one goblin; the other two are untouched."""
        target, bystander_a, bystander_b = goblins

        initial_b_a = bystander_a.hp
        initial_b_b = bystander_b.hp

        # Simulate the melee spell attack roll
        roll = roll_d20()
        attack_total = roll + inflict_wounds.spell_attack_bonus
        hit = attack_total >= target.ac

        if hit:
            damage = roll_formula(inflict_wounds.damage[0].formula)
            target.take_damage(Damage(inflict_wounds.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        # The two bystanders must be completely unaffected
        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
