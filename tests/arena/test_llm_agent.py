"""Tests for the LLMAgent — with a fully mocked Anthropic client (no network).

A fake client returns canned responses shaped like the SDK's (a ``.content`` list of
blocks), so we can assert the request shape, tool-call parsing, the note scratchpad, the
no-tool retry, and end-to-end wiring through the turn driver — all offline.
"""

from types import SimpleNamespace

import pytest

from src.arena import llm_agent as llm_mod
from src.arena.llm_agent import DEFAULT_MODEL, SYSTEM_PROMPT, LLMAgent
from src.arena.tools import TOOLS
from src.arena.turn_driver import run_turn

from .conftest import force_turn, melee_attack


def tool_use(name, inp, block_id="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=block_id)


def thinking(text="considering options"):
    return SimpleNamespace(type="thinking", thinking=text)


def text(body="here is my move"):
    return SimpleNamespace(type="text", text=body)


def response(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="tool_use")


class _Messages:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.calls.append(kwargs)
        return self._outer.responses.pop(0)


class FakeClient:
    """Minimal stand-in for anthropic.Anthropic: returns queued responses, records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = _Messages(self)


def _obs():
    # A minimal observation dict — the agent only serializes it into the prompt.
    return {"round": 1, "self": {"name": "Hero"}, "enemies": [], "legal_actions": {}}


def test_decide_returns_the_models_tool_call():
    client = FakeClient([response(thinking(), tool_use("attack", {"action_name": "Bite", "defender_id": "g1"}))])
    agent = LLMAgent("A", "a", client=client)

    call = agent.decide(_obs(), TOOLS)

    assert call.name == "attack"
    assert call.arguments == {"action_name": "Bite", "defender_id": "g1"}
    assert call.call_id == "t1"


def test_request_shape_is_well_formed():
    client = FakeClient([response(tool_use("end_turn", {}))])
    agent = LLMAgent("A", "a", client=client)

    agent.decide(_obs(), TOOLS)
    kwargs = client.calls[0]

    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["system"] == SYSTEM_PROMPT
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    # end_turn was augmented with an optional `note` for the scratchpad.
    end_turn = next(t for t in kwargs["tools"] if t["name"] == "end_turn")
    assert "note" in end_turn["input_schema"]["properties"]


def test_note_is_captured_and_stripped():
    client = FakeClient([response(tool_use("end_turn", {"note": "kite the archer next turn"}))])
    agent = LLMAgent("A", "a", client=client)

    call = agent.decide(_obs(), TOOLS)

    assert call.name == "end_turn"
    assert "note" not in call.arguments  # stripped before the executor sees it
    assert agent.notes == "kite the archer next turn"


def test_retries_once_when_no_tool_call_then_succeeds():
    client = FakeClient([response(text("I'll attack.")), response(tool_use("end_turn", {}))])
    agent = LLMAgent("A", "a", client=client)

    call = agent.decide(_obs(), TOOLS)

    assert call.name == "end_turn"
    assert len(client.calls) == 2  # one retry


def test_raises_if_no_tool_call_after_retry():
    client = FakeClient([response(text("thinking...")), response(text("still thinking..."))])
    agent = LLMAgent("A", "a", client=client)

    with pytest.raises(RuntimeError, match="no tool call"):
        agent.decide(_obs(), TOOLS)


def test_missing_dependency_gives_clear_error(monkeypatch):
    monkeypatch.setattr(llm_mod, "anthropic", None)
    with pytest.raises(ImportError, match="anthropic"):
        LLMAgent("A", "a")  # client=None -> would construct the real SDK


def test_llm_agent_drives_a_real_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    client = FakeClient([
        response(tool_use("attack", {"action_name": "Longsword", "defender_id": goblin.entity_id})),
        response(tool_use("end_turn", {})),
    ])
    agent = LLMAgent("A", "a", client=client)

    outcome = run_turn(combat, fighter, agent)

    assert outcome.actions_taken == 1  # attacked, then ended
    assert outcome.forced_end is False
    assert len(client.calls) == 2
    assert combat.get_current_entity() is not fighter  # the turn advanced
