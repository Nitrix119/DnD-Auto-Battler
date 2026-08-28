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

### 4.1 Targeting sets + iterator blocks (and fold AoE + multi_target in) — *do first*

**Goal:** move all fan-out out of `SpellResolver` into the program, as iterator blocks, and turn on
arity enforcement. This is the most self-contained Phase-2 step and immediately expands new-engine
coverage (Magic Missile, Scorching Ray, Eldritch Blast, and every AoE spell come home).

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

### 4.2 Lifetime scopes + grant handles — *do second*

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

This is the largest Phase-2 item and where the second vocabulary finally dies.

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

**Start 4.1 (iterators + AoE/multi_target fold + arity enforcement).** It is the most self-contained
Phase-2 slice, needs neither lifetimes nor triggers, and immediately brings the AoE and multi-target
corpus onto the new engine behind the parity harness. Concretely: add `for_each_target` (and the
targeting set it consumes), give the iterator the `roll_once` shared-roll seeding, wire child
`Invocation`s for `then`, turn on the arity check, teach the legacy adapter to wrap set-targeted spells
in an implicit iterator, and extend `can_run_on_blocks` to AoE/multi_target once Fireball / Magic
Missile / Scorching Ray dual-run green.

_See also: [SPELL_SYSTEM_BUILD_PLAN.md](SPELL_SYSTEM_BUILD_PLAN.md) (Phase-1 architecture + interface
decisions), [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) (design rationale), and the two decision
docs. Memories [[damage-typing-per-entry-resistance]] and [[upcasting-framework-pending]] hold the two
deferred design threads._
