"""Tests for the baseline agents — they must decide purely from the observation dict."""

import random

from src.arena.agent import RandomAgent, ScriptedAgent
from src.arena.observation import build_observation
from src.arena.tools import TOOLS

from .conftest import melee_attack


def _obs(make_combat, entities, viewer):
    return build_observation(make_combat(entities), viewer)


def test_scripted_attacks_reachable_enemy(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    obs = _obs(make_combat, [fighter, goblin], fighter)

    call = ScriptedAgent("A", "a").decide(obs, TOOLS)

    assert call.name == "attack"
    assert call.arguments["defender_id"] == goblin.entity_id
    assert call.arguments["action_name"] == "Longsword"


def test_scripted_targets_lowest_hp(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    healthy = make_entity("Ogre", team="b", pos=(5, 0, 0), hp=30)
    wounded = make_entity("Goblin", team="b", pos=(0, 0, 5), hp=30)
    wounded.current_hp = 4
    obs = _obs(make_combat, [fighter, healthy, wounded], fighter)

    call = ScriptedAgent("A", "a").decide(obs, TOOLS)

    assert call.arguments["defender_id"] == wounded.entity_id


def test_scripted_moves_toward_distant_enemy(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(60, 0, 0))
    obs = _obs(make_combat, [fighter, goblin], fighter)

    call = ScriptedAgent("A", "a").decide(obs, TOOLS)

    assert call.name == "move"
    # Steps toward the enemy, no further than the 30 ft movement budget.
    assert 0 < call.arguments["x"] <= 30
    assert call.arguments["z"] == 0


def test_scripted_ends_turn_with_no_enemies(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    ally = make_entity("Cleric", team="a", pos=(5, 0, 0))
    obs = _obs(make_combat, [fighter, ally], fighter)

    assert ScriptedAgent("A", "a").decide(obs, TOOLS).name == "end_turn"


def test_random_agent_is_deterministic_and_ends_turn_when_idle(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    ally = make_entity("Cleric", team="a", pos=(5, 0, 0))
    obs = _obs(make_combat, [fighter, ally], fighter)

    agent = RandomAgent("R", "a", rng=random.Random(0))
    # No enemies -> the only candidate is end_turn.
    assert agent.decide(obs, TOOLS).name == "end_turn"


def test_random_agent_only_picks_legal_candidates(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    obs = _obs(make_combat, [fighter, goblin], fighter)

    agent = RandomAgent("R", "a", rng=random.Random(1))
    call = agent.decide(obs, TOOLS)
    assert call.name in {"attack", "move", "end_turn"}
    if call.name == "attack":
        assert call.arguments["defender_id"] == goblin.entity_id


def test_agent_notes_are_capped():
    agent = ScriptedAgent("A", "a")
    agent.remember("x" * 1000)
    assert len(agent.notes) == ScriptedAgent.MAX_NOTES_CHARS
