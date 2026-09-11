"""Run a LIVE arena match with an OpenRouter model (team A) vs a chosen opponent.

    python -m examples.arena_openrouter_match                      # OpenRouter vs scripted
    python -m examples.arena_openrouter_match --model nvidia/nemotron-nano-9b-v2:free
    python -m examples.arena_openrouter_match --opponent claude    # cross-provider!
    python -m examples.arena_openrouter_match --opponent openrouter:openai/gpt-4o-mini

Free OpenRouter models cost ~nothing; paid models/opponents bill the respective key. Needs
the `openai` SDK and an OpenRouter key in secrets/openrouter.key (or $OPENROUTER_API_KEY) —
see docs/AGENT_ARENA_LLM_SETUP.md. Cross-provider (`--opponent claude`) also needs a Claude key.
"""

import argparse

from src.arena.agent import Agent, ScriptedAgent
from src.arena.match import run_match
from src.arena.openrouter_agent import DEFAULT_MODEL, OpenRouterAgent
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


def _make_agent(spec: str, name: str, team: str) -> Agent:
    """Build an opponent from a spec: 'scripted' | 'claude[:model]' | 'openrouter[:model]'."""
    if spec == "scripted":
        return ScriptedAgent(name, team)
    if spec.startswith("claude"):
        from src.arena.llm_agent import DEFAULT_MODEL as CLAUDE_DEFAULT, LLMAgent

        model = spec.split(":", 1)[1] if ":" in spec else CLAUDE_DEFAULT
        return LLMAgent(name, team, model=model)
    model = spec.split(":", 1)[1] if ":" in spec else DEFAULT_MODEL
    return OpenRouterAgent(name, team, model=model)  # 'openrouter[:model]' or a bare model id


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live OpenRouter arena match.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model for team A.")
    parser.add_argument(
        "--opponent", default="scripted",
        help="Team B: 'scripted' | 'claude[:model]' | 'openrouter[:model]'.",
    )
    parser.add_argument("--seed", type=int, default=1, help="RNG seed for a reproducible battle.")
    args = parser.parse_args()

    combat = build_combat([_fighter("Knight", "a", 0.0), _fighter("Bandit", "b", 10.0)])
    agents = {
        "a": OpenRouterAgent(f"OR:{args.model}", "a", model=args.model),
        "b": _make_agent(args.opponent, f"B:{args.opponent}", "b"),
    }

    print(f"Running OpenRouter {args.model} (team A) vs {args.opponent} (team B), seed {args.seed}...\n")
    transcript = Transcript()
    result = run_match(combat, agents, seed=args.seed, transcript=transcript)

    print(f"=== winner={result.winner!r} ({result.reason}) in {result.rounds} rounds ===")
    for team, frac in result.hp_fraction.items():
        print(f"  team {team}: {frac:.0%} HP remaining")

    path = transcript.save_auto(label=f"{args.model}_vs_{args.opponent}")
    print(f"\nTranscript saved to {path} ({len(transcript.records)} records).")


if __name__ == "__main__":
    main()
