"""Tests for the provider-neutral LLM helpers shared by every adapter."""

import pytest

from src.arena.llm_common import (
    augment_tools_with_notes,
    capture_notes,
    decide_one_action,
    render_observation,
)
from src.arena.tools import TOOLS, ToolCall


class _StubAgent:
    def __init__(self):
        self.name = "Stub"
        self.notes = ""

    def remember(self, text):
        self.notes = text


def test_augment_adds_note_only_to_end_turn():
    aug = {t["name"]: t for t in augment_tools_with_notes(TOOLS)}
    assert "note" in aug["end_turn"]["input_schema"]["properties"]
    assert "note" not in aug["attack"]["input_schema"].get("properties", {})
    # original TOOLS untouched (deep-copied)
    orig = {t["name"]: t for t in TOOLS}
    assert "note" not in orig["end_turn"]["input_schema"].get("properties", {})


def test_render_includes_notes_and_state():
    out = render_observation("kite the archer", {"round": 2})
    assert "kite the archer" in out
    assert '"round": 2' in out


def test_capture_notes_strips_and_stores():
    agent = _StubAgent()
    call = capture_notes(agent, ToolCall("end_turn", {"note": "focus the mage"}))
    assert "note" not in call.arguments
    assert agent.notes == "focus the mage"


def test_decide_one_action_returns_first_tool_call():
    agent = _StubAgent()
    seq = [ToolCall("attack", {"defender_id": "g1"})]
    call = decide_one_action(lambda m, t: seq.pop(0), agent, {}, TOOLS)
    assert call.name == "attack"


def test_decide_one_action_retries_then_raises():
    agent = _StubAgent()
    calls = {"n": 0}

    def always_none(messages, tools):
        calls["n"] += 1
        return None

    with pytest.raises(RuntimeError, match="no tool call"):
        decide_one_action(always_none, agent, {}, TOOLS)
    assert calls["n"] == 2  # initial + one retry
