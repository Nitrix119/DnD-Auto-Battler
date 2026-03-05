"""Example: Loading a stat block from JSON and running a simple combat."""

from src.models import AbilityScores, StatBlock, AttackAction, Damage, DamageType, Entity, ActionType
from src.combat import CombatSystem, CombatState
from src.loaders import StatBlockLoader

# Create a fighter manually
fighter_abilities = AbilityScores(
    strength=15, dexterity=14, constitution=13,
    intelligence=10, wisdom=12, charisma=11
)

fighter_block = StatBlock(
    name="Fighter",
    ability_scores=fighter_abilities,
    hit_points=30,
    hit_points_max=30,
    armor_class=16,
    proficiency_bonus=2
)

# Add longsword attack
longsword = AttackAction(
    name="Longsword",
    description="A melee weapon attack with a longsword",
    bonus_to_hit=5,
    damage=[Damage(DamageType.SLASHING, formula="1d8")]
)
fighter_block.add_action(longsword)

fighter = Entity(fighter_block, is_player_controlled=True)

# Load goblin from JSON
try:
    goblin_block = StatBlockLoader.load_from_json("examples/creatures/goblin.json")
    goblin = Entity(goblin_block)
    
    # Set up combat
    combat = CombatSystem()
    combat.add_combatant(fighter)
    combat.add_combatant(goblin)
    
    combat.start_combat()
    print("=== Combat Started ===")
    print(f"Initiative order: {[e.name for e in combat.initiative_tracker.get_turn_order()]}")
    print()
    
    # Run a few turns for demonstration
    turn_count = 0
    while combat.state == CombatState.ACTIVE and turn_count < 10:
        current = combat.get_current_entity()
        
        # Simple AI: first entity attacks the second
        enemies = combat.get_enemies(current)
        if enemies:
            enemy = enemies[0]
            
            # Use the first attack available
            if current.stat_block.actions:
                action = current.stat_block.actions[0]
                if isinstance(action, AttackAction):
                    hit, damage = combat.resolve_attack(current, enemy, action)
                    print(f"{current.name} HP: {current.hp}/{current.max_hp}")
                    print(f"{enemy.name} HP: {enemy.hp}/{enemy.max_hp}")
                    print()
        
        combat.end_turn()
        turn_count += 1
    
    # Print combat summary
    print("=== Combat Summary ===")
    print(f"Final state: {combat.state.value}")
    print(f"Rounds: {combat.round}")
    print()
    
    print("=== Combat Log ===")
    for log_entry in combat.get_combat_log():
        print(log_entry)

except FileNotFoundError:
    print("Could not find goblin.json. Make sure to run from the project root.")
