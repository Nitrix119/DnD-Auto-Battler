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

## 0. Current state — READ THIS FIRST (updated 2026-08-29)

> This section is the live snapshot; **§1 below is the older end-of-Phase-1 baseline** kept for history
> (do not read it as current). Phase 2 slices **4.1, 4.2, and 4.3b are complete**, and **§4.7 step 1
> (the live-event mutation contract) has landed** — all committed on branch `feat/spell-system-rework`.
> The full pure-event-flag modifier set has shipped (`modify_damage`, `force_critical`, `grant_advantage`,
> `grant_disadvantage`, `cancel`), and **the first production repoint has landed** — the event-modifier
> *global* rules (resistance/immunity/vulnerability, crits) now run on the block engine, not
> `BUILTIN_EFFECTS`. The suite is green (**718 tests**); `mypy src/` sits at a steady 44
> pre-existing errors (one is `src/spells/blocks/damage.py:82`, a benign register-signature variance, not
> from the new work); Black is pinned `==23.12.1` (see §9 in [CLAUDE.md](../CLAUDE.md) — do **not** run a
> newer Black on modified files; the dev env resolves Black 26.x).

### 0.1 What runs on the new engine now — **21 of 23 shipped spells**

- **Instantaneous single-target (9):** Acid Splash, Chill Touch, Cure Wounds, Fire Bolt, Guiding Bolt,
  Inflict Wounds, Poison Spray, Ray of Frost, Sacred Flame.
- **AoE (5)** + **multi-target (3):** Fireball, Burning Hands, Cone of Cold, Lightning Bolt, Thunderwave;
  Magic Missile, Scorching Ray, Eldritch Blast. (§4.1 — `for_each_target` iterator, shared `roll_once`.)
- **Persistent / concentration (4):** Shield of Faith, Longstrider, Vampiric Touch, Armor of Agathys.
  (§4.3b — `add_entity_effect` folded into a `lifetime{ … }` program.)
- **Still on legacy (2):** **Haste** (concentration duration on a *targeted ally* — the duration clock
  would tick on the wrong turn; needs the split-holder model) and **Charm Person** (uses
  `instance_fields`, not yet folded). Both route to the legacy `EffectPipeline` unchanged.

### 0.2 The new engine — `src/spells/` (18 registered blocks)

| File | What it holds |
|---|---|
| `block.py` | `Block(type, args, then)` immutable value + `from_dict`/`parse_program`. Nests only via `then`. |
| `contract.py` | `TargetArity{SINGLE,CASTER,SET}` + `BlockContract(reads, writes, target_arity, is_gate, installs_reactions, mutates_event)`. |
| `registry.py` | `BlockRegistry` + process-global `REGISTRY` (the block *vocabulary* — legitimately global). |
| `context.py` | `CastEnv` (frozen collaborators) + `Invocation` (per-run state holding an `env` ref, collaborators via property delegators; `.child()` spawns sub-runs — the one place they're threaded; `live_event` is the §4.7 handle onto the in-flight event), `InvocationResult`, `eval_context`, `seed_context`. |
| `runner.py` | `run_block`/`run_program`/`run_target` — pure dispatch + SPELL_HIT/DAMAGE_DEALT orchestration. Imported by blocks **and** the evaluator (breaks the old cycle). |
| `evaluator.py` | `resolve` (one target) / `resolve_program` (fan-out entry) — build invocations, call `runner`. |
| `lint.py` | `lint_program` — target-arity check (a SINGLE block under a set is a load-time error). |
| `adapter.py` | `to_program(effects, targeting_type, rule_lookup)` + `can_run_on_blocks(action, rule_lookup)` — transitional legacy→block shim + router capability check. |
| `fold.py` | `add_entity_effect` step (+ its entity-effect rule) → a `lifetime{ state + trigger }` program (§4.3b). Transitional. |
| `blocks/rolls.py` | `attack_roll`, `saving_throw` (gates). |
| `blocks/damage.py` | `damage` (consumes iterator-seeded `roll_once` shares). |
| `blocks/healing.py` | `healing`. |
| `blocks/state.py` | `apply_condition`, `add_modifier`, `grant_temporary_hp`, `add_resource`, `grant_action`. |
| `blocks/iterators.py` | `for_each_target` (fan-out over the target set; pre-rolls shared `roll_once`). |
| `blocks/lifetime.py` | `lifetime` (opens a scope, binds concentration/duration), `end_lifetime` (self-dispose). |
| `blocks/triggers.py` | `trigger` (subscribe a `then` to an event, holder-scoped, depth-guarded, priority −10; passes the live event to its firing). |
| `blocks/event_mod.py` | **event-modifier** blocks — mutate the in-flight event via `inv.live_event` (§4.7): `modify_damage` (resistance/immunity/vuln), `force_critical` (nat-20/1 crits), `grant_advantage`/`grant_disadvantage`/`cancel` (the condition library). |
| `global_rules.py` | `block_eligible` + `install_global_rules` — installs the event-modifier *global* rules as permanent priority-0 triggers at combat start (§4.7 step 3, first repoint). Reuses `fold.rule_to_trigger_blocks`. |
| *(model)* `src/models/lifetime.py` | `LifetimeScope` / `RevokeHandle` / `LifetimeKind` — pure ownership primitive with `rounds_remaining`/`tick()`. |

### 0.3 Key machinery & where parity lives

- **Fan-out (§4.1):** `resolve_program` runs a flat program once per target, or once on a root invocation
  when the top block consumes the set (`for_each_target`), which spawns a child per element and shares one
  `roll_once` roll. Arity is enforced by `lint.py`.
- **Lifetimes (§4.2):** every grant (`Entity.add_stat_modifier`/`add_condition`/`add_temporary_hp`/
  `grant_action`) returns an identity `RevokeHandle`; a `LifetimeScope` owns them and `dispose()`s in
  reverse. Concentration is a scope on the caster (`begin/end_concentration`, mirrored onto the legacy
  `concentrating_on`/`concentration_target` fields for consumers); a duration scope lives on the holder.
  The break rule (`force_concentration_check`) routes through `Entity.end_concentration`.
- **Duration clock (§4.3):** `LifetimeScope.rounds_remaining` + `Entity.tick_lifetimes()`, driven by the
  one `TURN_END` clock (`RuleEngine._tick_durations` calls it — a one-line hook, relocates in Phase 3).
- **Triggers (§4.3):** a `trigger` block captures its defining `inv`, subscribes at priority −10 (the
  legacy entity-effect slot), fires a fresh child invocation carrying the event data, guards with `when`,
  and — inside a `lifetime` — registers its *unsubscribe* as a scope-owned handle. A per-bus depth guard
  bounds re-entrancy. `run_target` flushes `DAMAGE_DEALT` before the first `installs_reactions` block so a
  rider doesn't fire on its own cast's damage.
- **The fold (§4.3b):** `SpellResolver` builds a `rule_lookup` from `rule_engine.effect_registry`;
  `fold.foldable` gates routing (defers un-resolvable rules, `instance_fields`, an unmapped action, or a
  concentration duration on a non-`on_caster` effect); `fold.to_lifetime_block` translates `on_apply` +
  the rule's reactive `triggers`/`effects` into one `lifetime{ … }`.
- **Router guard:** `SpellResolver._caster_has_injection_effect` — a cast stays on legacy **only** if the
  caster has a pipeline-*injecting* effect (Colossus Slayer's `InjectPipelineDamageStep`). All other
  active effects work on both engines.

### 0.4 Tests (the safety net)

`test_block_foundations`, `test_block_parity` (dual-run parity harness incl. AoE/multi-target fan-out),
`test_block_arity`, `test_lifetime_scope`, `test_entity_lifetimes`, `test_block_lifetime`,
`test_block_triggers`, `test_entity_effect_fold`. Folded spells are also covered by their original
behaviour tests (`test_spell_effects`, `test_spells::TestVampiricTouch`,
`test_armor_of_agathys`) — several were moved from asserting the legacy `active_effects` mechanism to
asserting the new-engine artifact (a lifetime scope), per CLAUDE.md §4 (test behaviour, not structure).

### 0.5 What is still legacy (alive by design through Phase 2)

`src/combat/effect_pipeline.py` (the legacy pipeline + `AttackResolver`'s compiled steps),
`src/rules/rule_engine.py` + `src/rules/effects.py::BUILTIN_EFFECTS`, `rules/entity_effects/*`,
`rules/global/*`, and the transitional `adapter.py` / `fold.py`. **Retiring `BUILTIN_EFFECTS` is its own
phase — see [§4.7](#47-phase-29--retiring-builtin_effects-the-core-rules-migration).**

### 0.6 Carried-forward debt / cleanups (all manageable — not blockers)

A review at the end of 4.3b (2026-08-29) flagged these. None is problematic debt of the kind the rewrite
set out to erase; they're ordinary cleanups to keep an eye on. Listed most-worth-doing first.

1. **Split `Invocation` into an immutable `CastEnv` + mutable per-run state — ✅ DONE (2026-08-29).**
   A frozen `CastEnv` now holds the constant collaborators (`action`/`event_bus`/`damage_processor`/
   `rule_engine`/`slot_level`); `Invocation` holds an `env` reference and exposes them as read-only
   property delegators, so every `inv.event_bus`/`inv.action` call site is unchanged and `.child()` reuses
   `self.env` by reference. Behaviour-preserving (green suite is the whole bar). This landed as the
   prerequisite refactor before §4.7's `live_event` handle, keeping that addition on the per-run state, not
   the environment.
2. **Keep `src/spells/fold.py` docstrings current.** It is the most intricate new module (target rebinding,
   holder-scoping, per-effect `when`, duration deferral, event-field detection) and the migration's Rosetta
   Stone. It is transitional (dies in Phase 3), so the *complexity* is fine, but its docstrings drift
   easily — one was already found stale. Treat its comments as load-bearing.
3. **Context-dependent `"caster"`/`"entity"` target semantics.** In a cast, `"caster"` is the spell caster;
   in a fired rider, the firing invocation's caster is the effect-*holder*, so `"caster"`/`entity` resolve
   to the holder. Correct and documented (`Invocation.child`, `fold._target`), but a real cognitive load —
   worth a second look if it ever surprises someone.
4. **`runner.run_target` now carries two ordering rules** — emit `SPELL_HIT` before the first non-gate
   block, and flush `DAMAGE_DEALT` before the first `installs_reactions` block. Both correct and minimal;
   if a third emission-ordering rule ever lands, extract the emission scheduling from the loop.
5. **A few migrated tests assert the new-engine *artifact*, not pure behaviour.** Moving Longstrider/AoA/VT
   tests off the legacy `active_effects` mechanism was right (CLAUDE.md §4), but a couple now assert
   `entity.lifetimes[...]`/`.disposed` — artifact-coupled, because the pure observable (e.g. "retaliation
   stops") is awkward to assert directly. Acceptable; note the coupling if those internals change.

---

## 1. Current state of the code (end of Phase 1 — historical baseline; see §0 for live status)

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

### 4.3 Inline trigger blocks + the entity-effect spell fold — ✅ **DONE** (2026-08-29)

The largest Phase-2 item, done in reviewable **sub-slices**, each independently green and committed.
(The `BUILTIN_EFFECTS` deletion once bundled here is promoted to [§4.7](#47-phase-29--retiring-builtin_effects-the-core-rules-migration).)

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
- **4.3b-2a — the trigger side, first fold ✅ DONE (2026-08-29).** `fold._triggers_from_rule` now
  translates a referenced rule's reactive `triggers`/`effects` into `trigger` blocks (one per event),
  guarded by the rule's `condition` as the `when`. **Holder-scoping** landed: a rider's `entity`/`caster`
  is the effect-**holder** (`inv.child(caster=holder, …)`; the fold sets `holder: caster|defender` from
  the step's `on_caster`), so a buff-an-ally rider fires relative to the ally, not the caster. Two more
  pieces: the `add_resource` state block (a transient per-turn grant — no revoke handle), and the trigger
  block now **subscribes at priority -10** (the legacy entity-effect slot, after the priority-0 refill),
  so a per-turn grant lands after the reset not before. A non-concentration `lifetime` is now held by the
  **target** (the holder), not the caster. **Longstrider** is folded onto the new engine at parity
  (movement +10 on its turn, after refill — proven end-to-end). Two Longstrider tests that asserted the
  legacy `active_effects` mechanism were rewritten to assert behaviour + the new-engine artifact (a
  lifetime on the target), per §4 (test behaviour, not structure). Still deferred by `foldable`: any rule
  with `duration_rounds` (Haste, Vampiric Touch — needs the §4.3c clock), a per-effect `when` (Armor of
  Agathys), `instance_fields` (Charm Person), or an unmapped action (`GrantAction`, `RemoveEffect`).
  Full suite green (675).
- **Duration clock ✅ DONE (2026-08-29).** `LifetimeScope` gained `rounds_remaining` + `tick()`;
  `Entity.tick_lifetimes()` counts down the entity's concentration scope + `lifetimes` on its turn,
  disposing the expired. The one `TURN_END` clock (`RuleEngine._tick_durations`) now calls it — a
  one-line hook (the tick *logic* lives in the block engine, so it relocates cleanly when the rule
  engine retires in Phase 3). The `lifetime` block takes `duration_rounds`; proven end-to-end through
  the real `TURN_END` clock (a rounds-duration buff revoked after N turns). **Parity note for relaxing
  the fold:** a *rounds* scope lives on the holder and ticks on the holder's turn (matches legacy); a
  *concentration* scope lives on the caster and ticks on the caster's turn — matching legacy only when
  the holder is the caster (`on_caster`). So Haste (concentration, target=defender, duration) stays
  deferred; Vampiric Touch (concentration, `on_caster`, duration) is unblocked once `grant_action` lands.
- **4.3b-2b — Vampiric Touch ✅ DONE (2026-08-29).** `grant_action` state block (builds the granted
  `AttackAction`, hands the scope its revoke handle so ending concentration removes it; `Entity.grant_action`
  now returns an identity handle). The fold maps `GrantAction` and passes the rule's `duration_rounds`
  into the lifetime block. A **reaction-ordering** fix landed with it: a new `installs_reactions` contract
  flag on `lifetime`/`trigger`; `run_target` flushes the pending `DAMAGE_DEALT` *before* the first such
  block, so a rider a cast installs does not fire on that cast's own damage — matching where the legacy
  pipeline emitted `DAMAGE_DEALT` (before the first `add_entity_effect`). **Vampiric Touch** now runs on
  the new engine at parity: instantaneous attack/damage/self-heal, a concentration lifetime (10 rounds,
  `on_caster` so the clock ticks correctly) holding the granted melee attack + a `DAMAGE_DEALT` heal
  rider; breaking concentration revokes the granted action via the scope handle. Four VT tests had their
  legacy-pipeline roll mocks retargeted to the block engine and their manual concentration-break switched
  to the real `end_concentration` teardown. Full suite green (681).
- **4.3b-2c — Armor of Agathys ✅ DONE (2026-08-29).** Two pieces: a **per-effect `when`** now folds as
  the effect block's fire-time `condition` (run_block evaluates it when the trigger fires); and a
  **self-dispose** path — `RemoveEffect` → an `end_lifetime` block that disposes the rider's own scope
  (the trigger passes its owning scope to the fired context via `Invocation.owning_scope`). The fold
  also learned **event-entity target rebinding**: a trigger whose effects hit an event entity (the
  attacker) sets its `target` to that expression so the effect addresses it. **Armor of Agathys** runs
  on the new engine at parity — grant 5 temp HP, retaliate 5 cold on a hit while temp HP remain, and end
  the effect (disposing the scope) once temp HP are gone. Its self-termination tests were moved off the
  legacy `active_effects` mechanism onto the new artifact (the lifetime scope's disposed state).
  Full suite green (682).
- **4.3b-2d — router guard narrowed ✅ DONE (2026-08-29).** `SpellResolver._caster_has_reactive_effects`
  → `_caster_has_injection_effect`: it now keeps a cast on legacy **only** when the caster has a
  pipeline-*injecting* effect (`InjectPipelineDamageStep`/`AddDamageToAttackHit` — Colossus Slayer), the
  one reactive mechanism the new engine can't reproduce. Every other active effect (advantage, resistance,
  retaliation) rides the EventBus identically on both engines and no longer forces legacy. Full suite
  green (683). Fully retiring even this guard waits on the entity-effect dispatch repoint below.

**4.3 status:** the entity-effect **spell fold is complete** — Shield of Faith, Longstrider, Vampiric
Touch, and Armor of Agathys run on the new engine at parity, and the reactive-effects guard is narrowed
to injection-only. The remaining item once filed under "4.3c — delete `BUILTIN_EFFECTS`" turned out to be
a **core-rules migration, not spell folding** (event-modifier effects behind the global concentration/
crit/resistance/refill rules; creature features applied via `RuleEngine.apply_effect`). It is promoted to
its own phase — **[§4.7 Phase 2.9](#47-phase-29--retiring-builtin_effects-the-core-rules-migration)** —
with the full challenge/solution write-up. Haste and Charm Person also stay on legacy until then
(reasons in §0.1 / §4.7).

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

### 4.7 Phase 2.9 — retiring `BUILTIN_EFFECTS` (the core-rules migration)

> **Promoted out of 4.3.** The persistent-effect *spell* fold is done (§4.3); what's left of the old
> "delete `BUILTIN_EFFECTS`" line item is a distinct, larger migration of **core combat rules** — worth
> its own phase and its own design pass. Nothing here blocks the spell rewrite's value; the legacy engine
> is meant to stay alive through Phase 2, and this is the bridge into Phase 3.

**Where the challenge comes from.** `BUILTIN_EFFECTS` (in `src/rules/effects.py`) is the handler table
the JSON *rule engine* dispatches through. Folding `add_entity_effect` spells retired the spell path into
it, but the table is still load-bearing for two things the spell adapter does **not** touch:

1. **Global rules use event-modifier effects that have no block equivalent.** Auditing every `rules/**`
   file, these actions are used **only** by `rules/global/*` — core combat mechanics, not spell content:

   | Action | Global rule it backs | Kind |
   |---|---|---|
   | `ForceConcentrationCheck` | concentration break on damage | reads event, forces a save, calls `end_concentration` |
   | `ForceCriticalHit` / `ForceCriticalMiss` | crit rules | mutates the in-flight `ATTACK_ROLLED` event |
   | `ModifyDamage` | damage resistance / immunity / vulnerability | multiplies the in-flight `DAMAGE_INCOMING` event |
   | `RefillResources` | per-turn action economy | mutates the entity on `TURN_START` |

   These are **event-modifier** effects (they change a *live* event mid-flight, or fire a bookkeeping
   side-effect), a category the block engine doesn't have — every block built so far
   (`damage`/`healing`/state/`grant_*`/`trigger`) is a *forward* effect that writes state or subscribes,
   not one that reaches into an event the resolver is mid-way through emitting. `ModifyDamage` /
   `GrantAdvantage` / `GrantDisadvantage` are also used by a few entity effects.

2. **The remaining entity effects are applied off the spell path.** The condition library
   (`rules/entity_effects/conditions/*` — charmed, blinded, petrified, …), poison, **Colossus Slayer**
   (injection), **Haste**, and **Charm Person** reach an entity via `RuleEngine.apply_effect` (creature
   features, save riders, `instance_fields`) — *not* a spell's `add_entity_effect`. So the fold/adapter
   can't reach them; they need the **dispatch itself repointed** at the block engine.

**Proposed solution (order matters — each step keeps the suite green):**

1. **Build an `event-modifier` block family.** *Pure-flag set shipped (2026-08-29).* A block category that
   operates on the *current* event via `Invocation.live_event` (the live-event handle). The pure event-flag
   modifiers are done and parity-gated: `modify_damage` ✅ (resistance/immunity/vuln), `force_critical` ✅
   (nat-20/1 crits), `grant_advantage` ✅ / `grant_disadvantage` ✅ / `cancel` ✅ (the whole condition
   library). They run inside a `trigger` (which fires with the event in scope) — so a global rule becomes a
   permanent (lifetime-less) trigger subscribed at load, and the block reaches back into the live event.
   `fold.py` has translators for all of these, so the condition library folds into `trigger{ grant_* /
   cancel }` (proven on the real `blinded` rule). **Still to build** — the two *side-effecting* members
   that fire *on* an event rather than mutating it: `force_concentration_check` (rolls a CON save, ends
   concentration) and `refill_resources` (resets an entity on `TURN_START`). These are forward effects,
   not event mutations, and land with their global rules' migration (step 3).
2. **Repoint `RuleEngine.apply_effect` at the block engine.** Instead of stashing an `EffectInstance` in
   `entity.active_effects`, translate the rule to a `lifetime{ trigger… }` program (reusing `fold`'s
   rule→trigger translation, now extended with the event-modifier actions) and install it via the block
   evaluator. This makes Colossus Slayer a trigger, kills `InjectPipelineDamageStep` (it becomes an
   `ATTACK_HIT` trigger dealing the bonus die), and lets the router guard (§4.3b-2d) be **removed
   entirely**. Fold Haste (needs the split-holder duration model: the duration scope on the ally, ticked
   on the ally's turn, with concentration still the caster's) and Charm Person (`instance_fields` → a
   trigger closure variable) here.
3. **Migrate the global rules** (`rules/global/*`) to the block form and subscribe them at combat start
   through the block engine rather than the rule engine.
4. **Delete `BUILTIN_EFFECTS`** and the now-unused rule-engine dispatch once nothing references them;
   move the `TURN_END` lifetime tick (§4.3, currently a one-line hook in `_tick_durations`) onto a
   standalone block-engine clock.

**Prerequisites / open decisions:** the live-event mutation contract (step 1) — **settled and proven**
(direct handle, see §5). The `Invocation` → `CastEnv` split ([§0.6.1](#06-carried-forward-debt--cleanups-all-manageable--not-blockers)) — **done**, landed before the handle. `remove_condition_type` and the condition
library's shape (are conditions plain state, or do some carry riders?) should be reviewed as they migrate.
Parity-gate every rule as it moves, the same way spells were.

**Definition of done:** `BUILTIN_EFFECTS`, `src/rules/effects.py`'s handler table, and the router's
injection guard are gone; every `rules/**` file and every creature feature runs through the block engine;
Haste and Charm Person are on the new engine. That clears the runway for **Phase 3** (delete the legacy
`EffectPipeline` + `adapter`/`fold` shims, fold `AttackResolver` in, migrate content to inline `program`s).

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
- **Live-event mutation contract** — *settled (2026-08-29), direct handle.* An event-modifier block,
  firing inside a `trigger` (which supplies the live event), writes **directly** onto
  `Invocation.live_event` — `.data` for multiplier/advantage/critical, `.cancelled` for cancel — mirroring
  the legacy handlers line-for-line, so parity is obvious. `live_event` is `None` outside a trigger, where
  such a block no-ops. Contract flag `mutates_event=True` marks the category. Proven on the smallest rule
  (damage resistance) — `modify_damage`, dual-run vs the legacy `damage_resistance_rule`
  (`tests/test_block_event_mod.py`). The remaining siblings (`grant_advantage`/`force_critical`/`cancel`/
  `force_concentration_check`/`refill_resources`) land as each global rule migrates.
- **Persistent-effect block name** — *settled*: the concept is the `lifetime` block wrapping state +
  `trigger` blocks (§4.2/§4.3), no separate "entity effect" vocabulary.
- **Summoning prerequisites** — enumerated in 4.4 / ENTITY_LIFECYCLE_DECISIONS; settle before 4.4.

---

## 6. The immediate next step

**4.1, 4.2, and 4.3 are done**; **§4.7 step 1 is substantially landed** (the pure-event-flag modifier set,
parity-gated and fold-wired); and **the first production repoint (§4.7 step 3, partial) is in** — the
event-modifier *global* rules run on the block engine (`src/spells/global_rules.py`; the web handler
installs them and disables exactly those on the rule engine, so nothing double-applies). The `Invocation`
→ `CastEnv` split (§0.6.1) shipped as the prerequisite. **21 of 23 shipped spells run on the new engine.**
Remaining in **[§4.7](#47-phase-29--retiring-builtin_effects-the-core-rules-migration)**:

1. **Repoint `RuleEngine.apply_effect` at the block engine** (§4.7 step 2) — **the next major slice; a
   production-behaviour change worth its own planning pass.** Translate an entity effect to a
   `lifetime{ trigger… }` program and install it via the evaluator, reusing `fold.rule_to_trigger_blocks`.
   This brings the **condition library** onto the new engine (its blocks + fold translators already exist),
   kills `InjectPipelineDamageStep` (Colossus Slayer → an `ATTACK_HIT` trigger dealing the bonus die) and
   lets the router's injection guard (§4.3b-2d) be removed; fold Haste (split-holder duration) and Charm
   Person (`instance_fields` → a trigger closure variable) here. Apply the same **disable-the-legacy-path**
   discipline the global-rule repoint used to avoid double-application. Per the user (2026-08-30): priority
   0 + subscription order is fine for the common case; force order only where something strictly must be
   first/last.
2. **Finish the global rules** — build the two *side-effecting* globals as forward blocks fired by a
   permanent trigger: `force_concentration_check` (rolls a CON save, ends concentration) and
   `refill_resources` (resets an entity on `TURN_START`), then route `concentration` / `action_economy_refill`
   through `install_global_rules` too. Then **delete `BUILTIN_EFFECTS`** and move the `TURN_END` tick to a
   standalone clock.

Parity-gate every rule as it moves, the same way spells were.

**Carried notes from the global-rule repoint (2026-08-30):** (a) a global-rule install invocation has no
caster/target (`None`, with a `type: ignore`) — its event-modifier effects reach the live event, not an
entity; if `Invocation.caster`/`target` ever want to be `Optional`, this is why. (b) `global_rules.py` (a
permanent module) imports `fold.rule_to_trigger_blocks` from the *transitional* `fold.py`; when `fold.py`
is deleted in Phase 3 that translation needs a new home (or global rules become native `program`s). (c)
double-application is prevented only by the caller disabling handled rules on the rule engine — currently
only the web handler loads global rules, so it is contained, but any new global-rule loader must do the
same.

_Reference — the 4.3 approach that this builds on: a `trigger` block captures its defining invocation and
subscribes a holder-scoped, depth-guarded handler at priority −10; a `lifetime` scope owns each grant's
and subscription's revoke handle; `fold.py` translates `add_entity_effect` + its rule into one
`lifetime{ state + trigger }` program; the `TURN_END` clock ticks `LifetimeScope.rounds_remaining`._

_See also: [SPELL_SYSTEM_BUILD_PLAN.md](SPELL_SYSTEM_BUILD_PLAN.md) (Phase-1 architecture + interface
decisions), [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) (design rationale), and the two decision
docs. Memories [[damage-typing-per-entry-resistance]] and [[upcasting-framework-pending]] hold the two
deferred design threads._
