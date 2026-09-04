"""Run a full match: two teams, one agent per side, until a winner or the round cap.

``run_match`` takes a prepared (but unstarted) :class:`CombatSystem` — combatants added,
spell registry set if needed — plus one :class:`~src.arena.agent.Agent` per team. It seeds
the RNG (for a reproducible battle), starts combat, and drives turns until the combat ends
or a **round cap** stops a runaway match, deciding the latter on remaining team-HP fraction
(E1). Everything is logged to the optional :class:`~src.arena.transcript.Transcript`.

Building the combat (loading creatures, positioning, teams) is the caller's job — this
keeps the runner decoupled from content loading; see ``examples/arena_match.py``.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from src.arena.agent import Agent
from src.arena.information_policy import FULL_INFORMATION, InformationPolicy
from src.arena.tools import ToolExecutor
from src.arena.transcript import Transcript
from src.arena.turn_driver import run_turn
from src.combat.enums import CombatState
from src.utils import dice

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem

DEFAULT_ROUND_CAP = 20


@dataclass
class MatchResult:
    """Outcome of a match.

    ``winner`` is the winning team's name, or ``None`` for a draw. ``reason`` is
    ``"last_standing"`` (a team was wiped out) or ``"round_cap"`` (decided on HP fraction).
    """

    winner: Optional[str]
    reason: str
    rounds: int
    survivors: Dict[Optional[str], List[str]] = field(default_factory=dict)
    hp_fraction: Dict[Optional[str], float] = field(default_factory=dict)


def _reroll_initiative(combat: "CombatSystem") -> None:
    """Re-roll initiative for all combatants under the *current* RNG state.

    Initiative is rolled at ``add_combatant`` time — before ``run_match`` can apply its
    seed — so a seeded match must re-roll it here for the seed to govern turn order too.
    Re-adds entities in stable combatant-insertion order so the result depends only on the
    seed, not on the (random) entity ids or a prior initiative sort.
    """
    tracker = combat.initiative_tracker
    tracker.initiative_order.clear()
    tracker.current_turn_index = 0
    for entity in combat.combatants:
        tracker.add_entity(entity)


def _teams(combat: "CombatSystem") -> Dict[Optional[str], List[str]]:
    teams: Dict[Optional[str], List[str]] = defaultdict(list)
    for e in combat.combatants:
        teams[e.team].append(e.entity_id)
    return dict(teams)


def _hp_fraction(combat: "CombatSystem") -> Dict[Optional[str], float]:
    cur: Dict[Optional[str], int] = defaultdict(int)
    mx: Dict[Optional[str], int] = defaultdict(int)
    for e in combat.combatants:
        cur[e.team] += max(0, e.current_hp or 0)
        mx[e.team] += e.stat_block.hit_points_max
    return {team: (cur[team] / mx[team] if mx[team] else 0.0) for team in mx}


def _decide_result(combat: "CombatSystem", round_cap: int) -> MatchResult:
    alive = combat.get_alive_entities()
    teams_alive = {e.team for e in alive}
    survivors: Dict[Optional[str], List[str]] = defaultdict(list)
    for e in alive:
        survivors[e.team].append(e.entity_id)
    hp_fraction = _hp_fraction(combat)

    if combat.state == CombatState.ENDED or len(teams_alive) <= 1:
        winner = next(iter(teams_alive)) if len(teams_alive) == 1 else None
        reason = "last_standing"
    else:  # round cap reached with both sides alive — decide on HP fraction
        reason = "round_cap"
        ranked = sorted(hp_fraction.items(), key=lambda kv: kv[1], reverse=True)
        winner = (
            ranked[0][0]
            if len(ranked) >= 2 and ranked[0][1] > ranked[1][1]
            else None
        )

    return MatchResult(
        winner=winner,
        reason=reason,
        rounds=combat.round,
        survivors=dict(survivors),
        hp_fraction=hp_fraction,
    )


def run_match(
    combat: "CombatSystem",
    agents: Dict[Optional[str], Agent],
    *,
    policies: Optional[Dict[Optional[str], InformationPolicy]] = None,
    seed: Optional[int] = None,
    round_cap: int = DEFAULT_ROUND_CAP,
    transcript: Optional[Transcript] = None,
) -> MatchResult:
    """Run *combat* (unstarted) to completion with one *agent* per team; return the result.

    Args:
        combat: Prepared CombatSystem — combatants added, registry set, not yet started.
        agents: Team name → controlling agent. Every team present must have one.
        policies: Team name → information policy (defaults to full information).
        seed: RNG seed for a reproducible battle (dice + initiative).
        round_cap: Hard round limit; a match still going is decided on HP fraction.
        transcript: Optional log to record the whole match into.
    """
    policies = policies or {}
    if seed is not None:
        dice.seed_rng(seed)
        _reroll_initiative(combat)  # so the seed governs turn order, not just resolution

    executor = ToolExecutor(combat)
    if transcript is not None:
        transcript.seed = seed
        transcript.match_start(_teams(combat), round_cap=round_cap)

    combat.start_combat()
    while combat.state == CombatState.ACTIVE and combat.round <= round_cap:
        actor = combat.get_current_entity()
        if actor is None:
            break
        agent = agents.get(actor.team)
        if agent is None:
            raise ValueError(f"No agent supplied for team {actor.team!r}")
        run_turn(
            combat,
            actor,
            agent,
            executor=executor,
            policy=policies.get(actor.team, FULL_INFORMATION),
            transcript=transcript,
        )

    result = _decide_result(combat, round_cap)
    if transcript is not None:
        transcript.match_end(result.winner, result.reason, result.rounds)
    return result
