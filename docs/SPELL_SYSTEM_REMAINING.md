# Spell/Combat Rework — What's Genuinely Left

> **Purpose.** A forward-looking map of everything the block-system rework still has open:
> the legacy code left to delete, the deliberate deviations and debts to **not lose**, the
> awkwardness we accepted to respect the old system (each a candidate refinement), and the
> design threads deferred until the rework lands. It deliberately omits the *history* of
> now-resolved work — for that, read [SPELL_SYSTEM_PHASE3_PLAN.md](SPELL_SYSTEM_PHASE3_PLAN.md)
> (the phase-by-phase record). Deeper intent lives in
> [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md); the composite-damage gap has its own
> note, [COMPOSITE_DAMAGE_DESIGN.md](COMPOSITE_DAMAGE_DESIGN.md).
>
> Keep this file current: when an item below is done, delete it here (don't accumulate a
> changelog — that's the phase plan's job).

---

## 0. Where the rework stands (one breath)

Every shipped spell, every rule (`rules/global/*`, `rules/entity_effects/**`), and weapon
attacks resolve on the **one** block engine (`src/spells/`). `EffectPipeline` and `fold.py`
are gone; content is authored as native block `program`s. What remains is the **legacy
`RuleEngine` dispatch machinery** (kept alive by one test-only fixture), a short list of
carried deviations, some awkwardness worth refining, and the post-rework feature threads.

---

## 1. Legacy machinery still to delete (the last removal)

These have **no production caller** — they're reached only by the one intentionally-legacy
fixture and the legacy-handler unit tests. The removal is a distinct slice: re-home or
retire those tests, then delete.

- **`BUILTIN_EFFECTS`** (`src/rules/effects.py`) — the `action`-verb handler registry.
- **`RuleEngine` legacy dispatch** — `_dispatch`, `_dispatch_trigger`, `_handle_entity_effects`,
  and `apply_effect`'s `EffectInstance` fallback (the `else` after `install_entity_effect`
  returns `False`).
- **`_tick_durations`** — the legacy effect-instance/condition-marker duration clock (the
  block-engine lifetime clock is already standalone in `src/combat/lifetime_clock.py`).
- **`spider_bite_poison`** (`rules/entity_effects/conditions/spider_bite_poison.json`) — the
  **one deliberately-legacy rule**, a DoT with no creature/spell that applies it. It exists
  only to exercise the machinery above; it is the documented exception in the
  `test_native_rules_parity` invariant. Retire it together with that machinery.
- Tests pinned to the legacy path (retire/convert with the above): the legacy-handler unit
  tests in `tests/rules/test_rules.py` and `tests/rules/test_entity_effects.py`
  (`deal_damage`, `modify_damage`, `force_concentration_check`, `heal_target`,
  `grant_advantage`, … imported from `src.rules.effects`), and the legacy-dispatch tests in
  `tests/test_block_entity_effects.py` (`test_without_damage_processor_falls_back_to_legacy`).

**After that:** author **weapon attacks** as native `program`s so `adapter.py`
(`to_program` / `can_run_on_blocks`, the last legacy-`pipeline_effects` → block compiler)
can be deleted, and then rename `Action.pipeline_effects` away.

---

## 2. Carried deviations & debt — **don't lose these**

Deliberate trades, still live. Each is fine where it is but must be revisited under the
noted condition.

- **Haste ticks its duration on the *caster's* turn, not the hasted ally's.** Native Haste
  is a `lifetime{ kind: concentration, duration_rounds: 10 }` on the caster with the rider
  `holder: "defender"`; the concentration scope carries the clock, so it counts down on the
  caster's `TURN_END`. Same 10 rounds, identical when self-cast; the split-holder machinery
  to tick on the ally's turn was rejected as not worth it. Revisit only if duration accuracy
  on a buffed ally starts to matter. (`examples/spells/haste.json`.)
- **A global-rule install invocation carries `caster=None`, `target=None`** (two
  `# type: ignore[arg-type]` in `src/spells/global_rules.py`). A global rule has no holder —
  its event-modifier/forward effects reach the live *event* entity, not a caster/target. If
  `Invocation.caster`/`target` are ever made `Optional`, this is the reason; until then the
  `type: ignore`s stay.
- **Double-install of a native global is the caller's responsibility.** `RuleEngine.load_rule`
  installs a native rule on the block engine once; calling `install_global_rules` *again* on
  a rule already loaded through the engine double-subscribes it. Production is fine (the web
  router calls only `load_from_directory`), but any new setup path must install a given
  global rule through exactly one route.

---

## 3. Awkwardness we accepted to respect the old system — refinement candidates

Not bugs; places where mirroring the retired machinery left a rough edge. Now that the
translator (`fold.py`) is gone, these can be cleaned up as standalone refinements.

- **The `target: "caster" | "defender"` two-value selector is mis-named for non-combat
  blocks.** `_target(block, inv)` returns `inv.caster` for `"caster"` and `inv.target` for
  *anything else*; `"defender"` just means "the current target slot". For a `TURN_START`
  global (resource refill) or `DAMAGE_DEALT` global (concentration), the trigger rebinds
  `inv.target` via `target: "event.entity"` / `"event.defender"` and the effect block then
  says `target: "defender"` to read it. It works but reads as if there were an attacker and a
  defender when there isn't. *Refinement:* let a forward/state block target an event
  expression directly (e.g. `target: "event.entity"`) and drop the rebind dance, or rename
  the selector to something intent-revealing (`self`/`current`). (Faithful copy of the old
  `fold._EVENT_REBIND`.)
- **A condition's `holder` is baked to `"defender"` in the rule file.** Every
  `rules/entity_effects/conditions/*` trigger hard-codes `holder: "defender"` because the
  shipped spells apply conditions to a target. A spell that applied a condition to *itself*
  (`apply_condition` with `target: "caster"`) would then resolve the holder wrong. No shipped
  spell does this, so it's latent. *Refinement:* make the condition rider holder-agnostic —
  install it on a child invocation whose `caster` **is** the conditioned entity, so the
  default `holder: "caster"` is always correct — and drop the baked `holder` from the files.
- **`RuleEngine.load_rule` installing native rules on the block engine is a transitional
  bridge.** The *legacy* engine reaching into the *new* engine is an inverted dependency we
  accept only until the legacy `RuleEngine` is deleted (§1). The clean end state is a small
  native rule loader that owns global/condition install with no `RuleEngine` involved.
- **`adapter.py`'s `rule_lookup` param is vestigial**, and `can_run_on_blocks` is effectively
  always-true for shipped content (no spell has `pipeline_effects`). Both disappear when
  weapons author natively and `adapter.py` goes (§1).
- **`_capture_bindings` distinguishes string bindings (expressions) from non-string
  (already-resolved values).** This lets both native `bindings: {"charmer": "event.caster"}`
  and `apply_effect(instance_fields={"charmer": <Entity>})` work. Fine, but a string value
  that was *meant* literally would be evaluated as an expression — no caller does this today.
  (`src/spells/blocks/triggers.py`.)
- **Marker-only conditions are `program: []`.** `deafened` / `exhaustion` / `grappled` have
  no implementable mechanics yet, so their native form is an empty program (the marker still
  applies). Correct and honest; just note it's intentional, not a stub to "fill in" blindly —
  each needs a real subsystem first (see the `_note` in each file).

---

## 4. Deferred design threads (post-rework features)

Unblocked once §1 lands; each is its own design.

- **Upcasting framework** — count/multiplicative scaling (extra darts, summon counts, longer
  durations). The user has a specific idea to discuss first. [[upcasting-framework-pending]]
- **Multi-component damage / per-type resistance** — one `damage` block = one type today, and
  the resistance/immunity/vulnerability rules gate on `damage_list[0]` and scale the whole
  packet (wrong for a composite hit). Full write-up and sketched fix (a first-class damage
  packet of typed components): [COMPOSITE_DAMAGE_DESIGN.md](COMPOSITE_DAMAGE_DESIGN.md).
  [[damage-typing-per-entry-resistance]]
- **Entity lifecycle / summoning** — the `entity_lifecycle` family; prerequisites in
  [ENTITY_LIFECYCLE_DECISIONS.md](ENTITY_LIFECYCLE_DECISIONS.md) (seed-stable IDs,
  pointer-safe initiative, "downed but present", `ENTITY_DIES`/dismissal).
- **Meta / `cast_spell`** — a block that invokes the resolver on another spell (Wish,
  Contingency) + copy/counter. The "add one block absorbs the exotic tail" proof; built last.
- **Fuller block schema + generated `BLOCK_REFERENCE.md`** (vision §5) — a per-field
  required/optional/domain schema for the block vocabulary (the `program` analogue of
  `STEP_SCHEMAS`), with a drift-tested generated reference. Also the natural home for the
  deferred **E6** debt (below). The current validator (`src/spells/validate.py`) already
  covers registered-type / required-arg / arity / context-ref — the highest-value catches.

---

## 5. Pre-existing debts surfaced (not caused by the rework)

Noticed while working; recorded so they aren't lost, but they predate the block system.

- **Composite damage / per-type resistance** — see §4 and its doc (this is the one with a
  written fix; the others below are just flags).
- **E6 nested entity-attribute typos are still swallowed at runtime.** Load-time validation
  catches `event.<field>` typos, but a nested `event.defender.typo` still raises
  `AttributeError` and is skipped. Needs an Entity-attribute schema — folds naturally into
  the fuller block schema (§4). (See [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md) E6.)
- **The spell/effect registry is a process-wide singleton** shared across web sessions — a
  concern once more than one battle runs concurrently. (CODEBASE_REVIEW E12.)
- **`src/rules/rule_engine.py` carries pre-existing flake8** (E402 module-level imports after
  the logger, one F401 `SAFE_BUILTINS`). Left alone to avoid unrelated churn; clean it when
  that file is next substantially edited (likely the §1 dispatch removal).

---

## 6. Source-of-truth pointers

- **Phase history / how each piece was built:** [SPELL_SYSTEM_PHASE3_PLAN.md](SPELL_SYSTEM_PHASE3_PLAN.md).
- **Design intent & the block vocabulary:** [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md),
  [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md).
- **Codebase health / older enumerated issues (E-series):** [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md).
- **The code is the source of truth for _what exists_;** this file is the source of truth for
  _what's left_. When they disagree, trust the code and fix this file.
