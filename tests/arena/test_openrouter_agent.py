"""Tests for the OpenRouter adapter — mocked OpenAI-style client, no network."""

from types import SimpleNamespace

import pytest

from src.arena import credentials
from src.arena import openrouter_agent as ora
from src.arena.llm_common import SYSTEM_PROMPT
from src.arena.openrouter_agent import DEFAULT_MODEL, OpenRouterAgent, _to_openai_tools
from src.arena.tools import TOOLS
from src.arena.turn_driver import run_turn

from .conftest import force_turn, melee_attack


def fn_call(name, arguments, call_id="tc1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def response(*tool_calls):
    message = SimpleNamespace(tool_calls=list(tool_calls) or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _Completions:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.calls.append(kwargs)
        return self._outer.responses.pop(0)


class FakeClient:
    """Stand-in for openai.OpenAI: returns queued chat completions, records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=_Completions(self))


def _obs():
    return {"round": 1, "self": {"name": "Hero"}, "enemies": [], "legal_actions": {}}


def test_tool_envelope_conversion():
    converted = {t["function"]["name"]: t for t in _to_openai_tools(TOOLS)}
    assert converted["attack"]["type"] == "function"
    # input_schema is carried through as the function's parameters.
    assert converted["attack"]["function"]["parameters"] == next(
        t["input_schema"] for t in TOOLS if t["name"] == "attack"
    )


def test_decide_parses_tool_call_and_json_arguments():
    client = FakeClient([response(fn_call("attack", '{"action_name": "Bite", "defender_id": "g1"}'))])
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs(), TOOLS)

    assert call.name == "attack"
    assert call.arguments == {"action_name": "Bite", "defender_id": "g1"}  # JSON string parsed
    assert call.call_id == "tc1"


def test_request_shape_is_well_formed():
    client = FakeClient([response(fn_call("end_turn", "{}"))])
    OpenRouterAgent("O", "a", client=client).decide(_obs(), TOOLS)
    kwargs = client.calls[0]

    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert kwargs["tool_choice"] == "auto"
    assert "extra_headers" in kwargs
    # end_turn tool was augmented with the note field (shared helper) and OpenAI-shaped.
    end_turn = next(t for t in kwargs["tools"] if t["function"]["name"] == "end_turn")
    assert "note" in end_turn["function"]["parameters"]["properties"]


def test_note_is_captured_and_stripped():
    client = FakeClient([response(fn_call("end_turn", '{"note": "kite next turn"}'))])
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs(), TOOLS)

    assert call.name == "end_turn"
    assert "note" not in call.arguments
    assert agent.notes == "kite next turn"


def test_retries_once_when_no_tool_call():
    client = FakeClient([response(), response(fn_call("end_turn", "{}"))])  # first: no tool call
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs(), TOOLS)

    assert call.name == "end_turn"
    assert len(client.calls) == 2


def test_raises_after_retry_with_no_tool_call():
    client = FakeClient([response(), response()])
    agent = OpenRouterAgent("O", "a", client=client)
    with pytest.raises(RuntimeError, match="no tool call"):
        agent.decide(_obs(), TOOLS)


def test_missing_dependency_gives_clear_error(monkeypatch):
    monkeypatch.setattr(ora, "openai", None)
    with pytest.raises(ImportError, match="openai"):
        OpenRouterAgent("O", "a")  # client=None -> would construct the real SDK


def test_missing_key_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ora, "openai", object())  # get past the dependency check
    monkeypatch.setattr(credentials, "_SECRETS_DIR", tmp_path)  # empty -> no key file
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterAgent("O", "a")


def test_openrouter_agent_drives_a_real_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    client = FakeClient([
        response(fn_call("attack", f'{{"action_name": "Longsword", "defender_id": "{goblin.entity_id}"}}')),
        response(fn_call("end_turn", "{}")),
    ])
    agent = OpenRouterAgent("O", "a", client=client)

    outcome = run_turn(combat, fighter, agent)

    assert outcome.actions_taken == 1
    assert outcome.forced_end is False
    assert len(client.calls) == 2
    assert combat.get_current_entity() is not fighter
