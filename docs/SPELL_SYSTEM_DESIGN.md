# Spell System Design — From Vision to Implementation

> **Status: design agreed, implementation not yet started (2026-08-22).** This document takes the
> intent in [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md) and makes it concrete: it pins the
> *current* mechanics down to the function level, specifies **precisely how you add a new spell and a
> new block ("hook") today and under the target model**, and enumerates the major challenges with a
> resolution for each. The design decisions in [SPELL_SYSTEM_DECISIONS.md](SPELL_SYSTEM_DECISIONS.md)
> are now **ratified and folded in** (see §0). We are still in the *planning* phase — no rework code
> has been written yet — with one exception already shipped: the §6.4 shared-mutation bug is
> **fixed** (test-first) since it was a standalone correctness defect independent of the rework.
> Everything else here is grounded in the code as it exists on 2026-08-22 and is meant to be
> implementable against.
>
> Read the vision doc first for the *why*. Read [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md) §3–§5 for
> the health context (what's sound, what's a wiring gap, the E-numbered debts). This doc is the
> bridge between them.

---

## 0. Decisions locked (2026-08-22)

Ratified in [SPELL_SYSTEM_DECISIONS.md](SPELL_SYSTEM_DECISIONS.md); the sections below have been
updated to assume them. Summarised here so the doc is self-contained.

| # | Decision | Consequence in this doc |
|---|---|---|
| **Scope** | Stay in planning; **build no rework code yet**. Front-load the design. | This is a plan, not a WIP. Stage 1 starts only on an explicit go. |
| **A2 bug** | Fix the `inject_pipeline_damage_step` shared-mutation defect **now**, standalone. | **Done** — see §6.4 (RESOLVED). |
| **Vocabulary name** | A single instruction is a **`block`**. | Used throughout; not "op"/"instruction". |
| **File shape** | The array is a **`program`** internally; the user-facing word stays **"spell"** (tunable later). | §3 uses `program`. |
| **Back-compat routing** | Keep the legacy interpreter during migration, but **route by shape** (`program` vs `effects`), **never by filename/spell name**. | §6.10 rewritten. |
| **Language line** | **No author-defined variables, loops, or functions.** Only bounded iterators over target sets + sandboxed side-effect-free expressions. Real computation is a registered Python block. | Bounds the linter (§6.9) and every block. |
| **Context contract** | Each block **declares** its `reads`/`writes` (no inference). | §5.5, §6.9. |
| **Nesting** | **Triggers/`then` only** for now; add sub-programs-as-arguments only if a real spell forces it (self-referential resolver makes it cheap later). | §6.6, §8. |
| **Conditions** | **Both** — a shared library for the canonical 17, inline for one-offs, with **functional equivalence** between "reference" and "define inline". | §3 C2, §6 note. |
| **Concentration/revocation** | Adopt **lifetime scopes + grant handles**; retire the `source_effect` string-tag convention. | §6.3 / §6.5. |
| **AoE** | **Fold AoE fan-out into the general targeting/iterator mechanism.** | §6.6. |
| **Trigger ordering** | Subscription order → initiative, **plus an optional `priority` field** on deferred triggers for the rare must-fire-first case. | §6.8. |
| **Upcasting** | `slot_level` in context **and** an explicit `scaling` modifier on scalable blocks. | §6.7. |
| **Roadmap** | Accept the staged order (§7); re-plan after stage 3. | §7. |
| **Migration safety** | **Dual-run old vs new over the seeded 22-spell conformance corpus**, assert identical results before deleting any old path. | §6.2 / §6.10. |
| **Guide generation** | Stage 1 **generates the authoring guide tables from the schema** (single source of truth). | §7 stage 1. |
| **Visual editor** | **Not a goal.** Schema is a validation/docs contract only; pay no editor cost speculatively. | §8. |
| **Entity lifecycle / summoning** | **Designed** (2026-08-24, [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md)): two mechanisms (real combatants via an `entity_lifecycle` family vs positioned effect-emitters for hazards); fixed-statblock summons first, referenced by name; own-initiative (5e RAW); lifetime-scope-owned with a death/dismissal split and an inert-vs-removed state; controller-driven; Simulacrum/command/horde-init deferred. | §6.12 (full), §7 prereqs, §8. |

---

## 1. What this document adds

The vision doc says *"spells should be programs of blocks, one definition per spell, one block
catalogue."* It deliberately stops at intent. Three things it left open, which this document
supplies:

1. **A function-level map of the current system** — not "a pipeline of steps" but *which* function
   dispatches *which* step, *what* it writes to context, *when* it emits each event, and exactly
   *where* the two-vocabulary seam is stitched (§2).
2. **A precise, test-first authoring procedure for a new spell** — today's real two-file procedure
   and the target's one-file procedure, each as a numbered checklist with a worked example (§4).
3. **A precise procedure for adding a new hook** — the three distinct kinds of "hook" (block type,
   event, context/expression name), the exact files each touches today, and the single-registration
   target, each with a worked example including the Wish escape hatch (§5).

Plus the honest hard part: §6, the challenges, each stated as a concrete failure the design must
survive, not an abstraction.

---

## 2. The current system, precisely (the mechanical baseline)

### 2.1 The load path

A spell is a JSON file in `examples/spells/` with an `effects` array. There is exactly one rename on
the way in: `StatBlockLoader` copies `action_data["effects"]` into `SpellAction.pipeline_effects`
verbatim ([`src/loaders/stat_block_loader.py:325`](../src/loaders/stat_block_loader.py#L325)). The
array is **not validated element-by-element** — malformed steps survive loading and fail (or
silently no-op) at run time. `web/app.py` scans `examples/spells/` and `rules/entity_effects/` into
process-global registries at startup.

So the authored `effects` list *is* the program. There is no compilation, no schema pass, no
linking step — the list of dicts is handed straight to the interpreter.

### 2.2 The interpreter: `EffectPipeline.run`

[`src/combat/effect_pipeline.py`](../src/combat/effect_pipeline.py) is the interpreter.
`SpellResolver.resolve` pre-rolls any `roll_once` damage steps once
([`spell_resolver.py:74`](../src/combat/spell_resolver.py#L74)), then calls `EffectPipeline.run`
**once per defender** — that per-target loop *is* the AoE fan-out. Inside `run`:

- A single **ephemeral `context` dict** is seeded with ~12 defaulted keys (`hit`, `save_success`,
  `damage_dealt`, `damage_rolled`, `attack_total`, …) so expression evaluation never hits an
  uninitialised name ([`effect_pipeline.py:121`](../src/combat/effect_pipeline.py#L121)).
- Steps are walked in order and dispatched by a hard-coded **`if/elif` ladder on `step["type"]`**
  ([`effect_pipeline.py:171-201`](../src/combat/effect_pipeline.py#L171-L201)). An unknown type logs
  a warning and is skipped — no error.
- Event emission is **positional and implicit**: `SPELL_HIT` is emitted lazily just before the first
  non-roll step; `DAMAGE_DEALT` is emitted just before the first `add_entity_effect` step (so a
  freshly-applied effect does *not* react to the damage that applied it). This ordering logic lives
  inline in `run` and is one of the subtler things a rewrite must preserve.

The eight step types and what each writes:

| Step type | Handler | Writes to context | Notable behaviour |
|---|---|---|---|
| `attack_roll` | `_handle_attack_roll` | `hit`, `attack_roll`, `attack_total`, `critical_hit/miss`, `had_advantage/disadvantage` | Emits `ATTACK_DECLARED` (cancellable) → rolls adv/dis per event flags → `ATTACK_ROLLED` → `ATTACK_HIT` |
| `saving_throw` | `_handle_saving_throw` | `save_roll`, `save_dc`, `save_success` | Emits `SAVING_THROW_DECLARED` so effects can flag adv/dis before the roll |
| `damage` | `_handle_damage` | `damage_dealt` (cumulative), `damage_rolled` | Crit-doubles the formula, honours `roll_once` seed, applies `save_result` half/none, routes through `DamageProcessor` (resistance) |
| `healing` | `_handle_healing` | `healing_amount` | `amount` expression **or** `formula`+`bonus`; catches eval errors and heals 0 |
| `add_entity_effect` | `_handle_add_entity_effect` | — | Applies a **named rule from a separate file**, tracks concentration, runs `on_apply` sub-actions |
| `grant_temporary_hp` | `_handle_grant_temporary_hp` | `temp_hp_granted` | Direct `Entity.add_temporary_hp` |
| `apply_condition` | `_handle_apply_condition` | — | **Adapter** — builds a synthetic dict and calls the rule-engine `ApplyCondition` handler |
| `add_modifier` | `_handle_add_modifier` | — | **Adapter** — builds a synthetic dict + stub `SPELL_HIT` event and calls the rule-engine `AddModifier` handler |

### 2.3 The second vocabulary, and the seam

Longer-lived / reactive behaviour is **not** expressible as pipeline steps. It lives as **named
entity effects**: separate JSON files in `rules/entity_effects/` loaded as `Rule`s that subscribe to
`EventBus` triggers, gated by `condition` / per-effect `on` / per-effect `when`, whose `effects`
array dispatches to a *different* registry — `BUILTIN_EFFECTS` in
[`src/rules/effects.py`](../src/rules/effects.py) (18 handlers: `ApplyCondition`, `HealTarget`,
`DealDamage`, `GrantAction`, `ModifyDamage`, `ForceConcentrationCheck`, `GrantTemporaryHP`,
`AddModifier`, …).

The two vocabularies overlap but are **not the same code**:

| Concept | Pipeline step (spell file) | Rule effect (entity-effect file) |
|---|---|---|
| Deal damage | `damage` — crit, `roll_once`, `save_result`, resistance | `DealDamage` — flat formula, optional resistance |
| Heal | `healing` — `amount` expr or `formula`+`bonus` | `HealTarget` — `formula`+`bonus` |
| Temp HP | `grant_temporary_hp` | `GrantTemporaryHP` |
| Condition | `apply_condition` → *calls* `ApplyCondition` | `ApplyCondition` |
| Modifier | `add_modifier` → *calls* `AddModifier` | `AddModifier` |

Two facts make the seam explicit, and both are load-bearing evidence for the vision's central
complaint:

1. **The pipeline literally reaches across into the other registry.** `_handle_apply_condition` and
   `_handle_add_modifier` construct a synthetic `on_apply`-shaped dict and a **stub `SPELL_HIT`
   event**, then invoke `rule_engine._effect_registry["ApplyCondition"]` /`["AddModifier"]`
   ([`effect_pipeline.py:536-605`](../src/combat/effect_pipeline.py#L536-L605)). The pipeline step is
   a thin adapter over the rule handler — the duplication is already half-collapsed, by hand, at a
   fragile seam.
2. **A spell with a lifetime is two files.** Vampiric Touch's attack/damage/heal live in
   `examples/spells/vampiric_touch.json`, but "repeat this attack each turn while concentrating" must
   be a *second* file, `rules/entity_effects/vampiric_touch.json`, whose `on_apply` `GrantAction`s a
   fresh attack that **re-derives the caster's spell attack bonus and damage by hand**. Armor of
   Agathys is the same shape (a retaliation rider as a separate `ATTACK_HIT`/`DAMAGE_DEALT` rule).

### 2.4 The expression sandbox (shared by both vocabularies — the one thing that *is* unified)

Every expression string in either place runs through
[`src/rules/expressions.py`](../src/rules/expressions.py): `ast.parse(mode="eval")` → walk against a
**node whitelist** (`ALLOWED_NODES`) → reject any `_`-prefixed name/attribute → allow only direct
calls to `SAFE_BUILTINS` (`max, min, abs, int, round, bool, len, hasattr`) → `compile` and cache →
`eval(code, {"__builtins__": {}}, ctx)`. Validation and compilation are memoised by expression
string. This is the safest, most reusable part of the system and any block model should keep it
exactly.

### 2.5 Concentration today (the "tiptoeing")

There is no first-class lifetime. Concentration is three cooperating conventions:

- On apply, `_handle_add_entity_effect` drops the previous concentration by calling
  `caster.concentration_target.remove_effect(caster.concentrating_on)` **before** applying the new
  one (order matters, or the new effect's teardown races the old)
  ([`effect_pipeline.py:490-503`](../src/combat/effect_pipeline.py#L490-L503)).
- The caster stores `concentrating_on` (effect name) + `concentration_target` (entity).
- On a failed CON save, the global `force_concentration_check` handler clears those fields and calls
  `remove_effect`, which also strips linked `StatModifier`s and granted actions tagged with that
  `source_effect` ([`effects.py:149`](../src/rules/effects.py#L149)).

This works, but "what a spell granted" is reconstructed from a name-tag convention (`source_effect`),
not owned by a lifetime object.

### 2.6 What is genuinely good — preserve it verbatim

- **One resolution path for weapons and spells** (`AttackResolver._build_pipeline_effects` compiles
  weapon attacks into the same steps). Do not reintroduce a second attack path.
- **The `roll_once` pre-roll + `save_result` half-damage** correctly model the two trickiest 5e AoE
  rules. Any new damage block must keep both.
- **The AST-whitelist sandbox.** Never widen it for authoring convenience.
- **The EventBus as the substrate for anything cross-cutting.** Triggers should ride it, not replace
  it.

---

## 3. The target model, made concrete

The vision's "one block language" becomes three concrete commitments:

**C1 — One catalogue.** Fold the `if/elif` step ladder *and* `BUILTIN_EFFECTS` into a single
registry of **block handlers**, keyed by block type, each with a declared contract. "Deal damage" is
one block whether it fires now or from a trigger later. The `damage`/`DealDamage` and
`healing`/`HealTarget` pairs collapse to one each (keeping the richer pipeline semantics —
crit/`roll_once`/`save_result`/resistance — as the survivor).

**C2 — One definition per spell.** A spell file carries its *entire* identity, including
lifetime-bound and reactive behaviour, via nested **trigger blocks** — no obligatory second file.
The engine may still *instantiate* a persistent effect under the hood, but the author writes it once,
inline. `rules/entity_effects/*.json` becomes an engine-internal representation or a *shared-library*
mechanism (for genuinely reusable effects like the 17 conditions), not the mandatory home for
per-spell riders. **A library reference and an inline definition must be functionally equivalent**
(decided): referencing the canonical `stunned` and defining an identical condition inline produce the
same behaviour — the library is deduplication for common content, never a *different mechanism*. That
equivalence is what keeps C2 honest; a per-spell rider is never *forced* into a second file, while
genuinely shared content (the 17 conditions) may still live in one.

**C3 — Every block declares a contract.** Each block type registers `{ reads, writes, targets, timing,
required_fields, field_domains, failure }`. The contract is simultaneously the **schema** (for the
linter), the **docs** (generated, not hand-maintained), and the **context-flow check** (a block whose
`when` reads `context.damage_dealt` must come after a block that writes it).

A block is a dict `{ "block": "<type>", ...fields, "then": [ ...sub-blocks ] }`. `then` is how
triggers and conditionals nest sub-programs. Concentration/duration is a **scope** wrapping a subtree,
not a boolean smeared across steps:

```jsonc
// illustrative target shape — NOT a committed schema
{
  "name": "Vampiric Touch",
  "concentration": true,
  "program": [
    { "block": "attack_roll", "bonus": "caster.spell_attack_bonus" },
    { "block": "damage", "formula": "3d6", "type": "necrotic", "when": "hit" },
    { "block": "heal", "target": "caster", "amount": "context.damage_dealt // 2" },
    { "block": "on_turn",                         // trigger block, bound to the enclosing
      "actor": "caster", "while": "concentration", // concentration scope, defined right here
      "then": [ { "block": "repeat_program" } ] }  // re-run this same program, fresh context
  ]
}
```

The point is not this syntax. It is that the fourth line — "repeat each turn while concentrating" —
is a block **in the same file**, capturing the parent program's context definition rather than a
hand-authored second file that re-derives everything.

---

## 4. Precisely how you add a NEW SPELL

### 4.1 Today (the real procedure, two files when there's a lifetime)

For a spell that is only instantaneous rolls/damage/heal (the majority — Fire Bolt, Fireball, Cure
Wounds), it is genuinely one file:

1. **Write a failing execution test first** (per CLAUDE.md §4 and the 2026-08-08 lesson). Build two
   `Entity`s, `dice.seed_rng(N)`, resolve the spell, assert HP/conditions changed. A parse-only test
   does **not** count.
2. Create `examples/spells/<name>.json` with the top-level fields (`type: "spell"`, `spell_level`,
   `spell_range`, `targeting_type`, `casting_time`, `duration`, `components`) and an `effects` array
   of steps from the eight types in §2.2.
3. Order matters: `attack_roll` / `saving_throw` before any `damage` that reads `context.hit` /
   `context.save_success`. Put `roll_once: true` on AoE damage; `requires_hit: true` on
   attack-gated damage; `save_result.on_success` for half-on-save.
4. Restart the app (registries are built at startup) or reload the registry in the test.
5. `black . && flake8 src/ web/ && pytest tests/ -q`. Update the guide if you used a field in a new
   way.

For a spell with **any persistent or reactive behaviour** (concentration buffs, riders, granted
repeat actions), step 2 forks into two files, and this is the friction the vision targets:

2a. The spell file carries the instantaneous part **plus** an `add_entity_effect` step naming a
   second file, with `concentration: true` if applicable, and optionally `on_apply` sub-actions.
2b. Create `rules/entity_effects/<name>.json`: a `Rule` with `triggers`, a `condition` that
   re-identifies the situation (e.g. `"event.source == entity and event.action_name == 'Vampiric
   Touch'"`), and an `effects` array using the **`BUILTIN_EFFECTS`** vocabulary — a *different*
   field shape from the pipeline. Any context from the original cast that the rider needs (the
   caster's attack bonus, the damage dealt) must be re-derived or threaded via `instance_fields`.

**Concrete gaps you will hit today**, and the honest workaround:

- **Split multi-target** (Magic Missile's 3 darts, Scorching Ray's 3 beams, Eldritch Blast). Not
  expressible — the pipeline is "one effect list, applied once per selected defender." Magic Missile
  currently fakes three `1d4+1` darts as a single `3d4+3` blob against one target. A true
  "N independent attack rolls, assign each to a chosen target" spell cannot be authored.
- **Upcasting.** `higher_level_scaling` is prose only (an explicit TODO in
  [`src/models/action.py`](../src/models/action.py)). To make a spell hit harder at a higher slot you
  copy the file and edit the dice — there is no slot parameter reaching a `damage` formula.
- **Rider that references "this attack's damage" later.** Works only because the rider re-subscribes
  to `DAMAGE_DEALT` and reads `event.total`; you cannot capture the *casting* context.

### 4.2 Target (one file, test-first)

1. **Failing execution test first** — unchanged; this discipline is the point.
2. Create `examples/spells/<name>.json` with one `program` array. Everything — the buff, the rider,
   the granted repeat, the concentration linkage — is a block or a nested `then` subtree in that one
   file. No second file unless you are deliberately authoring a *reusable* effect for a shared
   library.
3. **The linter runs at load** (§6.9): unknown block → named error; a `when` that reads a context key
   no prior block writes → named error at load, not a silent skip at run time; a field outside its
   declared domain → named error. The author gets a local diagnostic instead of a runtime no-op.
4. Format/lint/test. Because the linter validates the file, the "new spell" **skill** (the README
   future goal) can author against the schema and get structured feedback — the thing
   CODEBASE_REVIEW §8 says is blocked on this work.

**Worked example — Scorching Ray, target model** (a spell impossible to author today):

```jsonc
{
  "name": "Scorching Ray",
  "program": [
    { "block": "for_each_beam", "count": "3 + max(0, slot_level - 2)",   // upcast as a modifier
      "target": "chosen",                                                 // per-beam target choice
      "then": [
        { "block": "attack_roll", "bonus": "caster.spell_attack_bonus" },
        { "block": "damage", "formula": "2d6", "type": "fire", "when": "hit" }
      ] }
  ]
}
```

This exercises three target-model primitives at once: a **split multi-target** iterator, an
**upcast-driven count**, and a **nested sub-program** with its own per-iteration context — none of
which today's `effects` array can express.

---

## 5. Precisely how you add a NEW HOOK (extend the language)

"Hook" is used loosely in the vision. It is really **three distinct extension points**, with
different cost today:

### 5.1 The three kinds of hook

| Kind of hook | What it lets an author write | Where it's implemented today |
|---|---|---|
| **A new block/step type** | a new verb in a spell's `effects` (e.g. `forced_movement`) | an `elif` in `EffectPipeline.run` **and** a `_handle_*` method — OR a `BUILTIN_EFFECTS` handler + `register_effect`, for the rule side |
| **A new event** | a new moment effects can react to (e.g. `TURN_START` riders, on-death) | add to `EventType`, `emit` it from the right resolver, subscribe |
| **A new context / expression name** | a new value an expression can read (e.g. `context.targets_hit`, `slot_level`) | write the key into the `context` dict in `run`, expose it via `_make_eval_ctx` |

The vision's "add one new block" escape hatch is kind A. But most real gaps in CODEBASE_REVIEW §4
need a mix (forced movement is a block *and* arguably an event; upcasting is a context name *and* a
block modifier).

### 5.2 Today: adding a block type (worked example — `forced_movement`, i.e. Thunderwave push)

This is a real gap (review §4.7). Today it takes edits in **three** places and there is no schema:

1. **Handler.** Add `_handle_forced_movement(self, step, caster, defender, context)` to
   `EffectPipeline`: read `step["distance_ft"]`, compute a shove vector from caster→defender
   position, mutate `defender.x/y/z`. Decide and document the context it writes (e.g.
   `context.pushed_ft`).
2. **Dispatch.** Add `elif step_type == "forced_movement": self._handle_forced_movement(...)` to the
   ladder in `run` ([`effect_pipeline.py:171-201`](../src/combat/effect_pipeline.py#L171-L201)).
3. **Docs.** Add a section to `SPELL_DEFINITION_GUIDE.md` (fields, defaults, context written) — by
   hand, and it *will* drift from the code (the guide and code are two sources of truth today).
4. **Execution test.** Per the 2026-08-08 lesson, a test that *runs the pipeline* and asserts the
   defender actually moved — not one that asserts the JSON parsed.

If instead the hook belongs on the **reactive** side (say a retaliation-style block usable from an
entity effect), you write it as a `BUILTIN_EFFECTS` handler with the fixed
`(effect, ctx, event, event_bus)` signature and `register_effect("ForcedMovement", …)` — a *second*
implementation, a *second* field shape, a *second* place to document. That is the duplication tax.

### 5.3 Today: adding an event (worked example — an on-death trigger)

1. Add `ENTITY_DIES` (already exists) or a new member to `EventType`
   ([`src/combat/events.py`](../src/combat/events.py)).
2. Define its event-data payload in `event_data.py` and **emit it from the one place the state
   transition happens** (e.g. `DamageProcessor` when HP hits 0). Emit *after* the state change so
   subscribers see the final state, and beware re-entrancy (§6.4).
3. Effects subscribe by naming the trigger in their `triggers` array; global rules subscribe via
   `RuleEngine.load_rule`.

### 5.4 Today: adding a context name (worked example — `slot_level` for upcasting)

1. Thread the cast-time slot level from the WebSocket handler / `SpellResolver.resolve` into
   `EffectPipeline.run`.
2. Seed it into the `context` dict at the top of `run`
   ([`effect_pipeline.py:121`](../src/combat/effect_pipeline.py#L121)) so it survives into
   `_make_eval_ctx`, which already copies every non-`_` key into the expression namespace
   ([`effect_pipeline.py:676-699`](../src/combat/effect_pipeline.py#L676-L699)).
3. Now `"formula": "8d6"` can become a block that scales by `slot_level` — but note the *formula*
   itself is a dice string, not an expression, so upcasting needs a block-level modifier, not just a
   context name (this is exactly why upcasting is "context name **and** block", §5.1).

### 5.5 Target: one registration = handler + schema + docs

A single decorated registration replaces the ladder edit, the guide edit, and the drift:

```python
# illustrative target — NOT current code
@block(
    "forced_movement",
    reads=["hit"],
    writes=["pushed_ft"],
    targets="defender",
    timing="immediate",
    schema={"distance_ft": Int(min=0, required=True),
            "requires_hit": Bool(default=False)},
    fails="skip_if_no_position",
)
def forced_movement(bctx):
    if bctx.step.get("requires_hit") and not bctx.context["hit"]:
        return
    ...
    bctx.context["pushed_ft"] = moved
```

From that one declaration the engine gets: the dispatch entry (no `if/elif`), the linter rules
(unknown-field, wrong-type, `requires_hit` on a step with no prior `attack_roll` → context-flow
error), and the reference docs (the guide's `forced_movement` table is generated from `schema`). The
same registration is valid whether the block runs inline in a spell or inside a trigger's `then`
subtree — the two vocabularies are now one. Adding Wish's "cast another spell" becomes a `cast_spell`
block whose handler recursively invokes the resolver on a named/looked-up spell (the vision's Wish
test) — one registration, no resolver special-case.

### 5.6 The extensibility invariant

The measure of success (from the vision, made testable): **to support a spell whose signature
mechanic isn't expressible, the diff is exactly one new `@block` registration + its schema entry +
one execution test.** No edit to the interpreter's dispatch, no second-vocabulary twin, no
hand-written guide section. If a new mechanic still needs to touch `run`'s control flow, the block
abstraction is leaking and that leak is the bug to fix first.

---

## 6. Major challenges (each: the concrete failure, then the resolution)

### 6.1 Context capture across time

**Failure.** A trigger block that fires on a *later* turn (Vampiric Touch's repeat, Armor of Agathys'
retaliation) needs a context. If it reuses the original cast's `context` dict, it reads a stale
`damage_dealt` from three turns ago and heals the wrong amount. If it gets a blank context, it can't
express "heal half of *this* re-attack's damage." Today this is dodged entirely by re-subscribing to
`DAMAGE_DEALT` and reading `event.total` — which only works because the rider was hand-written to.

**Resolution.** Define two scopes explicitly. A trigger block captures a **closure** over its
*definition-time* constants (caster identity, spell DC, the program text) but runs its `then` subtree
against a **fresh per-invocation context** seeded like any pipeline run. "This attack's damage" always
means the current invocation's `context.damage_dealt`. Definition-time values a rider needs long-term
are captured explicitly into the closure at grant time (the honest version of today's
`instance_fields`), never read live off a mutable entity.

### 6.2 Collapsing two damage/heal implementations without regressing

**Failure.** `damage` (pipeline) does crit-doubling, `roll_once` seeding, `save_result`, and routes
through `DamageProcessor` for resistance; `DealDamage` (rule) does a flat formula and *optionally*
resistance. Naively merging to the simpler one silently drops crit/half-on-save/AoE-consistency — a
correctness regression that a shape-only test would miss (the exact trap of the 2026-08-08 lesson).

**Resolution.** The merged block is the **superset**: keep every pipeline semantic, make `roll_once`
and `save_result` optional fields that default off so the "flat 5 cold from Armor of Agathys" case
just omits them. Migrate the 22 existing spells onto it and run the full suite as the regression net
*before* deleting `DealDamage`. Same for `healing`/`HealTarget`.

### 6.3 Concentration as a first-class lifetime

**Failure.** Starting a new concentration spell must drop the old one **and its entire granted
subtree** (modifiers, granted actions, riders) deterministically; a failed CON save must revoke
exactly what the spell granted and nothing else. Today this is a name-tag convention
(`source_effect`) plus careful ordering in `_handle_add_entity_effect`; a rider that granted two
things under one name, or two effects sharing a name, can under- or over-remove.

**Resolution.** Model a **lifetime scope** object that *owns* a list of grant handles (each grant
returns a revoke closure). Concentration is one kind of lifetime; rounds/minutes are others. Teardown
walks the owned handles in reverse — no name matching, no reconstruction. `concentration: true` on a
program wraps its lifetime-producing blocks in the caster's concentration scope; replacing
concentration disposes the old scope atomically before creating the new one.

### 6.4 Ordering and re-entrancy

**The standalone bug — RESOLVED (2026-08-22).** `inject_pipeline_damage_step` (the
`AddDamageToAttackHit` handler, [`effects.py:286`](../src/rules/effects.py#L286)) **appended a step to
`action.pipeline_effects` while `run` was iterating that very list**, relying on Python list-iteration
picking up the appended element in the same pass. Weapon attacks were shielded because
`AttackResolver` runs on a `copy.copy` of the action with a freshly-built step list — but **spells run
on the shared registry `SpellAction` directly**, so the injected step persisted and **compounded
across casts and across AoE targets** (cast two, take 9 damage instead of 6; second AoE target takes
the first's injected step too). Fixed test-first: `EffectPipeline.run` now iterates a **run-local copy**
of the steps and, after each step, drains any freshly-injected steps into that local copy while
**truncating the shared list back to its original length** — the injection still executes this run but
never persists. Covered by
[`tests/rules/entity_effects/test_inject_pipeline_step.py`](../tests/rules/entity_effects/test_inject_pipeline_step.py)
(restore-length, no-compound-across-casts, no-leak-across-AoE-targets). *This was fixed independently
of the rework because it was a real correctness defect, not just a design smell.*

**The design-level failure it foreshadows.** List-surgery-during-iteration is a symptom: any event
that re-enters resolution (a `damage` block that kills a creature whose on-death trigger deals damage
back) needs defined ordering and a re-entrancy guard, which the current model lacks.

**Resolution.** Blocks never mutate the program list (the run-local-copy fix is the interim guarantee;
the model removes the need entirely). "Add damage on hit" becomes a declared sub-block in the program
or a trigger's `then`, resolved by the interpreter, not by list surgery. Event emission that can
re-enter (death, retaliation) runs through a **bounded work queue** with a depth guard and a
visited-set, and `SpellAction` stays immutable during resolution (per CLAUDE.md's "immutable template,
mutable state").

### 6.5 Revocation and ownership

**Failure.** Every "grant" (action, modifier, temp HP, condition, rider subscription) needs a
matching revoke with a single clear owner, or effects leak (a buff that never ends) or double-remove
(two effects strip the same modifier). Today ownership is implicit in `effect_name`/`source_effect`
string tags.

**Resolution.** §6.3's grant-handle model generalises: *every* grant returns a revoke handle owned by
the lifetime scope that created it. `remove_effect` becomes "dispose the scope," which disposes its
handles. No string tags, no scan-and-match.

### 6.6 Targeting sets and split multi-target

**Failure.** The engine's only target notions are "the current defender" (per-target fan-out) and
"caster." Magic Missile / Scorching Ray / Eldritch Blast — N independent rolls with *per-dart target
choice* — are inexpressible; Magic Missile fakes it as one blob (review §4.6).

**Resolution.** A **targeting block** produces an explicit set (`self`, `defender`, `chosen(n)`,
`all_in_area`, `derived(expr)`), and iterator blocks (`for_each_beam`, `for_each_target`) run a
sub-program per element with its own context. AoE fan-out — currently the implicit per-defender loop
in `SpellResolver` — becomes one such iterator, unifying "roll once, apply to all" and "roll per
dart" under one mechanism (§4.2's Scorching Ray).

### 6.7 Upcasting as a modifier over blocks

**Failure.** No slot level reaches the resolver; formulas are static dice strings. "1d6 per slot
above 3rd" and "one more dart per slot" cannot be authored (review §4.2).

**Resolution.** Thread `slot_level` as a context name (§5.4) *and* give scalable blocks an explicit
`scaling` modifier — `{ "per_slot_above": 3, "add_dice": "1d6" }` on a damage block, `count:` as an
expression on an iterator. Upcasting is then a *modifier over the program*, never a copied
higher-level file.

### 6.8 Determinism across deferred triggers

**Failure.** CLAUDE.md §1 promises a battle is reproducible under `dice.seed_rng`. A trigger that
fires three turns later still pulls from the shared RNG; if its firing *order* relative to other
same-turn triggers isn't deterministic, replays diverge.

**Resolution (decided).** Keep all randomness on the single `dice` RNG (already true). Give the
trigger work queue (§6.4) a **stable, documented ordering: subscription order, then entity
initiative**, so the sequence of RNG draws is fixed for a given seed. Add an **optional integer
`priority` field** on deferred-trigger blocks for the rare case where a trigger must fire first/last
regardless (higher priority resolves earlier; absent = 0); it costs almost nothing to support and
pre-empts the "these two same-turn triggers genuinely must order" corner without inventing per-spell
special cases. Add a replay test that resolves the same seeded battle twice and asserts identical logs.

### 6.9 The schema + linter, and the E6 debt

**Failure.** Today an unknown step type warns and skips; a typo'd field silently no-ops; a `when`
referencing a key its step can't have produced fails at run time or not at all. Worse, `RuleEngine`
deliberately swallows `AttributeError` in condition eval (E6) because it *can't distinguish* "this
event legitimately lacks that field" from "the author typo'd" — with no field schema, both look
identical.

**Resolution.** The block-contract registry (§3 C3, §5.5) *is* the schema. A load-time linter
validates: block type exists, required fields present, field values in domain, and — using each
block's declared `reads`/`writes` — that every `when`/`amount` expression references only context
keys some earlier block writes. That last check is exactly what lets us **retire E6**: a `when` that
reads a field the event provably lacks is now a *load error naming the field*, not a silent runtime
skip. The schema also becomes the generated source for the authoring guide, ending code/doc drift.

### 6.10 Migration & backwards compatibility

**Failure.** 22 shipped spells + 6 entity effects + the 550-test suite encode current behaviour. A
big-bang rewrite risks silent behavioural drift no one notices until play.

**Resolution (decided).** Schema-first, then linter, then migrate content (vision §7). Treat the
existing 22 spells as the **conformance corpus**: dual-run old and new interpreters over the same
seeded inputs and assert identical `PipelineResult`s before switching the default. Keep the JSON
`effects` shape loadable via an adapter that reads legacy step dicts as blocks, so content migrates
incrementally, not atomically.

**Route by shape, not by name.** The old vs new interpreter is chosen by **what the file contains** —
a `program` array (or an explicit `"schema_version": 2`) selects the new path; a legacy `effects`
array selects the old one. Do **not** route by filename or by prefixing the spell's `name`
(e.g. `old_fireball`): spells are looked up **by `name`** in the process-global registry and the web
API exposes them by name, so a name/filename prefix would force every reference (creature action
lists, tests, API callers) to change too and couples "which interpreter" to "what the spell is
called." Shape/version detection is the same <10 lines, needs zero renaming, and keys the decision on
the thing that actually differs. The legacy path is deleted once the whole corpus has migrated — it is
a migration scaffold, not a permanent second system.

### 6.11 The data/programming-language line (open, but bounded)

**Failure.** The vision's own open question: how much control flow before this is "Python badly
reimplemented in JSON" that we have to debug? Nested `then`, iterators, conditionals, and expressions
are already a small language.

**Resolution (decided — the hard line holds).** **No author-defined variables, no loops except
bounded iterators over target sets, no author-defined functions.** Expressions stay side-effect-free
and sandboxed (§2.4). Anything needing real computation is a *registered block in Python*, not
author-written control flow. The escape hatch is "add a block," which keeps the debuggable logic in
tested Python, not in data. This is the single most load-bearing constraint: it is what keeps the
whole thing *data* and lets a linter reason about it, and it is why offloading exotica (below) to new
blocks is safe where handing spell authors real Python never would be.

### 6.12 Entity lifecycle & summoning (designed — 2026-08-24)

Ratified in [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md). Vision §4's taxonomy
quietly assumes every block acts on the existing caster/defender pair; a large class of spells
(**the *Summon X* line, Conjure Animals, Animate Dead**, and the exotic tail) *creates combatants*
and reaches outside the pair. This is the design for that; it is the sharpest test of whether "add one
block" absorbs all of 5e, and it feeds directly into the prerequisites list in §7.

**The scope line — two mechanisms, not one (decided, F2).** The most important call. We do **not** make
everything an entity:

- **Real combatants** — things that need HP, a statblock, and a turn (elementals, undead, beasts,
  Find Familiar, Simulacrum) go through the roster/initiative machinery below, via an
  **`entity_lifecycle`** block family.
- **Positioned effects** — hazards and "objects" with no initiative, no independent action, and none
  of a combatant's stats (*Spiritual Weapon*, *Flaming Sphere*, *Moonbeam*, *Spike Growth*,
  *Wall of Fire*) are modelled as **lifetime-bound, movable AoE emitters** the caster operates on their
  own turn — reusing the AoE + lifetime machinery, keeping the initiative/pointer complexity out of the
  common "acts on your turn" cases. This is a sibling block family (§8), designed alongside AoE, not
  part of `entity_lifecycle`.
- **Out of scope (deliberately):** a generic non-entity *object* system (bottles, tables, cover,
  improvised weapons) — noted as scope creep and declined. *Guardian of Faith* is the one entity-like
  positioned effect (an "entity with a fixed heuristic — hit the nearest non-ally in range" rather than
  an AI); deferred until the rudimentary-behaviour hook exists.

**The `summon` block (fixed statblock first, A1).** Priority order: fixed single statblock → many-at-
once (falls out of the §6.6 targeting iterator) → copy-of-a-creature (Simulacrum) deferred.

- **Source (B2):** the created creature is referenced **by name from the creature registry**
  (`{ "summon": "elemental_spirit" }`), exactly as spells are — so the same creatures double as
  pre-placed combatants and aren't bloated into spell files. Inline definition is allowed with
  functional equivalence (same rule as conditions, spell doc C2/§0).
- **Placement (C3):** caster-chosen point(s) **within the spell's range, in unoccupied cells**, reusing
  the AoE target-point mechanism; engine fallback to nearest free cells; a horde fills unoccupied cells
  around the point.
- **Allegiance (C2):** inherits the summoner's `team` and controller flag on creation; an explicit
  `allegiance` field (default "summoner's team") keeps the rare hostile/neutral summon expressible
  without building wild-magic team-flip machinery now.
- **Identity (B1):** created entities get **seed-stable ids** from a deterministic factory
  (`<summoner>::summon::<n>`), not `uuid.uuid4()` — otherwise seeded replays diverge the moment a
  summon appears.

**Initiative (C1, G) — using the 5e ruleset, not 2024.** A summoned creature **rolls its own
initiative** and takes its own turn (5e RAW). The 2024 "acts with/after the summoner" simplification is
*not* used. Concretely:

- Insert **pointer-safe**: a mid-combat insert re-sorts the list, so the insertion must adjust
  `current_turn_index` so it still points at the in-progress creature (it must not hijack, skip, or
  repeat a turn). Removal has the same hazard in reverse.
- **Persist the rolled total.** `InitiativeEntry` already stores `initiative_total` and the entity
  keeps `initiative_roll`; a mid-combat insert compares against those, so post-modifier initiative must
  remain available after the initial order is set.
- **Ties → roll-off** (replacing the current DEX-modifier tiebreak) until resolved; same-team
  "team chooses order" is deferred because it entangles with the controller model.
- **Shared-initiative summons deferred:** *Conjure Woodland Creatures* rolls **one** initiative for the
  whole batch that then take separate turns — a small extra field on the summon block later; only the
  single-creature case is in scope now.

**Lifetime & teardown (D1–D3).** A summon is a grant **owned by a lifetime scope** (§6.3/6.5); here
"revoke" means **removing a combatant from the battle** (roster + initiative + its own ongoing
effects), not stripping a modifier. This is the biggest reason lifetime scopes (§6.3) must land before
the summon family.

- **Three occurrences, two events (decided, D2).** *Death* (reaching 0 HP by any means), *dismissal*
  (willful, not death unless the creature has a self-destruct reason), and *destruction*. **Destruction
  is not a discrete event** — spells worded "when the creature is destroyed" subscribe to **both**
  `ENTITY_DIES` and a new dismissal event; death fires on-death riders before removal, dismissal/expiry
  is silent.
- **Present-but-inert vs truly gone (G) — the key state split.** The engine *already* keeps dead and
  condition-incapacitated combatants in the initiative order and skips their turns
  (`TurnManager._should_skip` + `is_alive`), which is exactly right for **revivify/resurrection**: a
  downed creature **holds its slot and skips turns**. What's *new* is the **truly-gone** path —
  dismissed, banished, disintegrated, a destroyed construct — which must be **removed from the turn
  order** entirely. So teardown has two flavours: *inert* (keep slot, skip) and *remove* (pointer-safe
  delete). ⚠️ This is the one place the summon work touches an **unbuilt subsystem**: death
  saves / dying (CODEBASE_REVIEW §4.5) — we need at minimum a "downed, holds slot, skippable,
  revivable" state distinct from "removed", even if the full death-save mechanic is deferred.
- **Cascade & duration (D2/D3).** Teardown disposes bottom-up (the creature's own grants first, then
  the creature), routed through the same **bounded work queue** as other re-entrant events (§6.4) so a
  summon-that-summoned unwinds with a depth guard. Timed summons (minutes/rounds) **tick on the
  creature's own turn-end** via the lifetime tag and self-dismiss/expire at zero. Scope is **in-combat
  only** (D3): the summoner dying ends concentration-summons automatically; non-concentration summons
  drop when the encounter ends. Cross-encounter persistence is deferred (there is no out-of-combat
  model).

**Control & action economy (A2, E1).** Summons are **ordinary combatants driven by their team's single
`Controller`** (AI or human) — no bespoke summon-AI in the engine; *who chooses a summon's action* is
the same open question as for monsters (out of scope until the AI loop exists). The 5e "spend an action
/ bonus action to command" cost is **deferred** but a `command_cost` field is reserved on the block so
it can be added once "an AI taking a turn" is designed, without a redesign.

**Deferred (recorded so nothing is written out):** Simulacrum / copy-from-creature (F1 — provisionally
a `StatBlock`-template copy at half HP with a seed-stable id), horde shared-initiative field,
command action-economy, the *Guardian of Faith* heuristic-entity, wild-magic team-flips, and
cross-encounter persistence.

**Prerequisites this family needs first (ordered):**
1. **Seed-stable id factory** for created entities (B1).
2. **Pointer-safe initiative insert *and* remove**, persisted post-modifier rolls, and a **roll-off
   tiebreak** (C1, G) — a contained `InitiativeTracker` change.
3. **Lifetime scopes + grant handles** (§6.3), where a summon's revoke removes a combatant (D1).
4. A **"downed but present" entity state** distinct from "removed" (G) — overlaps the death-saves gap.
5. **`ENTITY_DIES` + a dismissal event**, with "destruction" = subscribing to both (D2), drained
   through the bounded work queue (§6.4).

---

## 7. A staged implementation roadmap

Ordered so each stage is independently valuable and testable, and none requires the next.

1. **Schema + linter for the *current* `effects` shape.** No behaviour change; validate the 8 step
   types at load, name errors, and **generate the guide's step tables from the schema** (the guide
   becomes a schema artefact, ending code/doc drift — decided). Unblocks the "new spell" skill (review
   §8) and retires E6. *This is the highest-leverage first step and needs no rewrite.*
2. **Thread `slot_level` + a `scaling` modifier** on damage/iterator blocks → real upcasting (review
   §4.2), the smallest net-new authoring capability.
3. **Targeting/iterator blocks** → split multi-target (Magic Missile done honestly, Scorching Ray,
   Eldritch Blast; review §4.6), folding AoE fan-out into the same mechanism. **Re-plan here** (per the
   roadmap decision) with real code in hand before committing to 4–7.
4. **Unify the two damage/heal/temp-HP/condition/modifier pairs** into superset blocks (§6.2);
   migrate content behind the conformance corpus (shape-routed, §6.10); delete the twins.
5. **Lifetime scopes + grant handles** (§6.3/6.5); reimplement concentration on them; remove the
   name-tag conventions. Resolve per-session registry isolation (E12) here, where it starts to bite.
6. **Inline trigger blocks** (`on_turn`, `on_hit`, `on_damage`) with fresh per-invocation context, the
   `priority` field (§6.8), and the bounded work queue (§6.1/6.4); migrate Vampiric Touch and Armor of
   Agathys to **single files** — the vision's headline result.
7. **`cast_spell` / meta blocks** (Wish, Contingency) once 1–6 are stable — the escape hatch that
   proves the model.

**Entity lifecycle / summoning** is now **designed** (§6.12) rather than a lurking unknown, which
de-risks the stage-4 lock. It slots in as its own stage after the unification, and pulls in a short
list of contained prerequisites (all listed in §6.12):

8. **Entity-lifecycle family** (`summon` + positioned effect-emitters). Prereqs first — a seed-stable
   id factory, pointer-safe initiative insert/remove with persisted rolls + roll-off tiebreak, a
   "downed but present" state distinct from "removed", and an `ENTITY_DIES`+dismissal event pair — then
   the `summon` block (fixed statblock, own initiative, lifetime-scope-owned). Depends on stage 5
   (lifetime scopes) and stage 6 (bounded work queue / triggers). Simulacrum, command economy, and
   shared-batch initiative are explicitly deferred within this stage.

Positioned effect-emitters (hazards like *Moonbeam*/*Spiritual Weapon*, §6.12) are a **sibling of the
targeting/AoE work (stage 3)** — they can land earlier than stage 8 since they need only AoE + lifetime,
not the roster machinery.

Stages 1–3 are pure additions on today's architecture and deliver most of the missing authoring
power. Stages 4–6 are the actual unification. Stage 7 is the proof. **Nothing here starts until an
explicit go — we are deliberately still planning.**

---

## 8. Open questions carried forward

Most of the vision's open questions are now decided (§0), and summoning/entity-lifecycle is designed
(§6.12). What genuinely remains:

- **Positioned effect-emitter sub-design.** §6.12 commits to modelling hazards (*Moonbeam*,
  *Spiritual Weapon*, *Wall of Fire*) as movable, lifetime-bound AoE emitters that act on the caster's
  turn — the *approach* is decided but the block shape (how it moves, how it re-emits each round, how
  the caster operates it) still needs specifying, alongside the stage-3 AoE work.
- **Downed/dying dependency.** §6.12's "present-but-inert vs removed" split needs a "downed, holds
  slot, revivable" state that overlaps the unbuilt death-saves subsystem (CODEBASE_REVIEW §4.5) —
  decide how much of dying/death-saves to build vs. a minimal downed flag when stage 8 is planned.
- **Controller model.** Summons are driven by "the team's single `Controller`" (A2) — that object
  doesn't exist yet; it's part of the future AI/turn-driver work, not this design.
- **User-facing terminology.** Internally settled on `block` / `program`; the *user-facing* label
  ("spell", vs something that also covers weapon/monster actions) is cosmetic and deferred — easy to
  change once the model exists.
- **Nesting, if forced.** `then`/triggers only for now (decided); revisit sub-programs-as-named-
  arguments only if a concrete spell proves triggers insufficient. The resolver being self-referential
  makes adding it cheap later, so we lose nothing by waiting.
- **Concurrent battles / registry isolation.** The process-global registry (E12) is scheduled for
  stage 5 alongside lifetime scopes; open only in the sense of "not yet done."

*Settled and no longer open:* instruction naming (`block`), internal array name (`program`),
back-compat by shape-routing, the no-variables/loops/functions language line, declared context
contracts, conditions as both library + inline with functional equivalence, lifetime scopes for
concentration, AoE as an iterator, upcasting shape, trigger ordering + `priority`, the staged roadmap,
conformance-corpus migration, schema-generated docs, and "no visual editor" — all in §0.

---

_See also: [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md) (the intent), [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md)
§3–§5 (health, gaps, E-debts), [CLAUDE.md](../CLAUDE.md) §3–§4 (architecture & TDD rules), and the
current authoring guide [examples/spells/SPELL_DEFINITION_GUIDE.md](../examples/spells/SPELL_DEFINITION_GUIDE.md)._
