"""Tests for the match runner — a full headless battle, end to end."""

from typing import Any, Dict, List

from src.arena.agent import Agent, ScriptedAgent
from src.arena.match import run_match
from src.arena.tools import ToolCall
from src.arena.transcript import Transcript
from src.combat.enums import CombatState

from .conftest import melee_attack


class PacifistAgent(Agent):
    """Always ends its turn — used to force a round-cap outcome."""

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        return ToolCall("end_turn", {})


def _duel(make_entity, make_combat):
    a = make_entity("Knight", team="a", pos=(0, 0, 0), hp=12, attacks=[melee_attack()])
    b = make_entity("Bandit", team="b", pos=(5, 0, 0), hp=12, attacks=[melee_attack()])
    return make_combat([a, b])


def test_scripted_duel_produces_a_winner(make_entity, make_combat):
    combat = _duel(make_entity, make_combat)
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
    transcript = Transcript()

    result = run_match(combat, agents, seed=7, transcript=transcript)

    assert combat.state == CombatState.ENDED
    assert result.reason == "last_standing"
    assert result.winner in {"a", "b"}
    assert result.rounds <= 20
    # The transcript captured the whole match.
    assert transcript.records_of("match_start")
    assert transcript.records_of("action")
    assert transcript.records_of("match_end")[0]["winner"] == result.winner


def test_match_is_deterministic_under_a_seed(make_entity, make_combat):
    def play():
        combat = _duel(make_entity, make_combat)
        agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
        return run_match(combat, agents, seed=42)

    first, second = play(), play()
    assert (first.winner, first.rounds) == (second.winner, second.rounds)


def test_round_cap_ends_a_stalemate_as_a_draw(make_entity, make_combat):
    combat = _duel(make_entity, make_combat)
    agents = {"a": PacifistAgent("A", "a"), "b": PacifistAgent("B", "b")}

    result = run_match(combat, agents, seed=1, round_cap=2)

    assert result.reason == "round_cap"
    assert result.winner is None  # equal (full) HP -> draw
    assert combat.state == CombatState.ACTIVE  # nobody died


def test_stronger_side_wins(make_entity, make_combat):
    strong = make_entity("Champion", team="a", pos=(0, 0, 0), hp=40, attacks=[melee_attack()])
    weakling = make_entity("Kobold", team="b", pos=(5, 0, 0), hp=3, attacks=[melee_attack()])
    combat = make_combat([strong, weakling])
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}

    result = run_match(combat, agents, seed=3)

    assert result.winner == "a"
    assert result.reason == "last_standing"
