"""Tests for combat system."""

import pytest
from src.models import AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType
from src.combat import CombatSystem, CombatState


class TestCombatSystem:
    """Test combat system."""
    
    @pytest.fixture
    def basic_combatants(self):
        """Create two basic entities for combat."""
        abilities_1 = AbilityScores(15, 14, 13, 12, 11, 10)
        stat_block_1 = StatBlock(
            name="Fighter",
            ability_scores=abilities_1,
            hit_points=30,
            hit_points_max=30,
            armor_class=16,
            proficiency_bonus=2
        )
        
        abilities_2 = AbilityScores(10, 16, 12, 11, 12, 8)
        stat_block_2 = StatBlock(
            name="Rogue",
            ability_scores=abilities_2,
            hit_points=20,
            hit_points_max=20,
            armor_class=15,
            proficiency_bonus=2
        )
        
        return Entity(stat_block_1, is_player_controlled=True), Entity(stat_block_2)
    
    def test_combat_setup(self, basic_combatants):
        """Test setting up combat."""
        combat = CombatSystem()
        assert combat.state == CombatState.SETUP
        
        for entity in basic_combatants:
            combat.add_combatant(entity)
        
        assert len(combat.combatants) == 2
    
    def test_combat_start(self, basic_combatants):
        """Test starting combat."""
        combat = CombatSystem()
        for entity in basic_combatants:
            combat.add_combatant(entity)
        
        combat.start_combat()
        assert combat.state == CombatState.ACTIVE
        assert combat.round == 1
    
    def test_cannot_add_after_start(self, basic_combatants):
        """Test that entities can't be added after combat starts."""
        combat = CombatSystem()
        for entity in basic_combatants:
            combat.add_combatant(entity)
        
        combat.start_combat()
        
        new_entity = Entity(basic_combatants[0].stat_block)
        with pytest.raises(RuntimeError):
            combat.add_combatant(new_entity)
    
    def test_attack_resolution(self, basic_combatants):
        """Test attack resolution."""
        attacker, defender = basic_combatants
        
        attack = AttackAction(
            name="Sword Attack",
            description="A basic melee attack",
            bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, 8)]
        )
        
        combat = CombatSystem()
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        
        initial_hp = defender.hp
        hit, damage = combat.resolve_attack(attacker, defender, attack)
        
        # Note: hit result depends on random d20 roll
        if hit:
            assert defender.hp < initial_hp
        else:
            assert defender.hp == initial_hp


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
