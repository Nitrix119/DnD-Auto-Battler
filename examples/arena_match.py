"""Run a headless arena match: two scripted agents duel, no API/LLM needed.

    python -m examples.arena_match

Demonstrates the whole pipeline end-to-end — build a combat, assign one agent per team,
run the match under a seed, and print the result plus a short battle log from the
transcript. This is the "see it run" milestone: no network, fully deterministic.
"""

from src.arena.agent import ScriptedAgent
from src.arena.match import run_match
from src.arena.setup import build_combat
from src.arena.transcript import Transcript
from src.models import AbilityScores, AttackAction, Damage, DamageType, Entity, StatBlock


def _fighter(name: str, team: str, hp: int, x: float) -> Entity:
    block = StatBlock(
        name=name,
        ability_scores=AbilityScores(16, 14, 14, 10, 12, 10),
        hit_points_max=hp,
        armor_class=15,
        proficiency_bonus=2,
    )
    block.add_action(
        AttackAction(
            name="Greatsword",
            description="A heavy two-handed sword.",
            bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, formula="2d6")],
            range_ft=5.0,
        )
    )
    entity = Entity(block, team=team)
    entity.x, entity.y, entity.z = x, 0.0, 0.0
    return entity


def main() -> None:
    knight = _fighter("Knight", "a", hp=30, x=0.0)
    bandit = _fighter("Bandit", "b", hp=30, x=10.0)  # 10 ft apart — one step to melee

    combat = build_combat([knight, bandit])
    agents = {"a": ScriptedAgent("Team A", "a"), "b": ScriptedAgent("Team B", "b")}
    transcript = Transcript()

    result = run_match(combat, agents, seed=2026, transcript=transcript)

    print(f"\n=== Match over: winner={result.winner!r} "
          f"({result.reason}) in {result.rounds} rounds ===\n")
    for team, frac in result.hp_fraction.items():
        print(f"  team {team}: {frac:.0%} HP remaining")

    print("\n--- Battle log ---")
    for record in transcript.records_of("action"):
        call, res = record["call"], record["result"]
        actor = record["actor_id"][:8]
        if not res["ok"]:
            line = f"illegal {call['name']} ({res['error']})"
        elif call["name"] == "attack":
            outcome = f"hit for {res['damage']}" if res["hit"] else "missed"
            line = f"attacks {res['target_id'][:8]} - {outcome}"
        elif call["name"] == "move":
            p = res["position"]
            line = f"moves to ({p['x']:.0f}, {p['z']:.0f})"
        else:
            line = call["name"]
        print(f"  [{actor}] {line}")


if __name__ == "__main__":
    main()
