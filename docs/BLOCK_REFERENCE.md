<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate with:  python -m src.spells.reference
     Source of truth:  the block REGISTRY (src/spells/blocks/*.py).
     A drift test (tests/test_block_reference_doc.py) fails if this is stale. -->


# Block Reference

The authoritative list of block types, generated from the registry the loader validates against. A spell, a weapon and a rule are all programs built from these blocks.

Block types: [`add_modifier`](#add_modifier), [`add_resource`](#add_resource), [`apply_condition`](#apply_condition), [`attack_roll`](#attack_roll), [`cancel`](#cancel), [`damage`](#damage), [`end_lifetime`](#end_lifetime), [`for_each_target`](#for_each_target), [`force_concentration_check`](#force_concentration_check), [`force_critical`](#force_critical), [`grant_action`](#grant_action), [`grant_advantage`](#grant_advantage), [`grant_disadvantage`](#grant_disadvantage), [`grant_temporary_hp`](#grant_temporary_hp), [`healing`](#healing), [`lifetime`](#lifetime), [`modify_damage`](#modify_damage), [`refill_resources`](#refill_resources), [`saving_throw`](#saving_throw), [`trigger`](#trigger).

**Reading this.** Each block lists every arg it accepts — anything else is rejected at load. *Kind* is how the value is validated; *req.* marks the args a block cannot be written without. *Reads*/*Writes context* are the `context.X` keys a block consumes and produces, so a later block may read what an earlier one wrote. *Target* is how the block addresses the current target.

Every block also accepts `condition` — Expression; the block is skipped when it evaluates falsy.

A key beginning with `_` (such as `_note`) is ignored by the engine and may be used for authoring commentary.

## `add_modifier`

Attach a labeled StatModifier to the target.

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `stat` | yes | a string | Stat to modify: 'ac', 'spell_save_dc', 'saving_throw.<ability>', 'max_hp', … |
| `value` | yes | an expression | How much to add (negative to subtract). |
| `source` |  | a string | Label for what applied this (a spell name). |
| `effect_name` |  | a string | Effect name, used to remove this by name later. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |

## `add_resource`

Add to a per-turn resource (movement, actions, …) on the target.

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `resource` | yes | `actions` / `bonus_actions` / `reactions` / `movement` | Which per-turn resource to top up. |
| `amount` | yes | an expression | How much to add. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |

A *transient* grant, not a durable one: it is re-applied each turn by a
``TURN_START`` rider and wiped by the next turn's refill, so it registers **no**
revoke handle — when the rider's lifetime ends it simply stops being re-added
(matching the legacy ``AddResource`` entity effect).

## `apply_condition`

Add a status condition to the target and install its reactive mechanics.

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `condition_type` | yes | a `ConditionType` name | Which condition to apply. |
| `duration` |  | an expression | Rounds the condition lasts; omitted = until dispelled. |
| `source` |  | a string | Label for what applied this (a spell name). |
| `effect_name` |  | a string | Effect name, used to remove this by name later. |
| `bindings` |  | an object of name → expression | Per-application values captured once at install and read later as instance_fields.<name>. |
| `instance_fields` |  | an object of name → expression | Deprecated spelling of `bindings`; prefer `bindings`. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | installs reactions (subscribes handlers to future events) |

The condition's marker (``Condition``) is inert on its own; its behaviour lives
in a reactive rule (``blinded`` → disadvantage, etc.). This block adds the marker
**and** installs that rule, both owned by one lifetime scope so they end together:
an enclosing scope (a concentration spell) when present, else a rounds scope on
the target keyed to ``duration``, else a permanent scope disposed only on dispel.
Emits CONDITION_ADDED. Degrades to marker-only when no reactive rule is wired.

## `attack_roll`

Emit ATTACK_DECLARED, roll to hit, emit ATTACK_ROLLED/ATTACK_HIT.

| Arg | Req. | Kind | |
|---|---|---|---|
| `attack_bonus` |  | an integer (or `use_caster_bonus`) | Flat bonus, or 'use_caster_bonus' for the caster's spell attack bonus. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | `hit`, `attack_roll`, `attack_total`, `critical_hit`, `critical_miss` |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | gate (a roll that later blocks are conditioned on) |

Writes hit / attack_roll / attack_total / critical_hit / critical_miss to the
context. Mirrors the legacy pipeline's attack-roll step exactly (same events,
same rolls) so the two engines stay in parity.

## `cancel`

Cancel the in-flight action by setting ``cancelled`` on the live event.

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | event modifier (mutates the in-flight event; only meaningful inside a `trigger`) |

The block form of ``effects.cancel_event`` — how incapacitated/paralysed/
stunned/… stop an action outright. Sets the flag on the ``CombatEvent``
itself (not its ``data``), which is what the emitter checks after each handler.

## `damage`

Apply typed damage to the current target. Returns the amount dealt.

| Arg | Req. | Kind | |
|---|---|---|---|
| `formula` | yes | a dice formula | Dice formula rolled at cast time. |
| `damage_type` | yes | a `DamageType` name, or an expression yielding one | Damage type name, or an expression yielding one (a rider dealing the weapon's own type). |
| `requires_hit` |  | `true` / `false` | Skip unless a preceding attack_roll hit. |
| `roll_once` |  | `true` / `false` | Inside for_each_target, roll once and share the result across every target (read by the iterator). |
| `save_result` |  | an object: `on_success`* | Modify damage based on a preceding saving_throw. |
| `scaling` |  | an object: `per_slot_above`*, `add_dice`* | Upcasting: add dice when cast with a higher slot. |

| | |
|---|---|
| **Reads context** | `hit`, `save_success`, `save_roll`, `critical_hit`, `slot_level` |
| **Writes context** | `damage_dealt`, `damage_rolled` |
| **Target** | acts on the current target, which must be exactly one entity |

## `end_lifetime`

End the effect whose rider is firing — dispose its owning lifetime scope.

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |

Used by a self-terminating effect (Armor of Agathys ends when its temp HP is
gone). Disposing the scope revokes every grant it owns and unsubscribes its
riders. A no-op outside a trigger firing (no owning scope).

## `for_each_target`

Run ``then`` once per target in the set, collecting a result per element.

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | consumes the target set (an iterator, or a genuine aggregate) |

Reads the set from the root invocation's ``targets`` and appends each
element's :class:`~src.spells.context.InvocationResult` to ``results``.

## `force_concentration_check`

Force the target's CON save; on a failure, end its concentration.

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `dc` | yes | an expression | Expression for the save DC, evaluated at fire time. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |

The block form of ``effects.force_concentration_check``. ``dc`` is an expression
evaluated at fire time against the event (e.g. ``max(10, event.total // 2)``).
``Entity.end_concentration`` disposes a block-engine concentration scope (Shield
of Faith, Vampiric Touch, Haste) and cleans a legacy string tag — one call covers
both, so this drives the whole concentration teardown on the new engine.

## `force_critical`

Force the in-flight attack to resolve as a critical hit (or miss).

| Arg | Req. | Kind | |
|---|---|---|---|
| `outcome` |  | `hit` / `miss` | Force a critical hit or a critical miss. Default 'hit'. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | event modifier (mutates the in-flight event; only meaningful inside a `trigger`) |

The block form of ``effects.force_critical_hit`` / ``force_critical_miss``
folded into one: ``outcome: "hit"`` (default) sets ``critical_hit`` on the live
``ATTACK_ROLLED``/``ATTACK_DECLARED`` event, ``outcome: "miss"`` sets
``critical_miss`` — the flags ``CombatSystem`` reads after emitting. The caller's
``when`` guard decides the trigger (a nat 20, a paralysed target, …).

## `grant_action`

Grant a temporary AttackAction to the target (e.g. a concentration's attack).

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `name` | yes | a string | Name of the granted action. |
| `description` |  | a string | Flavour text for the action. |
| `bonus_to_hit` |  | an expression | Attack bonus for the granted action. |
| `range_ft` |  | a number | Reach in feet. Default 5. |
| `damage` |  | a list of objects: `type`, `formula` | Damage entries the granted action deals. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |

Builds the action from the block's ``name``/``bonus_to_hit``/``range_ft``/
``damage`` fields and hands the scope its revoke handle, so ending the lifetime
removes the action.

## `grant_advantage`

Flag advantage on the live roll event (``ATTACK_DECLARED`` / ``SAVING_THROW_DECLARED``). The block form of ``effects.grant_advantage`` — how blinded/invisible/paralysed/… grant advantage to or against a creature.

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | event modifier (mutates the in-flight event; only meaningful inside a `trigger`) |

## `grant_disadvantage`

Flag disadvantage on the live roll event (the mirror of :func:`grant_advantage`). Advantage and disadvantage are independent flags — both set, they cancel per 5e — so these are two blocks, not one parametrised.

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | event modifier (mutates the in-flight event; only meaningful inside a `trigger`) |

## `grant_temporary_hp`

Grant temporary hit points to the target (non-stacking, keeps the higher).

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `amount` | yes | an expression | Temporary hit points to grant (non-stacking). |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | `temp_hp_granted` |
| **Target** | acts on the current target, which must be exactly one entity |

## `healing`

Heal a target by an ``amount`` expression, or a ``formula`` + ``bonus``.

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |
| `amount` |  | an expression | Expression for a computed amount; takes precedence over formula. |
| `formula` |  | a dice formula | Dice formula rolled at cast time. |
| `bonus` |  | an expression | Added to the formula roll (a number or an expression). |

| | |
|---|---|
| **Reads context** | `damage_dealt` |
| **Writes context** | `healing_amount` |
| **Target** | acts on the current target, which must be exactly one entity |

## `lifetime`

Run ``then`` with a fresh scope open, then bind the scope by its kind.

| Arg | Req. | Kind | |
|---|---|---|---|
| `kind` |  | `concentration` / `rounds` / `instant` | What ends this lifetime. Default 'rounds'. |
| `concentration` |  | `true` / `false` | Sugar for kind='concentration'. |
| `duration_rounds` |  | an integer | Rounds until it expires; omitted = permanent. |
| `source` |  | a string | Label for the scope; defaults to the action's name. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | installs reactions (subscribes handlers to future events) |

## `modify_damage`

Scale the amounts on the live ``DAMAGE_INCOMING`` event in place.

| Arg | Req. | Kind | |
|---|---|---|---|
| `multiplier` | yes | an expression | Scale matching damage by this (0.5 resist, 0 immune, 2 vulnerable). |
| `damage_type` |  | a `DamageType` name | Only scale this damage type; omitted scales every entry. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | event modifier (mutates the in-flight event; only meaningful inside a `trigger`) |

The block form of ``effects.modify_damage``: multiply each entry of the
event's ``damage_list`` by ``multiplier`` (0.5 resistance, 0 immunity, 2.0
vulnerability). An optional ``damage_type`` name restricts the change to
matching entries; absent, every entry is scaled (the caller's ``when`` guard
having already decided the event qualifies).

## `refill_resources`

Reset the target's action resources to its stat-block defaults.

| Arg | Req. | Kind | |
|---|---|---|---|
| `target` |  | `self` / `current` | 'self' acts on the block's owner (caster/holder); 'current' acts on the current target slot (the default). |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |

## `saving_throw`

Roll the current target's saving throw; write save_roll/save_dc/save_success.

| Arg | Req. | Kind | |
|---|---|---|---|
| `attribute` | yes | `strength` / `dexterity` / `constitution` / `intelligence` / `wisdom` / `charisma` | Which ability the save is rolled against. |
| `dc` | yes | an integer (or `use_caster_dc`) | Flat DC, or 'use_caster_dc' for the caster's spell save DC. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | `save_roll`, `save_dc`, `save_success` |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | gate (a roll that later blocks are conditioned on) |

Emits SAVING_THROW_DECLARED so effects (e.g. Restrained → disadvantage on DEX
saves) can flag advantage/disadvantage before the roll. Mirrors the legacy
pipeline's saving-throw step.

## `trigger`

Subscribe this block's ``then`` to an event; scope it to the open lifetime.

| Arg | Req. | Kind | |
|---|---|---|---|
| `event` | yes | a `EventType` name | The combat event this rider fires on. |
| `when` |  | an expression | Guard evaluated at fire time against the event; the rider is skipped when falsy. |
| `target` |  | an expression | Expression naming the entity to act on when it fires (e.g. 'event.defender'). |
| `holder` |  | `caster` / `defender` | Whose rider this is — which entity 'entity' resolves to. |
| `priority` |  | an integer | Bus subscription priority; lower runs later. |
| `bindings` |  | an object of name → expression | Values captured once at install, read later as instance_fields.<name>. |

| | |
|---|---|
| **Reads context** | _(none)_ |
| **Writes context** | _(none)_ |
| **Target** | acts on the current target, which must be exactly one entity |
| **Category** | installs reactions (subscribes handlers to future events) |
