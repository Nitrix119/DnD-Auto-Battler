"""Drive one entity's turn: observe → decide → act → observe, until the turn ends.

The driver calls the agent for **one** action at a time (B2), executes it through the
:class:`~src.arena.tools.ToolExecutor`, feeds the result back into the next observation,
and repeats. It stops when the agent ends its turn, or a guard trips:

* **failure budget (C2):** 3 consecutive or 5 total illegal/failed calls in a turn →
  auto-end the turn (illegal-move rate is a metric);
* **action cap:** a safety valve against an agent that acts forever without ending;
* **dead/again:** a downed actor's turn is skipped.

**Invariant:** every ``run_turn`` advances the combat exactly once — either the agent's
own ``end_turn`` (executed by the ``ToolExecutor``) or a single forced ``end_turn``.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.arena.agent import Agent
from src.arena.information_policy import FULL_INFORMATION, InformationPolicy
from src.arena.observation import build_observation, snapshot_state
from src.arena.tools import TOOLS, ToolExecutor
from src.arena.transcript import Transcript
from src.models.entity import Entity

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem

MAX_CONSECUTIVE_FAILURES = 3
MAX_TOTAL_FAILURES = 5
MAX_ACTIONS_PER_TURN = 20


@dataclass
class TurnOutcome:
    """Summary of one entity's turn (useful for tests and metrics)."""

    entity_id: str
    actions_taken: int
    failures: int
    forced_end: bool  # True when the driver ended the turn (budget/cap/skip), not the agent


def run_turn(
    combat: "CombatSystem",
    actor: Entity,
    agent: Agent,
    *,
    executor: Optional[ToolExecutor] = None,
    policy: InformationPolicy = FULL_INFORMATION,
    transcript: Optional[Transcript] = None,
    max_actions: int = MAX_ACTIONS_PER_TURN,
) -> TurnOutcome:
    """Run *actor*'s whole turn under *agent*'s control; return a :class:`TurnOutcome`."""
    executor = executor or ToolExecutor(combat)

    if not actor.is_alive():  # a downed creature takes no turn
        combat.end_turn(actor.entity_id)
        return _finish(transcript, combat, actor, 0, 0, forced=True)

    if transcript is not None:
        transcript.turn_start(actor.entity_id, combat.round, combat.turn)

    consecutive = 0
    failures = 0
    actions = 0

    while True:
        observation = build_observation(combat, actor, policy)
        call = agent.decide(observation, TOOLS)
        result = executor.apply(actor, call, policy)
        if transcript is not None:
            transcript.action(actor.entity_id, call, result)

        if not result["ok"]:
            consecutive += 1
            failures += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES or failures >= MAX_TOTAL_FAILURES:
                combat.end_turn(actor.entity_id)
                return _finish(transcript, combat, actor, actions, failures, forced=True)
            continue

        consecutive = 0
        if result.get("ended_turn"):  # the agent ended its own turn (already advanced)
            return _finish(transcript, combat, actor, actions, failures, forced=False)

        actions += 1
        if actions >= max_actions:
            combat.end_turn(actor.entity_id)
            return _finish(transcript, combat, actor, actions, failures, forced=True)


def _finish(
    transcript: Optional[Transcript],
    combat: "CombatSystem",
    actor: Entity,
    actions: int,
    failures: int,
    *,
    forced: bool,
) -> TurnOutcome:
    if transcript is not None:
        transcript.turn_end(actor.entity_id, snapshot_state(combat))
    return TurnOutcome(actor.entity_id, actions, failures, forced)
