"""Tests for the JSON-driven rule loader and the rules it installs.

A rule is authored as a native block ``program``; ``RuleEngine`` loads it and installs
its trigger blocks on the block engine, which resolves them. The engine dispatches
nothing itself, so what is worth testing here is the *loading* seam and that a real
shipped rule fires end to end — the concentration rule serves as the worked example.

Effect-level behaviour belongs with the blocks (``tests/test_block_*.py``) and the
global-rule install with ``tests/test_global_rules_via_blocks.py``.
"""

import os
import pytest
from unittest.mock import patch

from src.models import (
    AbilityScores, StatBlock, Entity, Damage, DamageType, AttackAction,
)
from src.combat import CombatSystem, EventBus, EventType
from src.rules import RuleEngine, RuleLoader

GLOBAL_RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "rules", "global")
CONCENTRATION_JSON = os.path.join(GLOBAL_RULES_DIR, "concentration.json")


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_entity(name="Tester", hp=30, ac=10, con=10):
    """Build a minimal Entity. CON score controls saving throw modifier."""
    stat_block = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, con, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
    )
    return Entity(stat_block)


# ── RuleLoader ───────────────────────────────────────────────────────────────

class TestRuleLoader:

    def test_load_from_file(self):
        # concentration is a native block rule: a DAMAGE_DEALT trigger running a
        # force_concentration_check block.
        rule = RuleLoader.load(CONCENTRATION_JSON)
        assert rule.name == "concentration_damage_check"
        assert rule.program and len(rule.program) == 1
        tb = rule.program[0]
        assert tb["block"] == "trigger" and tb["event"] == "DAMAGE_DEALT"
        assert tb["when"] == "event.defender.has_concentration and event.total > 0"
        assert tb["then"][0]["block"] == "force_concentration_check"


# ── RuleEngine: the install seam ──────────────────────────────────────────────

class TestRuleEngineInstall:

    def test_load_from_file_installs_and_subscribes(self):
        bus = EventBus()
        engine = RuleEngine(bus)
        rule = engine.load_from_file(CONCENTRATION_JSON)
        assert rule in engine._native_rules
        # Subscribed: a non-concentrating entity causes no crash.
        bus.emit(EventType.DAMAGE_DEALT, defender=make_entity(), damage_list=[], total=10)

    def test_apply_effect_rejects_a_rule_with_nothing_to_install(self):
        """An empty program has no triggers to install — say so rather than no-op."""
        engine = RuleEngine(EventBus())
        rule = RuleLoader.from_dict({"name": "hollow", "program": []})
        with pytest.raises(ValueError, match="hollow"):
            engine.apply_effect(make_entity(), rule)


# ── Concentration rule integration ───────────────────────────────────────────

class TestConcentrationRule:
    """Integration tests using the real concentration.json rule."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def engine(self, bus):
        eng = RuleEngine(bus)
        eng.load_from_file(CONCENTRATION_JSON)
        return eng

    @pytest.fixture
    def concentrating_entity(self):
        entity = make_entity(con=10)  # +0 CON modifier for predictable maths
        entity.concentrating_on = "Bless"
        return entity

    def test_rule_skips_non_concentrating_entity(self, bus, engine):
        """Condition 'event.target.has_concentration' is False — rule never fires."""
        entity = make_entity()
        assert not entity.has_concentration
        # Emit with a DC that would always fail any save — proves handler wasn't called
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=entity, damage_list=[], total=20)
        assert entity.concentrating_on is None  # was None to start, still None

    def test_rule_fires_for_concentrating_entity(self, bus, engine, concentrating_entity):
        """When entity IS concentrating, the concentration check runs."""
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=20):  # pass
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=10)
        # High roll → passed save → still concentrating
        assert concentrating_entity.concentrating_on == "Bless"

    def test_failed_save_ends_concentration(self, bus, engine, concentrating_entity):
        # Damage = 20 → DC = max(10, 10) = 10; CON +0; roll 1 → total 1 < 10
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=20)
        assert concentrating_entity.concentrating_on is None

    def test_passed_save_keeps_concentration(self, bus, engine, concentrating_entity):
        # Damage = 20 → DC = 10; CON +0; roll 10 → total 10 >= 10
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=10):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=20)
        assert concentrating_entity.concentrating_on == "Bless"

    def test_dc_scales_with_damage_low(self, bus, engine, concentrating_entity):
        """Low damage → DC 10 (minimum). Roll 10 should pass."""
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=10):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=8)
        # DC = max(10, 8//2=4) = 10; 10 + 0 = 10 → pass
        assert concentrating_entity.concentrating_on == "Bless"

    def test_dc_scales_with_damage_high(self, bus, engine, concentrating_entity):
        """High damage → DC rises above minimum. Same roll that passed above now fails."""
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=10):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=30)
        # DC = max(10, 30//2=15) = 15; 10 + 0 = 10 < 15 → fail
        assert concentrating_entity.concentrating_on is None

    def test_concentration_rule_via_combat_system(self):
        """End-to-end: attack through CombatSystem triggers the concentration rule."""
        attacker = make_entity("Attacker", ac=5)
        defender = make_entity("Defender", hp=100, ac=5, con=10)
        defender.concentrating_on = "Bless"

        combat = CombatSystem()
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        for i, entry in enumerate(combat.initiative_tracker.initiative_order):
            if entry.entity is attacker:
                combat.initiative_tracker.current_turn_index = i
                break

        engine = RuleEngine(combat.event_bus)
        engine.load_from_file(CONCENTRATION_JSON)

        attack = AttackAction(
            name="Sword", description="",
            bonus_to_hit=99,  # guaranteed hit
            damage=[Damage(DamageType.SLASHING, 20, "1d1+19")],
        )

        # Attack roll → 20 (hit); concentration save → 1 (fail)
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.spells.blocks.global_effects.roll_d20", return_value=1):
            combat.resolve_attack(attacker, defender, attack)

        assert defender.concentrating_on is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
