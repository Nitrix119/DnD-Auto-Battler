"""OpenRouter adapter — a provider-neutral Agent backed by any OpenRouter model.

Talks to OpenRouter's OpenAI-compatible Chat Completions API (its documented client) via the
``openai`` SDK pointed at https://openrouter.ai/api/v1. All prompt/notes/one-action-loop logic
is shared with the Claude adapter through :mod:`src.arena.llm_common`; only the request and the
tool-schema envelope differ. This lets us pit **free** models (e.g. NVIDIA Nemotron) against
Claude or the scripted baseline — cheap experimentation, and a way to surface where weaker
models fail. Wiring and the git-ignored key file are in ``docs/AGENT_ARENA_LLM_SETUP.md``.

Note: not every free model supports function/tool calling. Pick a tool-capable one (OpenRouter's
"Tools" filter). A model that can't will make no tool call — :func:`llm_common.decide_one_action`
retries once, then fails loudly, which is exactly how a flaw surfaces.
"""

import json
from typing import Any, Dict, List, Optional

from src.arena.agent import Agent
from src.arena.credentials import resolve_credential
from src.arena.llm_common import SYSTEM_PROMPT, decide_one_action
from src.arena.tools import ToolCall

try:  # optional dependency — only this module needs it (pip install -e ".[agents]")
    import openai
except ImportError:  # pragma: no cover - exercised via the missing-dep message
    openai = None

DEFAULT_MODEL = "nvidia/nemotron-nano-9b-v2:free"  # free + tool-capable; override with --model
DEFAULT_MAX_TOKENS = 4096
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Optional OpenRouter attribution headers (harmless; used only for their leaderboards).
_RANKING_HEADERS = {
    "HTTP-Referer": "https://github.com/Nitrix119/DnD-Auto-Battler",
    "X-Title": "DnD Auto-Battler Arena",
}


def _to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Neutral ``{name, description, input_schema}`` → OpenAI function-tool envelope."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


class OpenRouterAgent(Agent):
    """Drives a team by asking an OpenRouter model for one action at a time via tool use."""

    def __init__(
        self,
        name: str,
        team: Optional[str] = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: Any = None,
    ) -> None:
        super().__init__(name, team)
        if client is None:
            if openai is None:
                raise ImportError(
                    "OpenRouterAgent needs the 'openai' package. Install it with "
                    "`pip install -e \".[agents]\"` (see docs/AGENT_ARENA_LLM_SETUP.md)."
                )
            api_key = resolve_credential("OPENROUTER_API_KEY", "openrouter.key")
            client = openai.OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
        self._client = client
        self.model = model
        self.max_tokens = max_tokens

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        return decide_one_action(self._request_action, self, observation, tools)

    def _request_action(
        self, messages: List[Dict[str, Any]], api_tools: List[Dict[str, Any]]
    ) -> Optional[ToolCall]:
        """One OpenRouter (chat-completions) request; return the first tool call, or None."""
        oai_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
        response = self._client.chat.completions.create(
            model=self.model,
            messages=oai_messages,
            tools=_to_openai_tools(api_tools),
            tool_choice="auto",
            max_tokens=self.max_tokens,
            extra_headers=_RANKING_HEADERS,
        )
        message = response.choices[0].message
        for tc in getattr(message, "tool_calls", None) or []:
            fn = tc.function
            arguments = fn.arguments
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            return ToolCall(fn.name, args, call_id=getattr(tc, "id", None))
        return None
