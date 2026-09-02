# Spell System — Phase 3 Plan & "What's Genuinely Left"

> **Purpose.** Phase 2 of the block-system rewrite is **complete**: every shipped spell, every
> `rules/global/*` rule, and **weapon attacks** now resolve on the block engine (`src/spells/`). This
> document is the authoritative forward plan for **Phase 3** — retiring the legacy machinery and finishing
> the unification — written so a fresh session can take over with only this file and the code. It succeeds
> [SPELL_SYSTEM_PHASE2_PLAN.md](SPELL_SYSTEM_PHASE2_PLAN.md), which is now a completed historical record
> (read it for how the block engine, the fold, and the global-rule install were built). Deeper intent lives
> in [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md) and [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md).
>
> **This document is now mostly a phase *record*.** For the concise, current view of what remains — the last
> deletions, carried deviations to not lose, and known awkwardness worth refining — start with
> [SPELL_SYSTEM_REMAINING.md](SPELL_SYSTEM_REMAINING.md).

---

## 0. Where we are (2026-08-31)

> **Update (2026-09-02):** §5 is landed for the **whole spell corpus** — all 23 shipped spells are now
> native block `program`s (validated at load; parity-gated against frozen legacy snapshots), and 5
> two-file entity-effect rules were absorbed and deleted. See [§5a](#5a-foundation--pilot--done-2026-09-02)
> and [§5b](#5b-full-spell-corpus-migration--done-2026-09-02). Suite **831 green**; `mypy src/` at 41.
> `adapter.to_program` now backs only **weapon attacks**; `fold.rule_to_trigger_blocks` backs only
> **conditions/global rules**; the `add_entity_effect`-fold path is dead from spells (a §4-removal candidate).

**On the block engine (`src/spells/`):** all 23 shipped spells; all seven `rules/global/*` rules (damage
resistance/immunity/vulnerability, the nat-20/nat-1 crit rules, concentration break, per-turn refill); and
**weapon attacks** (`AttackResolver` folded — one `[attack_roll, damage…]` path for weapons and spells).
Suite green (**728 tests** after the Colossus migration retired the injection regression tests); `mypy src/`
at a steady 44 pre-existing errors; Black pinned `==23.12.1` (do **not** run a newer Black on modified files
— the dev env resolves 26.x; hand-match style).

**What still runs on the legacy machinery** — and therefore what Phase 3 must retire:

| Legacy piece | Still load-bearing for | Retired by (below) |
|---|---|---|
| ~~`EffectPipeline`~~ | **deleted (2026-08-31)** — one resolution path now; `can_run_on_blocks` is a loud validator | ✅ §4 |
| ~~`fold.py`~~ | **deleted (2026-09-03, §5f)** — every spell/rule is native, so nothing translates legacy shapes any more | ✅ §5f |
| `BUILTIN_EFFECTS` + `RuleEngine` legacy dispatch + `_tick_durations` | only `spider_bite_poison` (a test-only legacy fixture) and the legacy-handler unit tests; **no production caller** | next slice |
| `adapter.py` | still compiles **weapon attacks** into `[attack_roll, damage]` blocks (no longer fold-dependent) | after weapons author natively |

**The single knot — untied (2026-08-31).** Colossus Slayer's `InjectPipelineDamageStep` was the last thing
that needed the legacy pipeline's drain loop. It is now a native `ATTACK_HIT` block trigger (§2 below), the
injection handler and the router guard (`reactive_guard.py`) are deleted, and both resolvers always run on
the block engine. The drain loop in `EffectPipeline.run` is now vestigial (nothing injects) and goes with
the whole pipeline in §4.

**Production reality** (found during Phase 2.9): `apply_effect` is reached in production *only* via the
legacy pipeline's `add_entity_effect` step, whose shipped spells are all folded now. The functional gap
this exposed — a spell applying "blinded" added the `Condition` marker but never its reactive rule, so
every condition except charm was mechanically dead in production — is now **closed (2026-08-31)**: the
`apply_condition` block installs the condition's reactive rule under a lifetime scope (§3 below). Colossus
is likewise a native trigger (§2), and **§3 is now complete** — every cleanly-foldable entity effect
applied via `apply_effect` (with a damage_processor) installs on the block engine, durations and removal
included. What remains on the legacy `RuleEngine` dispatch: effects applied without a damage_processor or
with an untranslatable action, plus the `TURN_END` tick *driver* (`_tick_durations`), which §4 moves onto a
standalone clock.

---

## 1. Unify the attack path — ✅ DONE (2026-08-31)

`AttackResolver` routes weapon attacks through the block engine (`adapter.to_program` + `evaluator.resolve`
over `[attack_roll, damage…]`); the block `attack_roll` already mirrored the legacy attack step line for
line. (Originally, a caster/attacker with a pipeline-injecting effect (Colossus) stayed on legacy behind the
shared guard `caster_has_injection_effect` in `src/combat/reactive_guard.py` — **superseded by §2**: Colossus
is now a block trigger, the guard is deleted, and both resolvers always run on the block engine.) Proven by
`tests/test_attack_parity.py` (dual-run weapon attacks, field-for-field equal under one seed; routing pinned).
This is the gateway — weapons and spells now share the one resolution path.

## 2. Migrate Colossus Slayer to an `ATTACK_HIT` trigger — ✅ DONE (2026-08-31)

Colossus Slayer is now an ordinary `ATTACK_HIT` block `trigger`, and the whole injection mechanism is gone.
What landed:

- **Crit-doubling contract — "auto-seed from the event" (chosen).** `AttackHitData` gained a
  `critical_hit` field, set at both `ATTACK_HIT` emit sites (`spells/blocks/rolls.py`,
  `combat/effect_pipeline.py`). The `trigger` handler (`spells/blocks/triggers.py`) seeds that flag into the
  fresh firing context, so **any** `damage` block in a `then` body doubles on a crit exactly as a mid-cast
  damage block does — a general affordance, not a Colossus special-case. Proven in isolation by
  `tests/test_block_trigger_context.py`.
- **Dynamic damage type.** The block `damage` handler now accepts an *expression* for `damage_type`
  (resolved at fire time), so the rider deals the weapon's own type via
  `event.action.primary_damage_type`; `Action.primary_damage_type` falls back to `damage[0]` for a weapon
  whose steps are built on the fly. Colossus (`rules/entity_effects/colossus_slayer.json`) now uses the
  already-foldable `DealDamage` action.
- **Install seam (the §3 slice).** `RuleEngine.apply_effect` now installs a cleanly-foldable **permanent**
  reactive rider as holder-scoped block triggers on the shared bus (`src/spells/entity_effects.py`,
  mirroring `install_global_rules`), instead of filing an `EffectInstance` for legacy dispatch — the
  disable-the-legacy-path discipline, so it fires once. Duration/removal-bound effects and any
  untranslatable effect still fall back to legacy (the broader §3).
- **Deletions.** `reactive_guard.py`, both resolver guard call sites, `inject_pipeline_damage_step`, and its
  two `BUILTIN_EFFECTS` aliases are gone. Both resolvers always run on the block engine.
- Coverage: `tests/rules/entity_effects/test_colossus_slayer.py` (block-native end-to-end),
  `tests/test_block_trigger_context.py` (crit-seed + dynamic type), routing pinned in
  `tests/test_attack_parity.py`. Suite green (728).

## 3. Repoint `RuleEngine.apply_effect` onto the block engine — **partially done (2026-08-31)**

**Done — the reactive-rider slice (with §2):** `apply_effect` installs a cleanly-foldable, **permanent**
reactive rider (Colossus) as holder-scoped block triggers on the shared bus via
`src/spells/entity_effects.install_entity_effect`, returning without filing an `EffectInstance`.

**Done — conditions wired to actually apply (2026-08-31):** the `apply_condition` block
([src/spells/blocks/state.py](../src/spells/blocks/state.py)) now, after adding the marker, looks up the
condition's reactive rule (`inv.env.rule_engine.effect_registry`, keyed by `ConditionType.value`) and
installs it as holder-scoped triggers **owned by a lifetime scope** — an enclosing scope (a concentration
spell) if present, else a rounds scope on the target keyed to the condition's `duration`, else a permanent
scope disposed only on dispel. The scope owns both the marker's revoke handle and the rider's unsubscribe,
so expiry (`tick_lifetimes`), concentration loss (`end_concentration`), and dispel (`Entity.remove_condition`
→ `scope.dispose()`) tear the mechanics down with the condition. The marker's `rounds_remaining` is left
`None` so `_tick_durations` doesn't double-count. Degrades to marker-only when unwired. A `bindings` field
carries Charmed-style `instance_fields`. The whole condition library is now live in production; covered by
[tests/test_condition_wiring.py](../tests/test_condition_wiring.py). Suite green (738).

**Done — the general repoint (2026-08-31):** `install_entity_effect` now owns its triggers with a
`LifetimeScope` on `entity.lifetimes` keyed to `rule.name`. A `duration_rounds` rule expires on the
holder's turn via `Entity.tick_lifetimes`; a rule with no duration is a permanent scope. `remove_effect`
disposes the scope by name (`Entity.remove_effect` now handles both the block scope and the legacy
string-tags). So **every cleanly-foldable entity effect applied via `apply_effect` with a damage_processor
now installs on the block engine** — durations and removal included (proven with the poison DoT,
[tests/test_block_entity_effects.py](../tests/test_block_entity_effects.py)). `instance_fields` → `bindings`
was already handled. **§3 is complete.** What stays on legacy dispatch: an effect with an untranslatable
action, or one applied without a damage_processor.

Translate an entity effect to a `lifetime{ trigger… }` program via `fold.rule_to_trigger_blocks` (every
condition-library block and translator already exists — see Phase 2.9) and install it through the evaluator,
instead of stashing an `EffectInstance` in `entity.active_effects`. Reuse the **disable-the-legacy-path**
discipline (as the global-rule install does) to avoid double-application while both dispatch paths coexist.
Handle `remove_effect(name)` → dispose the installed scope, duration → the lifetime clock, and
`instance_fields` → the trigger's captured `bindings` (the Charm Person mechanism). **Pair with wiring
conditions to actually apply in production** (the functional gap in §0). This brings the whole condition
library + Colossus onto the block engine and empties `active_effects` of reactive rules.

## 4. Delete the legacy machinery

Once §2 and §3 leave nothing routing to them: delete `EffectPipeline`, `adapter.py`, `fold.py`,
`BUILTIN_EFFECTS` (`src/rules/effects.py`), and the `RuleEngine` entity-effect dispatch. Parity-gate each
removal (the removed path must have a block equivalent already green).

- **✅ Standalone lifetime clock (2026-08-31).** The `TURN_END` lifetime tick is off
  `RuleEngine._tick_durations` and onto a self-contained subscriber
  ([src/combat/lifetime_clock.py](../src/combat/lifetime_clock.py) `install_lifetime_clock`), installed once
  per battle by `CombatSystem.start_combat`. `_tick_durations` no longer calls `Entity.tick_lifetimes` (it
  now ticks only the legacy effect-instance/condition-marker durations), so the block engine's
  duration/concentration clock no longer depends on the legacy rule engine — that inverted dependency is
  gone, and `_tick_durations`/`RuleEngine` dispatch can be deleted without taking the clock with them. Suite
  744 green; the three duration/concentration-expiry tests now install the clock directly.
- **✅ `EffectPipeline` deleted (2026-08-31).** The ~750-line legacy interpreter and its `PipelineResult`
  are gone. `SpellResolver.resolve` now has **one path** — the block engine — with `can_run_on_blocks`
  flipped from a silent router (fall back to legacy) into a **loud validator** (raise on a spell the block
  engine can't express). The one non-legacy coupling — `effective_damage_formula`, which the block engine
  imported from the pipeline module — was rehomed to [src/spells/scaling.py](../src/spells/scaling.py). The
  five parity harnesses became block-only tests (the two behaviours whose only oracle was the pipeline —
  save-honours-disadvantage and temp-HP-from-an-expression — got block-engine tests first). Suite 734 green;
  `mypy src/` down to 41 (the pipeline's own errors went with it).
- **Still to delete (the big removals):** `adapter.py`/`fold.py` (needs §5's native content so spells stop
  being translated at cast time), `BUILTIN_EFFECTS` + `RuleEngine` entity dispatch (once no non-foldable
  effect and no no-`damage_processor` path remains), and `_tick_durations` itself.

## 5. Native content rewrite

Author spells and effects as inline `program`s (no `effects`→adapter translation), and complete the rename
`effects → program`, `step → block` (design §4; "spell" stays user-facing). This retires the transitional
shims for good and is where the schema/linter for the block language (vision §5) is worth building as the
authoring contract for the future "add a spell" skill.

### 5a. Foundation + pilot — ✅ DONE (2026-09-02)

The native read path, a load-time block validator, and three migrated spells landed as the first slice.
What shipped:

- **Native read path.** `Action`/`SpellAction` gained a `program` field
  ([src/models/action.py](../src/models/action.py)). A spell is *native* when `program` is non-empty
  (parsed by `src.spells.block.parse_program`, run directly), *legacy* when only `pipeline_effects` is
  (still adapter-translated). The loader reads either
  ([src/loaders/stat_block_loader.py](../src/loaders/stat_block_loader.py)); `SpellResolver.resolve`
  branches on `action.program`, and the legacy `can_run_on_blocks` loud-validator now guards **only** the
  legacy branch ([src/combat/spell_resolver.py](../src/combat/spell_resolver.py)). Fan-out is auto-detected
  from the program (`evaluator._has_set_consumer`), so native AoE authors an explicit `for_each_target`.
- **Load-time block validator.** [src/spells/validate.py](../src/spells/validate.py) `validate_program`
  elevates the runtime arity linter (`lint.py`) to the loader boundary and adds: unknown-block, missing
  **required arg**, and bad `context.X`-ref checks. `BlockContract` gained a general `required_args`
  ([src/spells/contract.py](../src/spells/contract.py)), annotated on the core blocks (damage→formula/type,
  saving_throw→attribute/dc, trigger→event, the state blocks). Registry-driven, no `if/elif` on type.
- **Three spells migrated (parity-gated).** Fire Bolt (single-target), Fireball (AoE, explicit
  `for_each_target` + `roll_once`), and **Vampiric Touch inlined into one file** — its granted repeatable
  action and concentration heal-rider are now a native `lifetime{ grant_action, trigger }`, absorbing and
  **deleting** `rules/entity_effects/vampiric_touch.json`. Proven native-==-legacy field-for-field under
  five seeds each by [tests/test_native_program.py](../tests/test_native_program.py); validator unhappy
  paths by [tests/test_validate_program.py](../tests/test_validate_program.py). Suite **757 green**;
  `mypy src/` steady at 41.

### 5b. Full spell-corpus migration — ✅ DONE (2026-09-02)

The remaining **20 spells** are now native `program`s — the whole shipped corpus (23) is off the legacy
`effects` vocabulary. What shipped:

- **Guardrail first.** A snapshot parity harness freezes each spell's pre-migration legacy shape in
  `tests/legacy_snapshots/*.json` (effects + the referenced entity-effect rule for persistent spells);
  [tests/test_native_corpus_parity.py](../tests/test_native_corpus_parity.py) resolves each migrated
  spell's native program and its folded snapshot under four seeds and asserts identical result fields, with
  a sentinel that fails until every spell is native. `test_block_parity.py`'s corpus smoke tests are now
  native-aware (`parse_program` when `program` is set).
- **15 instantaneous spells** (8 flat single-target + 7 set-targeted wrapped in an explicit
  `for_each_target`) migrated as pure `effects`→`program` / `type`→`block` renames — delegated to two
  Sonnet subagents, each gated on the parity harness. Per-spell structure tests
  (`test_spells.py`/`test_save_outcomes.py`/`test_multi_target.py`) were made native-aware via
  `_damage_entries`/`_save_entries`/`_block_types` helpers.
- **5 persistent spells** (shield_of_faith, armor_of_agathys, longstrider, haste, charm_person) **inlined**
  into self-contained programs (`lifetime`/`trigger`/`grant_action`/`apply_condition`), absorbing and
  **deleting** their 4 `rules/entity_effects/*.json` files (charm_person uses the native condition-wiring
  path, keeping the shared `conditions/charmed.json`). The obsolete adapter fold-shape/routing tests were
  removed; the dedicated haste/longstrider effect tests were rewired to install the rider by *casting the
  spell* (native path), preserving their granular coverage.
- **Result:** `rules/entity_effects/` now holds only `colossus_slayer.json` + `conditions/`. The
  `add_entity_effect`-fold path in `fold.py`/`adapter.py` is **spell-userless** (a §4-removal candidate);
  `adapter.to_program` stays for weapon attacks; `fold.rule_to_trigger_blocks` stays for conditions/globals.
  Suite **831 green**; `mypy src/` steady at 41.

### 5e. Native **rules** — full corpus + the library wiring fix — ✅ DONE (2026-09-03)

The rest of the rule corpus is native, and — the one non-mechanical part — native global rules now install
on the block engine in **library/`CombatSystem`** usage, not only under the web router.

- **Corpus migrated (parity-gated).** All 7 globals (added crit/crit-miss/concentration/refill) and all
  status conditions are native `program`s, authored to mirror the fold output exactly (behaviour identical).
  The 3 marker-only conditions (deafened/exhaustion/grappled — no implementable mechanics yet) became an
  explicit empty `program: []`. `test_native_rules_parity.py`'s `PILOT` covers the whole set; the sentinel is
  green. The 11 dead-simple single-trigger files were delegated to a Sonnet subagent, gated on the parity test.
- **`spider_bite_poison` stays legacy — deliberately.** It has **no production caller** (no creature/spell
  applies it), so it never routes through `fold` in production and does not block `fold.py`'s deletion. It
  remains the fixture for the legacy `RuleEngine` dispatch unit tests (which exercise machinery deleted later
  in §4, not now).
- **The library wiring fix (the genuinely tough part).** `install_global_rules` was called **only** by the web
  router, so native globals would have been silently dead in `CombatSystem`/library usage. Fixed at the seam:
  `RuleEngine.load_rule` now routes a **native** rule to the block engine (via `install_global_rules([rule], …)`,
  lazy-imported) instead of the legacy dispatch, so `load_from_directory("rules/global")` installs them
  everywhere. The web router's explicit install + disable step is gone (a debt reduction — the transitional
  §4.7 repoint retires). `RuleEngine._native_rules` tracks them for inspection.
- **Value vs. expression bindings.** `apply_effect(instance_fields={"charmer": <Entity>})` passes resolved
  **values**, whereas a native trigger's `bindings` are **expressions**; `_capture_bindings`
  ([blocks/triggers.py](../src/spells/blocks/triggers.py)) now passes a non-string binding straight through and
  only `evaluate`s strings, so both contracts work.
- **Test fallout** (all repointed, not faked): ~35 tests drove crit/concentration/refill/conditions through the
  legacy dispatch. Fixes: concentration/refill/crit tests rely on `load_from_directory` auto-installing natives;
  concentration save patches moved from `src.rules.effects.roll_d20` to `src.spells.blocks.global_effects.roll_d20`
  (the block engine's roll); condition tests (blinded/charmed) gained a `damage_processor` so `apply_effect`
  installs natively; loader-contract and fold-translation tests assert the native shape or use a frozen legacy
  snapshot. Suite **852 green**; `mypy src/` steady at 41.

- **`fold.py` is now production-unused.** Every shipped spell and rule is native; `fold.rule_to_trigger_blocks`
  is reached only by the transitional **tests** (the parity oracle + the fold unit tests). Its deletion is
  §5f below.

### 5f. Delete `fold.py` + the transitional shims it fed — ✅ DONE (2026-09-03)

`fold.py` (the last `action`-verb→block translator) is **deleted**. With it went its dead consumers:

- **Install seams simplified to native-only.** `install_global_rules` / `install_entity_effect` /
  `apply_condition`'s rider install no longer branch on a fold fallback — a rule without a `program` is simply
  not installed on the block engine (`install_entity_effect` returns `False` → the caller keeps a legacy rule
  on the legacy dispatch). `block_eligible` collapses to "is native"; the condition rider dropped its now-unused
  `holder` plumbing (holder is baked into the native trigger blocks).
- **`adapter.py` stays** (it still compiles weapon attacks' `[attack_roll, damage]` steps), with its dead
  `add_entity_effect`→`lifetime` fold branch removed; `rule_lookup` is now vestigial (kept only for caller
  signatures).
- **Transitional parity harnesses retired.** `test_native_corpus_parity`, `test_native_program`, and the fold
  unit tests in `test_block_event_mod` proved *native == old-legacy* during the migration — with legacy gone
  there is nothing to compare against, so they're deleted (behaviour stays covered by the per-spell/per-rule
  behavioural suites). `test_native_rules_parity` became a **native-invariant** test (every rule file is native
  + valid, `spider_bite_poison` the one documented legacy exception). `test_block_entity_effects` now exercises
  the §3 duration-bound block install with an inline **native** DoT rule (the legacy-fallback case still uses
  `spider_bite_poison`). `TestNoDoubleApplication` was dropped — native globals can't double-apply.
- **Still standing (the next removal):** `BUILTIN_EFFECTS` (`src/rules/effects.py`), the `RuleEngine` legacy
  entity/global dispatch (`_dispatch`, `_handle_entity_effects`, `apply_effect`'s `EffectInstance` fallback),
  and `_tick_durations` — still reached by `spider_bite_poison` and the legacy-handler unit tests, so their
  removal is a distinct slice (retire/re-home those tests, then delete). Then rename `Action.pipeline_effects`
  away once weapons author natively and `adapter.py` can go.

Suite **749 green**, 1 skipped (the `spider_bite_poison` invariant exception); the drop from 852 is the ~100
retired transitional parity cases. `mypy src/` steady at 41.

### 5d. Native **rules** — foundation + pilot — ✅ DONE (2026-09-03)

The rule content — `rules/global/*`, `rules/entity_effects/conditions/*`, and `colossus_slayer.json` — was
the last live consumer of `fold.rule_to_trigger_blocks` (the `action`-verb `Rule` shape, folded to trigger
blocks at install time). This slice builds the native read path and migrates a pilot, mirroring §5a:

- **Native read path.** `Rule` gained a `program` field ([src/rules/rule.py](../src/rules/rule.py)); a rule
  is *native* when it carries a block `program` and then leaves `triggers`/`effects` empty (so it is never on
  the legacy dispatch). `RuleLoader.from_dict` reads either shape and validates a native program via
  `spells.validate.validate_program` at the loader boundary (the `program` analogue of the legacy E6 field
  check). The three install seams branch native-or-fold: `install_global_rules`
  ([global_rules.py](../src/spells/global_rules.py), `block_eligible` now also passes any native rule),
  `install_entity_effect` ([entity_effects.py](../src/spells/entity_effects.py)), and the condition rider
  install ([blocks/state.py](../src/spells/blocks/state.py)).
- **Parity guardrail.** [tests/test_native_rules_parity.py](../tests/test_native_rules_parity.py) freezes each
  migrated rule's pre-migration legacy shape under `tests/legacy_snapshots_rules/` and asserts the live native
  `program` parses to exactly the fold's output (with the args each seam passes), plus a sentinel that fails
  until every pilot rule is native.
- **Pilot migrated (parity-gated):** the 3 damage-modifier globals (resistance/immunity/vulnerability),
  `colossus_slayer`, and the `restrained` condition — authored to mirror the fold output exactly (holder baked
  for the condition, `priority: 0` for globals), so behaviour is identical. Legacy-dispatch-only tests for
  these rules were repointed to the block-engine/native path or to an inline legacy rule where they document
  the still-real disable discipline; the superseded legacy-path Colossus tests were retired (behaviour is
  covered natively by `test_colossus_slayer.py`). Suite **834 green**; `mypy src/` steady at 41.

**Remaining §5 slices (follow-on):**

- **~~Migrate the rest of the rule corpus~~ — ✅ DONE (§5e).** All globals and conditions are native;
  `spider_bite_poison` stays legacy by design (test-only, no production caller).
- **~~Delete `fold.py`~~ — ✅ DONE (§5f).** The translator and its dead consumers/transitional harnesses are
  gone; `adapter.py`'s fold branch stripped (it stays for weapon attacks).
- **Delete the legacy `RuleEngine` machinery** (the remaining §4 big removal): `BUILTIN_EFFECTS`
  (`src/rules/effects.py`), the legacy `_dispatch`/`_handle_entity_effects`/`apply_effect` `EffectInstance`
  fallback, and `_tick_durations`. Reached now only by `spider_bite_poison` and the legacy-handler unit tests —
  re-home or retire those, then delete. Afterwards, author weapons natively so `adapter.py` can go and
  `Action.pipeline_effects` can be renamed away.
- **Fuller block schema + generated `BLOCK_REFERENCE.md`** (vision §5): a per-field required/optional/domain
  schema for the block vocabulary (the `program` analogue of `STEP_SCHEMAS`), with a drift-tested generated
  reference. Deferred deliberately from the pilot — the current validator covers registered-type / required-arg
  / arity / context-ref, the highest-value silent-failure catches; the full field schema is its own slice and
  the natural home for the deferred **E6** debt (vision §5).

## 6. Deferred design threads (unblocked once the above lands)

- **Upcasting framework** — count/multiplicative scaling (extra darts, summon counts, durations); a
  dedicated design the user has an idea for. [[upcasting-framework-pending]]
- **Entity lifecycle / summoning** — the `entity_lifecycle` family; prerequisites in
  [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md) (seed-stable IDs, pointer-safe initiative,
  "downed but present", `ENTITY_DIES`/dismissal). Positioned emitters (Moonbeam, Spiritual Weapon) ride the
  existing iterators/lifetimes.
- **Meta / `cast_spell`** — a block that invokes the resolver on another spell (Wish, Contingency) +
  copy/counter. The "add one block absorbs the exotic tail" proof; built last.
- **Multi-component damage / per-entry resistance** — one `damage` block currently = one type, and the
  resistance/immunity/vulnerability rules gate on `damage_list[0]` and scale the whole packet (wrong for a
  composite hit). A true fix is a first-class "damage packet" wrapping typed components, applying each
  defender modifier per type. Full write-up: [COMPOSITE_DAMAGE_DESIGN.md](COMPOSITE_DAMAGE_DESIGN.md).
  [[damage-typing-per-entry-resistance]]

---

## 7. Carried deviations & debt (don't lose these)

- **Haste ticks its duration on the caster's turn**, not the ally's (folds via the Vampiric Touch
  concentration+duration pattern). Accepted (2026-08-30): same 10 rounds, identical when self-cast; the
  split-holder machinery to tick on the ally's turn was rejected as debt in the transitional fold. If Haste
  is ever authored natively, revisit.
- **`global_rules.py` (permanent) imports `fold.rule_to_trigger_blocks` from the transitional `fold.py`.**
  When `fold.py` is deleted (§4/§5), that translation needs a new home — or global rules become native
  `program`s and need none.
- **Double-application safety lives in the caller.** Migrated rules are installed on the block engine *and*
  disabled on the rule engine by the web handler; any new global-rule/entity-effect loader must do the same
  disable, or effects apply twice.
- **A global-rule install invocation has no caster/target** (`None`, with a `type: ignore`) — its
  event-modifier/forward effects reach the event entity, not a holder. If `Invocation.caster`/`target` ever
  become `Optional`, this is why.
- **The `EffectPipeline.run` drain loop is now vestigial.** It snapshots the step list and drains any
  mid-run injected steps back off the shared action — machinery that existed only for Colossus's injection.
  Nothing injects any more; the loop is harmless and is removed wholesale with the pipeline in §4 (left in
  place now to keep the parity oracle byte-identical).
- **A permanent reactive rider installed via `apply_effect` has no lifetime scope**, so it can't be torn
  down by `remove_effect` — fine for Colossus (a permanent racial feature, never removed), but the general
  removal path is part of the remaining §3.

---

## 8. Verification (whole system)

- `pytest tests/ -q` green (currently 734). The parity harnesses are the safety net for each migration:
  `tests/test_block_parity.py` (spells), `tests/test_attack_parity.py` (weapons),
  `tests/test_global_rules_via_blocks.py` (global rules). Add one per migration in §2–§4.
- `mypy src/` — no new errors beyond the steady 44. `flake8 src/` clean of non-E501 on changed files.
  Black pinned `==23.12.1` — do not run a newer one on modified files.
- For a full-stack check, drive the web app (`serve.bat`) and land a weapon attack and a spell — both now
  resolve on the block engine.
