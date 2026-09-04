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

**Sensory layer built and green** (information policy, observation, legal-action
assembly — committed on `feat/agent-arena`, off `main`). The engine already supplies
everything the arena drives — `CombatSystem` is a strict referee, the web layer's
`_HANDLERS` command vocabulary is a tool schema in all but name, and
`serialize_combat_state` is a ready model for observations. The arena is a **driver
over the existing engine, not a second engine.** Next is the "motor" side (tools +
executor, agent interface, turn driver, match runner), then one live Claude turn;
batch matches, info-hiding experiments, and watching battles are deferred (§6).

**Primary purpose: LLM benchmarking** — "which model/prompt plays 5e combat better?"
The intent shifted from manual/for-fun play to benchmarking as a novel application, so
fairness, determinism, clean metrics, and provider-neutrality are first-order concerns.
Decisions of intent are recorded in [AGENT_ARENA_DECISIONS.md](AGENT_ARENA_DECISIONS.md);
the important ones are folded into the sections below.

---

## 1. Why this exists

Today every action is chosen by a human through the web client. The only "AI" is the
naive "attack the first enemy" loop in [../examples/example_combat.py](../examples/example_combat.py).
We want an **autonomous decision-maker**: on an entity's turn it reads the game state,
sees its legal options and resources, and issues actions. Two such agents can then
fight — Claude vs Claude, Claude vs another provider — to compare who plays 5e combat
better. A first-class **information policy** lets us hide facts (enemy HP, AC, …) and
measure how that changes play.

**Locked-in decisions** (from [AGENT_ARENA_DECISIONS.md](AGENT_ARENA_DECISIONS.md)):
- **Benchmarking is the point** (A1) — measure model skill; **neutral** system prompt
  (A2), no coaching, so we test the model's *own* tactics.
- **Headless-first.** A pure-Python arena drives `CombatSystem` directly — no browser,
  deterministic, batchable. Watching battles comes via a **replay** (§6), not live play.
- **One agent per team** (B1) — one brain controls all of a side's creatures; multi-agent
  teams are a later experiment. The interface stays written so per-entity is possible.
- **One action at a time** (B2) — the agent sees each result before choosing the next;
  fidelity beats the cost saving of whole-turn batching.
- **Provider-neutral, Claude-first** (E4) — Claude is the first adapter, but the core
  (tools, observations, the `Agent` interface) must stay plain-JSON and easy to point at
  other providers (OpenRouter, open-weight models); no Claude-only constructs leak in.
- **Information policy is a seam from day one** (code default `FULL_INFORMATION`); enemy
  facts — HP/AC/resources/conditions/slots **and capabilities** — hide via toggles for the
  info-asymmetry experiments (A3). The *experiment* default is hidden; the *code* default
  stays reveal-all so milestone-1 wiring is unaffected.

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

- **`information_policy.py`** — `InformationPolicy` dataclass, the experiment knob.
  Shipped toggles: `reveal_enemy_hp`, `hp_display` (`exact`|`bucketed`|`hidden`),
  `reveal_enemy_ac`, `reveal_enemy_resources`, `reveal_enemy_conditions`,
  `reveal_enemy_spell_slots`. **To add:** `reveal_enemy_actions` (A3) — an enemy's
  attacks/known spells, hidden by default (you learn them by being hit, via the combat
  log). Default `FULL_INFORMATION` keeps milestone-1 wiring unaffected. Position is never
  hidden in v1 (the engine needs it for range/overlap); fog-of-war is a separate, later
  design.

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
  **Resolution transparency (C3):** a success result always states the *outcome*
  (hit/miss, save success, damage dealt) and the acting agent's **own roll**; the values
  it rolled *against* — target AC, spell save DC, and the target's resulting HP — are
  gated by the same `InformationPolicy`, so a hidden-info match reports "hit for 7", not
  "19 vs AC 15 → 7". Result-shaping therefore takes the actor's policy.

- **`agent.py`** — the **provider-neutral** contract (E4): abstract
  `Agent.decide(observation, tools) -> ToolCall` (one action per call — B2). An agent
  controls a **team** (B1): the driver invokes it for whichever of its creatures is
  active, so the observation's `self` rotates. It may keep a small, strictly length-capped
  **notes** string carried turn-to-turn (B3) — the agent's own scratchpad memory across
  its turns; verbose per-turn reasoning is discarded. Concrete:
  - `RandomAgent` / `ScriptedAgent` — deterministic. **Built now** as test fixtures
    (deterministic driver tests need a non-LLM agent) and the first-milestone sparring
    partner. Random picks uniformly among `legal_actions`; Scripted does "move toward
    nearest enemy, use highest-expected-damage affordable attack."
  - `LLMAgent` (Claude) — §4. Plain-JSON tools/observations mean another provider is a new
    adapter class, not a rewrite; nothing Claude-specific leaks into the core.

- **`turn_driver.py`** — `run_turn(...)`: build observation + menu, call the agent for
  **one** action (B2), execute it, feed the result back, and repeat until `end_turn` or a
  guard trips. Guards: no legal actions left, a per-turn action cap, and the **failure
  budget** (C2) — **3 consecutive or 5 total** failed/illegal tool calls in a turn →
  auto-`end_turn`, logging the wasted turn (illegal-move rate is a metric); a total
  protocol breakdown (no parseable call across retries) is the only forfeit. The compact
  running **combat log** (what each side just did) is assembled here for the next
  observation, so an agent remembers what it has *seen* even though its raw reasoning is
  dropped (B3).

- **`match.py`** — `MatchRunner`: build a `CombatSystem` from two rosters
  ([StatBlockLoader](../src/loaders/stat_block_loader.py) + spell registry), seed the
  RNG, assign **one `Agent` per team** (B1), loop `run_turn` on
  `combat.get_current_entity()` until `ENDED`. Win = last team standing; a hard **round
  cap** (start ~20, tune down once we see real fight lengths — tables run ~6–8 rounds)
  ends a runaway match, decided on remaining team-HP fraction (E1). Returns a
  `MatchResult` + transcript.

- **`transcript.py`** — JSONL logging: one record per observation, tool call, dice
  result, and turn boundary, **plus the match's RNG seed and the concrete rolls**. Logs
  everything useful so metrics are computed from the data, never by re-running the LLMs
  (E2), and so a match can be **replayed** deterministically — by re-seeding the RNG or by
  reading the recorded rolls straight back (E5, §6 replay).

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
  "adaptive"}`). Effort starts at **`medium`** for the first live runs to hold cost down
  while shaking out bugs (E3), rising later if quality needs it.
- **`tools=`** the `tools.py` schemas; the **observation** (state + legal menu) in the
  user message; a lean **system prompt**: role, objective ("defeat the enemy team"),
  rules of engagement (act only via tools; the referee enforces legality), and a short
  **"how this engine works"** note — turn/resource model, positions in feet, targeting.
  **Neutral, not coached** (A2): no tactical advice; the model supplies its own strategy.
- **Honesty about the engine (D2):** the prompt states what is *not* modelled yet
  (opportunity attacks / reactions on other turns, legendary actions in milestone 1) so
  the agent plans against the real simulation. **Free-form (gridless) movement is a
  deliberate design choice, not a limitation** — it replaced an earlier grid; grids are a
  tabletop simplification, not canonical (cf. Baldur's Gate 3) — so present it as the
  intended model, framing only genuinely-absent mechanics as gaps.
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
    reveal_enemy_actions: bool = True   # enemy attacks/known spells (to add, A3)

FULL_INFORMATION = InformationPolicy()   # milestone-1 default (reveal all)
```

An experiment is a one-line policy change + a batch run: build
`InformationPolicy(reveal_enemy_hp=False, reveal_enemy_ac=False)`, pass it to the match,
compare against `FULL_INFORMATION`. No engine edits — the policy is the *only* thing
shaping the enemy view.

**Action results obey the same policy (C3).** After an attack/spell, the agent always
learns the outcome (hit/miss, save success, damage dealt) and its **own** roll, but the
number it rolled *against* is gated: the target's AC/DC only when `reveal_enemy_ac` is
set, the target's resulting HP only when `reveal_enemy_hp` is set. Under hidden info the
agent knows it hit and dealt 7, but not the AC it beat or the enemy's HP left — it must
infer, as at a real table.

---

## 6. Milestones

**Status: milestone-1 code complete and offline-green. The `LLMAgent` (Claude) is built
and mock-tested; the only thing left is running it *live* (needs the user's API key). The
full scripted pipeline runs end-to-end and deterministically.**

### Milestone 1 — Foundation + one live LLM turn (current)
TDD throughout (a test that **executes** the loop, not one that inspects shapes —
CLAUDE.md §4), in order:
1. ✅ `information_policy.py` + `observation.py` (with `FULL_INFORMATION`).
2. ✅ `action_space.py` — the legal-move assembler.
3. ✅ `tools.py` — schemas + `ToolExecutor` (validation + dispatch + structured errors +
   policy-gated result shaping, C3).
4. ✅ `agent.py` — provider-neutral `Agent` base (team-controlling, one action/call, capped
   notes) + `RandomAgent`/`ScriptedAgent`.
5. ✅ `turn_driver.py` + `transcript.py` — per-turn loop (one action at a time), the failure
   budget (3 consecutive / 5 total), and the transcript (seed + rolls + snapshots).
6. ✅ `match.py` (+ `setup.py`) — single-match runner (one agent per team, win = last
   standing, round cap on HP fraction). `setup.build_combat` installs the `rules/global/`
   set (per-turn refill, crits, damage mods) — the arena's mirror of the web's combat wiring.
7. ✅ `llm_agent.py` — `LLMAgent` (Claude), single-shot-per-action tool-use adapter with an
   injectable client; mock-tested offline. **Live run still pending the user's API key.**
   Wiring/creds/cost in [AGENT_ARENA_LLM_SETUP.md](AGENT_ARENA_LLM_SETUP.md); live demo
   `examples/arena_llm_match.py`.
8. ✅ Demo `examples/arena_match.py` (scripted-vs-scripted, deterministic); README section pending.

✅ `reveal_enemy_actions` added — enemy capabilities (attacks + known spells) show in the
observation only when revealed (default on; hide it for the info-asymmetry experiments).

### Deferred (designed-for, not built now)
- Information-hiding **experiments** + the **batch** match-runner and win-rate /
  illegal-move / efficiency **scoring** (computed from transcripts, not re-runs — E2).
- **Battle replay — the priority way to watch (E5):** since the transcript logs every
  action plus the seed/rolls, a replay feeds a recorded match into the existing web
  renderer to watch it back — no live agents, no re-run. Cheaper and simpler than live
  spectating, and the natural basis for a future "watch the newest battles" feature online.
- **Live web spectator:** watching a match *as it runs* (reuse `serialize_combat_state` +
  reintroduce a keyed session store, removed per CLAUDE.md §9 2026-08-08). After replay.
- `legendary_action` / **reaction** support in the tool set (fire on *other* entities'
  turns — outside the milestone-1 "own turn" loop).
- **Multi-agent teams** (B1) — several brains per side, coordinating; richer heuristics;
  non-Claude adapters (E4).

---

## 7. Files

**New (`src/arena/`):** `__init__.py`, `information_policy.py`, `observation.py`,
`action_space.py`, `tools.py`, `agent.py`, `turn_driver.py`, `transcript.py`, `match.py`,
`setup.py`, `llm_agent.py`.
**New (docs/examples):** `docs/AGENT_ARENA_LLM_SETUP.md`, `examples/arena_match.py`,
`examples/arena_llm_match.py`.
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
  serializer the web layer wraps with its coordinate swap. `setup.install_global_rules` and
  the web's `handle_start_combat` also both load `rules/global/` — a smaller duplication of
  the same wiring; fold into one shared helper if it grows.

### Two setup gotchas found while building the runner (worth remembering)
- **Global rules are load-bearing.** The per-turn action-economy **refill** is a global rule
  in `rules/global/`, not engine-default behaviour. A combat without it never refills
  resources, so every creature acts once and the fight silently stalemates. `build_combat`
  installs the globals so no arena caller has to remember (mirrors the web).
- **Initiative is rolled at `add_combatant` time, not at `start_combat`.** So a reproducibility
  seed applied at match start does *not* cover turn order. `run_match` reseeds and re-rolls
  initiative (in stable combatant order) so one seed governs the whole match — initiative and
  resolution alike.

---

## 10. Open questions (for iteration, non-blocking)

Resolved in [AGENT_ARENA_DECISIONS.md](AGENT_ARENA_DECISIONS.md): turn granularity (one
action at a time), agency (one agent per team), failure handling, resolution transparency,
and scoring (log-all, win-rate + illegal-move-rate first). Still genuinely open:

1. **Failure budget tuning:** 3-consecutive / 5-total is a starting point (C2) — revisit
   once we see how often strong models actually fumble the tool schema.
2. **Round-cap value:** start ~20; likely lower after observing real fight lengths (E1).
3. **Reactions / legendary actions** fire on *other* entities' turns — a dedicated design
   when added.
4. **Position / fog-of-war:** v1 always reveals position (engine needs it). Hidden
   positioning is a larger later design.
