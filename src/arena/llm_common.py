"""Provider-neutral pieces shared by every LLM adapter.

The prompt, the notes scratchpad, the tool-note augmentation, and the one-action-per-call
loop are the same whether the model is served by Anthropic, OpenRouter, or anything else —
only the actual request differs. Keeping them here means one copy for all adapters (CLAUDE.md
§2.7: no duplicated vocabulary); an adapter supplies just a ``request_fn`` that turns a list
of messages + tools into one :class:`~src.arena.tools.ToolCall` (or ``None``).
"""

import json
from typing import Any, Callable, Dict, List, Optional

from src.arena.tools import TOOL_END_TURN, ToolCall

#: One request → one ToolCall, or None when the model made no tool call.
RequestFn = Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Optional[ToolCall]]

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


def augment_tools_with_notes(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a copy of *tools* with an optional ``note`` field added to ``end_turn``.

    Lets the model leave a brief reminder for its next turn without spending an action or
    polluting the shared engine tool schema. Tools are in the neutral
    ``{name, description, input_schema}`` shape; each adapter reshapes the envelope for its
    own API.
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


def render_observation(notes: str, observation: Dict[str, Any]) -> str:
    """Render an observation as the user message: prior note, instruction, then state JSON."""
    parts: List[str] = []
    if notes:
        parts.append(f"Your note to self from last turn: {notes}")
    parts.append(
        "It is your turn. Study the battlefield and your legal options, then take "
        "exactly one action.\n\n"
        + json.dumps(observation, indent=2, default=str)
    )
    return "\n\n".join(parts)


def capture_notes(agent: Any, call: ToolCall) -> ToolCall:
    """Pull a ``note`` off an ``end_turn`` call into *agent*'s scratchpad; clean the call."""
    if call.name == TOOL_END_TURN and "note" in call.arguments:
        note = call.arguments.pop("note")
        if note:
            agent.remember(str(note))
    return call


def decide_one_action(
    request_fn: RequestFn,
    agent: Any,
    observation: Dict[str, Any],
    tools: List[Dict[str, Any]],
) -> ToolCall:
    """The shared decide skeleton: render → request → one retry → capture notes.

    *request_fn* is the adapter's provider call. If the model returns no tool call, we
    re-prompt once; if still none, we fail loudly (never silently end the turn).
    """
    api_tools = augment_tools_with_notes(tools)
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": render_observation(agent.notes, observation)}
    ]

    call = request_fn(messages, api_tools)
    if call is None:  # model replied without a tool call — correct it once
        messages.append({"role": "user", "content": "Respond with exactly one tool call."})
        call = request_fn(messages, api_tools)
    if call is None:
        raise RuntimeError(
            f"{agent.name}: the model returned no tool call after a retry; cannot act."
        )
    return capture_notes(agent, call)
