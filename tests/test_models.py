"""Tests for models."""

import pytest
from src.models import (
    AbilityScores, StatBlock, AttackAction, Damage, DamageType,
    Entity, Skill, ProficiencyLevel, Condition, ConditionType
)


class TestAbilityScores:
    """Test ability score calculations."""
    
    def test_ability_modifiers(self):
        """Test modifier calculation."""
        abilities = AbilityScores(15, 14, 13, 12, 11, 10)
        assert abilities.get_modifier("strength") == 2
        assert abilities.get_modifier("dexterity") == 2
        assert abilities.get_modifier("constitution") == 1
        assert abilities.get_modifier("intelligence") == 1
        assert abilities.get_modifier("wisdom") == 0
        assert abilities.get_modifier("charisma") == 0
    
    def test_invalid_ability_score(self):
        """Test validation of ability scores."""
        with pytest.raises(ValueError):
            AbilityScores(0, 10, 10, 10, 10, 10)
        with pytest.raises(ValueError):
            AbilityScores(31, 10, 10, 10, 10, 10)

    def test_high_ability_score_allowed(self):
        """Scores above 20 (up to 30) are valid for monsters and magic items."""
        abilities = AbilityScores(30, 10, 10, 10, 10, 10)
        assert abilities.get_modifier("strength") == 10


class TestStatBlock:
    """Test stat block functionality."""
    
    @pytest.fixture
    def basic_stat_block(self):
        """Create a basic stat block for testing."""
        abilities = AbilityScores(15, 14, 13, 12, 11, 10)
        return StatBlock(
            name="Test Fighter",
            ability_scores=abilities,
            hit_points_max=50,
            armor_class=16,
        )

    def test_skill_bonus_no_proficiency(self, basic_stat_block):
        """Test skill bonus without proficiency (just the ability modifier)."""
        bonus = basic_stat_block.get_skill_bonus("athletics")
        assert bonus == 2

    def test_skill_bonus_proficiency(self):
        """Test skill bonus with proficiency adds the proficiency bonus once."""
        abilities = AbilityScores(15, 14, 13, 12, 11, 10)
        stat_block = StatBlock(
            name="Test Fighter",
            ability_scores=abilities,
            hit_points_max=50,
            armor_class=16,
            skills={"athletics": Skill("Athletics", "strength", ProficiencyLevel.PROFICIENT)},
        )
        bonus = stat_block.get_skill_bonus("athletics")
        assert bonus == 4

    def test_skill_bonus_expertise(self):
        """Test skill bonus with expertise doubles the proficiency bonus."""
        abilities = AbilityScores(15, 14, 13, 12, 11, 10)
        stat_block = StatBlock(
            name="Test Rogue",
            ability_scores=abilities,
            hit_points_max=50,
            armor_class=16,
            skills={"athletics": Skill("Athletics", "strength", ProficiencyLevel.EXPERT)},
        )
        bonus = stat_block.get_skill_bonus("athletics")
        assert bonus == 6

    def test_damage_via_entity(self, basic_stat_block):
        """Test taking damage (HP now lives on Entity)."""
        entity = Entity(basic_stat_block)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 10))
        assert entity.hp == 40

    def test_healing_via_entity(self, basic_stat_block):
        """Test healing (HP now lives on Entity)."""
        entity = Entity(basic_stat_block)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 20))
        entity.heal(10)
        assert entity.hp == 40

    def test_death_via_entity(self, basic_stat_block):
        """Test death conditions (HP now lives on Entity)."""
        entity = Entity(basic_stat_block)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 50))
        assert not entity.is_alive()


class TestEntity:
    """Test entity functionality."""
    
    @pytest.fixture
    def basic_entity(self):
        """Create a basic entity for testing."""
        abilities = AbilityScores(15, 14, 13, 12, 11, 10)
        stat_block = StatBlock(
            name="Goblin",
            ability_scores=abilities,
            hit_points_max=7,
            armor_class=15,
        )
        return Entity(stat_block)
    
    def test_entity_identity(self, basic_entity):
        """Test entity uniqueness."""
        entity2 = Entity(basic_entity.stat_block)
        assert basic_entity != entity2
        assert basic_entity.entity_id != entity2.entity_id
    
    def test_entity_damage(self, basic_entity):
        """Test entity damage."""
        basic_entity.take_damage(Damage(DamageType.BLUDGEONING, 3))
        assert basic_entity.hp == 4
    
    def test_entity_conditions(self, basic_entity):
        """Test adding conditions."""
        condition = Condition(ConditionType.POISONED)
        basic_entity.add_condition(condition)
        assert len(basic_entity.get_active_conditions()) == 1


class TestTemporaryHP:
    """Test temporary hit point mechanics (D&D 5e rules)."""

    @pytest.fixture
    def entity(self):
        abilities = AbilityScores(10, 10, 10, 10, 10, 10)
        stat_block = StatBlock(
            name="Fighter",
            ability_scores=abilities,
            hit_points_max=30,
            armor_class=15,
        )
        return Entity(stat_block)

    def test_default_temp_hp_is_zero(self, entity):
        assert entity.temporary_hp == 0

    def test_add_temporary_hp(self, entity):
        entity.add_temporary_hp(10)
        assert entity.temporary_hp == 10

    def test_temp_hp_dont_stack_keeps_higher(self, entity):
        """Temp HP don't stack — keep the higher value."""
        entity.add_temporary_hp(10)
        entity.add_temporary_hp(5)
        assert entity.temporary_hp == 10

    def test_temp_hp_replaced_by_higher(self, entity):
        entity.add_temporary_hp(5)
        entity.add_temporary_hp(10)
        assert entity.temporary_hp == 10

    def test_damage_absorbed_by_temp_hp(self, entity):
        entity.add_temporary_hp(10)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 6))
        assert entity.temporary_hp == 4
        assert entity.hp == 30  # real HP untouched

    def test_damage_overflows_to_real_hp(self, entity):
        entity.add_temporary_hp(5)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 12))
        assert entity.temporary_hp == 0
        assert entity.hp == 23  # 30 - (12-5)

    def test_damage_exactly_depletes_temp_hp(self, entity):
        entity.add_temporary_hp(8)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 8))
        assert entity.temporary_hp == 0
        assert entity.hp == 30

    def test_healing_does_not_restore_temp_hp(self, entity):
        entity.add_temporary_hp(10)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 15))
        # temp HP gone, real HP at 25
        assert entity.temporary_hp == 0
        assert entity.hp == 25
        entity.heal(5)
        assert entity.hp == 30
        assert entity.temporary_hp == 0  # healing doesn't bring back temp HP

    def test_healing_does_not_add_temp_hp(self, entity):
        entity.take_damage(Damage(DamageType.BLUDGEONING, 10))
        entity.heal(5)
        assert entity.temporary_hp == 0

    def test_clear_temporary_hp(self, entity):
        entity.add_temporary_hp(15)
        entity.clear_temporary_hp()
        assert entity.temporary_hp == 0

    def test_add_zero_or_negative_temp_hp_ignored(self, entity):
        entity.add_temporary_hp(5)
        entity.add_temporary_hp(0)
        assert entity.temporary_hp == 5
        entity.add_temporary_hp(-3)
        assert entity.temporary_hp == 5

    def test_temp_hp_with_lethal_damage(self, entity):
        """Temp HP can't prevent death if overflow kills."""
        entity.add_temporary_hp(5)
        entity.take_damage(Damage(DamageType.NECROTIC, 50))
        assert entity.temporary_hp == 0
        assert entity.hp == 0
        assert not entity.is_alive()


class TestAttackAction:
    """Test attack actions."""
    
    def test_attack_creation(self):
        """Test creating an attack."""
        attack = AttackAction(
            name="Longsword",
            description="A melee attack",
            bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, 8)]
        )
        assert attack.name == "Longsword"
        assert attack.bonus_to_hit == 5
        assert len(attack.damage) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
