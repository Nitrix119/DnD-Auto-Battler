# Wiring up the LLM agent

How to run the arena with a real model. Two adapters exist —
[`LLMAgent`](../src/arena/llm_agent.py) (**Claude**, §1–6) and
[`OpenRouterAgent`](../src/arena/openrouter_agent.py) (**OpenRouter**, incl. free models, §7).
Everything else (scripted agents, matches, transcripts) runs offline; **only these adapters call
out to a model and spend tokens.**

> The core arena is provider-neutral (plain-JSON tools and observations) and the two adapters
> share their prompt/notes/loop logic via `llm_common`. Sections 1–6 cover Claude; §7 covers
> OpenRouter and cross-provider (Claude-vs-OpenRouter) matches.

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

## 7. OpenRouter (free & other models)

`OpenRouterAgent` ([`src/arena/openrouter_agent.py`](../src/arena/openrouter_agent.py)) is the
second adapter — it reaches any model on [OpenRouter](https://openrouter.ai) via their
OpenAI-compatible API, including **free** ones (e.g. NVIDIA Nemotron). It shares all
prompt/notes/loop logic with the Claude adapter (`llm_common`); only the request differs. Great
for cheap experimentation and for surfacing where weaker models fail.

1. **Install** — the `openai` SDK is in the same extra: `pip install -e ".[agents]"`.
2. **Key (git-safe)** — put your OpenRouter key in **`secrets/openrouter.key`** (the whole
   `secrets/` dir is git-ignored), or set `OPENROUTER_API_KEY`. The adapter reads it at
   runtime via `resolve_credential` — it never lands in a command line, output, or Git.
3. **Pick a tool-capable model** — not every free model supports function calling. Use
   OpenRouter's **"Tools"** filter; a model without it will make no tool call and the run
   fails loudly (which is often the point). Pass it with `--model`.
4. **Run:**
   ```bash
   python -m examples.arena_openrouter_match --model nvidia/nemotron-nano-9b-v2:free
   python -m examples.arena_openrouter_match --opponent claude          # cross-provider!
   python -m examples.arena_openrouter_match --opponent openrouter:openai/gpt-4o-mini
   ```
   `run_match` takes any `Agent` per team, so **Claude-vs-OpenRouter matches work out of the
   box** — the whole point of "use either". The default `--model` is a placeholder; verify a
   current free tool-capable slug on OpenRouter, as their catalog changes.

To add yet another provider, write a new `Agent` subclass whose `_request_action` calls it and
returns one `ToolCall`, delegating `decide` to `llm_common.decide_one_action` — everything else
is reused. (This repo's tooling generates Claude code only, so non-Claude adapters like the
OpenRouter one are deliberate additions built against the shared interface.)

## 8. Troubleshooting

- **`ImportError: LLMAgent needs the 'anthropic' package`** — run `pip install -e ".[agents]"`.
- **Auth error on first call** — set `ANTHROPIC_API_KEY` or run `ant auth login`; verify with
  `ant auth status`.
- **`RuntimeError: ... no tool call after a retry`** — the model answered with prose twice;
  usually a prompt/model mismatch. Check the model string and that tools were passed.
- **A model rejects a parameter** (e.g. forced tool use, or `effort` on an old SDK) — upgrade
  `anthropic`, or adjust the knob for that model.
- **OpenRouter: `No credential found for OPENROUTER_API_KEY`** — create `secrets/openrouter.key`
  (git-ignored) with your key, or set `OPENROUTER_API_KEY`.
- **OpenRouter: `ImportError: ... 'openai' package`** — run `pip install -e ".[agents]"`.
- **OpenRouter: no tool call / immediate loud failure** — the chosen model likely can't do tool
  calls. Pick one from OpenRouter's "Tools"-capable list.
