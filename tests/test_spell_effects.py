"""Tests for spell-applied entity effects.

Verifies that spells can declare entity effects via the ``effects`` field,
that saving throws gate their application via ``condition``, and that
``instance_fields`` expressions are evaluated correctly at spell-hit time.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import Entity, SpellAction, DamageType
from src.models.damage import Damage
from src.combat import EventBus, EventType
from src.combat.event_data import TurnEventData
from src.combat.spell_resolver import SpellResolver
from src.combat.damage_processor import DamageProcessor
from src.combat.attack_resolver import AttackResolver
from src.loaders.stat_block_loader import StatBlockLoader
from src.rules import EffectRegistry, RuleEngine, RuleLoader

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
SPELLS_DIR = EXAMPLES_DIR / "spells"
CHARACTERS_DIR = EXAMPLES_DIR / "creatures/characters"
CREATURES_DIR = EXAMPLES_DIR / "creatures"
CONDITIONS_DIR = Path(__file__).parent.parent / "rules" / "entity_effects" / "conditions"


# ── Fixtures ──────────────────────────────────────────────────────────────────

def load_wizard() -> Entity:
    sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "wizard.json"))
    return Entity(sb)


def load_goblin() -> Entity:
    sb = StatBlockLoader.load_from_json(str(CREATURES_DIR / "goblin.json"))
    return Entity(sb)


def setup_engine_and_resolver(*entities):
    """Return (bus, rule_engine, spell_resolver) wired together."""
    entity_list = list(entities)
    bus = EventBus()
    damage_proc = DamageProcessor(bus)
    registry = EffectRegistry()
    registry.scan_directory("rules/entity_effects")
    engine = RuleEngine(bus, entities_getter=lambda: entity_list,
                        damage_processor=damage_proc, effect_registry=registry)
    attack_res = AttackResolver(bus, damage_proc)
    resolver = SpellResolver(bus, damage_proc, attack_res, rule_engine=engine)
    return bus, engine, resolver


def charm_person_spell(save_dc: int = 13) -> SpellAction:
    """Load Charm Person from the example spell file."""
    spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "charm_person.json"))
    spell.save_dc = save_dc
    return spell


# ── Loading ───────────────────────────────────────────────────────────────────

class TestSpellEffectLoading:

    def test_charm_person_loads_effects(self):
        """charm_person.json should parse its effects list into spell_effects."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "charm_person.json"))
        assert len(spell.spell_effects) == 1
        entry = spell.spell_effects[0]
        assert "effect" in entry
        assert "condition" in entry
        assert "instance_fields" in entry
        assert entry["instance_fields"].get("charmer") == "event.caster"

    def test_charm_person_save_ability(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "charm_person.json"))
        assert spell.save_ability == "wisdom"
        assert spell.save_dc == 13

    def test_spell_without_effects_has_empty_list(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        assert spell.spell_effects == []

    def test_spell_without_save_ability_defaults_empty(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        assert spell.save_ability == ""


# ── Saving throws ─────────────────────────────────────────────────────────────

class TestSavingThrows:

    def test_save_roll_available_on_spell_hit_event(self):
        """SPELL_HIT event should carry save_success and save_roll when save_dc > 0."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell_hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: spell_hit_events.append(e))

        spell = charm_person_spell(save_dc=30)  # DC 30 — goblin always fails
        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        assert len(spell_hit_events) == 1
        event = spell_hit_events[0]
        assert event.data.get("save_roll") is not None
        assert event.data.get("save_success") is False

    def test_spell_hit_save_success_when_roll_beats_dc(self):
        """save_success should be True when the save roll exceeds the DC."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell_hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: spell_hit_events.append(e))

        spell = charm_person_spell(save_dc=1)  # DC 1 — goblin always succeeds
        with patch("src.combat.spell_resolver.roll_d20", return_value=20):
            resolver.resolve(wizard, [goblin], spell)

        assert spell_hit_events[0].data.get("save_success") is True

    def test_no_save_roll_when_save_dc_is_zero(self):
        """Spells with save_dc=0 should not roll a save (save_roll stays None)."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell_hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: spell_hit_events.append(e))

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))
        resolver.resolve(wizard, [goblin], spell)

        assert spell_hit_events[0].data.get("save_roll") is None
        assert spell_hit_events[0].data.get("save_success") is True


# ── Effect application on failed save ─────────────────────────────────────────

class TestSpellEffectApplicationOnFailedSave:

    def test_charmed_applied_when_save_fails(self):
        """Charm Person should apply the charmed effect when the defender fails the save."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = charm_person_spell(save_dc=30)  # DC 30 — goblin always fails

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        # The goblin should now have the charmed entity effect applied
        assert "attack_declared" in goblin.active_effects
        instances = goblin.active_effects["attack_declared"]
        assert len(instances) == 1
        assert instances[0].name == "charmed"
        assert instances[0].instance_fields.get("charmer") is wizard

    def test_charmed_not_applied_when_save_succeeds(self):
        """Charm Person should NOT apply the charmed effect when the defender succeeds."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = charm_person_spell(save_dc=1)  # DC 1 — goblin always succeeds

        with patch("src.combat.spell_resolver.roll_d20", return_value=20):
            resolver.resolve(wizard, [goblin], spell)

        assert goblin.active_effects.get("attack_declared", []) == []

    def test_charmed_attack_is_blocked_after_spell(self):
        """After a successful Charm Person cast, the charmed goblin cannot attack the wizard."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = charm_person_spell(save_dc=30)  # goblin always fails

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        # Now try the goblin attacking the wizard — should be cancelled
        action = next(a for a in goblin.stat_block.actions if a.name == "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=wizard, action=action)
        assert event.cancelled is True

    def test_charmed_goblin_can_still_attack_others(self):
        """The charmed goblin can still attack non-charmer entities."""
        wizard = load_wizard()
        goblin = load_goblin()
        bystander = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin, bystander)

        spell = charm_person_spell(save_dc=30)

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        action = next(a for a in goblin.stat_block.actions if a.name == "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=bystander, action=action)
        assert event.cancelled is False


# ── No rule_engine — effects silently skipped ─────────────────────────────────

class TestSpellEffectsWithoutRuleEngine:

    def test_spell_effects_silently_skipped_without_rule_engine(self):
        """If no rule_engine is set, spell effects do nothing and no error is raised."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus = EventBus()
        damage_proc = DamageProcessor(bus)
        attack_res = AttackResolver(bus, damage_proc)
        resolver = SpellResolver(bus, damage_proc, attack_res, rule_engine=None)

        spell = charm_person_spell(save_dc=30)

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            results = resolver.resolve(wizard, [goblin], spell)

        # Resolves without error; no active effects on goblin
        assert results[0][0] is True  # hit (auto-hit for save spell)
        assert goblin.active_effects == {}


# ── Rule caching ──────────────────────────────────────────────────────────────

class TestRuleCaching:

    def test_registry_returns_same_rule_object(self):
        """The same Rule object should be reused across multiple spell resolutions."""
        wizard = load_wizard()
        goblin_a = load_goblin()
        goblin_b = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin_a, goblin_b)

        spell = charm_person_spell(save_dc=30)

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin_a], spell)
            resolver.resolve(wizard, [goblin_b], spell)

        # Both goblins should share the same Rule template object
        instance_a = goblin_a.active_effects["attack_declared"][0]
        instance_b = goblin_b.active_effects["attack_declared"][0]
        assert instance_a.rule is instance_b.rule
        # But they should be different EffectInstances
        assert instance_a is not instance_b


# ── CombatSystem integration ──────────────────────────────────────────────────

class TestCombatSystemIntegration:

    def test_rule_engine_wired_via_combat_system(self):
        """Setting combat.rule_engine should wire the rule_engine to SpellResolver."""
        from src.combat import CombatSystem

        wizard = load_wizard()
        goblin = load_goblin()

        bus = EventBus()
        engine = RuleEngine(bus, entities_getter=lambda: [wizard, goblin])

        cs = CombatSystem()
        cs.event_bus = bus
        cs.rule_engine = engine

        assert cs._spell_resolver.rule_engine is engine

    def test_charm_person_via_combat_system_resolve_spell(self):
        """Calling CombatSystem.resolve_spell with Charm Person should apply charmed."""
        from src.combat import CombatSystem

        wizard = load_wizard()
        goblin = load_goblin()

        bus = EventBus()
        registry = EffectRegistry()
        registry.scan_directory("rules/entity_effects")
        engine = RuleEngine(bus, entities_getter=lambda: [wizard, goblin],
                            effect_registry=registry)

        cs = CombatSystem()
        cs.event_bus = bus
        cs.rule_engine = engine

        spell = charm_person_spell(save_dc=30)  # goblin always fails

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            cs.resolve_spell(wizard, [goblin], spell)

        assert "attack_declared" in goblin.active_effects
        instance = goblin.active_effects["attack_declared"][0]
        assert instance.name == "charmed"
        assert instance.instance_fields.get("charmer") is wizard


# ── Longstrider spell integration ────────────────────────────────────────────

def load_cleric() -> Entity:
    sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "cleric.json"))
    return Entity(sb)


# ── Shield of Faith ───────────────────────────────────────────────────────────

class TestShieldOfFaithEffect:
    """Shield of Faith adds +2 AC via AddModifier on_apply and tracks concentration."""

    def test_ac_increases_by_two_on_cast(self):
        """Casting Shield of Faith on an entity raises its AC by 2."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.ac

        resolver.resolve(cleric, [cleric], spell)

        assert cleric.ac == base_ac + 2

    def test_stat_modifier_is_recorded(self):
        """A StatModifier with the correct fields is added to the target."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        resolver.resolve(cleric, [cleric], spell)

        ac_mods = cleric.get_stat_modifiers("ac")
        assert len(ac_mods) == 1
        mod = ac_mods[0]
        assert mod.value == 2
        assert mod.source == "Shield of Faith"
        assert mod.effect_name == "shield_of_faith"

    def test_stat_breakdown_contains_base_and_modifier(self):
        """get_stat_breakdown returns the base AC line followed by the spell modifier."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.stat_block.armor_class
        resolver.resolve(cleric, [cleric], spell)

        breakdown = cleric.get_stat_breakdown("ac")
        assert len(breakdown) == 2
        assert breakdown[0] == {"source": "Base", "value": base_ac}
        assert breakdown[1] == {"source": "Shield of Faith", "value": 2}

    def test_concentration_tracked_on_caster(self):
        """After casting, the caster's concentrating_on and concentration_target are set."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        resolver.resolve(cleric, [cleric], spell)

        assert cleric.concentrating_on == "shield_of_faith"
        assert cleric.concentration_target is cleric

    def test_ac_restored_when_effect_removed(self):
        """Removing the shield_of_faith effect strips the modifier and restores base AC."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.ac
        resolver.resolve(cleric, [cleric], spell)

        assert cleric.ac == base_ac + 2

        cleric.remove_effect("shield_of_faith")

        assert cleric.ac == base_ac
        assert cleric.get_stat_modifiers("ac") == []

    def test_zero_damage_cast_does_not_break_concentration(self):
        """Casting a zero-damage buff spell must not trigger a concentration check.

        apply_damage always emits DAMAGE_DEALT (even with total=0), so the
        concentration rule must guard on event.total > 0 — otherwise the cleric
        risks losing concentration on a spell it just cast.
        """
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        # Load concentration rule so the engine enforces it
        engine.load_from_file("rules/concentration.json")

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.ac

        # Cast 20 times — if 0-damage DAMAGE_DEALT could strip concentration,
        # a failed DC-10 Con save would occasionally drop the AC back to base.
        for _ in range(20):
            cleric.remove_effect("shield_of_faith")
            cleric.concentrating_on = None
            cleric.concentration_target = None
            resolver.resolve(cleric, [cleric], spell)
            assert cleric.ac == base_ac + 2, (
                "AC should be base+2 immediately after casting Shield of Faith"
            )


def longstrider_spell() -> SpellAction:
    """Load Longstrider from the example spell file."""
    return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "longstrider.json"))


class TestLongstriderSpellEffects:

    def test_longstrider_loads_effects(self):
        """longstrider.json should parse its effects list into spell_effects."""
        spell = longstrider_spell()
        assert len(spell.spell_effects) == 1
        entry = spell.spell_effects[0]
        assert entry["effect"] == "longstrider"

    def test_longstrider_no_save(self):
        """Longstrider has no saving throw."""
        spell = longstrider_spell()
        assert spell.save_dc == 0
        assert spell.save_ability == ""

    def test_longstrider_applies_effect_on_cast(self):
        """Casting Longstrider should apply the longstrider movement effect."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = longstrider_spell()
        resolver.resolve(wizard, [goblin], spell)

        # The goblin should have the longstrider effect on turn_start
        assert "turn_start" in goblin.active_effects
        instances = goblin.active_effects["turn_start"]
        assert len(instances) == 1
        assert instances[0].name == "longstrider"

    def test_longstrider_grants_movement_on_turn(self):
        """After casting, the affected entity gets +10 movement on TURN_START."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)
        engine.load_from_file("rules/action_economy_refill.json")

        spell = longstrider_spell()
        resolver.resolve(wizard, [goblin], spell)

        # Emit TURN_START for the goblin
        bus.emit(EventType.TURN_START, TurnEventData(
            entity=goblin, round_num=2, turn_num=1,
        ))

        # Base speed (30) + longstrider (+10) = 40
        assert goblin.resources.movement == 40

    def test_longstrider_on_multiple_targets(self):
        """Longstrider can be applied to multiple targets (for future upcast)."""
        wizard = load_wizard()
        goblin_a = load_goblin()
        goblin_b = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin_a, goblin_b)
        engine.load_from_file("rules/action_economy_refill.json")

        spell = longstrider_spell()
        resolver.resolve(wizard, [goblin_a, goblin_b], spell)

        # Both goblins should have the effect
        assert "turn_start" in goblin_a.active_effects
        assert "turn_start" in goblin_b.active_effects

        bus.emit(EventType.TURN_START, TurnEventData(
            entity=goblin_a, round_num=2, turn_num=1,
        ))
        assert goblin_a.resources.movement == 40

        bus.emit(EventType.TURN_START, TurnEventData(
            entity=goblin_b, round_num=2, turn_num=2,
        ))
        assert goblin_b.resources.movement == 40
