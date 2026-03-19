"""Tests for the SpellRegistry and CombatSystem spell lookup integration."""

import pytest
from pathlib import Path

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat import CombatSystem, SpellRegistry
from src.loaders.stat_block_loader import StatBlockLoader

SPELLS_DIR = str(Path(__file__).parent.parent / "examples" / "spells")
WIZARD_JSON = str(Path(__file__).parent.parent / "examples" / "creatures" / "characters" / "wizard.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(name="Mage", known_spells=None):
    abilities = AbilityScores(8, 14, 14, 18, 12, 10)
    sb = StatBlock(
        name=name,
        ability_scores=abilities,
        hit_points_max=28,
        armor_class=12,
        proficiency_bonus=3,
        known_spells=known_spells or [],
    )
    return Entity(sb)


def _make_registry() -> SpellRegistry:
    registry = SpellRegistry()
    registry.scan_directory(SPELLS_DIR)
    return registry


# ---------------------------------------------------------------------------
# SpellRegistry unit tests
# ---------------------------------------------------------------------------

class TestSpellRegistry:
    def test_scan_directory_loads_spells(self):
        registry = _make_registry()
        assert len(registry) > 0

    def test_contains_fireball(self):
        registry = _make_registry()
        assert "Fireball" in registry

    def test_contains_fire_bolt(self):
        registry = _make_registry()
        assert "Fire Bolt" in registry

    def test_contains_haste(self):
        registry = _make_registry()
        assert "Haste" in registry

    def test_get_returns_spell_action(self):
        registry = _make_registry()
        spell = registry.get("Fireball")
        assert isinstance(spell, SpellAction)
        assert spell.name == "Fireball"
        assert spell.spell_level == 3

    def test_get_fire_bolt_is_cantrip(self):
        registry = _make_registry()
        spell = registry.get("Fire Bolt")
        assert spell.spell_level == 0

    def test_get_haste_is_concentration(self):
        registry = _make_registry()
        spell = registry.get("Haste")
        assert spell.duration.concentration is True

    def test_get_unknown_spell_raises_key_error(self):
        registry = _make_registry()
        with pytest.raises(KeyError):
            registry.get("Wish")

    def test_contains_returns_false_for_unknown(self):
        registry = _make_registry()
        assert "Wish" not in registry

    def test_register_adds_spell(self):
        registry = SpellRegistry()
        # Manually load one spell and register it
        spell = StatBlockLoader.load_spell_from_json(
            str(Path(SPELLS_DIR) / "firebolt.json")
        )
        registry.register(spell)
        assert spell.name in registry
        assert registry.get(spell.name) is spell

    def test_register_overwrites_existing(self):
        registry = _make_registry()
        old = registry.get("Fire Bolt")
        # Re-register the same spell (no error expected)
        registry.register(old)
        assert registry.get("Fire Bolt") is old

    def test_scan_duplicate_raises_value_error(self, tmp_path):
        """Two JSON files defining the same spell name should raise ValueError."""
        import shutil
        src = Path(SPELLS_DIR) / "firebolt.json"
        (tmp_path / "a.json").write_text(src.read_text())
        (tmp_path / "b.json").write_text(src.read_text())
        registry = SpellRegistry()
        with pytest.raises(ValueError, match="Duplicate"):
            registry.scan_directory(str(tmp_path))


# ---------------------------------------------------------------------------
# CombatSystem.get_spell_for_entity tests
# ---------------------------------------------------------------------------

class TestGetSpellForEntity:
    def test_returns_spell_when_entity_knows_it(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        wizard = _make_entity(known_spells=["Fireball", "Fire Bolt"])
        spell = combat.get_spell_for_entity(wizard, "Fireball")
        assert isinstance(spell, SpellAction)
        assert spell.name == "Fireball"

    def test_raises_value_error_when_entity_does_not_know_spell(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        wizard = _make_entity(known_spells=["Fire Bolt"])
        with pytest.raises(ValueError, match="does not know"):
            combat.get_spell_for_entity(wizard, "Fireball")

    def test_raises_value_error_for_empty_known_spells(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        wizard = _make_entity(known_spells=[])
        with pytest.raises(ValueError, match="does not know"):
            combat.get_spell_for_entity(wizard, "Fire Bolt")

    def test_raises_runtime_error_when_no_registry(self):
        combat = CombatSystem()
        wizard = _make_entity(known_spells=["Fire Bolt"])
        with pytest.raises(RuntimeError, match="No spell registry"):
            combat.get_spell_for_entity(wizard, "Fire Bolt")

    def test_raises_key_error_for_spell_not_in_registry(self):
        combat = CombatSystem()
        registry = SpellRegistry()  # empty registry
        combat.spell_registry = registry
        wizard = _make_entity(known_spells=["Wish"])
        with pytest.raises(KeyError):
            combat.get_spell_for_entity(wizard, "Wish")

    def test_different_entities_same_spell(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        w1 = _make_entity("Gandalf", known_spells=["Fireball"])
        w2 = _make_entity("Voldemort", known_spells=["Fireball"])
        assert combat.get_spell_for_entity(w1, "Fireball").name == "Fireball"
        assert combat.get_spell_for_entity(w2, "Fireball").name == "Fireball"

    def test_entity_cannot_use_spell_known_by_other(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        wizard = _make_entity(known_spells=["Fire Bolt"])
        goblin = _make_entity("Goblin", known_spells=[])
        # Wizard can cast Fire Bolt, goblin cannot
        assert combat.get_spell_for_entity(wizard, "Fire Bolt").name == "Fire Bolt"
        with pytest.raises(ValueError, match="does not know"):
            combat.get_spell_for_entity(goblin, "Fire Bolt")


# ---------------------------------------------------------------------------
# Wizard JSON integration tests
# ---------------------------------------------------------------------------

class TestWizardJsonIntegration:
    def test_wizard_loads_known_spells(self):
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        assert sb.known_spells == ["Fire Bolt", "Fireball", "Haste"]

    def test_wizard_knows_fire_bolt(self):
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        assert "Fire Bolt" in sb.known_spells

    def test_wizard_knows_fireball(self):
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        assert "Fireball" in sb.known_spells

    def test_wizard_knows_haste(self):
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        assert "Haste" in sb.known_spells

    def test_wizard_can_get_spells_via_combat_system(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        wizard = Entity(sb)
        for spell_name in ["Fire Bolt", "Fireball", "Haste"]:
            spell = combat.get_spell_for_entity(wizard, spell_name)
            assert spell.name == spell_name

    def test_wizard_cannot_cast_unknown_spell(self):
        combat = CombatSystem()
        combat.spell_registry = _make_registry()
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        wizard = Entity(sb)
        with pytest.raises(ValueError, match="does not know"):
            combat.get_spell_for_entity(wizard, "Charm Person")

    def test_stat_block_roundtrip_preserves_known_spells(self):
        sb = StatBlockLoader.load_from_json(WIZARD_JSON)
        data = StatBlockLoader.to_dict(sb)
        sb2 = StatBlockLoader.from_dict(data)
        assert sb2.known_spells == sb.known_spells


# ---------------------------------------------------------------------------
# StatBlockLoader known_spells parsing tests
# ---------------------------------------------------------------------------

class TestStatBlockLoaderKnownSpells:
    def test_from_dict_parses_known_spells(self):
        data = {
            "name": "Test Mage",
            "abilities": {"strength": 10, "dexterity": 10, "constitution": 10,
                          "intelligence": 16, "wisdom": 10, "charisma": 10},
            "hit_points": 20,
            "armor_class": 12,
            "known_spells": ["Fireball", "Fire Bolt"],
        }
        sb = StatBlockLoader.from_dict(data)
        assert sb.known_spells == ["Fireball", "Fire Bolt"]

    def test_from_dict_defaults_to_empty_list(self):
        data = {
            "name": "Fighter",
            "abilities": {"strength": 16, "dexterity": 10, "constitution": 14,
                          "intelligence": 10, "wisdom": 10, "charisma": 10},
            "hit_points": 40,
            "armor_class": 16,
        }
        sb = StatBlockLoader.from_dict(data)
        assert sb.known_spells == []

    def test_to_dict_includes_known_spells(self):
        sb = StatBlock(
            name="Mage",
            ability_scores=AbilityScores(8, 14, 14, 18, 12, 10),
            hit_points_max=28,
            armor_class=12,
            known_spells=["Fireball", "Haste"],
        )
        data = StatBlockLoader.to_dict(sb)
        assert data["known_spells"] == ["Fireball", "Haste"]

    def test_to_dict_empty_known_spells(self):
        sb = StatBlock(
            name="Fighter",
            ability_scores=AbilityScores(16, 10, 14, 10, 10, 10),
            hit_points_max=40,
            armor_class=16,
        )
        data = StatBlockLoader.to_dict(sb)
        assert data["known_spells"] == []
