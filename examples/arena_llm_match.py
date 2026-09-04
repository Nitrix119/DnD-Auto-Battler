"""Run a LIVE arena match with a real model. THIS SPENDS API TOKENS.

    python -m examples.arena_llm_match                # LLM (team A) vs scripted (team B)
    python -m examples.arena_llm_match --llm-vs-llm   # both sides LLM (~2x the tokens)

Needs the anthropic SDK and credentials — see docs/AGENT_ARENA_LLM_SETUP.md. A single
match is small, but start with one and watch the bill. The offline, free demo is
`examples.arena_match` (scripted vs scripted).
"""

import argparse

from src.arena.agent import ScriptedAgent
from src.arena.llm_agent import LLMAgent
from src.arena.match import run_match
from src.arena.setup import build_combat
from src.arena.transcript import Transcript
from src.models import AbilityScores, AttackAction, Damage, DamageType, Entity, StatBlock


def _fighter(name: str, team: str, x: float) -> Entity:
    block = StatBlock(
        name=name,
        ability_scores=AbilityScores(16, 14, 14, 10, 12, 10),
        hit_points_max=30,
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
    e = Entity(block, team=team)
    e.x, e.y, e.z = x, 0.0, 0.0
    return e


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live LLM arena match (spends tokens).")
    parser.add_argument("--llm-vs-llm", action="store_true", help="Both sides are LLM agents.")
    parser.add_argument("--model", default="claude-opus-5", help="Model id for the LLM agent(s).")
    parser.add_argument("--seed", type=int, default=1, help="RNG seed for a reproducible battle.")
    args = parser.parse_args()

    combat = build_combat([_fighter("Knight", "a", 0.0), _fighter("Bandit", "b", 10.0)])
    agents = {
        "a": LLMAgent("LLM A", "a", model=args.model),
        "b": (
            LLMAgent("LLM B", "b", model=args.model)
            if args.llm_vs_llm
            else ScriptedAgent("Scripted B", "b")
        ),
    }

    print(f"Running {'LLM vs LLM' if args.llm_vs_llm else 'LLM vs scripted'} "
          f"with {args.model} (seed {args.seed})...\n")
    transcript = Transcript()
    result = run_match(combat, agents, seed=args.seed, transcript=transcript)

    print(f"=== winner={result.winner!r} ({result.reason}) in {result.rounds} rounds ===")
    for team, frac in result.hp_fraction.items():
        print(f"  team {team}: {frac:.0%} HP remaining")

    path = "llm_match.jsonl"
    transcript.save(path)
    print(f"\nTranscript saved to {path} ({len(transcript.records)} records).")


if __name__ == "__main__":
    main()
