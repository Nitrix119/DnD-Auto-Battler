# Creature Definition Guide

This document describes how to define creatures and player characters as JSON for the DnD Auto-Battler. Creature files live under `examples/creatures/` and are loaded via `StatBlockLoader`.

---

## Table of Contents

1. [Overview](#overview)
2. [Top-Level Fields](#top-level-fields)
3. [Ability Scores](#ability-scores)
4. [Saving Throws](#saving-throws)
5. [Actions](#actions)
6. [Spellcasting](#spellcasting)
7. [Legendary Actions](#legendary-actions)
8. [Damage Modifiers](#damage-modifiers)
9. [Resource Defaults](#resource-defaults)
10. [Loading Creatures in Python](#loading-creatures-in-python)
11. [Reference Tables](#reference-tables)
12. [Complete Examples](#complete-examples)

---

## Overview

A creature file is a single JSON object describing the creature's static stat block — its base statistics, abilities, and actions. Mutable combat state (current HP, active conditions, spell slots remaining) is stored separately on the `Entity` wrapper at runtime.

```json
{
  "name": "Goblin",
  "size": "small",
  "abilities": { ... },
  "hit_points_max": 7,
  "armor_class": 12,
  "proficiency_bonus": 2,
  "saving_throws": [],
  "actions": [ ... ]
}
```

---

## Top-Level Fields

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | ✅ | string | — | Display name of the creature |
| `abilities` | ✅ | object | all 10 | Six ability scores; see [Ability Scores](#ability-scores) |
| `hit_points_max` | ✅ | int | `1` | Maximum hit points. Can also use `hit_points` as an alias; `hit_points_max` takes precedence |
| `armor_class` | ✅ | int | `10` | Base armor class |
| `proficiency_bonus` | ❌ | int | `2` | Proficiency bonus used for attack rolls, saving throws, and skills |
| `size` | ❌ | string | `"medium"` | Creature size; see [Size Categories](#size-categories) |
| `saving_throws` | ❌ | array of strings | `[]` | Abilities for which the creature has saving throw proficiency |
| `actions` | ❌ | array | `[]` | Available combat actions; see [Actions](#actions) |
| `known_spells` | ❌ | array of strings | `[]` | Names of spells the creature can use. Must match a loaded spell name |
| `spellcasting_ability` | ❌ | string | `""` | The ability used for spellcasting (e.g. `"intelligence"`). Required for spellcasters |
| `spell_slots` | ❌ | object | `{}` | Maximum spell slots per level, e.g. `{ "1": 4, "2": 3 }` |
| `legendary_actions` | ❌ | object | — | Legendary action configuration; see [Legendary Actions](#legendary-actions) |
| `damage_vulnerabilities` | ❌ | array of strings | `[]` | Damage types the creature is vulnerable to (takes double damage) |
| `damage_resistances` | ❌ | array of strings | `[]` | Damage types the creature is resistant to (takes half damage) |
| `damage_immunities` | ❌ | array of strings | `[]` | Damage types the creature is immune to (takes no damage) |
| `resource_defaults` | ❌ | object | — | Override per-turn action economy; see [Resource Defaults](#resource-defaults) |

---

## Ability Scores

All six ability scores are nested under the `"abilities"` key. Any omitted score defaults to `10`. Scores must be between 1 and 30.

```json
"abilities": {
  "strength": 16,
  "dexterity": 10,
  "constitution": 14,
  "intelligence": 10,
  "wisdom": 12,
  "charisma": 8
}
```

The ability modifier is computed automatically: `(score - 10) // 2`.

| Score | Modifier |
|---|---|
| 1 | −5 |
| 8–9 | −1 |
| 10–11 | +0 |
| 12–13 | +1 |
| 14–15 | +2 |
| 16–17 | +3 |
| 18–19 | +4 |
| 20 | +5 |

---

## Saving Throws

`saving_throws` is an array of ability names for which the creature is proficient. A proficient saving throw adds `proficiency_bonus` on top of the ability modifier.

```json
"saving_throws": ["wisdom", "charisma"]
```

Valid values: `"strength"`, `"dexterity"`, `"constitution"`, `"intelligence"`, `"wisdom"`, `"charisma"`

---

## Actions

Actions are defined in the `"actions"` array. Each action has a `"type"` field that controls how it is resolved. There are two supported types: `"attack"` and `"spell"`. Spell actions use the same JSON format described in the [Spell Definition Guide](../spells/SPELL_DEFINITION_GUIDE.md), so only attack actions are covered here.

### Attack Actions

```json
{
  "name": "Longsword",
  "description": "A melee weapon attack.",
  "type": "attack",
  "cost": { "actions": 1 },
  "range_ft": 5,
  "bonus_to_hit": 5,
  "damage": [
    { "type": "SLASHING", "formula": "1d8+3" }
  ]
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | ✅ | string | — | Display name |
| `description` | ❌ | string | `""` | Flavour text |
| `type` | ✅ | `"attack"` | — | Identifies this as a weapon attack |
| `cost` | ❌ | object | 1 action | Resource cost; see below |
| `cost.actions` | ❌ | int | `1` | Actions consumed |
| `cost.bonus_actions` | ❌ | int | `0` | Bonus actions consumed |
| `cost.reactions` | ❌ | int | `0` | Reactions consumed |
| `range_ft` | ❌ | float | `5.0` | Range in feet. `5` = melee, higher = ranged |
| `bonus_to_hit` | ❌ | int | `0` | Flat bonus added to the d20 attack roll |
| `damage` | ❌ | array | `[]` | One or more damage entries |
| `damage[].type` | ✅ | string | — | Damage type; see [Damage Types](#damage-types) |
| `damage[].formula` | ❌ | string | — | Dice formula, e.g. `"1d8+3"`. Format: `NdN` or `NdN±N` |
| `damage[].amount` | ❌ | int | `0` | Fixed fallback when no formula is given |
| `recharge` | ❌ | string | — | Recharge condition shown in UI, e.g. `"Recharge 5-6"` |
| `legendary_action_cost` | ❌ | int | `0` | If > 0, this action is only usable as a legendary action at this point cost |

> Provide at least one of `formula` or `amount` in each damage entry. When both are present, `formula` is rolled and `amount` is the fallback if the roll fails.

---

## Spellcasting

A creature can cast spells by setting `spellcasting_ability`, listing spell names in `known_spells`, and providing `spell_slots`. Spell definitions are loaded from the spell registry separately.

```json
{
  "spellcasting_ability": "intelligence",
  "known_spells": ["Fire Bolt", "Fireball", "Haste"],
  "spell_slots": { "1": 4, "2": 3, "3": 2 }
}
```

**How derived stats are computed:**

| Stat | Formula |
|---|---|
| Spell attack bonus | `proficiency_bonus + spellcasting ability modifier` |
| Spell save DC | `8 + proficiency_bonus + spellcasting ability modifier` |

For example: a Wizard with Intelligence 18 (+4) and `proficiency_bonus` 3 has a spell attack bonus of **+7** and a spell save DC of **15**.

**Spell slots:** Keys are level strings (`"1"` through `"9"`); values are the maximum count per long rest.

Spells listed in `known_spells` must match the `name` field in a registered spell file. Spell actions embedded directly in the `"actions"` array (using `"type": "spell"`) are also valid and take priority over the registry for that creature.

---

## Legendary Actions

Legendary creatures can act outside their normal turn. Set `legendary_action_count` via the `"legendary_actions"` block:

```json
"legendary_actions": {
  "count_per_round": 3
}
```

Each legendary action in the `"actions"` array must have a `legendary_action_cost` field greater than `0`. The creature spends that many legendary action points when it uses the action.

```json
{
  "name": "Legendary Slam",
  "type": "attack",
  "legendary_action_cost": 1,
  "range_ft": 5,
  "bonus_to_hit": 10,
  "damage": [{ "type": "BLUDGEONING", "formula": "2d6+6" }]
}
```

Legendary action points refresh at the start of the creature's turn.

---

## Damage Modifiers

Creatures can be vulnerable, resistant, or immune to specific damage types.

```json
"damage_vulnerabilities": ["FIRE"],
"damage_resistances": ["BLUDGEONING", "PIERCING", "SLASHING"],
"damage_immunities": ["POISON", "PSYCHIC"]
```

| Key | Effect |
|---|---|
| `damage_vulnerabilities` | Creature takes **double** damage from listed types |
| `damage_resistances` | Creature takes **half** damage from listed types |
| `damage_immunities` | Creature takes **no** damage from listed types |

These are enforced by the global damage modifier rules in `rules/global/`. All values must be uppercase damage type strings; see [Damage Types](#damage-types).

---

## Resource Defaults

By default, every creature starts each turn with 1 action, 1 bonus action, 1 reaction, and 30 ft of movement. Override any of these with `resource_defaults`:

```json
"resource_defaults": {
  "actions": 2,
  "bonus_actions": 1,
  "reactions": 1,
  "speed": 40
}
```

| Key | Default | Description |
|---|---|---|
| `actions` | `1` | Actions per turn |
| `bonus_actions` | `1` | Bonus actions per turn |
| `reactions` | `1` | Reactions per turn |
| `speed` | `30` | Movement in feet per turn |

---

## Loading Creatures in Python

```python
from src.loaders import StatBlockLoader
from src.models import Entity

# Load from JSON
stat_block = StatBlockLoader.load_from_json("examples/creatures/goblin.json")
entity = Entity(stat_block)

# Load a player character (same API)
wizard_block = StatBlockLoader.load_from_json("examples/creatures/characters/wizard.json")
wizard = Entity(wizard_block, is_player_controlled=True, team="players")

# Add to combat
from src.combat import CombatSystem
combat = CombatSystem()
combat.add_combatant(entity)
combat.add_combatant(wizard)
combat.start_combat()
```

**`Entity` constructor parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `stat_block` | `StatBlock` | — | Required. The loaded stat block |
| `is_player_controlled` | bool | `False` | Whether a human player controls this entity |
| `team` | str \| None | `None` | Faction label. Entities on the same team do not attack each other. `None` = hostile to all |
| `x`, `y`, `z` | float | `0.0` | Starting position on the combat grid (feet) |

---

## Reference Tables

### Size Categories

| Value | Footprint | Example |
|---|---|---|
| `"tiny"` | 2.5 × 2.5 ft | Imp, Sprite |
| `"small"` | 5 × 5 ft | Goblin, Halfling |
| `"medium"` | 5 × 5 ft | Human, Orc |
| `"large"` | 10 × 10 ft | Ogre, Hippogriff |
| `"huge"` | 15 × 15 ft | Giant, Adult Dragon |
| `"gargantuan"` | 20 × 20 ft | Tarrasque, Ancient Dragon |

### Damage Types

`ACID`, `BLUDGEONING`, `COLD`, `FIRE`, `FORCE`, `LIGHTNING`, `NECROTIC`, `PIERCING`, `POISON`, `PSYCHIC`, `RADIANT`, `SLASHING`, `THUNDER`, `GENERIC`

### Spellcasting Abilities

`"strength"`, `"dexterity"`, `"constitution"`, `"intelligence"`, `"wisdom"`, `"charisma"`

---

## Complete Examples

### Simple Melee Creature — Goblin

A small creature with two attacks and no spellcasting.

```json
{
  "name": "Goblin",
  "size": "small",
  "abilities": {
    "strength": 10,
    "dexterity": 14,
    "constitution": 10,
    "intelligence": 10,
    "wisdom": 8,
    "charisma": 8
  },
  "hit_points_max": 7,
  "armor_class": 12,
  "proficiency_bonus": 2,
  "saving_throws": [],
  "actions": [
    {
      "name": "Scimitar",
      "description": "A melee weapon attack.",
      "type": "attack",
      "cost": { "actions": 1 },
      "range_ft": 5,
      "bonus_to_hit": 4,
      "damage": [{ "type": "SLASHING", "formula": "1d6" }]
    },
    {
      "name": "Shortbow",
      "description": "A ranged weapon attack.",
      "type": "attack",
      "cost": { "actions": 1 },
      "range_ft": 80,
      "bonus_to_hit": 4,
      "damage": [{ "type": "PIERCING", "formula": "1d6" }]
    }
  ]
}
```

---

### Spellcasting Character — Wizard

A spellcaster with known spells and spell slots. Spell actions are loaded from the spell registry by name.

```json
{
  "name": "Wizard",
  "size": "medium",
  "abilities": {
    "strength": 8,
    "dexterity": 14,
    "constitution": 14,
    "intelligence": 18,
    "wisdom": 12,
    "charisma": 10
  },
  "hit_points_max": 28,
  "armor_class": 12,
  "proficiency_bonus": 3,
  "spellcasting_ability": "intelligence",
  "known_spells": ["Fire Bolt", "Fireball", "Haste"],
  "spell_slots": { "1": 4, "2": 3, "3": 2 }
}
```

With Intelligence 18 (+4) and proficiency bonus 3:
- Spell attack bonus: **+7**
- Spell save DC: **15**

---

### Mixed Character — Paladin

A martial spellcaster with weapon attacks and spell slots. Saving throw proficiencies are listed explicitly.

```json
{
  "name": "Paladin",
  "size": "medium",
  "abilities": {
    "strength": 16,
    "dexterity": 10,
    "constitution": 14,
    "intelligence": 10,
    "wisdom": 12,
    "charisma": 16
  },
  "hit_points_max": 44,
  "armor_class": 18,
  "proficiency_bonus": 3,
  "spellcasting_ability": "charisma",
  "spell_slots": { "1": 4, "2": 2 },
  "saving_throws": ["wisdom", "charisma"],
  "actions": [
    {
      "name": "Longsword",
      "description": "A melee weapon attack.",
      "type": "attack",
      "cost": { "actions": 1 },
      "range_ft": 5,
      "bonus_to_hit": 6,
      "damage": [{ "type": "SLASHING", "formula": "1d8+3" }]
    }
  ]
}
```

---

### Legendary Creature — Stone Golem

A large creature with legendary actions and multiple attack options at different legendary costs.

```json
{
  "name": "Stone Golem",
  "size": "large",
  "abilities": {
    "strength": 20,
    "dexterity": 9,
    "constitution": 20,
    "intelligence": 3,
    "wisdom": 11,
    "charisma": 1
  },
  "hit_points_max": 178,
  "armor_class": 17,
  "proficiency_bonus": 5,
  "legendary_actions": {
    "count_per_round": 3
  },
  "damage_immunities": ["POISON", "PSYCHIC"],
  "actions": [
    {
      "name": "Slam",
      "description": "Melee weapon attack.",
      "type": "attack",
      "cost": { "actions": 1 },
      "range_ft": 5,
      "bonus_to_hit": 10,
      "damage": [{ "type": "BLUDGEONING", "formula": "3d8+6" }]
    },
    {
      "name": "Legendary Slam",
      "description": "Melee weapon attack (legendary action).",
      "type": "attack",
      "legendary_action_cost": 1,
      "range_ft": 5,
      "bonus_to_hit": 10,
      "damage": [{ "type": "BLUDGEONING", "formula": "2d6+6" }]
    },
    {
      "name": "Rock Hurl",
      "description": "Ranged weapon attack (legendary action, costs 2).",
      "type": "attack",
      "legendary_action_cost": 2,
      "range_ft": 60,
      "bonus_to_hit": 10,
      "damage": [{ "type": "BLUDGEONING", "formula": "4d6+8" }]
    }
  ]
}
```

---

### Inline Spell — Creature with an Embedded Spell Action

Spell actions can be defined directly in the `"actions"` array without a separate spell file. This is useful for creature-specific abilities that use the effects pipeline. See the [Spell Definition Guide](../spells/SPELL_DEFINITION_GUIDE.md) for the full spell action format.

```json
{
  "name": "Fire Mage",
  "size": "medium",
  "abilities": {
    "strength": 8,
    "dexterity": 12,
    "constitution": 12,
    "intelligence": 16,
    "wisdom": 10,
    "charisma": 10
  },
  "hit_points_max": 22,
  "armor_class": 11,
  "proficiency_bonus": 3,
  "spellcasting_ability": "intelligence",
  "actions": [
    {
      "name": "Scorching Ray",
      "description": "Launches a ray of fire at a target.",
      "type": "spell",
      "spell_level": 2,
      "spell_range": { "type": "feet", "distance_ft": 120 },
      "targeting_type": "single_target",
      "casting_time": { "type": "action" },
      "duration": { "unit": "instantaneous" },
      "components": { "verbal": true, "somatic": true },
      "effects": [
        { "type": "attack_roll", "attack_bonus": "use_caster_bonus" },
        { "type": "damage", "damage_type": "FIRE", "formula": "2d6", "requires_hit": true }
      ]
    }
  ]
}
```
