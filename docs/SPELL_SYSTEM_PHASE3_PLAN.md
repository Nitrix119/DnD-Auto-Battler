# Spell System — Phase 3 Plan & "What's Genuinely Left"

> **Purpose.** Phase 2 of the block-system rewrite is **complete**: every shipped spell, every
> `rules/global/*` rule, and **weapon attacks** now resolve on the block engine (`src/spells/`). This
> document is the authoritative forward plan for **Phase 3** — retiring the legacy machinery and finishing
> the unification — written so a fresh session can take over with only this file and the code. It succeeds
> [SPELL_SYSTEM_PHASE2_PLAN.md](SPELL_SYSTEM_PHASE2_PLAN.md), which is now a completed historical record
> (read it for how the block engine, the fold, and the global-rule install were built). Deeper intent lives
> in [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md) and [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md).

---

## 0. Where we are (2026-08-31)

**On the block engine (`src/spells/`):** all 23 shipped spells; all seven `rules/global/*` rules (damage
resistance/immunity/vulnerability, the nat-20/nat-1 crit rules, concentration break, per-turn refill); and
**weapon attacks** (`AttackResolver` folded — one `[attack_roll, damage…]` path for weapons and spells).
Suite green (**728 tests** after the Colossus migration retired the injection regression tests); `mypy src/`
at a steady 44 pre-existing errors; Black pinned `==23.12.1` (do **not** run a newer Black on modified files
— the dev env resolves 26.x; hand-match style).

**What still runs on the legacy machinery** — and therefore what Phase 3 must retire:

| Legacy piece | Still load-bearing for | Retired by (below) |
|---|---|---|
| `EffectPipeline` (`src/combat/effect_pipeline.py`) | the parity oracle only (no shipped effect injects any more) | §4 |
| `BUILTIN_EFFECTS` + `RuleEngine` entity dispatch | `apply_effect` entity effects that don't cleanly fold — duration/removal-bound effects and (in test-only setups) conditions | §3 → §4 |
| `adapter.py` + `fold.py` (transitional shims) | translating legacy step/rule shapes into block programs | §4, after §5 |

**The single knot — untied (2026-08-31).** Colossus Slayer's `InjectPipelineDamageStep` was the last thing
that needed the legacy pipeline's drain loop. It is now a native `ATTACK_HIT` block trigger (§2 below), the
injection handler and the router guard (`reactive_guard.py`) are deleted, and both resolvers always run on
the block engine. The drain loop in `EffectPipeline.run` is now vestigial (nothing injects) and goes with
the whole pipeline in §4.

**Production reality to keep in mind** (found during Phase 2.9): `apply_effect` is reached in production
*only* via the legacy pipeline's `add_entity_effect` step, whose shipped spells are all folded now — so in
production **nothing applies conditions or creature features via `apply_effect`** (a spell applying
"blinded" adds the `Condition` but never its reactive rule; no loader applies Colossus). Conditions/Colossus
fire only in tests today. Repointing `apply_effect` (§3) is therefore best paired with *wiring conditions to
actually apply* — a real functional gap, not just a migration.

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

**Done (the reactive-rider slice, with §2):** `apply_effect` installs a cleanly-foldable, **permanent**
reactive rider (Colossus) as holder-scoped block triggers on the shared bus via
`src/spells/entity_effects.install_entity_effect`, and returns without filing an `EffectInstance` — the
disable discipline. **Still to do:** duration-bound effects (→ the lifetime clock), `remove_effect(name)` (→
dispose the installed scope), `instance_fields` on non-Colossus riders (→ captured `bindings`), and the real
functional gap — **wiring conditions to actually apply in production** (§0). Those still fall back to legacy.

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
`BUILTIN_EFFECTS` (`src/rules/effects.py`), and the `RuleEngine` entity-effect dispatch; move the `TURN_END`
lifetime tick from `RuleEngine._tick_durations` onto a standalone block-engine clock. Parity-gate each
removal (the removed path must have a block equivalent already green).

## 5. Native content rewrite

Author spells and effects as inline `program`s (no `effects`→adapter translation), and complete the rename
`effects → program`, `step → block` (design §4; "spell" stays user-facing). This retires the transitional
shims for good and is where the schema/linter for the block language (vision §5) is worth building as the
authoring contract for the future "add a spell" skill.

## 6. Deferred design threads (unblocked once the above lands)

- **Upcasting framework** — count/multiplicative scaling (extra darts, summon counts, durations); a
  dedicated design the user has an idea for. [[upcasting-framework-pending]]
- **Entity lifecycle / summoning** — the `entity_lifecycle` family; prerequisites in
  [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md) (seed-stable IDs, pointer-safe initiative,
  "downed but present", `ENTITY_DIES`/dismissal). Positioned emitters (Moonbeam, Spiritual Weapon) ride the
  existing iterators/lifetimes.
- **Meta / `cast_spell`** — a block that invokes the resolver on another spell (Wish, Contingency) +
  copy/counter. The "add one block absorbs the exotic tail" proof; built last.
- **Multi-component damage / per-entry resistance** — one `damage` block currently = one type; a true
  multi-type bundle needs a multi-component block + per-entry resistance. [[damage-typing-per-entry-resistance]]

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

- `pytest tests/ -q` green (currently 728). The parity harnesses are the safety net for each migration:
  `tests/test_block_parity.py` (spells), `tests/test_attack_parity.py` (weapons),
  `tests/test_global_rules_via_blocks.py` (global rules). Add one per migration in §2–§4.
- `mypy src/` — no new errors beyond the steady 44. `flake8 src/` clean of non-E501 on changed files.
  Black pinned `==23.12.1` — do not run a newer one on modified files.
- For a full-stack check, drive the web app (`serve.bat`) and land a weapon attack and a spell — both now
  resolve on the block engine.
