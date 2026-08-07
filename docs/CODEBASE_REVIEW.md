# D&D Auto-Battler — Codebase Review

_Last updated: 2026-08-08. A critical-but-fair health review to orient contributors
(human or agent) and to anchor the repair roadmap. Read alongside [CLAUDE.md](../CLAUDE.md)._

## Bottom line up front

- The project is **Python** (a FastAPI engine under `src/`) with a thin **JS browser client**
  under `web/static/js/`. The git-log "battle.js / ES modules" refactor was frontend-only.
- **The spell system is sound. Iterate, do not rebuild.** It is a data-driven `EffectPipeline`
  of typed steps with effectively zero spell-name special-casing, and weapon attacks are
  unified into the *same* pipeline. This is the strongest part of the codebase.
- The real risks are **wiring gaps and silent dead features**, not architecture. The three most
  serious (below, E1–E3) have been **fixed** as of this review; the rest remain as a roadmap.
- Despite the name, **nothing auto-battles yet** — there is no AI turn loop; every action is
  driven manually by the frontend/client.

---

## 1. Orientation

| Aspect | Reality |
|---|---|
| Language | Python 3.9+ engine; JS only in `web/static/js/` (rendering/input client) |
| Entry (web) | `uvicorn web.app:app` → `http://localhost:8000` (`serve.bat` on Windows) |
| Entry (lib) | `Entity(StatBlockLoader.load_from_json(...))` + `CombatSystem` (see [README.md](../README.md), `examples/example_combat.py`) |
| Packaging | `pyproject.toml` — zero core deps; `fastapi/uvicorn/jinja2` under `[web]`; `pytest/black/flake8/mypy` under `[dev]` |
| Tests | Large, real pytest suite (535 tests as of this review) — a genuine strength |
| Ignore | `build/lib/…` is a **stale, untracked** duplicate tree; read engine logic only from `src/` |

## 2. Architecture overview

**Two-layer data model (clean):** immutable template + mutable state.
- `src/models/stat_block.py` `StatBlock` — immutable creature template (abilities, HP max, AC,
  actions, damage modifiers, spell-slot/legendary defaults).
- `src/models/entity.py` `Entity` — mutable combat state wrapping a StatBlock (`current_hp`,
  `temporary_hp`, conditions, `stat_modifiers`, `granted_actions`, `resources`, `x/y/z`,
  concentration). Identity by `entity_id`. Computed `ac`, `spell_save_dc`, `spell_attack_bonus`,
  `bounding_box`.

**Combat is a facade over focused collaborators.** `src/combat/combat_system.py` `CombatSystem`
orchestrates and delegates to: `TurnManager` (round/turn lifecycle, condition-based skip),
`InitiativeTracker` (d20+DEX), the resolvers, `DamageProcessor`, and an `EventBus`.

**The spell/attack engine — the core idea.** Both weapons and spells run through one
`src/combat/effect_pipeline.py` `EffectPipeline`: a sequential list of typed steps
(`attack_roll`, `saving_throw`, `damage`, `healing`, `add_entity_effect`, `apply_condition`,
`add_modifier`, `grant_temporary_hp`) sharing an ephemeral `context`. Earlier steps write
results (`context.hit`, `context.damage_dealt`, `context.save_success`) that later steps read
via **sandboxed Python expressions** (`src/rules/expressions.py` — AST whitelist,
`__builtins__={}`, no dunder access). Weapon attacks are translated into pipeline steps by
`AttackResolver._build_pipeline_effects`. This unification is the design's best feature.

**Rules & effects are data-driven too.** `src/rules/rule_engine.py` `RuleEngine` loads global
rules (`rules/global/`: crits, concentration, damage modifiers) and named entity effects
(`rules/entity_effects/`: haste, charmed, 17 conditions, …) as JSON, dispatched through a
`BUILTIN_EFFECTS` handler registry (`src/rules/effects.py`). Cross-cutting behavior (resistance
multipliers, concentration saves, crit rules, conditions) subscribes to bus events rather than
being hardcoded into resolution. Effects support an `"on"` event-type gate and a `"when"`
expression guard so one rule can serve multiple triggers.

**Web layer.** `web/app.py` builds process-global spell/effect registries at startup by scanning
`examples/spells/` and `rules/entity_effects/`. `web/routers/combat.py` exposes creature/spell
HTTP endpoints and a `/ws/combat` WebSocket whose handlers (`start_combat`, `attack`,
`cast_spell`, `move`, `legendary_action`, `end_turn`) map 1:1 to engine calls and broadcast a
full state snapshot each time. The JS client is reactive: `state.js` holds a single shared
mutable state object (a deliberate ES-module live-binding workaround), and
`renderer/input/websocket/ui-panels` modules read/write it.

**Two loops, no AI.** The engine turn lifecycle (`TurnManager.end_turn`) and the WebSocket
message loop both exist, but **there is no autonomous action-selection loop** — monster turns are
not auto-played. "Auto-Battler" is currently a turn-enforced *manual* tactical client.
LLM-driven action selection is a README "Future Goal."

## 3. Spell-system verdict — sound; iterate, do not rebuild

**Why it's sound:**
- **No spell-name special-casing anywhere** — no `if spell.name == …`, no per-spell switch.
  Behavior is JSON pipeline steps + a `step["type"]` dispatch + a name→handler registry.
  Adding a spell = a JSON file; adding a mechanic = one handler + registry entry.
- **Weapon/spell unification** removed a whole class of duplication (one implementation of
  attack rolls, crits, damage).
- **Correct handling of the two trickiest 5e rules:** AoE "roll once, apply to all"
  (`SpellResolver._preroll_pipeline_damage`) and half-damage-on-save.
- Sandboxed expression evaluator is a thoughtful safety choice.

**Real weaknesses are wiring/coverage, not structure:** silent under-implementation of declared
spell riders (e.g. Chill Touch's no-heal, Ray of Frost's slow are absent from the JSON); two
parallel effect vocabularies bridged by synthetic stub events (`_handle_apply_condition` /
`_handle_add_modifier` reach into `rule_engine._effect_registry`); and no structured upcasting.

## 4. Significant missing features

1. **No autonomous AI / auto-battle loop** — the defining feature of an "auto-battler." Biggest
   product gap. (README Future Goal: LLM action selection.)
2. **Spell upcasting / level scaling** — `higher_level_scaling` is **prose only**; explicit TODO
   at `src/models/action.py`. No way to spend a higher slot for more dice.
3. **Reactions & opportunity attacks** — the `reactions` resource is tracked and spendable, but
   *nothing triggers a reaction* off the event bus. No Shield, no OA.
4. **Multiattack** — no field or handler; not in any creature JSON.
5. **Death saves / dying / stabilization** — none; `is_alive()` is binary at 0 HP.
6. **Split multi-target spells** (Magic Missile darts, Eldritch Blast beams, Scorching Ray) —
   only "same effect to a list" or true AoE is expressible.
7. **Forced movement** (Thunderwave push), **cantrip auto-scaling by level**, **component
   enforcement**, **monster traits** (Pack Tactics, regeneration), **innate/limited-use
   abilities**, **speed variants/senses**, **cylinder AoE + sight/unlimited ranges** (enum values
   exist, unimplemented).
8. **Damage `bonus_to_hit`/`amount` are hand-authored**, not derived from ability + proficiency.
9. **Save auto-fail** for paralyzed/stunned/petrified/unconscious (STR & DEX auto-fail) — the
   save-modifier mechanism now exists (see E3) but auto-fail is a distinct effect not yet wired.

## 5. Problems (severity-rated)

**CRITICAL — fixed in this review:**
- **E1. Damage resist/immune/vulnerable was unreachable from JSON.** `StatBlockLoader.from_dict`
  never passed the three modifier lists, so JSON-declared modifiers were silently dropped even
  though the rules/multipliers were correct and unit-tested against hand-built StatBlocks.
  **Fixed:** the loader now parses `damage_vulnerabilities/resistances/immunities` (with a
  friendly error on unknown types) and round-trips them; `stone_golem.json` gained
  `damage_immunities` as a live example; covered by `tests/test_loader_damage_modifiers.py`.
- **E2. `grant_temporary_hp` pipeline step crashed** — it called a non-existent
  `Entity.gain_temporary_hp`. **Fixed:** now calls `add_temporary_hp`; covered by
  `tests/test_grant_temporary_hp.py`.
- **E3. Saving throws ignored advantage/disadvantage** — `roll_saving_throw` always rolled a
  single d20, so conditions only affected attacks. **Fixed:** `_handle_saving_throw` now emits a
  `SAVING_THROW_DECLARED` event that effects can flag; `roll_saving_throw` honours
  advantage/disadvantage; `restrained` grants disadvantage on DEX saves; covered by
  `tests/test_save_advantage.py`.

**HIGH:**
- **E4. Loader brittleness on bad content — fixed.** `json.load` is now wrapped (naming the
  file), and every enum lookup (`DamageType`, `RangeType`, `TargetingType`, `AOEShape`,
  `CastingTimeType`, `DurationUnit`) goes through a `_enum_lookup` helper that reports the bad
  value and the valid options. Covered by `tests/test_loader_validation.py`.
- **E5. Loader regex vs. dice parser mismatch — open.** `_FORMULA_RE` accepts only a single
  `NdM(+/-K)` term, but `dice.py` rolls multi-term formulas (`2d6+1d8+5`); such damage is
  rejected at load time.
- **E6. RuleEngine swallows `AttributeError` — open.** In condition eval it DEBUG-logs and skips
  — a genuine typo in a rule expression is silently ignored (the code comment admits this "likely
  indicates a bug").

**MEDIUM:**
- **E7. Return-shape drift vs. docstrings — fixed.** `resolve_attack`/`parse_dice_formula`
  docstrings now match; the fragile per-target spell 6-tuple is a `NamedTuple`
  (`SpellTargetResult`) — still positionally unpackable, now self-documenting.
- **E8. Broken logging call — fixed.** The stray `logger.info("DC set as:", …)` in
  `spell_resolver.py` was removed.
- **E9. Dead code — fixed.** WebSocket reconnection (commented backend branch + orphaned session
  store, and the matching frontend `rejoin_combat` send/handler) was fully removed; the commented
  `resolve_saving_throw` and the deprecated `ModifyAC` handler are gone.
- **E10. Decorative/misleading `target: "for_each_defender"` — open.** In AoE spell JSON — the
  pipeline's
  `_resolve_target` only distinguishes `"caster"` vs. everything-else, so it silently means
  "defender."
- **E11. Non-seedable RNG** — `dice.py` calls module-global `random.*`; no injection/seed, so
  combat can't be tested deterministically without monkeypatching. Biggest *testability* gap.
- **E12. Cross-language duplication / process-global state** — `CELL_FEET` defined in both Python
  (`web/routers/combat.py`) and JS (`state.js`); the spell registry is a process-wide singleton
  shared across web sessions.
- **E13. Stale metadata** — `PKG-INFO` "Future Enhancements" lists shipped items as unchecked;
  `pyproject.toml` says MIT while `README.md` says "All rights reserved."

## 6. Prioritized repair roadmap

- **P0 — done:** E1 resistance loader · E2 `grant_temporary_hp` · E3 save advantage/disadvantage.
- **P1 — done:** E4 friendly loader validation (enum lookups + `json.load`) · E8 logging fix ·
  E7 reconcile return shapes / update docstrings · E9 delete dead code (reconnection removed).
  _Not yet done: a full spell/creature schema linter (deferred to feed the "new spell" skill)._
- **P2 — hardening (open):** E11 injectable/seedable RNG · E5 unify formula regex with the dice
  parser · E10 drop or implement `for_each_defender` · E6 stop swallowing rule-expression errors ·
  E12/E13 shared constants + metadata cleanup.
- **Then net-new features:** structured upcasting → reactions/OA → multiattack → death saves →
  the AI/auto-battle loop.

## 7. Appendix — file index for fast re-orientation

- **Engine core:** `src/combat/effect_pipeline.py` · `combat_system.py` · `attack_resolver.py` ·
  `spell_resolver.py` · `damage_processor.py` · `turn_manager.py` · `initiative.py`.
- **Rules:** `src/rules/rule_engine.py` · `effects.py` · `expressions.py` · `rule.py` ·
  `rule_loader.py`.
- **Data/loading:** `src/loaders/stat_block_loader.py` · `src/models/entity.py` ·
  `stat_block.py` · `action.py` · `spell_properties.py`.
- **Web:** `web/routers/combat.py` · `web/app.py` · `web/static/js/*`.
- **Content:** `examples/spells/*.json`, `examples/creatures/**`, `rules/**`.
- **Authoring guides:** `examples/creatures/CREATURE_DEFINITION_GUIDE.md` ·
  `examples/spells/SPELL_DEFINITION_GUIDE.md` · `examples/spells/ANIMATION_GUIDE.md`.

## 8. Follow-on

The "implement a new spell" **skill** is well-supported by this architecture: a skill that reads
`SPELL_DEFINITION_GUIDE.md` + `ANIMATION_GUIDE.md`, writes a JSON file to `examples/spells/`, and
adds an execution test would be low-risk precisely *because* spells are pure data. Best built
after P1 adds a spell-JSON schema validator (E4) so the skill gets structured feedback.
