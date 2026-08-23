<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate with:  python -m src.rules.step_schema
     Source of truth:  src/rules/step_schema.py (STEP_SCHEMAS).
     A drift test (tests/test_step_reference_doc.py) fails if this is stale. -->

# Spell Pipeline Step Reference

The authoritative list of pipeline step types and their fields, generated from the schema the loader validates against. Every context key an expression may read is listed under **Writes context** on the step that produces it.

Step types: [`attack_roll`](#attack_roll), [`saving_throw`](#saving_throw), [`damage`](#damage), [`healing`](#healing), [`add_entity_effect`](#add_entity_effect), [`grant_temporary_hp`](#grant_temporary_hp), [`apply_condition`](#apply_condition), [`add_modifier`](#add_modifier).

## `attack_roll`

Emit ATTACK_DECLARED, roll a d20, and write the hit result.

| Field | Required | Type | Description |
|---|---|---|---|
| `attack_bonus` | no | int or `use_caster_bonus` | Flat bonus, or 'use_caster_bonus' for the caster's spell attack bonus. |
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** `hit`, `attack_roll`, `attack_total`, `critical_hit`, `critical_miss`

## `saving_throw`

Roll a saving throw for the defender and write the outcome.

| Field | Required | Type | Description |
|---|---|---|---|
| `attribute` | yes | one of: `strength`, `dexterity`, `constitution`, `intelligence`, `wisdom`, `charisma` | The saving-throw ability. |
| `dc` | yes | int or `use_caster_dc` | A DC integer, or 'use_caster_dc' for the caster's spell save DC. |
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** `save_roll`, `save_dc`, `save_success`

## `damage`

Deal typed damage to the defender.

| Field | Required | Type | Description |
|---|---|---|---|
| `damage_type` | yes | one of: `GENERIC`, `ACID`, `BLUDGEONING`, `COLD`, `FIRE`, `FORCE`, `LIGHTNING`, `NECROTIC`, `PIERCING`, `POISON`, `PSYCHIC`, `RADIANT`, `SLASHING`, `THUNDER` | Damage type. |
| `formula` | yes | dice formula | Dice formula, e.g. '8d6' or '2d6+1d8+5', or a flat integer string. |
| `requires_hit` | no | true / false | Skip this step when context.hit is False. |
| `roll_once` | no | true / false | Roll once and share the total across all AoE targets. |
| `save_result` | no | object | Modify damage based on a preceding saving_throw. |
| `save_result.on_success` | yes | one of: `half_damage`, `no_damage` | How a passed save reduces the damage. |
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** `hit`, `save_success`, `save_roll`, `critical_hit`

**Writes context:** `damage_dealt`, `damage_rolled`

## `healing`

Heal a target by an expression amount or a formula+bonus.

| Field | Required | Type | Description |
|---|---|---|---|
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `amount` | no | expression | Expression for a computed amount; takes precedence over formula. |
| `formula` | no | dice formula | Dice formula rolled at cast time. |
| `bonus` | no | expression | Added to the formula roll (int or expression). |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** `healing_amount`

## `add_entity_effect`

Apply a named entity effect from the rule registry.

| Field | Required | Type | Description |
|---|---|---|---|
| `entity_effect_name` | yes | string | Name of the effect in rules/entity_effects/. |
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `on_caster` | no | true / false | Target the caster (equivalent to target='caster'). |
| `concentration` | no | true / false | Track as the caster's concentration; drops any prior one. |
| `instance_fields` | no | object | Per-instance data; values are expressions evaluated at cast time. |
| `on_apply` | no | list | Sub-actions dispatched to the rule-engine handler registry. |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** _(none)_

## `grant_temporary_hp`

Grant temporary hit points directly.

| Field | Required | Type | Description |
|---|---|---|---|
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `amount` | yes | expression | Amount of temp HP (int or expression). |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** `temp_hp_granted`

## `apply_condition`

Apply a status condition via the rule engine.

| Field | Required | Type | Description |
|---|---|---|---|
| `condition_type` | yes | one of: `BLINDED`, `CHARMED`, `DEAFENED`, `EXHAUSTION`, `FRIGHTENED`, `GRAPPLED`, `INCAPACITATED`, `INVISIBLE`, `PARALYZED`, `PETRIFIED`, `POISONED`, `PRONE`, `RESTRAINED`, `STUNNED`, `UNCONSCIOUS` | The condition to apply. |
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `duration` | no | object | Duration object (same shape as a spell duration). |
| `source` | no | string | Human-readable source label. |
| `instance_fields` | no | object | Per-instance data; values are expressions. |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** _(none)_

## `add_modifier`

Add a persistent stat modifier via the rule engine.

| Field | Required | Type | Description |
|---|---|---|---|
| `target` | no | `caster` / `defender` | "caster" or "defender". |
| `stat` | yes | string | Stat to modify, e.g. 'ac' or 'saving_throw.wisdom'. |
| `value` | yes | expression | Modifier amount (int or expression). |
| `source` | no | string | Human-readable source label. |
| `effect_name` | no | string | Links the modifier to a named effect for removal. |
| `condition` | no | expression | Expression; step is skipped if it evaluates falsy. |

**Reads context:** _(none)_

**Writes context:** _(none)_
