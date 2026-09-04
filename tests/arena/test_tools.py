"""Tests for the tool executor — the single execution seam.

These run against a live ``CombatSystem`` (started, with the actor's turn forced) so
they prove the executor really dispatches to the engine and shapes/gates results, not
that it echoes a hand-built dict.
"""

from src.arena.information_policy import InformationPolicy
from src.arena.tools import TOOLS, ToolCall, ToolExecutor
from src.models.action_resources import ActionCost

from .conftest import force_turn, load_spell, melee_attack

NO_AC = InformationPolicy(reveal_enemy_ac=False)


def _started(make_combat, entities, focus, registry=None):
    combat = make_combat(entities, registry=registry)
    combat.start_combat()
    force_turn(combat, focus)
    return combat


# -- schema ------------------------------------------------------------------


def test_tools_are_json_schema_shaped():
    names = {t["name"] for t in TOOLS}
    assert names == {"attack", "cast_spell", "move", "end_turn"}
    for tool in TOOLS:
        assert set(tool) >= {"name", "description", "input_schema"}
        assert tool["input_schema"]["type"] == "object"


# -- attack ------------------------------------------------------------------


def test_attack_applies_and_shows_own_roll(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=20)
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("attack", {"action_name": "Longsword", "defender_id": goblin.entity_id})
    )

    assert result["ok"] is True
    assert result["action"] == "attack"
    assert result["target_id"] == goblin.entity_id
    assert isinstance(result["hit"], bool)
    assert isinstance(result["damage"], int)
    # Own roll is always shown...
    assert "attack_roll" in result["roll"]
    assert "attack_total" in result["roll"]
    # ...and under full information the target's AC is too (C3).
    assert result["roll"]["target_ac"] == goblin.ac


def test_attack_hides_target_ac_under_policy(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=20)
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter,
        ToolCall("attack", {"action_name": "Longsword", "defender_id": goblin.entity_id}),
        NO_AC,
    )

    assert result["ok"] is True
    assert "attack_roll" in result["roll"]  # own roll still shown
    assert "target_ac" not in result["roll"]  # the number rolled against is hidden


def test_attack_unknown_defender_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("attack", {"action_name": "Longsword", "defender_id": "nope"})
    )
    assert result["ok"] is False
    assert "Unknown entity_id" in result["error"]


def test_attack_unknown_action_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("attack", {"action_name": "Fireball", "defender_id": goblin.entity_id})
    )
    assert result["ok"] is False
    assert "no attack called" in result["error"]


def test_attack_out_of_turn_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], goblin)  # goblin's turn, not fighter's

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("attack", {"action_name": "Longsword", "defender_id": goblin.entity_id})
    )
    assert result["ok"] is False
    assert "not" in result["error"].lower() and "turn" in result["error"].lower()


# -- move --------------------------------------------------------------------


def test_move_applies_and_spends_movement(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(50, 0, 50))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(fighter, ToolCall("move", {"x": 15, "y": 0, "z": 0}))

    assert result["ok"] is True
    assert result["position"] == {"x": 15, "y": 0, "z": 0}
    assert result["movement_remaining"] == 15  # 30 - 15 ft travelled
    assert (fighter.x, fighter.z) == (15, 0)


def test_move_too_far_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(200, 0, 200))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(fighter, ToolCall("move", {"x": 100, "z": 100}))
    assert result["ok"] is False
    assert "afford" in result["error"].lower()
    assert (fighter.x, fighter.z) == (0, 0)  # position unchanged on failure


# -- end_turn ----------------------------------------------------------------


def test_end_turn_advances_the_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)
    assert combat.get_current_entity() is fighter

    result = ToolExecutor(combat).apply(fighter, ToolCall("end_turn", {}))

    assert result["ok"] is True
    assert result["ended_turn"] is True
    assert combat.get_current_entity() is not fighter


# -- cast_spell --------------------------------------------------------------


def test_cast_attack_spell_shows_own_roll_gates_ac(make_entity, make_combat, registry_with):
    firebolt = load_spell("firebolt.json")
    wizard = make_entity(
        "Wizard", team="a", pos=(0, 0, 0),
        known_spells=[firebolt.name], spellcasting_ability="intelligence",
    )
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0), hp=20)
    combat = _started(make_combat, [wizard, goblin], wizard, registry=registry_with(firebolt))

    executor = ToolExecutor(combat)
    full = executor.apply(
        wizard, ToolCall("cast_spell", {"spell_name": firebolt.name, "target_ids": [goblin.entity_id]})
    )
    assert full["ok"] is True
    roll = full["results"][0]["roll"]
    assert "attack_roll" in roll
    assert roll["target_ac"] == goblin.ac

    # Reset the wizard's action for a second cast under a stricter policy.
    wizard.resources.actions = 1
    force_turn(combat, wizard)
    hidden = executor.apply(
        wizard,
        ToolCall("cast_spell", {"spell_name": firebolt.name, "target_ids": [goblin.entity_id]}),
        NO_AC,
    )
    assert "target_ac" not in hidden["results"][0]["roll"]


def test_cast_save_spell_shows_own_dc_gates_target_roll(make_entity, make_combat, registry_with):
    sacred_flame = load_spell("sacred_flame.json")
    cleric = make_entity(
        "Cleric", team="a", pos=(0, 0, 0),
        known_spells=[sacred_flame.name], spellcasting_ability="wisdom",
    )
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0), hp=20)
    combat = _started(make_combat, [cleric, goblin], cleric, registry=registry_with(sacred_flame))

    result = ToolExecutor(combat).apply(
        cleric,
        ToolCall("cast_spell", {"spell_name": sacred_flame.name, "target_ids": [goblin.entity_id]}),
        NO_AC,
    )

    assert result["ok"] is True
    roll = result["results"][0]["roll"]
    assert "save_dc" in roll  # the actor's own DC is shown...
    assert "target_saved" in roll  # ...and the outcome...
    assert "target_save_roll" not in roll  # ...but not the target's roll value under NO_AC


def test_cast_unknown_spell_is_structured_error(make_entity, make_combat, registry_with):
    firebolt = load_spell("firebolt.json")
    wizard = make_entity("Wizard", team="a", known_spells=[firebolt.name],
                         spellcasting_ability="intelligence")
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0))
    combat = _started(make_combat, [wizard, goblin], wizard, registry=registry_with(firebolt))

    result = ToolExecutor(combat).apply(
        wizard, ToolCall("cast_spell", {"spell_name": "Meteor Swarm", "target_ids": [goblin.entity_id]})
    )
    assert result["ok"] is False
    assert "does not know" in result["error"]


# -- dispatch ----------------------------------------------------------------


def test_unknown_tool_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(fighter, ToolCall("teleport", {}))
    assert result["ok"] is False
    assert "Unknown tool" in result["error"]


def test_cost_constant_sanity():
    # Guards the melee fixture's cost assumption used across tests.
    assert ActionCost(actions=1).actions == 1
