"""The match_start record must carry replay setup: stat blocks + an initial snapshot.

These are behaviour tests (CLAUDE.md §4): they run a real ``run_match`` and assert the
logged setup is populated from the live combat, and that the stat-block serializer is
pure. The playback page relies on this data to render an exact frame 0 and show every
combatant's options.
"""

import copy

from src.arena.agent import ScriptedAgent
from src.arena.match import run_match
from src.arena.observation import serialize_stat_block
from src.arena.transcript import Transcript

from .conftest import melee_attack


def _duel(make_entity, make_combat):
    a = make_entity("Knight", team="a", pos=(0, 0, 0), hp=12, attacks=[melee_attack()])
    b = make_entity("Bandit", team="b", pos=(5, 0, 0), hp=12, attacks=[melee_attack()])
    return make_combat([a, b])


def test_match_start_logs_stat_blocks_with_options(make_entity, make_combat):
    combat = _duel(make_entity, make_combat)
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
    transcript = Transcript()

    run_match(combat, agents, seed=7, transcript=transcript)

    start = transcript.records_of("match_start")[0]
    assert len(start["combatants"]) == 2
    by_name = {c["name"]: c for c in start["combatants"]}
    knight = by_name["Knight"]

    # Abilities carry both score and modifier for every ability.
    assert set(knight["abilities"]) == {
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    }
    assert knight["abilities"]["strength"]["score"] == 15
    assert knight["abilities"]["strength"]["modifier"] == 2
    # The full action menu is present with its damage formula.
    assert [a["name"] for a in knight["actions"]] == ["Longsword"]
    assert knight["actions"][0]["damage"][0]["formula"] == "1d8"
    assert knight["actions"][0]["range_ft"] == 5.0
    assert knight["ac"] == 15
    assert knight["max_hp"] == 12


def test_match_start_logs_initial_state_at_full_hp(make_entity, make_combat):
    combat = _duel(make_entity, make_combat)
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
    transcript = Transcript()

    run_match(combat, agents, seed=7, transcript=transcript)

    initial = transcript.records_of("match_start")[0]["initial_state"]
    ids = {e["entity_id"] for e in initial["entities"]}
    assert len(ids) == 2
    # Frame 0 is pre-combat: everyone at full HP and starting positions in feet.
    for e in initial["entities"]:
        assert e["hp"] == e["max_hp"] == 12
    positions = {e["position"]["x"] for e in initial["entities"]}
    assert positions == {0.0, 5.0}


def test_serialize_stat_block_is_pure(make_entity, make_combat):
    entity = make_entity(
        "Knight", team="a", pos=(0, 0, 0), hp=12, attacks=[melee_attack()]
    )
    before = copy.deepcopy(entity.stat_block)

    serialize_stat_block(entity)

    assert entity.stat_block == before


def test_match_start_stays_optional_without_setup():
    """A bare match_start (no combatants/initial_state) omits the keys, not null."""
    transcript = Transcript()
    transcript.match_start({"a": ["x"]}, round_cap=20)

    start = transcript.records_of("match_start")[0]
    assert "combatants" not in start
    assert "initial_state" not in start
    assert start["round_cap"] == 20
