"""A weapon attack is a block program, like everything else the engine resolves.

A weapon is authored in the concise flat form creature JSON has always used
(`bonus_to_hit` + a `damage` list); `AttackResolver._default_program` builds the
implied `[attack_roll, damage…]` program from it. A weapon that needs more than the
default may author a `program` directly — the same field, validated the same way, as
a spell. These prove both halves, including that the loader actually populates the
field (a model field + a resolver branch can both exist while nothing wires them).
"""

import json
from unittest.mock import patch

import pytest

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType
from src.models.action import AttackAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver, _default_program
from src.loaders import StatBlockLoader


def _entity(name="E", ac=10, hp=60):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=ac,
    )
    return Entity(sb)


def _resolver():
    bus = EventBus()
    dp = DamageProcessor(bus)
    return AttackResolver(bus, dp)


def _hit(ar, attacker, defender, weapon, roll=18, dmg=4):
    with patch("src.spells.blocks.rolls.roll_d20", return_value=roll), \
         patch("src.spells.blocks.damage.roll_formula", return_value=dmg):
        return ar.resolve(attacker, defender, weapon)


# ── The implied program ───────────────────────────────────────────────────────

class TestDefaultProgram:

    def test_flat_weapon_builds_attack_roll_then_damage(self):
        weapon = AttackAction(
            name="Sword", description="", bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, 0, formula="1d8")],
        )
        program = _default_program(weapon)
        assert [b["block"] for b in program] == ["attack_roll", "damage"]
        assert program[0]["attack_bonus"] == 5
        assert program[1] == {
            "block": "damage", "formula": "1d8",
            "damage_type": "SLASHING", "requires_hit": True,
        }

    def test_multiple_damage_entries_each_get_a_block(self):
        weapon = AttackAction(
            name="Flametongue", description="", bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, 0, formula="1d8"),
                    Damage(DamageType.FIRE, 0, formula="2d6")],
        )
        assert [b["block"] for b in _default_program(weapon)] == [
            "attack_roll", "damage", "damage",
        ]

    def test_it_resolves(self):
        ar = _resolver()
        attacker, defender = _entity("A"), _entity("D", ac=5)
        weapon = AttackAction(
            name="Sword", description="", bonus_to_hit=5,
            damage=[Damage(DamageType.SLASHING, 0, formula="1d8")],
        )
        hp0 = defender.hp
        hit, damage, _log, _detail = _hit(ar, attacker, defender, weapon)
        assert hit and damage == 4
        assert hp0 - defender.hp == 4

    def test_damage_is_gated_on_the_hit(self):
        ar = _resolver()
        attacker, defender = _entity("A"), _entity("D", ac=30)
        weapon = AttackAction(
            name="Sword", description="", bonus_to_hit=0,
            damage=[Damage(DamageType.SLASHING, 0, formula="1d8")],
        )
        hp0 = defender.hp
        hit, damage, _log, _detail = _hit(ar, attacker, defender, weapon, roll=2)
        assert not hit and damage == 0
        assert defender.hp == hp0


# ── An authored program wins ──────────────────────────────────────────────────

class TestAuthoredProgram:

    _PROGRAM = [
        {"block": "attack_roll", "attack_bonus": 7},
        {"block": "damage", "formula": "1d8", "damage_type": "SLASHING",
         "requires_hit": True},
        {"block": "damage", "formula": "2d6", "damage_type": "RADIANT",
         "requires_hit": True},
    ]

    def test_authored_program_is_used_instead_of_the_default(self):
        ar = _resolver()
        attacker, defender = _entity("A"), _entity("D", ac=5)
        weapon = AttackAction(
            name="Holy Avenger", description="", bonus_to_hit=7,
            damage=[Damage(DamageType.SLASHING, 0, formula="1d8")],
            program=self._PROGRAM,
        )
        hp0 = defender.hp
        hit, _damage, _log, _detail = _hit(ar, attacker, defender, weapon)
        # Two damage blocks fire (4 each), not the one the flat list implies.
        assert hit and hp0 - defender.hp == 8


# ── The loader wires it end to end ────────────────────────────────────────────

class TestLoaderWiring:

    def _creature(self, action_extra):
        return {
            "name": "Test Knight",
            "ability_scores": {"strength": 10, "dexterity": 10, "constitution": 10,
                               "intelligence": 10, "wisdom": 10, "charisma": 10},
            "hit_points_max": 40, "armor_class": 12,
            "actions": [dict({
                "type": "attack", "name": "Blade", "description": "",
                "bonus_to_hit": 7,
                "damage": [{"type": "SLASHING", "amount": 0, "formula": "1d8"}],
            }, **action_extra)],
        }

    def test_loader_populates_a_weapon_program(self, tmp_path):
        path = tmp_path / "knight.json"
        path.write_text(json.dumps(self._creature(
            {"program": TestAuthoredProgram._PROGRAM})))
        sb = StatBlockLoader.load_from_json(str(path))
        blade = sb.actions[0]
        assert [b["block"] for b in blade.program] == [
            "attack_roll", "damage", "damage",
        ]

    def test_a_loaded_weapon_program_actually_resolves(self, tmp_path):
        path = tmp_path / "knight.json"
        path.write_text(json.dumps(self._creature(
            {"program": TestAuthoredProgram._PROGRAM})))
        sb = StatBlockLoader.load_from_json(str(path))
        ar = _resolver()
        attacker, defender = Entity(sb), _entity("D", ac=5)
        hp0 = defender.hp
        _hit(ar, attacker, defender, sb.actions[0])
        assert hp0 - defender.hp == 8  # both authored damage blocks landed

    def test_a_weapon_without_a_program_loads_with_an_empty_one(self, tmp_path):
        path = tmp_path / "knight.json"
        path.write_text(json.dumps(self._creature({})))
        sb = StatBlockLoader.load_from_json(str(path))
        assert sb.actions[0].program == []  # falls back to _default_program at resolve

    def test_a_malformed_weapon_program_fails_at_load(self, tmp_path):
        path = tmp_path / "knight.json"
        path.write_text(json.dumps(self._creature(
            {"program": [{"block": "no_such_block"}]})))
        with pytest.raises(ValueError, match="no_such_block"):
            StatBlockLoader.load_from_json(str(path))

    def test_round_trip_preserves_the_program(self, tmp_path):
        path = tmp_path / "knight.json"
        path.write_text(json.dumps(self._creature(
            {"program": TestAuthoredProgram._PROGRAM})))
        sb = StatBlockLoader.load_from_json(str(path))
        serialized = StatBlockLoader._serialize_action(sb.actions[0])
        assert serialized["program"] == TestAuthoredProgram._PROGRAM
