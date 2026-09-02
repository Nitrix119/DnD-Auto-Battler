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

**The migration is done.** Spells, weapon attacks and rules are all block `program`s run by
the one engine (`src/spells/`). Every translation layer is deleted — `EffectPipeline`,
`fold.py`, `adapter.py`, `BUILTIN_EFFECTS`, `EffectInstance`, `step_schema.py`, and both
legacy authoring shapes (`Rule.triggers`/`effects` and `SpellAction.pipeline_effects`).
Content that is not a block program no longer loads. What remains is **no legacy code at
all**: a short list of carried deviations, some awkwardness worth refining, and the
post-rework feature threads — of which **rich program linting (§4) is the priority**.

---

## 1. The one structural loose end

**`RuleEngine.load_rule` installing rules on the block engine is an inverted dependency.**
`RuleEngine` is now only a loader seam — it reads rule JSON and hands each program to
`spells.global_rules.install_global_rules` / `spells.entity_effects.install_entity_effect` —
plus a carrier for the `effect_registry` that `blocks/state.py` and `SpellResolver` read.
The clean end state is a small native rule loader in `src/spells/` that owns global and
condition install, with no `RuleEngine` at all, and the registry passed explicitly.

Small and low-risk, but it is a *rename-and-move*, not a deletion: worth doing when the rich
linting work (§4) is next in that area, so the two land together rather than churning the
same files twice.

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
- **Rich program linting: a per-field block schema + generated `BLOCK_REFERENCE.md`**
  (vision §5) — the `program` analogue of `STEP_SCHEMAS`, with a drift-tested generated
  reference. Raised as a priority after the §1 slice, where two separate silent failures
  (`petrified`'s dead trigger guard, the marker-only condition clock) were both *shapes the
  validator could have rejected*. The engine's stance is §2.5 "fail loudly": **an authoring
  mistake must not be silently ignored** — today an unrecognised field simply does nothing,
  which is the worst outcome for clarity.

  `src/spells/validate.py` currently covers registered-type / required-arg / arity /
  `context.X` refs / `event.<field>` refs. The catches wanted on top, roughly in value order:

  | Check | Example it catches |
  |---|---|
  | **Unknown/unused field on a block** | `{"block": "damage", "fomula": "1d6"}` — silently deals nothing today |
  | **Type/domain per field** | `when: 4`, `multiplier: "half"`, `duration_rounds: "2"` |
  | **Iterator/arity mismatch beyond the current lint** | a set-producing block feeding a block wanting a single target, and the converse |
  | **Unreachable / dead references** | a `context.X` read before any block writes it; a `then` under a block that never runs one |
  | **Enum values** | `damage_type: "SLASHNG"`, `event: "ATTACK_HITT"` (the latter now caught) |
  | **Nested entity attributes** | `event.defender.typo` — the remaining half of E6 (§5) |

  Design note: the required/optional/domain data belongs on `BlockContract` (beside
  `required_args`) so a block's schema lives with its handler and the generated reference
  cannot drift from it.

---

## 5. Pre-existing debts surfaced (not caused by the rework)

Noticed while working; recorded so they aren't lost, but they predate the block system.

- **Composite damage / per-type resistance** — see §4 and its doc (this is the one with a
  written fix; the others below are just flags).
- **E6 nested entity-attribute typos are still swallowed at runtime.** Load-time validation
  catches a `trigger`'s `event.<field>` typos (`spells.validate._check_event_refs`), but a
  nested `event.defender.typo` still raises `AttributeError` and is skipped — in a trigger
  guard that reads as "did not fire". Needs an Entity-attribute schema — folds naturally into
  the fuller block schema (§4). (See [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md) E6.)
- **No block removes a condition.** The legacy `RemoveConditionType` verb was not ported: no
  shipped content needs it (removal happens by disposing the owning lifetime scope, which
  tears the marker and its mechanics down together). If a future spell must strip a condition
  by *type* rather than by the scope that applied it, that is a new block, not a regression.
- **The spell/effect registry is a process-wide singleton** shared across web sessions — a
  concern once more than one battle runs concurrently. (CODEBASE_REVIEW E12.)

---

## 6. Source-of-truth pointers

- **Phase history / how each piece was built:** [SPELL_SYSTEM_PHASE3_PLAN.md](SPELL_SYSTEM_PHASE3_PLAN.md).
- **Design intent & the block vocabulary:** [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md),
  [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md).
- **Codebase health / older enumerated issues (E-series):** [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md).
- **The code is the source of truth for _what exists_;** this file is the source of truth for
  _what's left_. When they disagree, trust the code and fix this file.
