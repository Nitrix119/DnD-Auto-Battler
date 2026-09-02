"""Tests that StatBlockLoader wires damage vulnerability/resistance/immunity.

Regression coverage for a bug where the loader parsed no damage-modifier fields,
so per-creature resistances/immunities/vulnerabilities declared in JSON were
silently dropped and could never fire in an actual battle (the rules were only
ever exercised against hand-built StatBlocks in test_damage_modifiers.py).
"""

import os

import pytest

from src.combat.damage_processor import DamageProcessor
from src.combat.event_bus import EventBus
from src.loaders.stat_block_loader import StatBlockLoader
from src.models import Damage, DamageType, Entity
from src.rules import RuleEngine

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")
GLOBAL_RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules", "global")
STONE_GOLEM_JSON = os.path.join(EXAMPLES_DIR, "creatures", "stone_golem.json")


# ---------------------------------------------------------------------------
# from_dict parses the three modifier lists
# ---------------------------------------------------------------------------

class TestLoaderParsesDamageModifiers:
    def _load(self, **fields):
        data = {
            "name": "Test",
            "abilities": {},
            "hit_points_max": 20,
            "armor_class": 12,
        }
        data.update(fields)
        return StatBlockLoader.from_dict(data)

    def test_resistances_parsed(self):
        sb = self._load(damage_resistances=["FIRE", "cold"])  # case-insensitive
        assert DamageType.FIRE in sb.damage_resistances
        assert DamageType.COLD in sb.damage_resistances

    def test_immunities_parsed(self):
        sb = self._load(damage_immunities=["POISON", "PSYCHIC"])
        assert DamageType.POISON in sb.damage_immunities
        assert DamageType.PSYCHIC in sb.damage_immunities

    def test_vulnerabilities_parsed(self):
        sb = self._load(damage_vulnerabilities=["fire"])
        assert DamageType.FIRE in sb.damage_vulnerabilities

    def test_absent_fields_default_empty(self):
        sb = self._load()
        assert sb.damage_resistances == []
        assert sb.damage_immunities == []
        assert sb.damage_vulnerabilities == []

    def test_unknown_type_raises_friendly_error(self):
        with pytest.raises(ValueError) as exc:
            self._load(damage_resistances=["SLASH"])  # not a real DamageType
        assert "SLASH" in str(exc.value)
        assert "damage_resistances" in str(exc.value)

    def test_round_trip_preserves_modifiers(self):
        sb = self._load(
            damage_resistances=["FIRE"],
            damage_immunities=["POISON"],
        )
        data = StatBlockLoader.to_dict(sb)
        assert data["damage_resistances"] == ["FIRE"]
        assert data["damage_immunities"] == ["POISON"]
        # Empty categories are omitted, not emitted as [].
        assert "damage_vulnerabilities" not in data
        reloaded = StatBlockLoader.from_dict(data)
        assert DamageType.FIRE in reloaded.damage_resistances
        assert DamageType.POISON in reloaded.damage_immunities


# ---------------------------------------------------------------------------
# End-to-end: a JSON-loaded creature actually benefits from its immunity
# ---------------------------------------------------------------------------

class TestJsonCreatureDamageModifierEndToEnd:
    def _setup(self):
        # Mirror web/routers/combat.py: the damage-modifier globals are native block
        # rules (§5d), so they resolve on the block engine — install them there and
        # disable the handled ones on the legacy engine (no double application).
        from src.spells.global_rules import install_global_rules

        bus = EventBus()
        processor = DamageProcessor(bus)
        engine = RuleEngine(bus, damage_processor=processor)
        rules = engine.load_from_directory(GLOBAL_RULES_DIR)
        handled = install_global_rules(rules, event_bus=bus, damage_processor=processor)
        for r in rules:
            if r.name in handled:
                r.enabled = False
        return processor

    def test_stone_golem_is_immune_to_poison_from_json(self):
        processor = self._setup()
        golem = Entity(StatBlockLoader.load_from_json(STONE_GOLEM_JSON))
        start = golem.hp
        processor.apply_damage(golem, [Damage(DamageType.POISON, 25)])
        assert golem.hp == start  # immunity applied → no damage

    def test_stone_golem_takes_normal_bludgeoning_from_json(self):
        processor = self._setup()
        golem = Entity(StatBlockLoader.load_from_json(STONE_GOLEM_JSON))
        start = golem.hp
        processor.apply_damage(golem, [Damage(DamageType.BLUDGEONING, 10)])
        assert golem.hp == start - 10  # not immune → full damage
