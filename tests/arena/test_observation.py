"""Tests for building an agent's observation, including information hiding."""

from src.arena.information_policy import (
    FULL_INFORMATION,
    HP_BUCKETED,
    HP_HIDDEN,
    InformationPolicy,
)
from src.arena.observation import build_observation

from .conftest import melee_attack


def _setup(make_entity, make_combat):
    me = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    ally = make_entity("Cleric", team="a", pos=(5, 0, 0), hp=25)
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30, ac=13)
    enemy.current_hp = 7  # 7 of 30 -> "critical" bucket
    combat = make_combat([me, ally, enemy])
    return me, ally, enemy, combat


def test_observation_shape_and_viewpoint(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    obs = build_observation(combat, me)

    assert set(obs) >= {
        "state",
        "round",
        "turn",
        "is_my_turn",
        "self",
        "allies",
        "enemies",
        "legal_actions",
    }
    assert obs["self"]["entity_id"] == me.entity_id
    assert [a["entity_id"] for a in obs["allies"]] == [ally.entity_id]
    assert [e["entity_id"] for e in obs["enemies"]] == [enemy.entity_id]
    # Positions are reported in backend feet, not cell units.
    assert obs["self"]["position"] == {"x": 0, "y": 0, "z": 0}


def test_full_information_shows_enemy_hp_and_ac(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    enemy_view = build_observation(combat, me, FULL_INFORMATION)["enemies"][0]

    assert enemy_view["hp"] == 7
    assert enemy_view["max_hp"] == enemy.max_hp
    assert enemy_view["ac"] == 13
    assert "conditions" in enemy_view
    assert "resources" in enemy_view


def test_allies_are_never_redacted(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    policy = InformationPolicy(reveal_enemy_hp=False, reveal_enemy_ac=False)
    obs = build_observation(combat, me, policy)

    # Self and allies keep full detail regardless of the (enemy-only) policy.
    assert obs["self"]["hp"] == me.current_hp
    assert obs["self"]["ac"] == me.ac
    assert obs["allies"][0]["hp"] == ally.current_hp


def test_hidden_hp_removes_enemy_hp_fields(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    policy = InformationPolicy(hp_display=HP_HIDDEN)
    enemy_view = build_observation(combat, me, policy)["enemies"][0]

    assert "hp" not in enemy_view
    assert "max_hp" not in enemy_view
    assert "hp_bucket" not in enemy_view
    # position/name/team are still shown — the battlefield is shared.
    assert enemy_view["name"] == "Goblin"


def test_bucketed_hp_shows_label_not_number(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)  # enemy at 7/30

    policy = InformationPolicy(hp_display=HP_BUCKETED)
    enemy_view = build_observation(combat, me, policy)["enemies"][0]

    assert "hp" not in enemy_view
    assert enemy_view["hp_bucket"] == "critical"


def test_hidden_ac_and_resources(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    policy = InformationPolicy(reveal_enemy_ac=False, reveal_enemy_resources=False)
    enemy_view = build_observation(combat, me, policy)["enemies"][0]

    assert "ac" not in enemy_view
    assert "resources" not in enemy_view
    # HP still shown (default), proving flags are independent.
    assert enemy_view["hp"] == 7
