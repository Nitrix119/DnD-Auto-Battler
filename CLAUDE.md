# CLAUDE.md

Guidance for AI agents working in this repo. For a full critical health review, read
[docs/CODEBASE_REVIEW.md](docs/CODEBASE_REVIEW.md).

## What this is

A **D&D 5e combat simulator**. The engine is **Python** (`src/`), exposed both as a library and
via a FastAPI web app (`web/`) with a browser JS client (`web/static/js/`). Creatures, spells,
and rules are **JSON data** — most content is added without touching Python. Despite the name,
there is **no autonomous AI turn loop yet**; combat is driven action-by-action by the client.

## Run / test / lint

```bash
pip install -e ".[web,dev]"      # core + web + dev tooling
uvicorn web.app:app --reload      # web UI at http://localhost:8000  (serve.bat on Windows)
pytest tests/ -q                  # full suite (fast, ~500+ tests)
black src/ web/ tests/            # format
flake8 src/ web/                  # lint
mypy src/                         # type-check
```

Run a single test file: `pytest tests/test_spells.py -q`. There is no coverage gate committed.

## Layout

- `src/models/` — data structures. `StatBlock` (immutable template), `Entity` (mutable combat
  state), `Action`/`AttackAction`/`SpellAction`, `Damage`/`DamageType`, `Condition`, `SpellSlots`,
  `LegendaryActions`, `spell_properties.py` (ranges/AoE/targeting enums).
- `src/combat/` — `CombatSystem` (facade), `TurnManager`, `InitiativeTracker`, `AttackResolver`,
  `SpellResolver`, **`EffectPipeline`** (the heart), `DamageProcessor`, `EventBus`, `events.py`,
  `event_data.py`, `SpellRegistry`.
- `src/rules/` — `RuleEngine`, `effects.py` (handler registry `BUILTIN_EFFECTS`), `expressions.py`
  (sandboxed evaluator), `rule.py`/`rule_loader.py`.
- `src/loaders/` — `StatBlockLoader` (JSON ↔ model).
- `src/spatial/` — 3D geometry, AoE volumes, range checks. `src/utils/` — `dice.py`, `saving_throw.py`.
- `web/` — `app.py` (factory + global registries), `routers/combat.py` (HTTP + `/ws/combat`),
  `static/js/` (reactive client; `state.js` is the shared-state module).
- `examples/` — `creatures/**`, `spells/*.json`, and three `*_GUIDE.md` authoring guides.
- `rules/` — `global/` (crits, concentration, damage modifiers) and `entity_effects/` (named
  buffs/debuffs + `conditions/`).
- `tests/` — pytest. **Ignore `build/lib/`** — a stale, untracked duplicate of `src/`.

## Core mental model

- **One pipeline for everything.** A `SpellAction` carries `pipeline_effects`: an ordered list of
  typed steps (`attack_roll`, `saving_throw`, `damage`, `healing`, `add_entity_effect`,
  `apply_condition`, `add_modifier`, `grant_temporary_hp`). `EffectPipeline.run` walks them,
  sharing an ephemeral `context` where earlier steps write values (`context.hit`,
  `context.damage_dealt`, `context.save_success`) that later steps read. **Weapon attacks are
  converted into the same steps** by `AttackResolver._build_pipeline_effects` — do not add a
  parallel attack path.
- **Cross-cutting behavior rides the EventBus.** Resolvers emit typed events (`ATTACK_DECLARED`,
  `ATTACK_ROLLED`, `SAVING_THROW_DECLARED`, `DAMAGE_INCOMING`, `DAMAGE_DEALT`, `SPELL_HIT`, …).
  Global rules and entity effects subscribe and can modify or cancel the event (e.g. damage
  resistance multiplies on `DAMAGE_INCOMING`; conditions set advantage/disadvantage on the
  declared event). Add new reactive mechanics as event subscribers, not inline branches.
- **Content is JSON.** A new spell = a JSON file in `examples/spells/` (auto-scanned at startup).
  A new mechanic = a step handler in `effect_pipeline.py` **or** an effect in `effects.py` +
  `BUILTIN_EFFECTS` registry entry, exercised from a JSON rule.

## Invariants an agent must respect

- **`StatBlock` is an immutable template; mutate `Entity`.** Per-battle state (HP, conditions,
  modifiers, position) lives on `Entity`, never on the shared `StatBlock`.
- **Expressions run in a sandbox** (`src/rules/expressions.py`): AST whitelist, `__builtins__={}`,
  no imports, no dunder/private-attribute access. Only `SAFE_BUILTINS` (`max`, `min`, `abs`,
  `int`, `round`, `bool`, `len`, `hasattr`) are callable. Keep JSON expressions inside this.
- **Coordinate axis swap.** Frontend uses 2D cell units (x east, y south); backend uses feet with
  **y = up, z = south** (`CELL_FEET = 5`). Conversions live in `web/routers/combat.py`. This
  constant is currently duplicated in `state.js` — keep them in sync.
- **Rule effects can gate by event.** Use an effect's `"on"` (event-type) and `"when"`
  (expression) keys to route different effects within one multi-trigger rule (see
  `rules/entity_effects/conditions/restrained.json`).

## Testing conventions & known traps

- Many spell tests assert **JSON structure** (which steps a file parses to), not execution. When
  you add or change a **step type**, add a test that actually **runs the pipeline** — a
  structure-only test will not catch a runtime crash. (This is how the `grant_temporary_hp` bug
  and the resistance-loader gap slipped through; see their regression tests
  `tests/test_grant_temporary_hp.py`, `tests/test_loader_damage_modifiers.py`.)
- **RNG is module-global and not seedable.** For deterministic tests, `patch` the roll functions
  at the module that uses them, e.g. `patch("src.utils.saving_throw.roll_d20", return_value=15)`
  or `patch("src.utils.dice.roll_d20", side_effect=[...])`.
- Before finishing, run `pytest tests/ -q` and keep it green.

## Live gotchas (see docs/CODEBASE_REVIEW.md §5 for the full list)

- `RuleEngine` swallows `AttributeError` in rule-condition eval and only DEBUG-logs it, so a typo
  in a rule expression is silently skipped (E6 — still open).
- RNG is a single shared `random.Random` in `dice.py`; call `dice.seed_rng(seed)` for
  deterministic battles/tests (you can also still patch the roll functions).
- `resolve_spell`/`resolve_legendary_action` return `SpellTargetResult` namedtuples
  (`entity, hit, damage, roll_detail, healing, healed`) — unpack by name or position.
- `CELL_FEET` is duplicated in `web/routers/combat.py` and `web/static/js/state.js` — keep in sync.
- `license` in `pyproject.toml` (MIT) contradicts `README.md` ("all rights reserved") — unresolved
  owner decision (E13).
