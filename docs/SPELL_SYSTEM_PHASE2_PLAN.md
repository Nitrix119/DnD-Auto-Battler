# Spell System — Phase 2+ Plan & Handoff

> **Purpose: a clean handoff.** Phase 1 of the block-system rewrite is **done**. This document is the
> authoritative forward plan for **Phase 2 and beyond**, written so a fresh session can take over with
> only this file and the code. It records (1) exactly where the code sits now, (2) every deviation
> from the original plan and every new finding, and (3) the remaining work in order.
>
> It **supersedes [SPELL_SYSTEM_BUILD_PLAN.md](SPELL_SYSTEM_BUILD_PLAN.md) §4–§5** for Phase 2+. That
> doc remains the record of the Phase-1 architecture and its interface decisions (block contract,
> arity type-checking, module tree) — still all in force. The deeper design rationale lives in
> [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md); ratified decisions in
> [SPELL_SYSTEM_DECISIONS.md](SPELL_SYSTEM_DECISIONS.md) and
> [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md).

---

## 1. Current state of the code (end of Phase 1)

### 1.1 The new engine — `src/spells/`

A clean-slate package; the legacy `src/combat/effect_pipeline.py` is untouched and frozen.

| File | What it holds |
|---|---|
| `block.py` | `Block(type, args, then)` immutable value + `Block.from_dict` (parses `then` recursively) + `parse_program`. Programs use the `"block"` key and nest **only** via `then`. |
| `contract.py` | `TargetArity{SINGLE, CASTER, SET}` and `BlockContract(reads, writes, target_arity, is_gate)`. |
| `registry.py` | `BlockRegistry` (register/get/is_registered/types) + process-global `REGISTRY`. One catalogue, dict dispatch — no `if/elif`. |
| `context.py` | `seed_context(slot_level)`, `Invocation` (per-run mutable state), `InvocationResult` (**field-compatible with the legacy `PipelineResult`**), `eval_context(inv)` (sandboxed expression namespace, reuses `src.rules.expressions`). |
| `evaluator.py` | `resolve(...)` (top-level: seeds, event orchestration, returns `InvocationResult`), `run_program`/`run_block` (pure dispatch, honour the `condition` guard, recurse into `then`). |
| `blocks/rolls.py` | `attack_roll`, `saving_throw` (both `is_gate=True`). |
| `blocks/damage.py` | `damage` — superset of `damage`/`DealDamage` (`requires_hit`, slot `scaling`, crit-double, `save_result`, resistance routing). **No `roll_once`** (see deviations). |
| `blocks/healing.py` | `healing` — superset of `healing`/`HealTarget` (`amount` expr or `formula`+`bonus`, caster/defender). |
| `blocks/state.py` | `apply_condition`, `add_modifier`, `grant_temporary_hp` — done **directly** (no rule-engine/stub-event bridge). |
| `adapter.py` | `to_program(effects)` (legacy step-dicts → block program; transitional) + `can_run_on_blocks(action)` (router capability check). |

**Blocks ported (7):** `attack_roll`, `saving_throw`, `damage`, `healing`, `apply_condition`,
`add_modifier`, `grant_temporary_hp`.

### 1.2 Integration & routing

- **`SpellResolver.resolve`** now routes: if `can_run_on_blocks(action)` **and**
  `not _caster_has_reactive_effects(caster)` → new engine (`_resolve_via_blocks`, one `Invocation`
  per defender); else the legacy `EffectPipeline`. `_format_result` is shared by both paths.
- `can_run_on_blocks`: `targeting_type == SINGLE_TARGET`, every step type is a registered block, and
  no step has `roll_once`.
- **`AttackResolver` is untouched** — weapon attacks still run on the legacy pipeline.
- **In production right now:** 9 shipped single-target spells run on the new engine
  (Acid Splash, Chill Touch, Cure Wounds, Fire Bolt, Guiding Bolt, Inflict Wounds, Poison Spray,
  Ray of Frost, Sacred Flame). The other 14 (AoE, multi-target, entity-effect, concentration) route
  to legacy.

### 1.3 Tests

- `tests/test_block_foundations.py` — Block/contract/registry unit tests.
- `tests/test_block_parity.py` — the **parity harness**: dual-runs a spell on both engines under one
  seed on identical fresh entities and asserts equal result fields + caster/target HP. Covers
  hand-authored spells (Fire Bolt, saves, healing, state blocks) **and** auto-discovers every shipped
  spell the router accepts and parity-tests it. This harness is the gate for all future block ports.
- Full suite green (632 at handoff). Legacy behaviour unchanged.

### 1.4 What is *not* built yet (the Phase-2+ surface)

Iterators / AoE fold · lifetime scopes · trigger blocks · `add_entity_effect`'s replacement ·
`BUILTIN_EFFECTS` deletion · entity lifecycle/summoning · the upcasting framework · meta/`cast_spell` ·
`AttackResolver`→blocks · content migration to `program` · legacy deletion.

---

## 2. Deviations from the original plan & new findings

Read this before planning any Phase-2 work — several original assumptions changed.

1. **`add_entity_effect` is retired, not ported (moved to Phase 2).** It is the seam to the entity-effect
   `Rule` subsystem and only makes sense to fold once **lifetime scopes (4.2)** and **trigger blocks
   (4.3)** exist. It was deliberately *not* ported in Phase 1 to avoid a throwaway bridge.
2. **`BUILTIN_EFFECTS` deletion moved from Phase 1 to Phase 2 (§4.3).** It is inseparable from the
   entity-effect fold: entity-effect rules run in an event-driven model that only unifies with blocks
   once a trigger can synthesise an `Invocation` from an event. The legacy engine + rule engine +
   `BUILTIN_EFFECTS` + `rules/entity_effects/*` therefore **stay alive through Phase 2** and are
   deleted in **Phase 3**.
3. **Full-corpus parity is a Phase-2 *completion* milestone, not a Phase-1 one.** Phase 1's target was
   the instantaneous single-target subset; the rest reach parity as their Phase-2 blocks land.
4. **The router has a reactive-effects guard (new finding).** Routing single-target *attack* spells to
   the new engine broke `InjectPipelineDamageStep` (Colossus Slayer) — the one legacy reactive
   mechanism that mutates the running action's step list on `ATTACK_HIT`. The new engine intentionally
   does not implement it (it becomes a trigger block in 4.3). Fix: casts by a caster with **any active
   entity effect** stay on legacy (`SpellResolver._caster_has_reactive_effects`). Conservative but
   parity-safe. **This guard relaxes/dies once triggers (4.3) exist.**
5. **`roll_once` is deliberately absent from the `damage` block.** It shares one rolled total across an
   AoE's targets — a property of *fan-out*, so it belongs to the **iterator** (4.1), not `damage`.
   The new engine will handle `roll_once` when iterators land; until then, `can_run_on_blocks` refuses
   any spell using it.
6. **Multi-type damage is a known debt (new finding, user-raised).** One `damage` block = one type;
   multi-type (a smite: slashing+fire+radiant) is several blocks, and per-type resistance works *only*
   because each is a single-element `apply_damage`. The global resistance rules read `damage_list[0]`
   with an unfiltered multiplier — a true multi-type bundle would resist wrong. Plan: multi-component
   `damage` block + per-entry resistance. **Fix shape needs a short deliberation first** (see
   [[damage-typing-per-entry-resistance]] and §5). Do it when finishing the damage block; parity-gate
   it (touches the rule layer).
7. **Upcasting is additive-dice only.** Stage-2 `scaling` (`{per_slot_above, add_dice}`) covers dice
   growth. Count/multiplicative scaling (Magic Missile +1 dart/slot; *Summon Woodland Beings* ×2/×3)
   is **deferred to a dedicated upcasting-framework design** the user has an idea for (see
   [[upcasting-framework-pending]] and §4.5). Do not build bespoke count-scaling before that.
8. **Arity enforcement is defined but dormant.** `TargetArity` is on every block contract, but nothing
   checks it yet — fan-out still lives in `SpellResolver`, so the evaluator only ever sees a single
   current target. Arity **turns on in 4.1** when fan-out moves into iterators.
9. **`AttackResolver`→blocks (design D4) is not done.** Weapon attacks still compile to
   `pipeline_effects` and run on the legacy pipeline. Fold this in Phase 2/3 to keep the single
   weapon/spell path on the new engine.

---

## 3. Phase 2 — capabilities as blocks on the evaluator

Each is a block family on the Phase-1 substrate; ordered so each is independently shippable and
parity-gated. **Re-plan checkpoints after 4.1 and after 4.2.**

### 4.1 Targeting sets + iterator blocks (and fold AoE + multi_target in) — ✅ **DONE** (2026-08-29)

**Goal:** move all fan-out out of `SpellResolver` into the program, as iterator blocks, and turn on
arity enforcement. This is the most self-contained Phase-2 step and immediately expands new-engine
coverage (Magic Missile, Scorching Ray, Eldritch Blast, and every AoE spell come home).

**What shipped (and where it deviated from the sketch below):**

- **`for_each_target` iterator** (`src/spells/blocks/iterators.py`), `target_arity=SET`. It reads the
  target set from a **root `Invocation`** (`targets`) and runs its `then` body once per element via a
  fresh per-target child invocation, collecting one `InvocationResult` each into `root.results`. The
  single per-target execution primitive (SPELL_HIT/DAMAGE_DEALT orchestration) is factored into
  `evaluator._run_one_target`, shared by the flat single-target path and each iterator element — the
  seam that keeps both paths at parity.
- **`roll_once` is the iterator's property**, as planned: the iterator pre-rolls each `roll_once`
  damage block in its `then` body once (with slot scaling) and seeds every child via
  `context["_shared_rolls"]`, keyed by `id(block)`. The `damage` block only **consumes** a seeded
  total (no re-roll, no crit-double) — the one interpretation of the sketch: the flag stays as data on
  the damage JSON, but producing/sharing lives in the iterator, not the block.
- **Arity linter** (`src/spells/lint.py`, `ProgramArityError`): SET consumes a set and makes its
  `then` single; a SINGLE block under set cardinality is the category error; CASTER is valid either
  way. Run as a **runtime assertion** at the top of `evaluator.resolve_program` (deriving cardinality
  from whether the program has a top-level set-consumer). *Deviation:* not yet a load-time gate at
  spell-load — that lands when content migrates to `program` form (Phase 3); today `resolve_program`
  is the enforcement point and the linter is unit-tested directly.
- **Adapter** (`adapter.to_program(effects, targeting_type)`) wraps AoE/multi_target legacy blocks in
  an implicit `for_each_target`; single_target stays flat. `can_run_on_blocks` now accepts
  `SINGLE_TARGET` + `AOE` + `MULTI_TARGET` and no longer refuses `roll_once`.
- **Wiring:** `SpellResolver._resolve_via_blocks` calls the new `evaluator.resolve_program` **once**
  with the whole defender set (fan-out gone from the block path); the **legacy** path (per-defender
  loop + `_preroll_pipeline_damage`) is untouched, and the reactive-effects guard still holds.
- **Not moved:** AoE **geometry** (deriving the defender set from shape/origin) stays in
  `CombatSystem.resolve_spell` — only iteration + shared-roll moved into the block, as the sketch
  predicted. `for_each_beam` and richer targeting sets (`chosen(n)`, `all_in_area`, `derived`) were
  **not** built — `for_each_target` over the resolver-supplied set covers the whole current corpus;
  add the others when a spell needs them.
- **In production now:** the 9 single-target spells from Phase 1 **plus** 5 AoE (Fireball, Burning
  Hands, Cone of Cold, Lightning Bolt, Thunderwave) and 3 multi_target (Magic Missile, Scorching Ray,
  Eldritch Blast) — 17 of 23 shipped spells on the new engine. The remaining 6 are the
  entity-effect/concentration spells (blocked on 4.2/4.3).
- **Tests:** `tests/test_block_arity.py` (linter) + new fan-out parity in `tests/test_block_parity.py`
  (multi-defender dual-run vs the legacy `SpellResolver` fan-out; shared-roll behaviour proof; runtime
  arity assertion) + the set-targeted corpus auto-parity test. Three Fireball integration tests in
  `test_save_outcomes.py` had their `roll_formula` mock moved from `spell_resolver` to the iterator
  (the pre-roll relocated). Full suite green (643).

**Original sketch (kept for the record):**

- A **targeting block** yields a set (`self`, `defender`, `chosen(n)`, `all_in_area`, `derived`);
  iterator blocks (`for_each_target`, `for_each_beam`) run a `then` sub-program per element with its
  own child `Invocation` (rebinding the current target). `run_program`/`run_block` already recurse
  into `then` — wire child-context creation in.
- **`roll_once`** becomes an iterator property: roll the shared total once, seed each element's
  invocation. This is where the `damage` block's deferred `roll_once` need is met — *not* by adding
  it to `damage`.
- **Fold AoE**: `SpellResolver`/`CombatSystem` currently derive the AoE target set from geometry and
  pre-roll `roll_once`. Decide what moves into the iterator vs stays as set-derivation in the resolver
  (geometry likely stays; iteration + shared-roll move into the block). Re-express stage-3
  `multi_target` as an iterator too.
- **Turn on arity**: a `single`-arity block reached while the current target is a set is a **static
  load-time error** + runtime assertion (build plan §3.6 D1). The linter seeds cardinality from
  `targeting_type` and iterators reduce set→single. The **legacy adapter** must now wrap a set-targeted
  legacy spell's blocks in an implicit `for_each_target` so the rule holds uniformly (not built yet —
  it's a 4.1 task; today the router simply keeps set-targeted spells on legacy).
- **Parity**: dual-run Fireball (AoE `roll_once` half-damage), Magic Missile, Scorching Ray against
  the legacy engine; extend `can_run_on_blocks` to accept AoE/multi_target once green.

### 4.2 Lifetime scopes + grant handles — ✅ **DONE** (2026-08-29)

**What shipped (and the one scoping call):**

- **`LifetimeScope` + `RevokeHandle`** ([src/models/lifetime.py](../src/models/lifetime.py)) — a scope
  owns an ordered list of revoke closures; `dispose()` runs them in reverse, once (idempotent); a grant
  made after dispose is revoked immediately. `LifetimeKind` = `CONCENTRATION`/`ROUNDS`/`INSTANT`. It's a
  **pure domain primitive** (placed in `models`, not `spells`) so `Entity` holds it with no
  `models → spells` dependency.
- **`Entity` grants return identity-based revoke handles** — `add_stat_modifier` / `add_condition` /
  `add_temporary_hp` now return a `RevokeHandle` that removes *exactly* that grant by object identity
  (fixes the string-tag over-remove when two effects share a name). Return values are backward-compatible
  (old callers ignore them). `Entity` gained `concentration_scope` + a `lifetimes` list, and
  `begin_concentration` / `end_concentration` / `_dispose_current_concentration`: concentration is a
  first-class lifetime; starting a new one disposes the prior atomically. The legacy string fields
  (`concentrating_on`/`concentration_target`) still work — `_dispose_current_concentration` tears down
  whichever is present, so legacy spells are unchanged (parity).
- **`lifetime` wrapper block** ([blocks/lifetime.py](../src/spells/blocks/lifetime.py)) — opens a fresh
  scope, makes it `Invocation.active_scope` while its `then` runs (grants register their handles into
  it via `blocks/state.py`'s `_own`), then binds it: `kind: concentration` → the caster's concentration;
  otherwise → the caster's `lifetimes`. Grants **outside** a lifetime stay instantaneous/permanent.
- **One minimal legacy touch:** the global concentration-break rule's `force_concentration_check` now
  calls `Entity.end_concentration()` (which disposes a scope *and* cleans a legacy string tag) instead
  of inlining the string cleanup — so a new-engine scoped concentration breaks correctly on a failed
  CON save. Behaviour-preserving for legacy spells.
- **E12 resolved by construction:** scopes are per-battle state living on `Entity`, never in the
  process-global `REGISTRY` (which stays code — the block vocabulary). No shared mutable process state.

**The scoping call (important for whoever does 4.3):** every shipped persistent spell uses
`add_entity_effect`, whose fold into blocks is **4.3's** job, so 4.2 could **not** route a shipped JSON
spell onto the new engine without doing 4.3's work. 4.2 therefore delivers the *mechanism*, proven
**end-to-end through the real evaluator + `Entity` + the actual global concentration rule** (not just
unit tests): [tests/test_block_lifetime.py](../tests/test_block_lifetime.py) runs a native "Shield of
Faith" program (`lifetime{concentration}{ add_modifier ac+2 }`), then drives real damage through
`DamageProcessor` + the concentration rule and asserts the failed CON save disposes the scope and
revokes the buff — plus atomic replacement and the outside-a-lifetime permanence case. **Shield of Faith
and the other persistent spells are migrated onto the engine in 4.3**, where `add_entity_effect` folds
in and the adapter learns to emit `lifetime{…}` programs.

- **Tests:** `tests/test_lifetime_scope.py` (scope/handle unit), `tests/test_entity_lifetimes.py` (grant
  handles + concentration on `Entity`), `tests/test_block_lifetime.py` (the end-to-end proof). Full
  suite green (662).
- **Deferred (not needed yet, no test demands them):** a **duration clock** — nothing ticks `ROUNDS`
  scopes down (matching the pre-existing engine, which never expired durations either); a multi-target
  concentration (one scope for a whole AoE) — `for_each_target` gives each element its own invocation,
  so a concentration inside it would bind per-element; revisit when a spell needs it.

**Original sketch (kept for the record):**

- A **lifetime-scope** object *owns* revoke handles; every grant (modifier, condition, temp HP,
  granted action, later a rider subscription, later a summoned creature) returns a revoke handle it
  owns; teardown walks handles in reverse. Retires the `source_effect`/`effect_name` string-tag
  cleanup (design §6.3/§6.5). Concentration is one lifetime kind; replacing concentration disposes the
  old scope atomically.
- Touches `Entity` (where grants live today). Keep changes minimal and behind parity for the spells
  that currently use durations/concentration.
- **Resolve per-session registry isolation (E12) here** — lifetimes make shared process state bite.
  Note: the block *type* catalogue (`REGISTRY`) is legitimately global (it's code); the concern is
  per-battle **content/state**, not the vocabulary.

### 4.3 Inline trigger blocks — *and the entity-effect fold / `BUILTIN_EFFECTS` deletion*

This is the largest Phase-2 item and where the second vocabulary finally dies. Being done in
reviewable **sub-slices**, each independently green and committed:

- **4.3a — trigger-block foundation ✅ DONE (2026-08-29).** The `trigger` block
  ([blocks/triggers.py](../src/spells/blocks/triggers.py)): args `event` (an `EventType` name), a
  firing guard `when` (a **distinct key from the evaluator's install-time `condition`** — the collision
  was the first bug: `run_block` was evaluating a trigger's guard at install time against a context with
  no event, so the trigger never subscribed), an optional `target` expression, and a `then` body. On
  run it captures the defining caster + collaborators, subscribes a handler to the event, and — if a
  `lifetime` scope is open — registers the **unsubscribe as a revoke handle the scope owns** (a
  subscription is just another grant; concentration/duration teardown unsubscribes the rider for free).
  On fire it builds a **fresh `Invocation` carrying the event's data** (`Invocation.event_data`, exposed
  as `event.<field>` and `entity`/`caster` via `eval_context`), checks `when`, binds `target`, and runs
  `then`. A module-level **depth guard** (`_MAX_TRIGGER_DEPTH`) bounds re-entrant firings.
  Proven in [tests/test_block_triggers.py](../tests/test_block_triggers.py): a Vampiric-Touch-style heal
  rider fires on `DAMAGE_DEALT`, is gated by `when`, and **unsubscribes when its concentration lifetime
  is disposed**; the depth guard blocks at the cap. Full suite green (667). *No content migrated and
  `BUILTIN_EFFECTS` untouched yet — that's 4.3b/4.3c.*
- **4.3b-1 — the entity-effect fold, state-only case ✅ DONE (2026-08-29).** New
  [src/spells/fold.py](../src/spells/fold.py) translates a foldable `add_entity_effect` step into a
  `lifetime{ … }` block: `on_apply` grants → state blocks (via an `_ACTION_TO_BLOCK` map:
  AddModifier/ApplyCondition/GrantTemporaryHP/HealTarget/DealDamage), `concentration`/duration → the
  lifetime kind. The adapter's `to_program`/`can_run_on_blocks` take a `rule_lookup` (`name -> Rule`)
  so foldability can inspect the referenced entity-effect rule; `SpellResolver` supplies it from
  `rule_engine.effect_registry`. **Shield of Faith** now runs on the new engine (its rule declares no
  triggers). Conservative boundary — a step is **not** foldable if the rule can't be resolved (can't
  prove there are no reactive triggers to drop), or the rule declares any trigger, or it uses
  `instance_fields`, or an `on_apply` action has no block translator — so Vampiric Touch, Longstrider,
  Haste, Armor of Agathys, Charm Person all stay on legacy for now. `Entity.begin_concentration` now
  mirrors the scope onto the legacy `concentrating_on`/`concentration_target` display fields (the scope
  stays authoritative for teardown), so consumers reading them are consistent. Tests:
  [tests/test_entity_effect_fold.py](../tests/test_entity_effect_fold.py) (routing boundary, fold shape,
  end-to-end cast + concentration break through the real router). Full suite green (673).
- **4.3b-2 — the trigger side of the fold (next).** Translate the referenced rule's reactive
  `triggers`/`effects` into `trigger` blocks (holder-scoped: the rider's `entity` is the effect-holder,
  not necessarily the caster — matters for buff-an-ally). Add the missing state blocks (`add_resource`
  for Haste/Longstrider, `grant_action` for Vampiric Touch) and a self-dispose path for Armor of
  Agathys. Relax the router's reactive-effects guard as triggers subsume `InjectPipelineDamageStep`.
  Parity-gate each migrated spell.
- **4.3c — repoint dispatch + delete `BUILTIN_EFFECTS`.** Repoint the rule engine's effect dispatch at
  the block registry, migrate `rules/entity_effects/*`, delete `BUILTIN_EFFECTS`, and name the
  persistent-effect concept. The duration clock (`RuleEngine._tick_durations` on `TURN_END`) must be
  taught to dispose `ROUNDS` lifetime scopes so migrated durations still expire.

**Original sketch (kept for the record):**

- **Trigger blocks** (`on_hit`, `on_turn`, `on_damage`, …) register a `then` sub-program against an
  event, scoped to a lifetime (4.2), running in a **fresh per-invocation context** (design §6.1) via a
  **bounded work queue** with a depth guard for re-entrant events (design §6.4).
- **Replace `add_entity_effect`** (retired, not ported): a persistent effect becomes a lifetime scope
  wrapping state blocks + trigger blocks, authored **inline in one spell file**. Repoint the rule
  engine's effect dispatch at the block registry (a trigger firing synthesises an `Invocation` from
  its event), migrate `rules/entity_effects/*` (or make them a shared library), and **delete
  `BUILTIN_EFFECTS`**. **Name the persistent-effect concept here**, with the lifetime-scope shape — the
  old "entity effect" name is retired, not carried forward.
- **Relax the router's reactive-effects guard** (deviation #4) as triggers subsume injection etc.
- **Headline parity result:** Vampiric Touch and Armor of Agathys become **single files** — the split
  the whole rewrite exists to erase.

### 4.4 Entity lifecycle / summoning

- The `entity_lifecycle` family — design §6.12, decisions in
  [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md). Depends on 4.2 + 4.3. Prerequisites
  first: **seed-stable entity IDs**, **pointer-safe initiative insert/remove + roll-off tiebreak**, a
  **"downed but present" state** distinct from "removed", and an **`ENTITY_DIES` + dismissal event**
  pair. Positioned effect-emitters (Moonbeam, Spiritual Weapon) are the sibling mechanism (ride 4.1 +
  4.2, no roster machinery).

### 4.5 Upcasting framework

- The count/multiplicative scaling additive-dice `scaling` doesn't cover (projectile counts, summon
  counts, durations, target numbers). **Design pending a user idea** ([[upcasting-framework-pending]]).
  Unify all count/scaling here; slots in once iterators (4.1) and summoning (4.4) exist to scale.

### 4.6 Meta / `cast_spell` blocks

- A block that invokes the resolver on another spell (Wish, Contingency) + copy/counter. Built last —
  the proof the "add one block" model absorbs the exotic tail (design §5.5, §6.11).

---

## 4. Phase 3 — migration & retirement

1. Migrate the 22 spells + 6 entity effects to single-file `program`s, each parity-checked as it moves.
2. Fold `AttackResolver` into blocks (deviation #9) so weapons and spells share the one path on the new
   engine.
3. **Delete** the legacy `EffectPipeline`, the `adapter.py` shim, `BUILTIN_EFFECTS` (if not already),
   and the legacy route in `SpellResolver`.
4. Complete the rename: `effects` → `program`, `step` → `block`. "Spell" stays user-facing.

---

## 5. Invariants & open decisions carried forward

**Invariants (never regress — all currently tested / parity-gated):** one resolution path for weapons
and spells · `roll_once` + `save_result` + crit-doubling + resistance routing · determinism under
`dice.seed_rng` (incl. deferred triggers — needs a documented ordering + replay test) · the
AST-whitelist expression sandbox · EventBus as the substrate for cross-cutting behaviour · immutable
`StatBlock` / mutable `Entity`.

**Open design decisions that gate their items (settle before building):**
- **Multi-component damage / per-entry resistance** — fix shape (rewritten global rule vs. resistance
  in `DamageProcessor`; how crit/save-half/scaling apply across a bundle; block field shape). Gates
  finishing the `damage` block. [[damage-typing-per-entry-resistance]]
- **Upcasting framework** — count/multiplicative scaling shape. Gates 4.5. [[upcasting-framework-pending]]
- **Persistent-effect block name** — decided in 4.3 with the lifetime-scope shape.
- **Summoning prerequisites** — enumerated in 4.4 / ENTITY_LIFECYCLE_DECISIONS; settle before 4.4.

---

## 6. The immediate next step

**4.1 and 4.2 are done** (see the ✅ blocks in §4.1 / §4.2). **Next is 4.3 — inline trigger blocks +
the entity-effect fold + `BUILTIN_EFFECTS` deletion**, the largest Phase-2 item, where the second
vocabulary finally dies and persistent spells become single files on the new engine.

4.3 stands directly on 4.2's substrate. Re-derive its shape from the code as it now stands:

- **Trigger blocks** (`on_hit`, `on_turn`, `on_damage`, …) register their `then` sub-program against an
  EventBus event, **scoped to a lifetime** (the `lifetime` block from 4.2 — a trigger subscription is
  just another grant whose revoke handle the scope owns, so concentration/duration teardown
  unsubscribes it for free). They run in a **fresh per-invocation context** synthesised from the event,
  via a **bounded work queue** with a depth guard for re-entrant events (design §6.1/§6.4).
- **Replace `add_entity_effect`** (retired, not ported): a persistent effect becomes a `lifetime` scope
  wrapping state blocks **+ trigger blocks**, authored inline in one spell file. Teach the adapter to
  translate the legacy `add_entity_effect` + `on_apply` + entity-effect-rule shape into a `lifetime{…}`
  program (extending 4.2's `lifetime` block), repoint the rule engine's effect dispatch at the block
  registry, migrate `rules/entity_effects/*`, and delete `BUILTIN_EFFECTS`.
- **Relax the router's reactive-effects guard** (deviation #4) as triggers subsume `InjectPipelineDamageStep`.
- **Headline parity result:** Vampiric Touch and Armor of Agathys become single files; Shield of Faith /
  Longstrider / Haste / Charm Person come onto the new engine (Shield of Faith's `lifetime{…}` program
  already exists and is tested — it just needs routing from JSON).
- **Name the persistent-effect concept here**, with the lifetime-scope shape (the open decision in §5).

_The 4.2 approach, for reference: a pure `LifetimeScope`/`RevokeHandle` in `models`; `Entity` grants
return identity handles and hold a first-class `concentration_scope`; a `lifetime` wrapper block whose
`then` grants register into the open scope; the concentration-break rule routed through
`Entity.end_concentration`; proven end-to-end via a native Shield of Faith program + real damage._

_See also: [SPELL_SYSTEM_BUILD_PLAN.md](SPELL_SYSTEM_BUILD_PLAN.md) (Phase-1 architecture + interface
decisions), [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) (design rationale), and the two decision
docs. Memories [[damage-typing-per-entry-resistance]] and [[upcasting-framework-pending]] hold the two
deferred design threads._
