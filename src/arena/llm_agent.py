"""An LLM-backed arena agent — the Claude adapter.

The first concrete "brain" for the arena: it implements the provider-neutral
:class:`~src.arena.agent.Agent` contract by asking a Claude model, via tool use, for its
next action. Wiring, credentials, cost, and how to run a live match are in
``docs/AGENT_ARENA_LLM_SETUP.md``. The provider-neutral prompt/notes/loop logic lives in
:mod:`src.arena.llm_common`; this module holds only the Anthropic-specific request.

**Design decisions worth reviewing** (they shape what we're measuring):

* **Single-shot per action.** ``decide`` makes *one* API request and returns *one*
  action. The turn driver rebuilds the observation after each action, so the model sees
  the consequence of its last move in the *next* observation rather than through a
  tool-result thread. This keeps the ``Agent`` interface pure (observation → action), keeps
  a stable, cacheable system+tools prefix, and matches "one action at a time" (B2). The
  cost is no intra-turn chain-of-thought continuity — each decision is freshly grounded in
  the current state.
* **One action, via ``tool_choice`` auto + ``disable_parallel_tool_use``**, plus a system
  instruction to emit exactly one tool call. We deliberately do *not* force
  ``tool_choice: any`` — forcing is incompatible with extended thinking on some models and
  is rejected outright by others (e.g. Fable 5.1), and we want this to work across
  providers (E4). If the model returns no tool call, :func:`llm_common.decide_one_action`
  re-prompts once, then fails loudly.
* **Neutral prompt (A2)** and **notes scratchpad (B3)** — both in :mod:`llm_common`.
"""

from typing import Any, Dict, List, Optional

from src.arena.agent import Agent
from src.arena.llm_common import SYSTEM_PROMPT, decide_one_action  # noqa: F401 (re-export)
from src.arena.tools import ToolCall

try:  # optional dependency — only this module needs it (pip install -e ".[agents]")
    import anthropic
except ImportError:  # pragma: no cover - exercised via the missing-dep message
    anthropic = None

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "medium"  # step down from the API default (high) to hold first-run cost (E3)
DEFAULT_MAX_TOKENS = 8192


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
        return decide_one_action(self._request_action, self, observation, tools)

    def _request_action(
        self, messages: List[Dict[str, Any]], api_tools: List[Dict[str, Any]]
    ) -> Optional[ToolCall]:
        """One Anthropic request; return the single tool call, or None if the model made none."""
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
                # SDK returns block.input as a dict; copy so `note` can be popped safely.
                return ToolCall(block.name, dict(block.input), call_id=block.id)
        return None
