# Agent Arena — Plan & Handover

> **Purpose.** The design and build plan for letting autonomous agents (LLMs, or
> scripted policies) control combatants, so two agents can be matched against each
> other under identical rules. This is the source of truth for **what we're building
> and why**; the code, once written, is the source of truth for what exists.
>
> Read this in full before working on the arena. For the engine seams it drives, read
> [../CLAUDE.md](../CLAUDE.md) §3 (architecture) and the combat modules under `src/combat/`.
> Keep this file current: as milestones land, update the status line in §6; when the
> whole plan is delivered, prune the deferred sections rather than accumulating a changelog.

---

## 0. Where this stands (one breath)

**Nothing built yet.** Branch `feat/agent-arena` off `main`. The engine already
supplies everything the arena drives — `CombatSystem` is a strict referee, the web
layer's `_HANDLERS` command vocabulary is a tool schema in all but name, and
`serialize_combat_state` is a ready model for observations. The arena is a **driver
over the existing engine, not a second engine.** The first milestone builds the
headless foundation and wires one live Claude agent taking full turns; batch matches,
info-hiding experiments, and a web spectator are deferred (§6).

---

## 1. Why this exists

Today every action is chosen by a human through the web client. The only "AI" is the
naive "attack the first enemy" loop in [../examples/example_combat.py](../examples/example_combat.py).
We want an **autonomous decision-maker**: on an entity's turn it reads the game state,
sees its legal options and resources, and issues actions. Two such agents can then
fight — Claude vs Claude, Claude vs another provider — to compare who plays 5e combat
better. A first-class **information policy** lets us hide facts (enemy HP, AC, …) and
measure how that changes play.

**Locked-in decisions (from planning Q&A):**
- **Headless-first.** A pure-Python arena drives `CombatSystem` directly — no browser,
  deterministic, batchable. A web spectator bridge is a later phase.
- **First milestone = foundation + one live LLM turn**, proving the full
  observe→decide→act→observe loop before automating matches.
- **Provider-agnostic agent interface**, concrete Claude implementation now; a
  non-Claude implementation is a later drop-in subclass.
- **Information policy is a seam from day one** (default: reveal everything); the
  hide-info *experiments* and *eval batch* come later.

---

## 2. The mental model (how modern agent harnesses work)

Four ideas underlie every serious agent harness. They map cleanly onto this engine.

1. **The environment is the referee; the agent only proposes.** The agent never
   mutates state — it emits a *request*, the harness validates it against the engine
   and applies it only if legal. An illegal or hallucinated move becomes an **error
   observation** to react to, never a crash and never a silent success. `CombatSystem`
   already raises named `ValueError`s (wrong turn, unaffordable, out of range, no
   slots) that map exactly onto "illegal move, here's why, try again" — the same
   fail-loudly discipline as CLAUDE.md §2.5.

2. **The loop is Observe → Decide → Act → Observe (a POMDP).** Each turn the agent
   receives an **observation** (what it may know), chooses **action(s)**, sees the
   **results**, repeats until it ends its turn. It acts on the observation, not the
   true state — which is precisely the information knob: "can it see enemy HP?" is just
   "what goes in the observation." Hiding information = shrinking the observation.

3. **Tool use (function calling), not free-text parsing.** Give the model **tools**
   with typed JSON schemas (`attack(defender_id, action_name)`, `move(x, y)`,
   `end_turn()`); it returns a **structured tool call** we execute directly — no
   regex, far more reliable than prose. The `_HANDLERS` command shapes are already
   these schemas.

4. **Determinism + transcripts = science.** To compare agents, remove confounds. Dice
   flow through one seedable RNG (`dice.seed_rng`), so the *environment* is
   reproducible; the *model* is not (sampling), which is the correct setup — fixed
   environment, variable player. Every observation, tool call, and dice outcome is
   logged to a transcript (JSONL) for replay, audit, and scoring. Single games are
   high-variance; real comparison is win-rate over many seeded matches.

**Key design choice — static tools + rich observation + referee validation (chosen),
vs. dynamic action masking.** Dynamic masking regenerates the tool schema each turn so
only legal moves exist — but it **breaks prompt caching** and gets unwieldy. We instead
use a **small fixed tool set**, put the **legal-options menu inside the observation**,
and have the **referee validate each call**, returning a structured error for
self-correction. Stable, cacheable prompt prefix; mirrors the existing web handlers;
the engine's precise errors do the enforcing. The model may still *propose* an illegal
move, but it's caught and corrected in one round-trip.

---

## 3. Architecture

A new **headless** package `src/arena/` (engine-side, **no `web/` dependency**),
beside the web layer, reusing the same `CombatSystem` seam the web handlers use.

```
Match (two teams, seeded RNG)
  └─ MatchRunner ── owns a CombatSystem (the referee)
       loops turns → for the current entity:
         TurnDriver
           1. build_observation(combat, entity, policy)   → dict   (what the agent sees)
           2. legal_actions(combat, entity)               → menu   (what it may do)
           3. Agent.decide(observation, tools)            → ToolCall(s)
           4. ToolExecutor.apply(combat, entity, call)    → result / structured error
           5. feed result back; repeat until end_turn or a guard trips
       until CombatSystem.state == ENDED → MatchResult + transcript
```

### Modules to create (`src/arena/`)

- **`observation.py`** — `build_observation(combat, entity, policy) -> dict`. The
  agent's sensory input from *one entity's* viewpoint. Reuses the field set of
  [`serialize_combat_state`](../web/routers/combat.py) (hp, ac, resources, spell_slots,
  conditions, position, team) but **headless**: positions stay in **backend feet** (no
  cell-swap — honest to the engine; the future web bridge applies the swap). Includes
  `self`, allies, enemies, round/turn, and an embedded **legal-options menu**. Runs each
  *enemy* through the `InformationPolicy`.

- **`information_policy.py`** — `InformationPolicy` dataclass, the experiment knob:
  `reveal_enemy_hp`, `hp_display` (`exact`|`bucketed`|`hidden`), `reveal_enemy_ac`,
  `reveal_enemy_resources`, `reveal_enemy_conditions`, `reveal_enemy_spell_slots`.
  Ships now with a `FULL_INFORMATION` default so milestone 1 is unaffected. Position is
  never hidden in v1 (the engine needs it for range/overlap); fog-of-war is a separate,
  later design.

- **`action_space.py`** — **the one real engine gap.** `legal_actions(combat, entity)
  -> LegalActions`. Nothing today assembles the true legal set; this does, from
  existing pieces:
  - attacks/abilities: `entity.stat_block.actions + entity.granted_actions`, filtered
    by `entity.can_afford(a.cost)` (generalizes `get_affordable_actions`, which misses
    `granted_actions`).
  - spells: each `entity.stat_block.known_spells` name →
    `combat.get_spell_for_entity(...)`, filtered by `can_afford` **and**
    `spell_slots.can_afford(level)`.
  - targets: `get_enemies`/`get_allies`, each range-checked via
    [range_check.py](../src/spatial/range_check.py) so only reachable targets are listed.
  - movement: `entity.resources.movement`.
  Reusable beyond agents (e.g. a future "valid moves" UI hint).

- **`tools.py`** — provider-neutral tool **schemas** (`attack`, `cast_spell`, `move`,
  `end_turn`; `legendary_action` later) and `ToolExecutor.apply(combat, entity, call)`,
  the single execution seam: validate a call, dispatch to
  `CombatSystem.resolve_attack`/`resolve_spell`/`move_entity`/`end_turn`, catch engine
  `ValueError`s and return `{ "ok": false, "error": "<message>" }` (the self-correction
  signal). The arena's mirror of the web `_HANDLERS`. **No second resolution path**
  (CLAUDE.md §3).

- **`agent.py`** — the **provider-agnostic** contract: abstract
  `Agent.decide(observation, tools) -> list[ToolCall]`. Concrete:
  - `RandomAgent` / `ScriptedAgent` — deterministic. **Built now** as test fixtures
    (deterministic driver tests need a non-LLM agent) and the first-milestone sparring
    partner. Random picks uniformly among `legal_actions`; Scripted does "move toward
    nearest enemy, use highest-expected-damage affordable attack."
  - `LLMAgent` (Claude) — §4. Provider-neutral shapes mean a future `OpenAIAgent`
    (user-added) is a new subclass, not a rewrite.

- **`turn_driver.py`** — `run_turn(...)`: build observation + menu, call the agent,
  execute each tool call, feed results back, repeat until `end_turn` **or** a guard
  trips (max tool-calls per turn, or no legal actions) — the loop-safety valve.
  Auto-`end_turn` when out of options.

- **`match.py`** — `MatchRunner`: build a `CombatSystem` from two rosters
  ([StatBlockLoader](../src/loaders/stat_block_loader.py) + spell registry), seed the
  RNG, assign an `Agent` per entity/team, loop `run_turn` on
  `combat.get_current_entity()` until `ENDED`. Returns a `MatchResult` + transcript.

- **`transcript.py`** — JSONL logging: one record per observation, tool call, dice
  result, turn boundary. Enables replay, debugging, scoring.

### Reuse, don't re-create
`CombatSystem` (referee + `resolve_*`/`move_entity`/`end_turn`/`get_enemies`/`get_allies`/
`get_spell_for_entity`), `range_check.py`, `SpellRegistry`, `StatBlockLoader`,
`dice.seed_rng`.

---

## 4. The LLM agent (Claude), concretely

`LLMAgent.decide` runs a **tool-use loop** against the Claude Messages API (official
`anthropic` Python SDK, added under an optional `[agents]` extra in `pyproject.toml`):

- **Model `claude-opus-5`** by default (constructor takes a `model` string, so models
  can be pitted against each other), **adaptive thinking** (`thinking={"type":
  "adaptive"}`), `output_config={"effort": "high"}`.
- **`tools=`** the `tools.py` schemas; the **observation** (state + legal menu) in the
  user message; a **system prompt** with role, objective ("defeat the enemy team"), and
  rules of engagement (act only via tools; the referee enforces legality).
- Loop: send → while `stop_reason == "tool_use"`, execute each `tool_use` block via
  `ToolExecutor`, return **all** results as `tool_result` blocks in **one** user message
  (parallel-tool-use rule), continue until `end_turn` or the per-turn guard. Illegal
  moves return as error `tool_result`s so the model self-corrects.
- **Determinism scope:** the engine (dice) is seeded and reproducible; the model's
  token choices are not — the correct scientific setup.
- **Cost/latency hygiene from the start:** stable cacheable system+tools prefix (why we
  chose static tools), compact per-turn observation, and a summarized running combat log
  rather than resending it raw each turn.

Per Claude API guidance, this plan specs only the Claude implementation; a non-Anthropic
agent is a later subclass against the same interface.

---

## 5. Information policy (the experiment knob)

`build_observation` serializes `self`/allies in full but runs each **enemy** through the
policy before emitting it:

```python
@dataclass(frozen=True)
class InformationPolicy:
    reveal_enemy_hp: bool = True
    hp_display: str = "exact"          # "exact" | "bucketed" | "hidden"
    reveal_enemy_ac: bool = True
    reveal_enemy_resources: bool = True
    reveal_enemy_conditions: bool = True
    reveal_enemy_spell_slots: bool = True

FULL_INFORMATION = InformationPolicy()   # milestone-1 default
```

An experiment is a one-line policy change + a batch run: build
`InformationPolicy(reveal_enemy_hp=False, reveal_enemy_ac=False)`, pass it to the match,
compare against `FULL_INFORMATION`. No engine edits — the policy is the *only* thing
shaping the enemy view.

---

## 6. Milestones

**Status: not started (branch `feat/agent-arena`).**

### Milestone 1 — Foundation + one live LLM turn (current)
TDD throughout (a test that **executes** the loop, not one that inspects shapes —
CLAUDE.md §4), in order:
1. `information_policy.py` + `observation.py` (with `FULL_INFORMATION`).
2. `action_space.py` — the legal-move assembler.
3. `tools.py` — schemas + `ToolExecutor` (validation + dispatch + structured errors).
4. `agent.py` — `Agent` base + `RandomAgent`/`ScriptedAgent`.
5. `turn_driver.py` + `transcript.py` — per-turn loop + safety guard.
6. `match.py` — single-match runner.
7. `LLMAgent` (Claude) — one real agent taking full turns vs `ScriptedAgent`,
   end-to-end. **Needs an API key + costs real tokens** — coordinate with the user
   before running live (steps 1–6 run fully offline with a mocked client).
8. Demo script `examples/arena_match.py` + README section.

### Deferred (designed-for, not built now)
- Information-hiding **experiments** + the **batch** match-runner and win-rate /
  efficiency / illegal-move **scoring**.
- **Web spectator bridge**: reuse `serialize_combat_state` + reintroduce a keyed
  session store (removed per CLAUDE.md §9 2026-08-08) so a match can be watched live.
- `legendary_action` / **reaction** support in the tool set (these fire on *other*
  entities' turns — outside the milestone-1 "own turn" loop).
- Richer heuristics; non-Claude concrete agent.

---

## 7. Files

**New (`src/arena/`):** `__init__.py`, `information_policy.py`, `observation.py`,
`action_space.py`, `tools.py`, `agent.py`, `turn_driver.py`, `match.py`, `transcript.py`.
**New (tests, mirroring `tests/`):** `tests/arena/test_action_space.py`,
`test_observation.py`, `test_tools.py`, `test_turn_driver.py`, `test_match.py`, and a
mocked-LLM `test_llm_agent.py` (patch the API client — no network in the suite).
**New (demo):** `examples/arena_match.py`.
**Modified:** `pyproject.toml` (`anthropic` under `[agents]`), `README.md`,
`CLAUDE.md` §8 (document `src/arena/`).

---

## 8. Verification

- **Behavioural unit tests:** `pytest tests/arena/ -q`. `action_space` returns only
  affordable, in-range options (incl. unhappy paths: no slots, out of range, dead
  targets — CLAUDE.md §4). `ToolExecutor` applies a legal call *and* returns a
  structured error for an illegal one. `turn_driver` completes a turn and honors the
  guard.
- **Determinism:** same seed + same scripted agents ⇒ identical transcript.
- **Live LLM turn:** `examples/arena_match.py` (Claude vs Scripted) reaches `ENDED`;
  the transcript shows observe → valid tool calls → self-correction on illegal → end
  turn. Spends real tokens; needs credentials.
- **Green tree before done:** `black src/ web/ tests/` (pinned `black==23.12.1` —
  CLAUDE.md §9 2026-08-29), `flake8 src/ web/`, `mypy src/`, `pytest tests/ -q`.

---

## 9. Debt & convolution note (CLAUDE.md §2.7 / §6.3)

- **Removes debt:** adds the legal-action assembler the engine lacks (`action_space.py`),
  reusable beyond agents; supersedes the incomplete `get_affordable_actions`.
- **No new resolution path** (CLAUDE.md §3): `ToolExecutor` dispatches to existing
  `CombatSystem.resolve_*`; tool schemas mirror the web `_HANDLERS` rather than inventing
  a vocabulary.
- **Correct dependency direction:** `src/arena/` depends on `src/combat` + `src/models`;
  the engine never depends on the arena.
- **Deliberate trade:** a new `anthropic` dependency, quarantined to `LLMAgent` behind
  the provider-neutral interface, under an optional extra — core engine and offline tests
  stay import-clean without it.
- **Watch item ([CODEBASE_REVIEW.md](CODEBASE_REVIEW.md)):** `observation.py` and the web
  `serialize_combat_state` now describe overlapping entity fields. Kept separate for
  milestone 1 (headless = feet, policy-aware); if they drift, extract one shared entity
  serializer the web layer wraps with its coordinate swap.

---

## 10. Open questions (for iteration, non-blocking)

1. **Turn granularity:** one tool call at a time (see each result before the next — truer
   to "attack, see if it lands, then decide the bonus action") vs. plan a whole turn as
   parallel calls. Recommendation: one-at-a-time within a turn, guarded by the per-turn cap.
2. **Reactions / legendary actions** fire on *other* entities' turns — a dedicated design
   when added.
3. **Scoring metrics** for the eval phase: win-rate, damage-per-turn, resource efficiency,
   illegal-move rate, turns-to-win.
4. **Position / fog-of-war:** v1 always reveals position (engine needs it). Is hidden
   positioning a later goal?
