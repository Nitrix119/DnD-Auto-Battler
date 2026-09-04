"""The agent contract and two deterministic baseline agents.

An :class:`Agent` controls a **team** (B1): the turn driver invokes it for whichever of
its creatures is currently active, so the ``observation``'s ``self`` rotates. Each call
returns exactly **one** action (B2) — the driver loops until the agent ends its turn.

The contract is **provider-neutral** (E4): an agent receives a plain-dict observation and
a list of plain-JSON tool schemas, and returns a plain :class:`~src.arena.tools.ToolCall`.
An LLM adapter is one implementation; the deterministic agents here are baselines and test
fixtures. An agent may keep a small, capped ``notes`` string across its turns — a scratchpad
memory (B3) the deterministic agents don't use but an LLM agent will.
"""

import math
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.arena.tools import TOOL_ATTACK, TOOL_CAST_SPELL, TOOL_END_TURN, TOOL_MOVE, ToolCall


class Agent(ABC):
    """Base class: decides one action from an observation.

    Subclasses implement :meth:`decide`. ``notes`` is an optional scratchpad the agent may
    carry between its own turns (capped at :data:`MAX_NOTES_CHARS`).
    """

    MAX_NOTES_CHARS = 500

    def __init__(self, name: str, team: Optional[str] = None) -> None:
        self.name = name
        self.team = team
        self.notes = ""

    def remember(self, text: str) -> None:
        """Store a capped scratchpad note to carry to the agent's next turn."""
        self.notes = (text or "")[: self.MAX_NOTES_CHARS]

    @abstractmethod
    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        """Return one action to attempt, given the current observation."""


# ---------------------------------------------------------------------------
# Geometry / selection helpers (operate purely on the observation dict)
# ---------------------------------------------------------------------------


def _dist(a: Dict[str, float], b: Dict[str, float]) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2
    )


def _pick_target(self_view: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose the enemy to hit: lowest HP if HP is visible for all, else the nearest."""
    if candidates and all("hp" in c for c in candidates):
        return min(candidates, key=lambda c: c["hp"])
    sp = self_view["position"]
    return min(candidates, key=lambda c: _dist(sp, c["position"]))


def _move_toward(
    self_view: Dict[str, Any], target_view: Dict[str, Any], budget_ft: float
) -> Optional[ToolCall]:
    """A ``move`` ToolCall stepping toward *target*, stopping just inside melee reach.

    Stops at a standoff of ``self_half + target_half + 0.5`` ft between centres — close
    enough to attack (edge gap 0.5 ft ≤ melee reach) without overlapping. Returns ``None``
    when already at/inside that standoff or the step would be negligible.
    """
    sp, tp = self_view["position"], target_view["position"]
    dist = _dist(sp, tp)
    if dist == 0:
        return None
    standoff = self_view["size_ft"] / 2 + target_view["size_ft"] / 2 + 0.5
    travel = min(dist - standoff, budget_ft)
    if travel < 1:
        return None
    ux, uy, uz = (tp["x"] - sp["x"]) / dist, (tp["y"] - sp["y"]) / dist, (tp["z"] - sp["z"]) / dist
    return ToolCall(
        TOOL_MOVE,
        {"x": sp["x"] + ux * travel, "y": sp["y"] + uy * travel, "z": sp["z"] + uz * travel},
    )


def _attacks_on_enemies(
    observation: Dict[str, Any], enemy_ids: set
) -> List[tuple]:
    """All ``(attack, enemy_target_view)`` pairs the actor could make this call."""
    enemy_by_id = {e["entity_id"]: e for e in observation["enemies"]}
    pairs = []
    for atk in observation["legal_actions"]["attacks"]:
        for t in atk["targets"]:
            if t["entity_id"] in enemy_ids:
                pairs.append((atk, enemy_by_id[t["entity_id"]]))
    return pairs


def _spells_on_enemies(
    observation: Dict[str, Any], enemy_ids: set
) -> List[tuple]:
    """All ``(spell, enemy_target_view)`` pairs for single-target spells with a reachable enemy."""
    enemy_by_id = {e["entity_id"]: e for e in observation["enemies"]}
    pairs = []
    for sp in observation["legal_actions"]["spells"]:
        for t in sp["targets"]:
            if t["entity_id"] in enemy_ids:
                pairs.append((sp, enemy_by_id[t["entity_id"]]))
    return pairs


# ---------------------------------------------------------------------------
# Baseline agents
# ---------------------------------------------------------------------------


class RandomAgent(Agent):
    """Picks uniformly among legal actions — a sanity floor.

    Candidates are every affordable attack/single-target spell against a reachable enemy,
    a step toward a random enemy when movement remains, and ``end_turn``. Deterministic
    when given a seeded ``rng``.
    """

    def __init__(self, name: str, team: Optional[str] = None, rng: Optional[random.Random] = None):
        super().__init__(name, team)
        self._rng = rng or random.Random()

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        la = observation["legal_actions"]
        enemy_ids = {e["entity_id"] for e in observation["enemies"]}
        candidates: List[ToolCall] = [ToolCall(TOOL_END_TURN, {})]

        for atk, target in _attacks_on_enemies(observation, enemy_ids):
            candidates.append(
                ToolCall(TOOL_ATTACK, {"action_name": atk["name"], "defender_id": target["entity_id"]})
            )
        for sp, target in _spells_on_enemies(observation, enemy_ids):
            candidates.append(
                ToolCall(TOOL_CAST_SPELL, {"spell_name": sp["name"], "target_ids": [target["entity_id"]]})
            )
        if la["movement_remaining_ft"] > 0 and observation["enemies"]:
            move = _move_toward(
                observation["self"], self._rng.choice(observation["enemies"]), la["movement_remaining_ft"]
            )
            if move is not None:
                candidates.append(move)

        return self._rng.choice(candidates)


class ScriptedAgent(Agent):
    """A deterministic heuristic: hit the weakest reachable enemy, else close, else end.

    Priority each call: (1) attack the lowest-HP reachable enemy; (2) failing that, cast a
    single-target spell at one; (3) failing that, move toward the nearest enemy; (4) end the
    turn. A fixed skill benchmark for LLM agents to be measured against.
    """

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        self_view = observation["self"]
        enemies = observation["enemies"]
        enemy_ids = {e["entity_id"] for e in enemies}

        attack_pairs = _attacks_on_enemies(observation, enemy_ids)
        if attack_pairs:
            target = _pick_target(self_view, [t for _, t in attack_pairs])
            atk = next(a for a, t in attack_pairs if t["entity_id"] == target["entity_id"])
            return ToolCall(TOOL_ATTACK, {"action_name": atk["name"], "defender_id": target["entity_id"]})

        spell_pairs = _spells_on_enemies(observation, enemy_ids)
        if spell_pairs:
            target = _pick_target(self_view, [t for _, t in spell_pairs])
            sp = next(s for s, t in spell_pairs if t["entity_id"] == target["entity_id"])
            return ToolCall(TOOL_CAST_SPELL, {"spell_name": sp["name"], "target_ids": [target["entity_id"]]})

        budget = observation["legal_actions"]["movement_remaining_ft"]
        if budget >= 1 and enemies:
            nearest = min(enemies, key=lambda e: _dist(self_view["position"], e["position"]))
            move = _move_toward(self_view, nearest, budget)
            if move is not None:
                return move

        return ToolCall(TOOL_END_TURN, {})
