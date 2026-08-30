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
Suite green (**735 tests**); `mypy src/` at a steady 44 pre-existing errors; Black pinned `==23.12.1` (do
**not** run a newer Black on modified files — the dev env resolves 26.x; hand-match style).

**What still runs on the legacy machinery** — and therefore what Phase 3 must retire:

| Legacy piece | Still load-bearing for | Retired by (below) |
|---|---|---|
| `EffectPipeline` (`src/combat/effect_pipeline.py`) | the injection fallback (Colossus) + is the parity oracle | §2 → §4 |
| `BUILTIN_EFFECTS` + `RuleEngine` entity dispatch | `apply_effect` entity effects (conditions test-only; **Colossus** injection) | §2, §3 → §4 |
| the router injection guard (`src/combat/reactive_guard.py`) | keeping Colossus casters/attackers on legacy | §2 |
| `adapter.py` + `fold.py` (transitional shims) | translating legacy step/rule shapes into block programs | §4, after §5 |

**The single knot:** Colossus Slayer's `InjectPipelineDamageStep` mutates the *running weapon attack's*
step list and depends on the legacy pipeline's drain loop. Nothing else needs the legacy pipeline. So
Colossus (§2) is the load-bearing next step — it unblocks deleting the guard, the pipeline, and
`BUILTIN_EFFECTS`.

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
line. A caster/attacker with a pipeline-injecting effect (Colossus) stays on legacy behind the shared guard
`caster_has_injection_effect` (`src/combat/reactive_guard.py`, extracted from `SpellResolver`). Proven by
`tests/test_attack_parity.py` (dual-run weapon attacks, field-for-field equal under one seed; routing pinned).
This is the gateway — weapons and spells now share the one resolution path.

## 2. Migrate Colossus Slayer to an `ATTACK_HIT` trigger — **the load-bearing next step**

Turn `InjectPipelineDamageStep` into a block `trigger` on `ATTACK_HIT` that deals the bonus die, then
**remove the injection guard from both resolvers** and delete `InjectPipelineDamageStep`.

- **Open design decision (settle first): crit-doubling on `ATTACK_HIT`.** The injected step crit-doubles
  today because it lands mid-pipeline while `context["critical_hit"]` is set. A trigger fires as a fresh
  invocation and `AttackHitData` carries no crit flag. **Proposed contract:** add `critical_hit` to
  `AttackHitData` (the block `attack_roll` already has `ctx["critical_hit"]` to populate it), and let the
  Colossus rider's `damage` block double when `event.critical_hit` — a small, general "seed crit from the
  event" affordance, not a Colossus special-case. Prototype against the existing
  `tests/rules/entity_effects/test_inject_pipeline_step.py` behaviour (base die + bonus die, crit doubles
  both) before generalising.
- Colossus reaches an entity via `apply_effect` (a creature feature), so this pairs with §3 (or lands as a
  native rule fold). Once done, `reactive_guard.py` and its use in both resolvers can be deleted.

## 3. Repoint `RuleEngine.apply_effect` onto the block engine

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
- **The injection guard (`reactive_guard.py`) is transitional** — it exists only for Colossus and dies with
  §2.

---

## 8. Verification (whole system)

- `pytest tests/ -q` green (currently 735). The parity harnesses are the safety net for each migration:
  `tests/test_block_parity.py` (spells), `tests/test_attack_parity.py` (weapons),
  `tests/test_global_rules_via_blocks.py` (global rules). Add one per migration in §2–§4.
- `mypy src/` — no new errors beyond the steady 44. `flake8 src/` clean of non-E501 on changed files.
  Black pinned `==23.12.1` — do not run a newer one on modified files.
- For a full-stack check, drive the web app (`serve.bat`) and land a weapon attack and a spell — both now
  resolve on the block engine.
