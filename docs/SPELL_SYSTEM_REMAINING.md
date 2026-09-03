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
all** and nothing structural outstanding: a short list of carried deviations, some
awkwardness worth refining, and the post-rework feature threads.

---

## 1. Nothing structural

The last loose end — `RuleEngine`'s inverted dependency — is gone: `src/spells/rules.py`
owns rule install, the plumbing carries `condition_rules` (an `EffectRegistry`) explicitly,
and `src/rules` is pure data. What remains is all in §2–§5 below.

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
- **Double-install of a global rule is the caller's responsibility.** `install_rule`
  subscribes a rule's triggers each time it is called; installing the same rule twice
  double-subscribes it. Production is fine (the web router calls
  `load_rules_from_directory` once), but any new setup path must install a given global
  rule through exactly one route.

---

## 3. Awkwardness we accepted to respect the old system — refinement candidates

Not bugs; places where mirroring the retired machinery left a rough edge. Now that the
translator (`fold.py`) is gone, these can be cleaned up as standalone refinements.

- **`_capture_bindings` distinguishes string bindings (expressions) from non-string
  (already-resolved values).** This lets both native `bindings: {"charmer": "event.caster"}`
  and `apply_entity_rule(instance_fields={"charmer": <Entity>})` work. Not awkwardness to
  remove — it is **load-bearing**: `apply_condition` pre-resolves a spell's bindings against
  the cast invocation and passes the resolved values through this same non-string branch, so
  the condition rider can install on a child whose caster is the conditioned entity (the
  holder-agnostic fix) without the `charmer` binding re-resolving to the wrong entity.
  A string value that was *meant* literally would still be evaluated as an expression — no
  caller does this today. (`src/spells/blocks/triggers.py`.)
- **Marker-only conditions are `program: []`.** `deafened` / `exhaustion` / `grappled` have
  no implementable mechanics yet, so their native form is an empty program (the marker still
  applies). Correct and honest; just note it's intentional, not a stub to "fill in" blindly —
  each needs a real subsystem first (see the `_note` in each file).

---

## 4. Deferred design threads (post-rework features)

Each is its own design.

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
- **Richer program linting — the remaining checks.** The per-field block schema shipped
  (`BlockContract.fields`, `src/spells/validate.py`, drift-guarded by
  `tests/test_block_schema_drift.py`), so unknown args, wrong kinds and domains, enums,
  nested object shapes, unparseable or out-of-sandbox expressions, unknown expression
  roots, and dead `then`s are all caught at load. What is deliberately **not** done:

  | Check | Why it was deferred |
  |---|---|
  | **Context flow analysis** — `context.damage_dealt` read before anything writes it; `save_result` with no preceding `saving_throw`; `requires_hit` with no `attack_roll` | A `trigger`/`lifetime` `then` body runs later in a **fresh invocation with a fresh context**, so lexical order is not execution order. A naive check produces false positives, and in a gate that refuses to load content a false positive is worse than a miss. Needs a per-scope reachability model. |
  | **Nested entity attributes** — `event.defender.typo` | Needs an Entity-attribute schema; E6's remaining half (§5). |
  | **Expression result types** — `when: "event.total"` (an int used as a bool), `value: "'abc'"` | Needs type inference over the expression language. |
  | **"One of these is required"** — `healing` needs `amount` **or** `formula`, and silently returns when neither is present | `Field.required` cannot express an either/or; it wants a block-level constraint. |
  | **Unknown *top-level* keys** on spell/rule/creature JSON, outside any block | The same hole one level up. `_note` already lives there, so the `_`-prefix convention carries over. |

- **`target` is overloaded.** On `trigger` it is an *expression* naming an entity to rebind
  to; on state/healing/global blocks it is a `self`/`current` selector (renamed from
  `caster`/`defender`, which read wrong inside a global rule — §3). The per-block schema
  declares both correctly so nothing breaks, but the remaining half — the `trigger` one —
  should be renamed (`trigger.rebind_target`) to retire the overload entirely: a content
  migration, not a lint.
- **`damage`/`attack_roll`/`saving_throw` have no target selector.** They act on the current
  target; retargeting is the enclosing `trigger`'s job. If a spell ever needs self-damage
  that is a deliberate feature (implement `target` on `damage`), not a lint fix.

---

## 5. Pre-existing debts surfaced (not caused by the rework)

Noticed while working; recorded so they aren't lost, but they predate the block system.

- **Composite damage / per-type resistance** — see §4 and its doc (this is the one with a
  written fix; the others below are just flags).
- **E6 nested entity-attribute typos are still swallowed at runtime.** Load-time validation
  catches a `trigger`'s `event.<field>` typos and unknown expression *roots*, but a nested
  `event.defender.typo` still raises `AttributeError` and is skipped — in a trigger guard
  that reads as "did not fire". Needs an Entity-attribute schema (§4).
  (See [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md) E6.)
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
