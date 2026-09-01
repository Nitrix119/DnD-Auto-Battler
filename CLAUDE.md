# CLAUDE.md

Guidance for AI agents (and humans) working in this repository. Read this file in
full before making changes. It is the source of truth for **how** we build here;
the code is the source of truth for **what** currently exists.

For the deeper design intent behind the spell/combat engine, read
[docs/SPELL_SYSTEM_VISION.md](docs/SPELL_SYSTEM_VISION.md). For the current health
of the codebase and the open repair roadmap, read
[docs/CODEBASE_REVIEW.md](docs/CODEBASE_REVIEW.md).

---

## 0. How to use and maintain this file

This document is designed to **grow over time**. When a mistake is made and a
lesson is learned, the fix is not only in the code — it is also a new rule here so
the mistake is not repeated.

- Keep entries **short, imperative, and scannable**. Prefer a one-line rule over a
  paragraph; if a rule needs justification, add a parenthetical _(why: ...)_.
- **Do not delete history.** Supersede a rule by editing it and noting the change,
  rather than silently rewriting the project's reasoning.
- New durable lessons go in [§9 Lessons Learned](#9-lessons-learned-append-only) as
  dated, append-only entries. Promote stable lessons up into the relevant section.
- Keep the commands in [§7](#7-stack--commands) exact — agents rely on them. Fix a
  wrong command the moment you find it.
- If two rules conflict, the more specific one wins; flag the conflict to the user.

---

## 1. Project overview

**D&D Auto-Battler** — a D&D 5e combat simulator. The engine is **Python** (`src/`),
usable as a library or through a FastAPI web app (`web/`) with a browser JS client
(`web/static/js/`). **Creatures, spells, and rules are JSON data** — most content is
added without touching Python.

The ambition (see [the vision doc](docs/SPELL_SYSTEM_VISION.md)): a **massively
flexible, generic engine** that can express the vast, messy diversity of D&D combat
through composable, data-defined effects rather than per-spell special-casing.

**Domain boundaries / principles:**

- **Data-driven first.** A new spell should be a JSON file; a new *mechanic* a small,
  registered effect handler — never a branch on a spell's name.
- **Model the rules honestly, and where you can't yet, decline loudly** rather than
  fake it (an unsupported step logs and is skipped; an image-only case should say so).
- **Determinism on demand.** All randomness flows through one seedable RNG
  (`dice.seed_rng`) so a battle can be reproduced exactly.

---

## 2. Core principles

Non-negotiable. Every change should be justifiable against these.

1. **Modularity first.** Small, single-responsibility units with narrow, well-named
   interfaces. A reader should understand a module without reading the whole system.
2. **Flexibility over hard-coding.** The engine's value is its generic pipeline. Reach
   for a new composable effect + a schema entry before you special-case a spell. If a
   mechanic can only be expressed by naming a specific spell, the abstraction is wrong.
3. **Test-driven.** No behaviour change without a test that demanded it — and for the
   pipeline, a test that *executes* it, not one that only inspects JSON shape
   ([§4](#4-test-driven-development-tdd), and §9 2026-08-08).
4. **Design for failure.** Where a system breaks matters as much as where it works.
   Enumerate the unhappy paths — malformed JSON, missing fields, dead targets,
   concentration loss, both-advantage-and-disadvantage — and decide each deliberately.
5. **Fail loudly, early, and specifically.** Validate at boundaries (the JSON loaders);
   raise precise errors that name the bad value and the valid options. Spell `effects`
   and rule `event.<field>` references are schema-validated at load
   (`src/rules/step_schema.py`, `RuleLoader._validate_event_field_refs`). The runtime
   `AttributeError` skip in `RuleEngine` now covers only the legitimate multi-trigger
   case (a field absent on one of a rule's several triggers), not typos — those are
   caught at load (E6 resolved).
6. **Small, reversible changes.** Many small, well-tested commits over one large one.
   Keep `main` clean; do non-trivial work on a branch.
7. **Debt and convolution are first-class.** In an engine whose whole value is modular
   flexibility to absorb new mechanics, technical debt and tangle are not side concerns —
   they are the thing that kills that flexibility. Treat a change's effect on them as a
   design factor on par with correctness. Prefer the option that *removes* debt/convolution;
   when a change adds either, that is a deliberate, justified trade, not an accident. Name
   it explicitly (see [§6](#6-agent-working-agreement)). Watch especially for **inverted
   dependencies** (new code depending on legacy), **duplicated vocabularies/engines**, and
   **silent coupling** — the recurring smells this rework exists to remove.

---

## 3. Architecture & modularity rules

- **One resolution path for everything.** A `SpellAction` is authored either natively
  (`program` in JSON, keyed by `block`) or legacily (`effects`, keyed by `type`). A native
  `program` is parsed by `block.parse_program` and validated at load by
  `spells.validate.validate_program`; a legacy `effects` list is translated at cast time by
  `adapter.to_program`. Both become a **block program** run by the block **evaluator**
  (`src/spells/evaluator.py`) over a shared ephemeral `context`: earlier blocks write results
  (`context.hit`, `context.damage_dealt`, `context.save_success`), later blocks read them.
  **Weapon attacks compile into the same blocks** via `AttackResolver._build_pipeline_effects`
  — never add a second resolution path. Prefer native `program` for new content; the legacy
  `effects` form retires as the corpus migrates (Phase 3 §5). (The legacy `EffectPipeline` is
  deleted.)
- **Registry, never `if/elif` on type.** New block type → add a handler under
  `src/spells/blocks/` and register it in the block `REGISTRY` (`src/spells/registry.py`),
  dispatched on the block's type. New spell → drop a JSON file in `examples/spells/`
  (auto-scanned at startup). Do **not** branch on a spell's name. (The legacy
  `BUILTIN_EFFECTS`/`effects.py` rule-effect vocabulary is transitional — reached only via
  the `fold`/`adapter` shims — and retires in §5.)
- **Cross-cutting behaviour rides the EventBus.** Resolvers emit typed events
  (`ATTACK_DECLARED`, `ATTACK_ROLLED`, `SAVING_THROW_DECLARED`, `DAMAGE_INCOMING`,
  `DAMAGE_DEALT`, `SPELL_HIT`, …). Rules and entity effects subscribe and may modify or
  cancel the event. Add reactive mechanics as subscribers, not inline branches.
- **Immutable template, mutable state.** `StatBlock` is a shared, immutable template;
  all per-battle state (HP, conditions, modifiers, position, concentration) lives on
  `Entity`. Never mutate a `StatBlock` during combat.
- **Pure core, imperative shell.** Keep dice/geometry/expression evaluation
  deterministic and side-effect-free; push I/O (WebSocket, disk, clock) to the web
  layer. Seed randomness through `dice.seed_rng` rather than reaching for `random`.
- **Explicit data contracts.** JSON is validated at the loader boundary and trusted
  within. Enum/format errors must name the bad value and the valid set
  (`_enum_lookup`, `_validate_formula`).
- **Name for intent, not implementation.** `spell_attack_bonus`, not `calc2`.
- **Sandbox stays a sandbox.** JSON expressions run under `src/rules/expressions.py`
  (AST whitelist, `__builtins__={}`, no imports/dunder). Anything a rule author can
  type must remain inside it — never widen it for convenience.

---

## 4. Test-Driven Development (TDD)

TDD is the default workflow, not an afterthought. The suite is a genuine strength
(550+ tests) — keep it that way.

**Testing rules:**

- **Bug fixes start with a failing test that reproduces the bug** _(why: proves the fix,
  prevents regression)_.
- **Test behaviour, not structure — especially for the pipeline.** A test that only
  asserts which steps a spell JSON parses into does **not** prove the steps *run*. New
  step types and effects need a test that executes the pipeline and checks the outcome
  (see §9 2026-08-08 — a structure-only test hid a hard crash).
- **Prove wiring end-to-end.** A model field + a rule can both exist while nothing
  populates the field from JSON. When you add data-driven content, assert it takes
  effect in a real resolution, not just in a hand-built object.
- **Cover the unhappy paths.** Malformed JSON, unknown enums, dead targets, empty AoE,
  failed saves, concentration drops, advantage+disadvantage cancelling.
- **Deterministic.** Seed with `dice.seed_rng(...)` or patch the roll functions; never
  rely on real randomness. No network in the suite.
- **The suite must be green before any task is done.** Report failures honestly.

---

## 5. Coding conventions

- Let the **formatter and linter** be the authority: `black`, `flake8`, `mypy`
  ([§7](#7-stack--commands)). Keep changed files clean.
- **Type annotations** throughout; prefer named structures (`NamedTuple`/dataclass) over
  bare positional tuples for anything with more than two fields.
- **Comments explain _why_, not _what_.** Delete commented-out code — it belongs in git
  history, not the source (see §9 2026-08-08 on the reconnection cleanup).
- **No magic values.** Name constants; if one must be duplicated across the Python/JS
  boundary (`CELL_FEET`), comment both copies to keep them in sync.
- **Handle errors with intent.** No bare/blanket catches that hide failures.

---

## 6. Agent working agreement

1. **Understand before changing.** Read the relevant modules *and their tests*; match
   existing patterns.
2. **Plan non-trivial work.** State the approach before large or cross-cutting changes;
   prefer the smallest change that solves the problem.
3. **Account for debt and convolution — explicitly** ([§2.7](#2-core-principles)). When
   planning a non-trivial change, include a short **debt & convolution note**: name where it
   *removes* or *adds* technical debt and tangle, and why (e.g. "removes an inverted
   dependency: the block engine no longer imports from the legacy module"; "collapses two
   resolution paths into one"). Quantify when you can (lines/files/paths/errors deleted). This
   is a first-class part of the plan and the commit message, not an afterthought — it is how
   this modular engine keeps its flexibility. If a change *adds* debt, say so and justify it as
   a deliberate trade, and record follow-up in [CODEBASE_REVIEW.md](docs/CODEBASE_REVIEW.md).
4. **Work test-first** per [§4](#4-test-driven-development-tdd).
5. **Keep the tree green.** Run the formatter, linter, and full suite before declaring a
   task done. If tests fail or a step was skipped, say so with the output.
6. **Don't expand scope silently.** Note adjacent problems (in
   [CODEBASE_REVIEW.md](docs/CODEBASE_REVIEW.md)); don't fold unrelated fixes in.
7. **Update docs with code.** Behaviour/command/structure changes update this file, the
   README, and the relevant guide in the same change.
8. **Capture lessons.** When a non-obvious mistake is found and fixed, append to
   [§9](#9-lessons-learned-append-only).
9. **Branch, don't touch `main`.** Do work on a feature branch; commit/push only when
   asked; write commit messages that explain the _why_.

---

## 7. Stack & commands

| Task | Command |
|---|---|
| Install (core + web + dev) | `pip install -e ".[web,dev]"` |
| Run the web UI | `uvicorn web.app:app --reload` → `http://localhost:8000` (`serve.bat` on Windows) |
| Run all tests | `pytest tests/ -q` |
| Run one test | `pytest tests/test_spells.py::TestX::test_y -q` |
| Format | `black src/ web/ tests/` |
| Lint | `flake8 src/ web/` |
| Type-check | `mypy src/` |

- **RNG:** one shared `random.Random` in `src/utils/dice.py`; call `dice.seed_rng(seed)`
  for reproducible battles. `dice.py` is the only module that touches `random`.

---

## 8. Project structure

An agent should know where a new file belongs without guessing — read the tree
(`src/` is the engine, `web/` the FastAPI app, `examples/` and `rules/` the JSON
content). Note `tests/` mirrors the engine; ignore `build/lib/` (stale untracked copy).

**Content invariants:**

- Coordinate axis swap: frontend cell units (x east, y south) ↔ backend feet
  (x east, y **up**, z south), `CELL_FEET = 5`. Conversions live in
  `web/routers/combat.py`; the constant is mirrored in `state.js` — keep both in sync.
- Adding a spell = a JSON file in `examples/spells/`; adding an entity effect = a JSON
  file in `rules/entity_effects/`. Both are scanned at startup.

---

## 9. Lessons Learned (append-only)

Durable lessons from real mistakes. **Append; do not rewrite.** Newest at the top. When
an entry stabilises into a general rule, promote it into the relevant section above and
leave a brief note here.

**Entry template:**

```
### YYYY-MM-DD — <short title>
- **Context:** what we were doing.
- **What went wrong:** the mistake or surprise.
- **Rule going forward:** the concrete, testable rule.
```

### 2026-09-02 — A load-time validator needed the block catalogue, which nothing had imported
- **Context:** Building `spells.validate.validate_program`, the loader-boundary validator for native block
  `program`s (Phase 3 §5a). It checks each block against the process-global block `REGISTRY`.
- **What went wrong:** The full test suite passed, but a *loader-first* process (load a native spell before
  anything imports the evaluator/adapter) raised "unknown block type … registered: (none)". The block
  catalogue only populates when `src.spells.blocks` is imported (each block module self-registers on import);
  the evaluator and adapter do this via `from . import blocks`, but `validate.py` did not — so in the suite it
  worked only because some *other* import had already registered the catalogue. A registry-dependent module
  must not assume someone else populated the registry.
- **Rule going forward:** Any module that reads the block `REGISTRY` must itself import the catalogue
  (`from . import blocks as _blocks  # noqa: F401`) so it is self-sufficient regardless of import order. Smoke-
  test new loader/validation paths in a **fresh, minimal process** (a one-off script), not only via the full
  suite whose broad imports mask missing self-registration.

### 2026-08-31 — A condition's marker and its mechanics were joined only by a name string
- **Context:** Wiring conditions to apply in production (Phase 3 §3). A condition has two parts: a
  `Condition` marker (inert data on `entity.conditions`) and a reactive rule
  (`rules/entity_effects/conditions/<name>.json`) that makes it *do* something.
- **What went wrong:** `apply_condition` added only the marker; nothing installed the reactive rule. The
  two shared nothing but a name string, so every applied condition except charm was mechanically dead in
  production — yet it looked complete (marker model + full rule library + passing tests), because the tests
  installed the *rule* directly via `apply_effect` and never exercised `apply_condition`. Charm worked only
  because it bypassed `apply_condition` entirely (via `add_entity_effect` → the rule).
- **Rule going forward:** When one representation of a thing (a marker/flag/record) is meant to trigger
  behaviour defined elsewhere (a rule/handler), verify the code path that creates it also installs the
  behaviour — a shared *name* is not a wire. Test the real entry point (`apply_condition`), not the
  behaviour-half in isolation. (Same seam-auditing lesson as 2026-08-08; this is a fresh instance.)

### 2026-08-31 — On the block path a weapon's `pipeline_effects` is empty at fire time
- **Context:** Migrating Colossus Slayer to a native `ATTACK_HIT` trigger. The rider deals the *weapon's
  own* damage type via `event.action.primary_damage_type`, which reads `Action.pipeline_effects`.
- **What went wrong:** `AttackResolver._resolve_via_blocks` builds the `[attack_roll, damage…]` steps on the
  fly and passes the **raw** `AttackAction` to the evaluator — it never assigns them to
  `action.pipeline_effects` (deliberately, to avoid mutating the shared template). So at fire time the
  action's `pipeline_effects` is `[]` and `primary_damage_type` returned `None`, silently degrading the
  rider's damage to `GENERIC`. The legacy path had hidden this because it ran on a *copy* whose
  `pipeline_effects` was populated.
- **Rule going forward:** A reactive block reading off `event.action` at fire time must not assume the action
  was compiled into `pipeline_effects` — a weapon's flat `damage`/`bonus_to_hit` list is the source of truth
  on the block path. `Action.primary_damage_type` now falls back to `damage[0]`. When a rider reads any
  action field, verify it is populated on the *raw* action the evaluator receives, not just on a compiled copy.

### 2026-08-29 — Black must be version-pinned; the repo predates the 2024 style
- **Context:** Running `black src/ …` on files touched during the spell rework produced huge
  whole-file reformats (even on files with no functional change), inflating every diff.
- **What went wrong:** `pyproject.toml` only floored `black>=23.0`, so a fresh env resolved to
  Black 26.x. The repo is formatted to Black's **2023 stable style**; Black 24.0 changed the
  stable style (e.g. a blank line after a class docstring, import re-explosion), so any 24.0+
  Black rewraps the *entire tree* — nothing to do with the edit. `black --check` wants to
  reformat files never touched; the drift is version-driven, not line-length-driven (churns at
  any `--line-length`).
- **Rule going forward:** Black is now pinned `==23.12.1` in `pyproject.toml` — do **not** bump it
  without a deliberate, standalone "reformat the whole repo" commit. If your environment has a
  newer Black, **do not run it on modified files**; hand-match the surrounding style instead, and
  keep the commit to the functional change. (E501 is not enforced here — the tree has ~460 lines
  >79 chars; match neighbours, not flake8's default width.)

### 2026-08-08 — A structure-only test passed while the feature crashed
- **Context:** Reviewing the spell pipeline; the `grant_temporary_hp` step was documented
  and had a test.
- **What went wrong:** The step called a non-existent `Entity.gain_temporary_hp` and
  raised `AttributeError` on every use. It went unnoticed because the only test asserted
  the *JSON structure* the step parsed into and never executed the pipeline branch, and
  the one temp-HP spell reached temp HP through a different (entity-effect) path.
- **Rule going forward:** For any pipeline step or effect handler, write a test that
  **runs the pipeline and asserts the outcome** — parsing/shape assertions do not prove
  execution. Cross-check that each documented step type has an execution test.

### 2026-08-08 — A shipped feature was silently unreachable at the wiring seam
- **Context:** Per-creature damage resistance/immunity/vulnerability — the rules and
  multipliers existed, were unit-tested against hand-built `StatBlock`s, and were
  documented in the creature guide.
- **What went wrong:** `StatBlockLoader` never parsed those fields, so **no creature
  loaded from JSON could ever trigger them.** The feature looked done (model + rules +
  docs + tests) but was dead in real play because one wiring step was missing.
- **Rule going forward:** When a model field and its rules both exist, **prove the loader
  populates it and it fires in a real resolution**, end-to-end — don't trust unit tests on
  hand-built objects. Audit the *seams* between layers, not just each layer.

### 2026-08-08 — "Disabled" is not "broken" — check before deleting
- **Context:** WebSocket reconnection: the backend `rejoin_combat` handler was commented
  out, so a reconnect returned an "unknown command" error.
- **What went wrong:** It was easy to read as fundamentally broken, but the session store
  underneath was live and working — the feature was *disabled*, not defective, and likely
  would have worked if re-enabled. Deleting it discarded recoverable work.
- **Rule going forward:** Before characterising or removing code as dead, verify its
  *actual* state (git history, the other side of the wire). Half-wired features that can
  only error should be **either finished or removed with the decision recorded** — not
  left commented in place. Recoverable work lives in git history, so note the commit.
