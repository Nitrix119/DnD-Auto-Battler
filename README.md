# D&D Auto-Battler

A Python library for simulating battles under the Dungeons & Dragons 5e combat system.

## Features

- **Complete Stat Blocks**: Store and manage D&D entity stat blocks with all core mechanics
- **Combat System**: Full D&D 5e combat simulator with initiative, turns, and action resolution
- **Entity Management**: Create characters and creatures with abilities, skills, and actions
- **Extensible Design**: Easy to extend with new action types, conditions, and rules

## Project Structure

```
src/
├── models/          # Data structures for entities and combat
├── combat/          # Combat simulation logic
├── loaders/         # Stat block I/O (JSON/YAML)
└── utils/           # Dice rolling and helper functions
```

## Quick Start

### Creating a Stat Block

```python
from src.models import AbilityScores, StatBlock, AttackAction, Damage, DamageType
from src.models import Entity

# Define ability scores
abilities = AbilityScores(
    strength=15, dexterity=14, constitution=12,
    intelligence=10, wisdom=13, charisma=8
)

# Create a stat block
stat_block = StatBlock(
    name="Fighter",
    ability_scores=abilities,
    hit_points=50,
    hit_points_max=50,
    armor_class=16,
    proficiency_bonus=2
)

# Add an attack action
longsword = AttackAction(
    name="Longsword",
    description="A melee weapon attack",
    bonus_to_hit=5,
    damage=[Damage(DamageType.SLASHING, 8)]
)
stat_block.add_action(longsword)

# Create an entity
fighter = Entity(stat_block, is_player_controlled=True)
```

### Running Combat

```python
from src.combat import CombatSystem

# Create combat and add combatants
combat = CombatSystem()
combat.add_combatant(fighter)
combat.add_combatant(goblin_entity)

# Start combat
combat.start_combat()

# Run combat loop
while combat.state == CombatState.ACTIVE:
    current = combat.get_current_entity()
    # Perform action logic here
    combat.end_turn()

# View the log
for entry in combat.get_combat_log():
    print(entry)
```

### Loading Stat Blocks from JSON

```python
from src.loaders import StatBlockLoader

# Load from file
stat_block = StatBlockLoader.load_from_json("path/to/goblin.json")
entity = Entity(stat_block)

# Save to file
StatBlockLoader.save_to_json(stat_block, "path/to/save.json")
```

## Core Classes

### Models
- **AbilityScores**: The six D&D ability scores with modifier calculation
- **StatBlock**: Complete stat block with abilities, skills, actions, and hit points
- **Entity**: A combatant instance with unique ID and initiative tracking
- **Action/AttackAction/SpellAction**: Combat actions with polymorphic support
- **Condition**: Status effects with duration tracking
- **Skill**: Skill checks with proficiency support

### Combat System
- **CombatSystem**: Main simulator managing turns, actions, and damage
- **InitiativeTracker**: Initiative order management
- **CombatLog**: Action log for replay and analysis

### Utilities
- **Dice**: Dice rolling (d20, formula parsing, advantage/disadvantage)
- **StatBlockLoader**: JSON serialization of stat blocks

## Design Principles

1. **Composition over Inheritance**: Entities contain stat blocks, don't inherit
2. **Separation of Concerns**: Models (what), Combat (how), Loaders (I/O)
3. **Extensibility**: Add new action types and conditions without modifying core
4. **Serializable**: Easy JSON/YAML import and export
5. **Type Safety**: Full type hints for IDE support and mypy checking

## Installation

```bash
# Install in development mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=src  # With coverage
```

## Future Enhancements

- [ ] Full spell system with saving throws
- [ ] Spell slot tracking
- [ ] Team/party support
- [ ] Equipment and magic items
- [ ] More condition types
- [ ] Custom reaction support
- [ ] Multiclassing support (future)
- [ ] YAML support for stat blocks
- [ ] Web UI for combat visualization

## License

MIT