"""An LLM-backed arena agent — the Claude adapter.

This is the first concrete "brain" for the arena. It implements the provider-neutral
:class:`~src.arena.agent.Agent` contract by asking a Claude model, via tool use, for its
next action. Wiring, credentials, cost, and how to run a live match are in
``docs/AGENT_ARENA_LLM_SETUP.md``.

**Design decisions worth reviewing** (they shape what we're measuring):

* **Single-shot per action.** ``decide`` makes *one* API request and returns *one*
  action. The turn driver rebuilds the observation after each action, so the model sees
  the consequence of its last move in the *next* observation rather than through a
  tool-result thread. This keeps the ``Agent`` interface pure (observation → action), keeps
  a stable, cacheable system+tools prefix, and matches "one action at a time" (B2). The
  cost is no intra-turn chain-of-thought continuity — each decision is freshly grounded in
  the current state. Easy to revisit later (hold a per-turn message thread) if we want
  richer within-turn reasoning.
* **One action, via ``tool_choice`` auto + ``disable_parallel_tool_use``**, plus a system
  instruction to emit exactly one tool call. We deliberately do *not* force
  ``tool_choice: any`` — forcing is incompatible with extended thinking on some models and
  is rejected outright by others (e.g. Fable 5.1), and we want this to work across
  providers (E4). If the model ever returns no tool call, we re-prompt once, then fail
  loudly.
* **Neutral prompt (A2)** — role, objective, engine rules, and an honest note on what is
  and isn't modelled (D1/D2); no tactical coaching. The model supplies its own strategy.
* **Notes scratchpad (B3)** — the model may leave a short note to its future self via an
  optional ``note`` on ``end_turn`` (added only to this agent's tool list). It's echoed
  back at the top of the next turn's prompt.
"""

import json
from typing import Any, Dict, List, Optional

from src.arena.agent import Agent
from src.arena.tools import TOOL_END_TURN, ToolCall

try:  # optional dependency — only this module needs it (pip install -e ".[agents]")
    import anthropic
except ImportError:  # pragma: no cover - exercised via the missing-dep message
    anthropic = None

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "medium"  # step down from the API default (high) to hold first-run cost (E3)
DEFAULT_MAX_TOKENS = 8192

SYSTEM_PROMPT = """\
You are commanding a team in a Dungeons & Dragons 5th Edition combat encounter. \
Your goal is to defeat the enemy team.

How you play:
- You act one creature at a time, one action at a time. Each message shows the current \
battlefield and your legal options for the active creature.
- Respond with EXACTLY ONE tool call (attack, cast_spell, move, or end_turn) and nothing \
else. After it resolves you'll see the updated battlefield and act again, until you end \
the turn.
- A referee enforces the rules: an illegal action is rejected with an error you can learn \
from and correct. Prefer choices from the listed legal options.
- End your turn when you have nothing more worth doing.

The world model:
- Positions and distances are in FEET, on an open battlefield — there is no grid. You may \
move to any point within your movement budget; melee reach is measured edge to edge.
- You only know what you can observe. An enemy's HP, AC, or capabilities may be hidden; \
you learn about them by seeing what they do and the damage they take.

Not modelled (do not plan around these): opportunity attacks and other reactions on \
another creature's turn, and legendary actions.

No tactics are scripted for you — use your own judgment and knowledge of 5e to play well."""


def _augment_tools_with_notes(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a copy of *tools* with an optional ``note`` field added to ``end_turn``.

    Lets the model leave a brief reminder for its next turn without spending an action or
    polluting the shared engine tool schema.
    """
    augmented: List[Dict[str, Any]] = []
    for tool in tools:
        if tool["name"] == TOOL_END_TURN:
            tool = json.loads(json.dumps(tool))  # deep copy
            tool["input_schema"].setdefault("properties", {})["note"] = {
                "type": "string",
                "description": "Optional: a short reminder to your future self for next turn.",
            }
        augmented.append(tool)
    return augmented


class LLMAgent(Agent):
    """Drives a team by asking a Claude model for one action at a time via tool use."""

    def __init__(
        self,
        name: str,
        team: Optional[str] = None,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ) -> None:
        super().__init__(name, team)
        if client is None:
            if anthropic is None:
                raise ImportError(
                    "LLMAgent needs the 'anthropic' package. Install it with "
                    "`pip install -e \".[agents]\"` (see docs/AGENT_ARENA_LLM_SETUP.md)."
                )
            client = anthropic.Anthropic()
        self._client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        api_tools = _augment_tools_with_notes(tools)
        messages = [{"role": "user", "content": self._render(observation)}]

        call = self._request_action(messages, api_tools)
        if call is None:  # model replied without a tool call — correct it once
            messages.append({"role": "user", "content": "Respond with exactly one tool call."})
            call = self._request_action(messages, api_tools)
        if call is None:
            raise RuntimeError(
                f"{self.name}: the model returned no tool call after a retry; cannot act."
            )
        return self._capture_notes(call)

    # -- internals -------------------------------------------------------------

    def _request_action(
        self, messages: List[Dict[str, Any]], api_tools: List[Dict[str, Any]]
    ) -> Optional[ToolCall]:
        """One API request; return the single tool call, or None if the model made none."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=api_tools,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                # SDK returns block.input as a dict; copy so we can pop `note` safely.
                return ToolCall(block.name, dict(block.input), call_id=block.id)
        return None

    def _capture_notes(self, call: ToolCall) -> ToolCall:
        """Pull a `note` off an end_turn call into the agent's scratchpad; clean the call."""
        if call.name == TOOL_END_TURN and "note" in call.arguments:
            note = call.arguments.pop("note")
            if note:
                self.remember(str(note))
        return call

    def _render(self, observation: Dict[str, Any]) -> str:
        """Render the observation as the user message: notes, objective, then state JSON."""
        parts: List[str] = []
        if self.notes:
            parts.append(f"Your note to self from last turn: {self.notes}")
        parts.append(
            "It is your turn. Study the battlefield and your legal options, then take "
            "exactly one action.\n\n"
            + json.dumps(observation, indent=2, default=str)
        )
        return "\n\n".join(parts)
