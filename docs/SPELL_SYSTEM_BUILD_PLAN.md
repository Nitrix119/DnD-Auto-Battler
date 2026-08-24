# Spell System — Build Plan for the Remaining Work

> **Scope: only what remains.** Stages 1–3 and E6 are done (the "pure additions" to the *existing*
> engine). This document plans the second half: **building the new block-based spell system** and
> retiring the old one. It uses the current committed state as its base and supersedes the roadmap in
> [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) §7 for everything not yet built. The design intent
> and ratified decisions still live in that doc (§0, §3, §6); this is the *how and in what order*.
>
> **The one question this plan answers up front:** *when does the truly new spell system — the block
> evaluator and its surrounding architecture — come into play?* **Immediately. It is Phase 1 of the
> remaining work, not the end of it.** See §2.
>
> **Guiding principle (decided 2026-08-25): destroy debt.** This is treated as a near-full rewrite of
> spell evaluation, not an incremental patch. The old system was accreted slowly and is not judged
> sufficient going forward. Every choice favours **flexibility, modularity, and low debt** over
> continuity with the old shapes. Concretely: the two vocabularies **collapse aggressively** into one
> block catalogue in Phase 1 (§3.3) — no lingering `BUILTIN_EFFECTS`, no permanent compatibility
> shims — and the new engine lives in its **own module tree**, not grown onto `effect_pipeline.py`.
> The only thing we hold sacred is *observable behaviour*, pinned by the parity corpus (§3.5); the
> internals are free to be rebuilt from clean interfaces.

---

## 1. Where we are (the base)

Delivered, all on the **existing** flat pipeline, deliberately as additions that needed no rewrite:

| Done | What it added | Left the old engine… |
|---|---|---|
| Stage 1 | Step schema + linter + generated `STEP_REFERENCE.md` | unchanged at runtime; validated at load |
| E6 | Per-event field schema + load-time rule validation | unchanged; typos now caught at load |
| Stage 2 | `slot_level` in context + additive-dice `scaling` on damage | one new optional field |
| Stage 3 | `multi_target` targeting via the existing fan-out | one new targeting type |
| (bug) | Shared-`SpellAction` injection fix; loader import-cycle fix | correctness only |

**What the base still is, mechanically** (the thing we are about to replace):

- `EffectPipeline.run` is a **flat loop** with a hard-coded `if/elif` ladder on `step["type"]`
  ([`effect_pipeline.py`](../src/combat/effect_pipeline.py)). One ephemeral context. No nesting.
- **Two effect vocabularies** still exist: the pipeline step types *and* `BUILTIN_EFFECTS`
  ([`effects.py`](../src/rules/effects.py)), bridged by synthetic stub events. A lifetime-bearing
  spell is still two files (spell JSON + entity-effect JSON).
- Fan-out (AoE and now `multi_target`) lives in `SpellResolver`, outside the pipeline.

Everything below replaces this with one block catalogue on one evaluator. The stage-1 schema is the
head start: `STEP_SCHEMAS` already declares each step's fields and its context reads/writes — that is
90% of a block contract.

---

## 2. When the new system comes into play — the pivot

**Now. Phase 1 is the new evaluator.** Three reasons it is the immediate next step and not a distant
finale:

1. **"Unify into one block catalogue" *is* the evaluator.** The old §7 stage 4 ("unify the two
   vocabularies into superset blocks") cannot be done without a block registry + evaluator to unify
   *into*. Building the catalogue and building the evaluator are the same act.
2. **The remaining capabilities require nesting the old loop cannot express.** The deferred
   `for_each_target` iterator, inline trigger blocks (Vampiric Touch's repeat, Armor of Agathys'
   retaliation in one file), and lifetime-scoped sub-programs all need **nested sub-programs run over
   a per-invocation context**. A flat `if/elif` loop has nowhere to put a sub-program.
3. **Stages 1–3 were sequenced *first on purpose*** so their value (validation, upcasting,
   multi-target) landed without waiting on the rewrite. That runway is now spent; there is no more
   high-value work that *doesn't* want the evaluator.

So the shape of the second half is: **build the evaluator, prove it runs every existing spell
identically (behind shape-routing), then express every remaining capability as blocks on it, then
delete the old pipeline.** The old `EffectPipeline` stops being extended the moment Phase 1 starts;
from then on it only runs legacy content until parity retires it.

```
 Phase 1  ── The block evaluator (the pivot) ─────────────────┐  the new system
 Phase 2  ── Capabilities as blocks on the evaluator ─────────┤  is "in play"
 Phase 3  ── Migrate all content, retire the old pipeline ────┘  from Phase 1 on
```

---

## 3. Phase 1 — The block evaluator (the foundation)

**Goal:** a new evaluator that runs a `program` (a nested list of typed blocks) over a per-invocation
context, with **one registry** (no `if/elif`), and re-expresses today's eight step types as blocks —
running the full existing spell corpus **byte-for-byte identically** to the old pipeline, selected by
file shape. No new authoring capability yet; this is the substrate.

### 3.1 The block contract & registry
- Promote `STEP_SCHEMAS` (data) into a **runtime block registry**: each block type registers a
  handler *plus* its declared contract (`reads`, `writes`, `targets`, `timing`, fields/domains,
  failure mode) — §3 C3 / §5.5 of the design doc. One `register_block(...)`; dispatch is a dict
  lookup, never a branch on type.
- The linter (stage 1) already validates against the contract; it now validates the same registry the
  evaluator dispatches from — schema and execution share one source of truth.

### 3.2 The evaluator
- `evaluate(program, ctx)` walks a list of blocks; a block may carry a `then` sub-program that the
  evaluator runs recursively over a **child context**. Extract the current per-step dispatch body of
  `EffectPipeline.run` into a reusable `run_block`/`run_program` so nesting is natural.
- **Preserve the delicate bits exactly:** the `SPELL_HIT` / `DAMAGE_DEALT` emission ordering, the
  `roll_once` seed, `save_result`, crit-doubling, resistance routing. These are correctness-critical
  and covered by tests — they are the parity target.
- Per-invocation context: a fresh context per program invocation (top-level cast, and later per
  iterator element / per trigger firing), seeded like `run` does today.

### 3.3 Re-express the 8 step types as blocks — aggressive fold (decided)
- Port `attack_roll, saving_throw, damage, healing, add_entity_effect, grant_temporary_hp,
  apply_condition, add_modifier` to block handlers, and **in the same phase collapse every
  pipeline/`BUILTIN_EFFECTS` twin** (`damage`/`DealDamage`, `healing`/`HealTarget`, temp-HP,
  condition, modifier, and the advantage/crit/etc. helpers) into **one superset block each**, keeping
  the richer pipeline semantics (design §6.2).
- **`BUILTIN_EFFECTS` is retired, not shimmed.** The rule engine's effect dispatch is repointed at the
  block registry so entity-effect JSON and spell JSON draw from the *same* single vocabulary. There is
  one block catalogue, full stop — the two-vocabulary seam and its synthetic stub events are deleted,
  not preserved behind a compatibility layer. (The legacy *step-shape* adapter in §3.4 is the only
  transitional code, and it too dies in Phase 3.)
- Rationale: the split vocabulary is the single biggest source of debt in the current system; folding
  it later would mean building the evaluator around a seam we intend to remove. Remove it first.
- **Multi-component damage + per-entry resistance (planned superset detail).** Today one `damage`
  block carries one type; multi-type damage (a smite: slashing + fire + radiant; a fire weapon) is
  several blocks, and per-type resistance works *only* because each block is a single-element
  `apply_damage` call. The resistance/immunity/vulnerability rules inspect `damage_list[0]` and apply
  an **unfiltered** `ModifyDamage` — so a genuine multi-type bundle would resist incorrectly. The
  new `damage` block should accept a **list of typed components** applied as one bundle (one hit, one
  `DAMAGE_INCOMING`), and resistance must become **per-entry** (each `Damage` resisted by its own
  type; the `modify_damage` handler already supports a `damage_type` filter — the global rules don't
  use it). This removes the fragile one-type-per-block convention. Do it when finishing the damage
  block; it touches the rule layer, so parity-gate it. See [[damage-typing-per-entry-resistance]].

### 3.4 Shape-routing + backwards-compat adapter
- Route by shape (decided, §6.10): a file with a `program` array → new evaluator; a legacy `effects`
  array → old path (or an **adapter** that reads legacy step dicts as blocks). Never route by name.
- The adapter lets the 22 existing spells run on the new evaluator without being rewritten yet.

### 3.5 The parity gate (non-negotiable)
- **Dual-run** old vs new over the seeded 22-spell conformance corpus and assert identical
  `PipelineResult`s / HP / conditions before the new evaluator becomes the default (design §6.2/§6.10).
- Only after green parity does the default flip. The old pipeline stays reachable until Phase 3.

**Phase 1 deliverable:** the new evaluator is the default for spells authored as `program`, runs all
legacy content identically via the adapter, and has zero new authoring features — a pure, provable
substrate swap.

### 3.6 Phase 1 architecture (concrete)

For a low-debt rewrite the **interfaces are the whole game**; this pins them down.

**Module tree (new, clean-slate).** A new package `src/spells/` owns the block system, leaving
`src/combat/effect_pipeline.py` untouched until Phase 3 retires it:

```
src/spells/
  block.py        # Block dataclass (type, fields, then[]) + parse from JSON
  contract.py     # BlockContract (reads/writes/targets/timing/fields) — from STEP_SCHEMAS
  registry.py     # register_block(type, handler, contract); dict dispatch, no if/elif
  context.py      # InvocationContext: shared mutable state for one program invocation
  evaluator.py    # run_program(program, inv) / run_block(block, inv); nesting + events
  blocks/         # one module per block family: rolls.py, damage.py, healing.py,
                  #   state.py (conditions/modifiers/temp-hp), effects.py (entity effects)
  adapter.py      # legacy `effects` step-dicts -> Block program (transitional, dies Phase 3)
```

**The block-handler contract** — one signature, registered with its declared contract:

```python
# illustrative
def handler(block: Block, inv: InvocationContext) -> None: ...
register_block("damage", handler, BlockContract(
    reads=("hit", "save_success", "slot_level"),
    writes=("damage_dealt", "damage_rolled"),
    targets="current",           # acts on inv.target
    fields=DAMAGE_FIELDS,        # the stage-1 schema, promoted
))
```

A handler reads/writes `inv.context`, acts on `inv.target`, emits via `inv.events`, and runs
sub-programs via `inv.run_program(block.then, target=...)`. It never branches on another block's type
and never touches a second registry.

**The four interface decisions that determine debt** (recommendations; the ones worth confirming
before code are marked ⚑):

- **D1 — target addressing, as arity type-checking (decided).** The evaluator carries a **current
  target** (always a single entity); a set-typed target never reaches a block directly. Each block
  declares a **target arity** in its contract:
  - `single` — acts on the current target (`damage`, `attack_roll`, `saving_throw`, `apply_condition`,
    `add_modifier`);
  - `caster` — acts on the caster regardless of the current target (heal-self, grant-temp-HP-to-caster);
  - `set` — *consumes* a target set and rebinds the current target per element for its `then`
    sub-program (the iterator blocks `for_each_target`/`for_each_beam`/AoE), or a rare genuine
    aggregate that declares it operates on the whole set.

  **The strict rule (decided 2026-08-25):** a `single`-arity block reached while the current target is
  a *set* is a **static load-time error** — "`damage` cannot act on a target set; wrap it in a
  `for_each_target` iterator" — backed by a **runtime assertion** so it can never silently degrade
  (no looping, no `[0]`). "Damage a list" is thus *unrepresentable*, not merely discouraged. This is an
  arity mismatch check, precise rather than blanket: set-consuming blocks *declare* they take a set;
  caster-acting blocks are exempt. It reuses the same static-flow machinery as the stage-1
  context reads/writes check.

  **Cardinality flow.** The linter seeds the top-level current-target cardinality from the spell's
  `targeting_type` (`single_target`/`touch`/`self` → single; `multi_target`/`aoe` → set), and each
  iterator reduces set → single inside its `then`. A `single` block is valid only where the flow
  proves the current target is single.

  **Sequencing.** The arity is part of the block **contract from Phase 1**, but only *bites* once
  fan-out moves into iterators (Phase 4.1): during Phase 1, AoE/multi-target fan-out still happens in
  `SpellResolver`, so the evaluator only ever sees a single current target and the rule is a dormant
  no-op. The Phase-1 legacy **adapter** (§3.4), when it ports a set-targeted legacy spell, wraps its
  blocks in an implicit `for_each_target` — making the old *implicit* fan-out explicit — so the rule
  holds uniformly on the new engine. *(Alternative: blocks take target-sets directly — rejected; it
  spreads fan-out and cardinality handling across every block, the exact debt we're removing.)*
- **D2 — context.** One **mutable `InvocationContext` per invocation**, with explicit child contexts
  for sub-programs (iterator elements, trigger firings). Matches today's model; the reads/writes
  contract keeps mutation disciplined and lets the linter reason about it. *(No functional/immutable
  threading — needless ceremony here.)*
- **D3 — results.** Blocks write outcomes to context; the evaluator derives `PipelineResult` from the
  final context (as today). Sub-program results merge into the parent via defined rules (e.g. an
  iterator sums `damage_dealt`).
- **D4 — integration seam.** `SpellResolver` chooses evaluator by file shape; `AttackResolver`
  compiles weapon attacks into a **block program** instead of `pipeline_effects`, preserving the one
  weapon/spell path on the new engine.

**Parity harness (built first, in 1.2).** A test that, for every corpus spell, resolves it under one
seed on both engines and asserts identical `PipelineResult` + resulting HP/conditions. This is the
gate; it exists before the first block is ported so every port is checked against it.

**Phase 1 commit sequence** (small, each green):
1. `block.py` + `contract.py` + `registry.py` + the parity harness scaffold (no behaviour).
2. `evaluator.py` with nesting; port `attack_roll` + `damage` (superset) → first parity spell (Fire Bolt).
3. Port `saving_throw` + `healing` (superset) → Fireball, Cure Wounds parity.
4. Port state blocks (condition/modifier/temp-hp, folding the twins) → save-or-effect spells parity.
5. Port `add_entity_effect`, repoint rule-engine dispatch at the registry, delete `BUILTIN_EFFECTS`.
6. Shape-routing + legacy adapter; flip default; full corpus parity green.

---

## 4. Phase 2 — Capabilities as blocks on the evaluator

Each is now a block family on the Phase-1 substrate; none was expressible on the flat loop. Ordered so
each is independently shippable and testable.

### 4.1 Targeting sets + iterator blocks (and fold AoE in)
- A targeting block yields an explicit set (`self`, `defender`, `chosen(n)`, `all_in_area`,
  `derived`); iterator blocks (`for_each_target`, `for_each_beam`) run a sub-program per element with
  its own context (design §6.6, §4.2).
- **Re-express stage-3 `multi_target`** as an iterator block (the honest version of the fan-out), and
  **fold AoE fan-out** out of `SpellResolver` into the same iterator — unifying "roll once, apply to
  all" and "roll per projectile" under one mechanism. Parity-gated against current AoE/multi-target
  tests.

### 4.2 Lifetime scopes + grant handles
- A lifetime-scope object owns revoke handles; teardown walks them in reverse (design §6.3/§6.5).
  Reimplement concentration on it; retire the `source_effect`/`effect_name` string-tag convention.
- Resolve the **per-session registry isolation** (E12) here, where lifetimes make shared process
  state actually bite.

### 4.3 Inline trigger blocks
- `on_hit` / `on_turn` / `on_damage` register a sub-program against an event, scoped to a lifetime,
  with a **fresh per-invocation context** (design §6.1) and a **bounded work queue** with a depth
  guard for re-entrant events (design §6.4).
- **Headline result:** migrate Vampiric Touch and Armor of Agathys to **single files** — the split
  the whole vision exists to erase.

### 4.4 Entity lifecycle / summoning
- The `entity_lifecycle` block family (design §6.12, decisions in
  [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md)). Depends on 4.2 (lifetimes) and 4.3
  (triggers/work-queue). Prerequisites to land first: seed-stable entity IDs, pointer-safe initiative
  insert/remove + roll-off tiebreak, a "downed but present" state distinct from "removed", and an
  `ENTITY_DIES` + dismissal event pair.
- Positioned effect-emitters (hazards: *Moonbeam*, *Spiritual Weapon*) are the sibling mechanism —
  can ride 4.1 (AoE + lifetime) without the roster machinery.

### 4.5 Upcasting framework
- The count/multiplicative scaling the additive-dice stage-2 `scaling` does not cover — projectile
  counts (Magic Missile, Scorching Ray) and multiplicative summon counts (*Summon Woodland Beings*
  ×2/×3). **Design pending a user idea** ([[upcasting-framework-pending]]); unify all count/scaling
  here rather than piecemeal. Slots in once iterators (4.1) and summoning (4.4) exist to scale.

### 4.6 Meta / `cast_spell` blocks
- The escape hatch: a block that invokes the resolver on another spell (Wish, Contingency), plus
  copy/counter. Built last, once 4.1–4.4 are stable — it is the proof the "add one block" model
  really absorbs the exotic tail (design §5.5, §6.11).

---

## 5. Phase 3 — Migration & retirement

1. Migrate the 22 spells (and the 6 entity effects) from `effects`/entity-effect files to single-file
   `program`s, each parity-checked as it moves.
2. Delete the legacy flat-pipeline path and the compat adapter once the corpus is fully migrated.
3. Complete the rename: `effects` → `program` internally, `step` → `block` (design §0). "Spell" stays
   the user-facing word.
4. Finish positioned effect-emitters for the remaining hazards.

---

## 6. Invariants to preserve through all of it

Non-negotiable properties the rewrite must not regress (each is currently tested):

- **One resolution path for weapons and spells.** Weapon attacks compile into the same blocks; never a
  second attack path.
- **`roll_once` + `save_result` + crit-doubling + resistance routing** — the 5e-correct damage
  behaviours. The parity corpus guards them.
- **Determinism under `dice.seed_rng`**, including deferred trigger firings — stable ordering (design
  §6.8) and a replay test.
- **The AST-whitelist expression sandbox** — never widened for authoring convenience.
- **The EventBus** as the substrate for anything cross-cutting; triggers are a friendlier face over it.
- **Immutable `StatBlock`, mutable `Entity`.**

---

## 7. Sequence, gates, and dependencies at a glance

| Phase | Item | Depends on | Gate before "done" |
|---|---|---|---|
| 1 | Block registry + contract | stage-1 schema | linter dispatches from the registry |
| 1 | Evaluator + nesting | registry | parity dual-run on corpus |
| 1 | 8 step types as blocks; fold twins | evaluator | superset blocks pass all step tests |
| 1 | Shape-routing + legacy adapter | evaluator | 22 spells run identically on new path |
| 2 | Iterators + AoE fold | Phase 1 | AoE/multi-target tests green on iterator |
| 2 | Lifetime scopes; E12 isolation | Phase 1 | concentration parity; per-session state |
| 2 | Inline triggers + work queue | lifetimes | Vampiric Touch/Agathys single-file |
| 2 | Entity lifecycle / summoning | lifetimes, triggers, prereqs | summon parity + teardown tests |
| 2 | Upcasting framework | iterators, summoning, **user idea** | count/mult scaling covered |
| 2 | Meta / `cast_spell` | most of Phase 2 | Wish-class spell resolves |
| 3 | Migrate content; delete old path | Phase 2 parity | corpus fully on `program` |

---

## 8. Risks & how we hold the line

- **Rewrite drift.** Mitigated by the parity gate (dual-run corpus) and the shape-router keeping the
  old path alive — nothing flips to the new evaluator until it is provably identical.
- **The event-ordering seam.** The `SPELL_HIT`/`DAMAGE_DEALT` emission logic is subtle; it moves into
  the evaluator early (Phase 1) with its existing tests as the spec, not late.
- **Re-entrancy** (a block that kills a creature whose on-death trigger deals damage). The bounded work
  queue + depth guard (§6.4) is a Phase-2 prerequisite, not an afterthought — and the shared-mutation
  class of bug is already fixed.
- **Scope creep across families.** Each Phase-2 item is independently shippable behind the router;
  land and test one before the next. Re-plan checkpoints after Phase 1 and after 4.1/4.2.
- **Two pending designs** gate their items and must be settled first: the **upcasting framework**
  ([[upcasting-framework-pending]]) before 4.5, and the **summoning prerequisites** before 4.4.

---

## 9. The immediate next step

Phase 1.1 + 1.2: stand up the **block registry** and the **evaluator with nesting**, re-express the
eight step types as blocks, and get the **parity dual-run** green over the 22-spell corpus behind
shape-routing. That is the smallest slice that puts the new system "in play" while changing no
observable behaviour — the safe beachhead everything else builds from.

_See also: [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) (full design + completed-stage notes),
[SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md) (intent), [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md)
(summoning), [SPELL_SYSTEM_DECISIONS.md](SPELL_SYSTEM_DECISIONS.md) (block-model decisions)._
