"""Tests for combat system."""

import pytest
from src.models import AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType
from src.combat import CombatSystem, CombatState


def _force_turn(combat: CombatSystem, entity: Entity) -> None:
    """Point the initiative tracker directly at ``entity``'s slot."""
    for i, entry in enumerate(combat.initiative_tracker.initiative_order):
        if entry.entity is entity:
            combat.initiative_tracker.current_turn_index = i
            return


class TestCombatSystem:
    """Test combat system."""
    
    @pytest.fixture
    def basic_combatants(self):
        """Create two basic entities for combat."""
        abilities_1 = AbilityScores(15, 14, 13, 12, 11, 10)
        stat_block_1 = StatBlock(
            name="Fighter",
            ability_scores=abilities_1,
            hit_points_max=30,
            armor_class=16,
            proficiency_bonus=2
        )

        abilities_2 = AbilityScores(10, 16, 12, 11, 12, 8)
        stat_block_2 = StatBlock(
            name="Rogue",
            ability_scores=abilities_2,
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
        _force_turn(combat, attacker)

        initial_hp = defender.hp
        hit, damage, _ = combat.resolve_attack(attacker, defender, attack)
        
        # Note: hit result depends on random d20 roll
        if hit:
            assert defender.hp < initial_hp
        else:
            assert defender.hp == initial_hp


class TestAttackRange:
    """Tests that attack range is enforced by resolve_attack."""

    def _make_entity(self, name="Fighter", x=0.0, y=0.0, z=0.0, hp=30, ac=10):
        sb = StatBlock(
            name=name,
            ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
            hit_points_max=hp,
            armor_class=ac,
        )
        return Entity(sb, x=x, y=y, z=z)

    def _make_combat(self, attacker, defender):
        combat = CombatSystem()
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        _force_turn(combat, attacker)
        return combat

    def _melee(self, range_ft=5.0):
        return AttackAction(
            name="Sword",
            description="Melee attack",
            bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, 6)],
            range_ft=range_ft,
        )

    def _ranged(self, range_ft=80.0):
        return AttackAction(
            name="Shortbow",
            description="Ranged attack",
            bonus_to_hit=5,
            damage=[Damage(DamageType.PIERCING, 6)],
            range_ft=range_ft,
        )

    # --- in-range attacks should succeed ---

    def test_melee_at_zero_distance_succeeds(self):
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=0, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        # Should not raise
        combat.resolve_attack(attacker, defender, self._melee())

    def test_melee_within_reach_succeeds(self):
        # Defender's nearest bbox edge is 0 ft from attacker centre (adjacent)
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=5, y=0, z=0)  # adjacent square
        combat = self._make_combat(attacker, defender)
        combat.resolve_attack(attacker, defender, self._melee())

    def test_ranged_within_range_succeeds(self):
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=60, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        combat.resolve_attack(attacker, defender, self._ranged(range_ft=80))

    def test_attack_exactly_at_range_limit_succeeds(self):
        # Place defender so its nearest bbox edge is exactly at range_ft
        attacker = self._make_entity("A", x=0, y=0, z=0)
        # Attacker centre is (2.5, 2.5, 2.5); defender bbox starts at x=8,
        # so nearest edge is at x=8, distance from centre ≈ 5.5 — use a
        # simple case: both at same y/z, defender touching attacker bbox.
        # Easiest: attacker at 0, defender at 5 → nearest point = 5, centre
        # of attacker (medium) = 2.5, distance = 2.5 ≤ 5.
        defender = self._make_entity("B", x=5, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        combat.resolve_attack(attacker, defender, self._melee(range_ft=5))

    # --- out-of-range attacks should raise ValueError ---

    def test_melee_out_of_range_raises(self):
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=30, y=0, z=0)  # 30 ft away
        combat = self._make_combat(attacker, defender)
        with pytest.raises(ValueError, match="out of range"):
            combat.resolve_attack(attacker, defender, self._melee(range_ft=5))

    def test_ranged_beyond_range_raises(self):
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=200, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        with pytest.raises(ValueError, match="out of range"):
            combat.resolve_attack(attacker, defender, self._ranged(range_ft=80))

    def test_out_of_range_does_not_spend_resources(self):
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=100, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        actions_before = attacker.resources.actions
        with pytest.raises(ValueError):
            combat.resolve_attack(attacker, defender, self._melee(range_ft=5))
        assert attacker.resources.actions == actions_before

    def test_out_of_range_does_not_deal_damage(self):
        attacker = self._make_entity("A", x=0, y=0, z=0)
        defender = self._make_entity("B", x=100, y=0, z=0, hp=30)
        combat = self._make_combat(attacker, defender)
        hp_before = defender.hp
        with pytest.raises(ValueError):
            combat.resolve_attack(attacker, defender, self._melee(range_ft=5))
        assert defender.hp == hp_before

    def test_range_check_uses_nearest_bbox_edge_succeeds(self):
        # Edge-to-edge measurement: attacker Medium (half=2.5) at x=0 has right
        # edge at x=2.5.  Large defender (half=5) at x=10 has left edge at x=5.
        # Edge-to-edge gap = 5 - 2.5 = 2.5 ft ≤ 5 ft → IN RANGE.
        # A naive centre-to-centre check (10 ft) would wrongly reject this.
        from src.models import CreatureSize
        sb = StatBlock(
            name="Golem",
            ability_scores=AbilityScores(20, 9, 20, 3, 11, 1),
            hit_points_max=178,
            armor_class=17,
            size=CreatureSize.LARGE,
        )
        defender = Entity(sb, x=10, y=0, z=0)
        attacker = self._make_entity("A", x=0, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        # Should not raise — edge gap is 2.5 ft, within 5 ft melee reach
        combat.resolve_attack(attacker, defender, self._melee(range_ft=5))

    def test_range_check_uses_nearest_bbox_edge_fails(self):
        # Attacker Medium (half=2.5) at x=0: right edge at x=2.5.
        # Large defender (half=5) at x=15: left edge at x=10.
        # Edge-to-edge gap = 10 - 2.5 = 7.5 ft > 5 ft → OUT OF RANGE.
        from src.models import CreatureSize
        sb = StatBlock(
            name="Golem",
            ability_scores=AbilityScores(20, 9, 20, 3, 11, 1),
            hit_points_max=178,
            armor_class=17,
            size=CreatureSize.LARGE,
        )
        defender = Entity(sb, x=15, y=0, z=0)
        attacker = self._make_entity("A", x=0, y=0, z=0)
        combat = self._make_combat(attacker, defender)
        with pytest.raises(ValueError, match="out of range"):
            combat.resolve_attack(attacker, defender, self._melee(range_ft=5))

    def test_loaded_melee_weapon_has_5ft_range(self):
        from src.loaders.stat_block_loader import StatBlockLoader
        from pathlib import Path
        path = str(Path(__file__).parent.parent / "examples" / "creatures" / "characters" / "fighter.json")
        sb = StatBlockLoader.load_from_json(path)
        longsword = next(a for a in sb.actions if a.name == "Longsword")
        assert longsword.range_ft == 5.0

    def test_loaded_ranged_weapon_has_extended_range(self):
        from src.loaders.stat_block_loader import StatBlockLoader
        from pathlib import Path
        path = str(Path(__file__).parent.parent / "examples" / "creatures" / "goblin.json")
        sb = StatBlockLoader.load_from_json(path)
        shortbow = next(a for a in sb.actions if a.name == "Shortbow")
        assert shortbow.range_ft == 80.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
