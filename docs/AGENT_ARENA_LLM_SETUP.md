# Wiring up the LLM agent

How to run the arena with a real model behind [`src/arena/llm_agent.py`](../src/arena/llm_agent.py).
Everything else in the arena (scripted agents, matches, transcripts) runs offline; **only the
`LLMAgent` calls out to a model and spends tokens.**

> The core arena is provider-neutral (plain-JSON tools and observations). `LLMAgent` is the
> **Claude** adapter and the first one built; another provider (OpenRouter, an open-weight
> model, …) is a new `Agent` subclass against the same interface — see *Other providers* below.

## 1. Install the dependency

The `anthropic` SDK is an optional extra so the engine and offline arena don't require it:

```bash
pip install -e ".[agents]"
# opus-5, adaptive thinking, and effort need a recent SDK; upgrade if in doubt:
pip install -U anthropic
```

## 2. Authenticate

`LLMAgent()` constructs `anthropic.Anthropic()`, which resolves credentials from the
environment. Pick one:

- **API key:** `export ANTHROPIC_API_KEY=sk-ant-...` (PowerShell: `$env:ANTHROPIC_API_KEY="sk-ant-..."`).
- **CLI profile:** `ant auth login` once — the SDK reads the stored profile automatically, no
  env var needed. Check with `ant auth status`.

No key in code. If nothing is configured the first live call raises an auth error.

## 3. Run a live match

A one-command demo pits an `LLMAgent` (team A) against the deterministic `ScriptedAgent`
(team B) — a good, cheaper first test of the whole loop:

```bash
python -m examples.arena_llm_match          # LLM vs scripted
python -m examples.arena_llm_match --llm-vs-llm   # both sides LLM (2x the tokens)
```

Or in code:

```python
from src.arena.agent import ScriptedAgent
from src.arena.llm_agent import LLMAgent
from src.arena.match import run_match
from src.arena.setup import build_combat
from src.arena.transcript import Transcript
# ... build your entities on teams "a" and "b" ...

combat = build_combat([hero_a, hero_b])          # installs global rules (refill, crits, ...)
agents = {"a": LLMAgent("Claude A", "a"), "b": ScriptedAgent("Scripted B", "b")}
transcript = Transcript()
result = run_match(combat, agents, seed=1, transcript=transcript)
print(result.winner, result.reason, result.rounds)
transcript.save("match.jsonl")                    # replayable log (seed + rolls + snapshots)
```

To run Claude-vs-Claude, make both values `LLMAgent`s (optionally different models).

## 4. Cost & guardrails

You pay per token, so watch the first runs (E3 in the decisions doc):

- Defaults are **`claude-opus-5`**, **adaptive thinking**, **effort `medium`** (a deliberate
  step down from the API default `high` while shaking things out).
- **One API request per action** (one action at a time). A turn is usually a few actions, a
  match a few dozen turns — a single match is typically well under a dollar, but a batch of
  many multiplies. Start with one match.
- Hard limits already bound a match: the **round cap** (`run_match(round_cap=...)`, default 20)
  and the per-turn **action cap** and **failure budget** in the turn driver.
- Cheaper knobs: `LLMAgent(..., model="claude-sonnet-5")`, or `effort="low"`, or fewer/lower-HP
  combatants. Pit `opus-5` vs `sonnet-5` to see the harness surface a skill gap.

## 5. Configuration knobs

```python
LLMAgent(
    name="Claude A", team="a",
    model="claude-opus-5",   # any model string; the value to vary when benchmarking
    effort="medium",         # "low" | "medium" | "high" | "xhigh" | "max"
    max_tokens=8192,         # room for thinking + one tool call
    client=my_client,        # inject a client (tests pass a fake; None -> real SDK)
)
```

## 6. How it behaves (worth knowing before you read a transcript)

- **Single-shot per action.** Each `decide()` is one request returning one action; the model
  sees the result of its last move in the *next* observation, not a tool-result thread. Clean
  and cache-friendly, at the cost of no within-turn chain-of-thought carryover. (Revisit if we
  want richer intra-turn reasoning — hold a per-turn message thread.)
- **One tool call is requested via `tool_choice: auto` + `disable_parallel_tool_use`** plus a
  system instruction, *not* forced `tool_choice: any` — forcing conflicts with extended
  thinking on some models and is rejected by others (e.g. Fable 5.1). If a model returns no
  tool call, the agent re-prompts once, then fails loudly.
- **Neutral prompt** (no coaching) with an honest note on what the engine does and doesn't
  model. Free-form (gridless) movement is presented as intended, not a limitation.
- **Notes scratchpad:** the model may leave a short reminder to its next turn via an optional
  `note` on `end_turn`; it's echoed at the top of the next turn's prompt.

## 7. Other providers

`LLMAgent` is the Claude adapter. To try another provider, write a new `Agent` subclass whose
`decide(observation, tools)` calls that provider and returns one `ToolCall` — the tools and
observations are already plain JSON. Nothing else in the arena changes. (This repo's tooling
generates Claude code only, so a non-Claude adapter is a deliberate addition you own.)

## 8. Troubleshooting

- **`ImportError: LLMAgent needs the 'anthropic' package`** — run `pip install -e ".[agents]"`.
- **Auth error on first call** — set `ANTHROPIC_API_KEY` or run `ant auth login`; verify with
  `ant auth status`.
- **`RuntimeError: ... no tool call after a retry`** — the model answered with prose twice;
  usually a prompt/model mismatch. Check the model string and that tools were passed.
- **A model rejects a parameter** (e.g. forced tool use, or `effort` on an old SDK) — upgrade
  `anthropic`, or adjust the knob for that model.
