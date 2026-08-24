# Action & Spell Definition Guide

This document describes how to define weapon attacks and spells as JSON for the DnD Auto-Battler.
Both live in a creature's stat block under the `"actions"` array, or as standalone spell files under
`examples/spells/`.

---

## Table of Contents

1. [Weapon Attacks](#weapon-attacks)
2. [Spells — Top-Level Fields](#spells--top-level-fields)
   - [Spell Range](#spell-range)
   - [Targeting](#targeting)
   - [Casting Time](#casting-time)
   - [Duration](#duration)
   - [Components](#components)
3. [The Effects Pipeline](#the-effects-pipeline)
   - [attack_roll](#attack_roll)
   - [saving_throw](#saving_throw)
   - [damage](#damage)
   - [healing](#healing)
   - [add_entity_effect](#add_entity_effect)
   - [grant_temporary_hp](#grant_temporary_hp)
   - [apply_condition](#apply_condition)
   - [add_modifier](#add_modifier)
4. [Expressions](#expressions)
5. [Reference Tables](#reference-tables)

---

## Weapon Attacks

Weapon attacks use `"type": "attack"`. They do not use the effects pipeline; damage is resolved
directly by the attack resolver.

```json
{
  "name": "Longsword",
  "description": "A melee weapon attack.",
  "type": "attack",
  "cost": { "actions": 1 },
  "range_ft": 5,
  "bonus_to_hit": 7,
  "damage": [
    { "type": "SLASHING", "formula": "1d8+4" }
  ]
}
```

### Weapon Attack Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | ✅ | string | Display name |
| `description` | ✅ | string | Flavour text |
| `type` | ✅ | `"attack"` | Discriminates from spells |
| `cost` | ❌ | object | Resource cost (default: 1 action) |
| `cost.actions` | ❌ | int | Actions consumed (default `1`) |
| `cost.bonus_actions` | ❌ | int | Bonus actions consumed |
| `cost.reactions` | ❌ | int | Reactions consumed |
| `range_ft` | ❌ | float | Range in feet. `5` = melee, higher = ranged (default `5.0`) |
| `bonus_to_hit` | ❌ | int | Added to the d20 attack roll (default `0`) |
| `damage` | ❌ | array | One or more damage entries (default `[]`) |
| `damage[].type` | ✅ | string | Damage type (see [Damage Types](#damage-types)) |
| `damage[].formula` | ❌ | string | Dice formula, e.g. `"1d8+4"`. Format: `NdN` or `NdN±N` |
| `damage[].amount` | ❌ | int | Fixed fallback amount when no formula is given |
| `recharge` | ❌ | string | Recharge condition, e.g. `"Recharge 5-6"` |
| `legendary_action_cost` | ❌ | int | If > 0, action is only usable as a legendary action |

> At least one of `formula` or `amount` should be provided in each damage entry.

---

## Spells — Top-Level Fields

Spells use `"type": "spell"`. All spell-specific behaviour is driven by the `"effects"` array
(the pipeline). A spell without any `"effects"` entries auto-hits and does nothing.

```json
{
  "name": "Fireball",
  "description": "...",
  "type": "spell",
  "spell_level": 3,
  "spell_range": { "type": "feet", "distance_ft": 150 },
  "targeting_type": "aoe",
  "aoe": { "shape": "sphere", "size_ft": 20 },
  "casting_time": { "type": "action" },
  "duration": { "unit": "instantaneous" },
  "components": { "verbal": true, "somatic": true, "material": ["a tiny ball of bat guano"] },
  "higher_level_scaling": "Damage increases by 1d6 per slot level above 3rd.",
  "can_target_self": false,
  "cannot_cause_self_damage": false,
  "effects": [ ... ],
  "animation": [ ... ]
}
```

### Top-Level Spell Fields

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | ✅ | string | — | Display name |
| `description` | ✅ | string | — | Flavour text |
| `type` | ✅ | `"spell"` | — | Discriminates from attacks |
| `spell_level` | ❌ | int 0–9 | `0` | Spell slot level; 0 = cantrip |
| `spell_range` | ❌ | object | touch | See [Spell Range](#spell-range) |
| `targeting_type` | ❌ | string | `"single_target"` | See [Targeting](#targeting) |
| `aoe` | ✅ if AOE | object | — | Required when `targeting_type` is `"aoe"`. See [Targeting](#targeting) |
| `casting_time` | ❌ | object | 1 action | See [Casting Time](#casting-time) |
| `duration` | ❌ | object | instantaneous | See [Duration](#duration) |
| `components` | ❌ | object | V + S | See [Components](#components) |
| `higher_level_scaling` | ❌ | string | — | Free-text description of upcast behaviour (structured scaling not yet implemented) |
| `can_target_self` | ❌ | bool | `false` | Whether the caster can choose themselves as the target |
| `cannot_cause_self_damage` | ❌ | bool | `false` | If `true`, the caster is automatically excluded from AoE damage (e.g. Cone of Cold, Lightning Bolt) |
| `effects` | ❌ | array | `[]` | Sequential pipeline steps. See [The Effects Pipeline](#the-effects-pipeline) |
| `animation` | ❌ | array | `[]` | Visual effect frames; not used by the combat engine |
| `recharge` | ❌ | string | — | Recharge condition, e.g. `"Recharge 5-6"` |
| `legendary_action_cost` | ❌ | int | `0` | If > 0, usable only as a legendary action |

---

### Spell Range

Controls how far the spell can reach.

| Field | Required | Type | Description |
|---|---|---|---|
| `type` | ✅ | string | One of: `"self"`, `"touch"`, `"feet"`, `"sight"`, `"unlimited"`, `"special"` |
| `distance_ft` | ✅ if `feet` | int | Range in feet; must be ≥ 0 |

```json
{ "type": "feet", "distance_ft": 120 }
{ "type": "touch" }
{ "type": "self" }
```

**Range type behaviour:**
- `self` / `touch` — caster must be adjacent to the target
- `feet` — target must be within `distance_ft`; the engine enforces this and clamps AoE blast points
- `sight` / `unlimited` — no distance limit is enforced

---

### Targeting

| Field | Required | Type | Description |
|---|---|---|---|
| `targeting_type` | ❌ | string | `"single_target"` (default), `"multi_target"`, `"aoe"`, or `"special"` |
| `aoe` | ✅ if AOE | object | Geometry of the AoE area |
| `aoe.shape` | ✅ | string | `"sphere"`, `"cone"`, `"line"`, `"cylinder"`, `"cube"`, `"special"` |
| `aoe.size_ft` | ✅ | int | Radius (sphere/cylinder), half-length of side (cube), or length (cone/line). Must be > 0 |
| `aoe.height_ft` | ❌ | int | Cylinder height in feet; must be > 0 if provided |
| `aoe.width_ft` | ❌ | int | Line width in feet; must be > 0 if provided (defaults to 5 ft at runtime) |

**`multi_target`** models split projectiles — Magic Missile's darts, Scorching Ray's rays,
Eldritch Blast's beams. The caller supplies one target per projectile (the `defenders`/`target_ids`
list, repeats allowed to stack projectiles on one creature), and the effect pipeline runs
**independently per projectile** — each gets its own attack roll and its own damage roll (do **not**
use `roll_once`). Model the spell as the per-projectile effect (e.g. one `damage` step of `1d4+1`,
or an `attack_roll` + `requires_hit` `damage`); the number of projectiles comes from the supplied
target list. _(Projectile-count scaling on upcast is not yet modelled — see `higher_level_scaling`.)_

For AoE spells, the caster must provide a target point at cast time; the engine auto-selects all
living combatants whose token overlaps the area, then runs the full effect pipeline once per
selected defender. This fan-out is automatic — `damage` and `saving_throw` steps always apply to
the current defender and take no `target` field. (Use `roll_once` on a `damage` step so every
target in the area takes the same rolled total, per D&D 5e.)

---

### Casting Time

| Field | Required | Type | Description |
|---|---|---|---|
| `type` | ✅ | string | `"action"`, `"bonus_action"`, `"reaction"`, `"instant"`, `"minute"`, `"hour"`, `"special"` |
| `count` | ❌ | int ≥ 1 | Number of actions/minutes/hours (default `1`; ignored for bonus_action, reaction, instant, special) |
| `reaction_trigger` | ❌ | string | Free-text trigger description for reaction spells |
| `special_description` | ❌ | string | Free-text description when `type` is `"special"` |

The casting time also determines the action economy cost:

| `casting_time.type` | Resource spent |
|---|---|
| `action` | 1 action |
| `bonus_action` | 1 bonus action |
| `reaction` | 1 reaction |
| `instant` / `minute` / `hour` / `special` | No automatic cost (set `cost` manually if needed) |

---

### Duration

| Field | Required | Type | Description |
|---|---|---|---|
| `unit` | ✅ | string | `"instantaneous"`, `"round"`, `"minute"`, `"hour"`, `"day"`, `"until_dispelled"`, `"special"` |
| `count` | ❌ | int ≥ 1 | Number of units (default `1`; only meaningful for round/minute/hour/day) |
| `concentration` | ❌ | bool | `true` if the caster must concentrate to sustain the spell (default `false`; not valid for instantaneous) |
| `special_description` | ❌ | string | Free-text when `unit` is `"special"` |

```json
{ "unit": "minute", "count": 10, "concentration": true }
{ "unit": "instantaneous" }
```

---

### Components

| Field | Required | Type | Description |
|---|---|---|---|
| `verbal` | ❌ | bool | Requires spoken words (default `true`) |
| `somatic` | ❌ | bool | Requires physical gestures (default `true`) |
| `material` | ❌ | array of strings | Material component descriptions (default `[]`) |

```json
{ "verbal": true, "somatic": true, "material": ["a tiny ball of bat guano and sulfur"] }
```

---

## The Effects Pipeline

> **Authoritative field reference:** [STEP_REFERENCE.md](STEP_REFERENCE.md) is generated from the
> loader's schema (`src/rules/step_schema.py`) and is the source of truth for each step type's fields,
> value domains, and the context keys it reads/writes. A drift test keeps it in sync with the code, and
> the loader validates every spell against that schema on load — an unknown step type, a typo'd field,
> a bad enum, or a `context.X` reference to a key nothing writes is a named error at load time. The
> sections below add prose and worked examples; when they disagree with the generated reference, the
> reference wins.

The `"effects"` array is a sequential list of steps. Each step has a `"type"` that determines what
it does. Steps share an ephemeral **context** — a dictionary of values written by earlier steps and
readable by later ones via [expressions](#expressions).

**Execution order matters.** Steps run top-to-bottom. An `attack_roll` or `saving_throw` step must
appear before any `damage` step that depends on its result.

### Context values available to all steps

| Key | Written by | Description |
|---|---|---|
| `context.hit` | `attack_roll` | `True` if the attack connected |
| `context.save_roll` | `saving_throw` | The raw d20 roll (or `None` if no save was rolled) |
| `context.save_success` | `saving_throw` | `True` if the target passed (default `True` until a save is rolled) |
| `context.attack_roll` | `attack_roll` | The raw d20 roll |
| `context.attack_total` | `attack_roll` | Roll + bonus |
| `context.damage_dealt` | `damage` | Cumulative damage dealt so far this pipeline run |
| `context.damage_rolled` | `damage` | Damage rolled before resistance |
| `context.healing_amount` | `healing` | Amount healed in the most recent healing step |
| `context.temp_hp_granted` | `grant_temporary_hp` | Temp HP from the most recent grant step |

### Shared optional field

All step types accept one optional field not listed in their individual tables:

| Field | Type | Description |
|---|---|---|
| `condition` | string (expression) | If present, the step is skipped when the expression evaluates falsy. Errors in evaluation also skip the step. See [Expressions](#expressions) |

---

### `attack_roll`

Emits an `ATTACK_DECLARED` event (which entity effects can cancel), rolls a d20, and writes the
result to context. If the event is cancelled the step sets `hit = false` without rolling.

```json
{
  "type": "attack_roll",
  "attack_bonus": "use_caster_bonus",
  "target": "defender"
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `attack_bonus` | ❌ | int or `"use_caster_bonus"` | `0` | Flat bonus added to the d20. `"use_caster_bonus"` uses the caster's `spell_attack_bonus` |
| `target` | ❌ | `"defender"` | `"defender"` | Currently always targets the defender |

**Context written:** `hit`, `attack_roll`, `attack_total`

---

### `saving_throw`

Rolls a saving throw for the defender and writes the result to context. If `dc` resolves to 0 or
`attribute` is empty, no roll is made and `save_success` defaults to `true`.

```json
{
  "type": "saving_throw",
  "attribute": "dexterity",
  "dc": "use_caster_dc"
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `attribute` | ✅ | string | — | Saving throw ability: `"strength"`, `"dexterity"`, `"constitution"`, `"intelligence"`, `"wisdom"`, `"charisma"` |
| `dc` | ✅ | int or `"use_caster_dc"` | — | Difficulty class. `"use_caster_dc"` uses the caster's computed spell save DC (8 + proficiency + spellcasting modifier) |

The save is always rolled by the current defender; for AoE the pipeline runs once per target
automatically, so there is no `target` field here.

**Context written:** `save_roll`, `save_success`

---

### `damage`

Deals damage to the target. Respects `requires_hit` and optionally modifies the amount based on
a preceding saving throw result.

```json
{
  "type": "damage",
  "damage_type": "FIRE",
  "formula": "8d6",
  "roll_once": true,
  "save_result": { "on_success": "half_damage" }
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `damage_type` | ✅ | string | — | See [Damage Types](#damage-types) |
| `formula` | ✅ | string | — | Dice formula: one or more `NdN` / flat terms joined by `+`/`-` (e.g. `"8d6"`, `"2d6+1d8+5"`, `"1d20-2"`), or a plain integer string `"20"` for a fixed amount |
| `requires_hit` | ❌ | bool | `false` | If `true`, skips this step entirely when `context.hit` is `false` |
| `roll_once` | ❌ | bool | `false` | If `true`, the formula is rolled once before the pipeline runs and that result is shared across all AoE targets (set on AoE damage for consistent damage). The pre-roll is seeded by `SpellResolver` |
| `save_result` | ❌ | object | — | Modifies damage based on a preceding `saving_throw` result |
| `save_result.on_success` | ✅ if `save_result` | string | — | `"half_damage"` (floor halves the rolled amount) or `"no_damage"` (sets amount to 0) |

**Context written:** `damage_dealt` (cumulative), `damage_rolled`

> `save_result` only applies when `context.save_roll` is not `None` (i.e. a saving throw was
> actually rolled earlier in the pipeline). Auto-hit spells without a `saving_throw` step are
> unaffected.

**Upcasting (`scaling`).** A damage step scales with the slot the spell is cast at via an optional
`scaling` object — the dice grow, the formula stays a dice string (no expressions):

```json
{
  "type": "damage", "damage_type": "FIRE", "formula": "8d6", "roll_once": true,
  "save_result": { "on_success": "half_damage" },
  "scaling": { "per_slot_above": 3, "add_dice": "1d6" }
}
```

`per_slot_above` is the threshold slot level (usually the spell's base level); `add_dice` is added
once per slot level above it. A Fireball cast with a 5th-level slot rolls `8d6+2d6`. The cast-time
slot is also exposed as `context.slot_level` for conditions/expressions. Casting at a slot **below**
the spell's base level is rejected, and the slot actually spent is the one cast at.

---

### `healing`

Heals a target for an amount determined by either an expression or a dice formula with an optional
bonus.

```json
{
  "type": "healing",
  "target": "defender",
  "formula": "1d8",
  "bonus": "event.caster.spellcasting_modifier"
}
```

```json
{
  "type": "healing",
  "target": "caster",
  "amount": "context.damage_dealt // 2",
  "condition": "context.damage_dealt > 0"
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `target` | ❌ | `"defender"` or `"caster"` | `"defender"` | Who receives the healing |
| `formula` | ✅ (or `amount`) | string | — | Dice formula rolled at cast time |
| `bonus` | ❌ | int or expression | `0` | Added to the formula roll. Commonly `"event.caster.spellcasting_modifier"` |
| `amount` | ✅ (or `formula`) | expression | — | Evaluated expression for a computed amount (e.g. `"context.damage_dealt // 2"`). Takes precedence over `formula` if both are present |

Exactly one of `formula` or `amount` must be provided.

**Context written:** `healing_amount`

---

### `add_entity_effect`

Applies a named entity effect from the rule registry to a target. Requires the spell resolver to
be wired to a `RuleEngine` with the matching effect loaded; silently skips otherwise.

```json
{
  "type": "add_entity_effect",
  "entity_effect_name": "charmed",
  "target": "defender",
  "condition": "not context.save_success",
  "instance_fields": {
    "charmer": "event.caster"
  }
}
```

```json
{
  "type": "add_entity_effect",
  "entity_effect_name": "shield_of_faith",
  "target": "defender",
  "concentration": true,
  "on_apply": [
    {
      "action": "AddModifier",
      "target": "event.defender",
      "stat": "ac",
      "value": 2,
      "source": "Shield of Faith",
      "effect_name": "shield_of_faith"
    }
  ]
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `entity_effect_name` | ✅ | string | — | Name of the effect in the rule registry (matches the JSON filename in `rules/entity_effects/`) |
| `target` | ❌ | `"defender"` or `"caster"` | `"defender"` | Who receives the effect. Overridden by `on_caster` |
| `on_caster` | ❌ | bool | `false` | Alternative way to target the caster; equivalent to `"target": "caster"` |
| `concentration` | ❌ | bool | `false` | If `true`, drops any existing concentration effect before applying this one, then tracks this effect as the caster's concentration |
| `instance_fields` | ❌ | object | `{}` | Per-instance data attached to the effect. Values are [expressions](#expressions) evaluated at cast time (e.g. `"event.caster"` to store a reference to the caster) |
| `on_apply` | ❌ | array | `[]` | Sub-actions dispatched through the rule engine's built-in handler registry immediately after the effect is applied. See [on_apply sub-actions](#on_apply-sub-actions) |

#### on_apply sub-actions

`on_apply` entries are dispatched to the rule engine's built-in handler registry. The following
handlers are available:

**`GrantTemporaryHP`** — grants temp HP immediately on cast:

| Field | Required | Type | Description |
|---|---|---|---|
| `action` | ✅ | `"GrantTemporaryHP"` | — |
| `target` | ✅ | expression | Typically `"event.defender"` or `"event.caster"` |
| `amount` | ✅ | int or expression | Amount of temp HP |

**`AddModifier`** — adds a stat modifier immediately on cast:

| Field | Required | Type | Description |
|---|---|---|---|
| `action` | ✅ | `"AddModifier"` | — |
| `target` | ✅ | expression | Typically `"event.defender"` or `"event.caster"` |
| `stat` | ✅ | string | Stat to modify, e.g. `"ac"`, `"speed"` |
| `value` | ✅ | int or expression | Modifier amount |
| `source` | ❌ | string | Human-readable source label |
| `effect_name` | ❌ | string | Links this modifier to a named effect so it is removed when the effect ends |

**`GrantAction`** — grants an additional action to the target:

| Field | Required | Type | Description |
|---|---|---|---|
| `action` | ✅ | `"GrantAction"` | — |
| `target` | ✅ | expression | Typically `"event.caster"` |
| `name` | ✅ | string | Display name of the granted action |
| `description` | ❌ | string | Flavour text |
| `bonus_to_hit` | ❌ | int or expression | Attack roll bonus |
| `range_ft` | ❌ | int | Range in feet |
| `damage` | ❌ | array | Damage entries; same format as weapon attack damage |
| `source_effect` | ❌ | string | The granted action is revoked when this named effect is removed from the entity |

---

### `grant_temporary_hp`

Grants temporary hit points directly via the pipeline (without needing an entity effect).

```json
{
  "type": "grant_temporary_hp",
  "target": "caster",
  "amount": 10
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `target` | ❌ | `"defender"` or `"caster"` | `"defender"` | Who receives the temp HP |
| `amount` | ✅ | int or expression | — | Amount of temporary HP to grant |

**Context written:** `temp_hp_granted`

---

### `apply_condition`

Applies a status condition via the rule engine's `ApplyCondition` handler.

```json
{
  "type": "apply_condition",
  "condition_type": "prone",
  "target": "defender",
  "duration": { "unit": "round", "count": 1 },
  "source": "Thunderwave"
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `condition_type` | ✅ | string | — | Name of the condition to apply (e.g. `"prone"`, `"stunned"`) |
| `target` | ❌ | `"defender"` or `"caster"` | `"defender"` | Who receives the condition |
| `duration` | ❌ | object | — | Duration of the condition; same structure as the spell-level [Duration](#duration) object |
| `source` | ❌ | string | — | Human-readable source label |
| `instance_fields` | ❌ | object | `{}` | Per-instance data for the condition; values are expressions |

Requires a `RuleEngine` with an `ApplyCondition` handler registered. Silently skips if unavailable.

---

### `add_modifier`

Adds a persistent stat modifier to a target via the rule engine, without attaching it to an entity
effect.

```json
{
  "type": "add_modifier",
  "target": "defender",
  "stat": "ac",
  "value": -2,
  "source": "Hex"
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `target` | ❌ | `"defender"` or `"caster"` | `"defender"` | Who receives the modifier |
| `stat` | ✅ | string | — | Stat to modify (e.g. `"ac"`, `"speed"`) |
| `value` | ✅ | int or expression | — | Modifier amount (can be negative) |
| `source` | ❌ | string | — | Human-readable source label |
| `effect_name` | ❌ | string | — | Links to a named effect for removal tracking |

Requires a `RuleEngine` with an `AddModifier` handler registered. Silently skips if unavailable.

---

## Expressions

Several fields across the pipeline accept **expression strings** — sandboxed Python expressions
evaluated at runtime. Expressions have access to the following namespace:

| Name | Type | Description |
|---|---|---|
| `event.caster` | Entity | The spell's caster |
| `event.defender` | Entity | The current target |
| `event.action` | SpellAction | The spell being cast (not available in healing steps) |
| `context` | SimpleNamespace | All non-private pipeline context keys as attributes (e.g. `context.damage_dealt`) |
| `save_success` | bool | Shorthand alias for `context.save_success` |
| `save_roll` | int\|None | Shorthand alias for `context.save_roll` |

**Commonly used entity attributes:**
- `event.caster.spellcasting_modifier` — ability modifier for the caster's spellcasting ability
- `event.caster.spell_attack_bonus` — spell attack bonus (proficiency + spellcasting modifier)
- `event.caster.spell_save_dc` — spell save DC (8 + proficiency + spellcasting modifier)
- `event.defender.ac` — armour class

**Allowed operations:** arithmetic (`+`, `-`, `*`, `/`, `//`, `%`), comparisons (`==`, `!=`, `<`,
`<=`, `>`, `>=`), boolean logic (`and`, `or`, `not`), attribute access, subscript, and calls to
the safe built-ins: `max`, `min`, `abs`, `int`, `round`, `bool`, `len`, `hasattr`.

**Not allowed:** assignments, imports, list comprehensions, lambdas, method calls, or any access to
private (`_`-prefixed) attributes.

### Expression examples

```
"event.caster.spellcasting_modifier"      # caster's spellcasting mod as a bonus
"context.damage_dealt // 2"               # half of damage dealt so far
"not context.save_success"                # condition: only if the save was failed
"context.damage_dealt > 0"               # condition: only if damage was dealt
"max(context.damage_dealt, 10)"           # at least 10
```

---

## Reference Tables

### Damage Types

`ACID`, `BLUDGEONING`, `COLD`, `FIRE`, `FORCE`, `LIGHTNING`, `NECROTIC`, `PIERCING`, `POISON`,
`RADIANT`, `SLASHING`, `THUNDER`, `GENERIC`

### Saving Throw Attributes

`strength`, `dexterity`, `constitution`, `intelligence`, `wisdom`, `charisma`

### Spell Range Types

| Value | Description |
|---|---|
| `self` | Caster only / originates from caster |
| `touch` | Must be adjacent (within 5 ft) |
| `feet` | Explicit distance; requires `distance_ft` |
| `sight` | No distance limit enforced |
| `unlimited` | No distance limit enforced |
| `special` | Non-standard; no enforcement |

### AOE Shapes

| Value | `size_ft` meaning | Extra fields |
|---|---|---|
| `sphere` | Radius | — |
| `cone` | Length | — |
| `line` | Length | `width_ft` (default 5 ft) |
| `cylinder` | Radius | `height_ft` |
| `cube` | Half side length | — |
| `special` | Custom | — |

### Casting Time Types

| Value | Resource cost |
|---|---|
| `action` | 1 action |
| `bonus_action` | 1 bonus action |
| `reaction` | 1 reaction |
| `instant` | None (instant; no cost deducted automatically) |
| `minute` | None (requires `count` minutes) |
| `hour` | None (requires `count` hours) |
| `special` | None |

### Duration Units

`instantaneous`, `round`, `minute`, `hour`, `day`, `until_dispelled`, `special`

---

## Complete Examples

### Fire Bolt — attack-roll cantrip

```json
{
  "name": "Fire Bolt",
  "type": "spell",
  "spell_level": 0,
  "spell_range": { "type": "feet", "distance_ft": 120 },
  "targeting_type": "single_target",
  "casting_time": { "type": "action" },
  "duration": { "unit": "instantaneous" },
  "components": { "verbal": true, "somatic": true, "material": [] },
  "effects": [
    { "type": "attack_roll", "attack_bonus": "use_caster_bonus" },
    { "type": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": true }
  ]
}
```

### Fireball — AoE saving throw with shared roll

```json
{
  "name": "Fireball",
  "type": "spell",
  "spell_level": 3,
  "spell_range": { "type": "feet", "distance_ft": 150 },
  "targeting_type": "aoe",
  "aoe": { "shape": "sphere", "size_ft": 20 },
  "casting_time": { "type": "action" },
  "duration": { "unit": "instantaneous" },
  "components": { "verbal": true, "somatic": true, "material": ["a tiny ball of bat guano"] },
  "effects": [
    {
      "type": "saving_throw",
      "attribute": "dexterity",
      "dc": "use_caster_dc"
    },
    {
      "type": "damage",
      "damage_type": "FIRE",
      "formula": "8d6",
      "roll_once": true,
      "save_result": { "on_success": "half_damage" }
    }
  ]
}
```

### Cure Wounds — healing with caster modifier

```json
{
  "name": "Cure Wounds",
  "type": "spell",
  "spell_level": 1,
  "spell_range": { "type": "touch" },
  "can_target_self": true,
  "targeting_type": "single_target",
  "casting_time": { "type": "action" },
  "duration": { "unit": "instantaneous" },
  "components": { "verbal": true, "somatic": true, "material": [] },
  "effects": [
    {
      "type": "healing",
      "target": "defender",
      "formula": "1d8",
      "bonus": "event.caster.spellcasting_modifier"
    }
  ]
}
```

### Charm Person — save-or-effect with conditional application

```json
{
  "name": "Charm Person",
  "type": "spell",
  "spell_level": 1,
  "spell_range": { "type": "feet", "distance_ft": 30 },
  "targeting_type": "single_target",
  "casting_time": { "type": "action" },
  "duration": { "unit": "hour", "count": 1 },
  "components": { "verbal": true, "somatic": true, "material": [] },
  "effects": [
    {
      "type": "saving_throw",
      "attribute": "wisdom",
      "dc": "use_caster_dc"
    },
    {
      "type": "add_entity_effect",
      "entity_effect_name": "charmed",
      "target": "defender",
      "condition": "not context.save_success",
      "instance_fields": { "charmer": "event.caster" }
    }
  ]
}
```

### Vampiric Touch — attack, damage, then heal from damage dealt

```json
{
  "name": "Vampiric Touch",
  "type": "spell",
  "spell_level": 3,
  "spell_range": { "type": "touch" },
  "targeting_type": "single_target",
  "casting_time": { "type": "action" },
  "duration": { "unit": "minute", "count": 1, "concentration": true },
  "components": { "verbal": true, "somatic": true, "material": [] },
  "effects": [
    { "type": "attack_roll", "attack_bonus": "use_caster_bonus" },
    { "type": "damage", "damage_type": "NECROTIC", "formula": "3d6", "requires_hit": true },
    {
      "type": "healing",
      "target": "caster",
      "amount": "context.damage_dealt // 2",
      "condition": "context.damage_dealt > 0"
    },
    {
      "type": "add_entity_effect",
      "entity_effect_name": "vampiric_touch",
      "on_caster": true,
      "concentration": true
    }
  ]
}
```
