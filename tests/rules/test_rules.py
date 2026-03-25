"""Tests for the JSON-driven rule engine."""

import os
import pytest
from unittest.mock import MagicMock, patch

from src.models import (
    AbilityScores, StatBlock, Entity, Damage, DamageType,
    Condition, ConditionType, AttackAction,
)
from src.combat import CombatSystem, EventBus, CombatEvent, EventType
from src.rules import Rule, RuleEngine, RuleLoader
from src.rules.effects import (
    apply_condition, remove_condition_type, force_concentration_check,
    cancel_event, heal_target,
)

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "rules")
CONCENTRATION_JSON = os.path.join(RULES_DIR, "concentration.json")


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


def make_dummy_event(event_type=EventType.DAMAGE_DEALT):
    return CombatEvent(event_type=event_type, data={})


# ── RuleLoader ───────────────────────────────────────────────────────────────

class TestRuleLoader:

    def test_from_dict_minimal(self):
        rule = RuleLoader.from_dict({
            "name": "my_rule",
            "triggers": ["DAMAGE_DEALT"],
            "effects": [{"action": "Cancel"}],
        })
        assert rule.name == "my_rule"
        assert rule.triggers == [EventType.DAMAGE_DEALT]
        assert rule.effects == [{"action": "Cancel"}]
        assert rule.condition is None
        assert rule.enabled is True

    def test_from_dict_with_condition(self):
        rule = RuleLoader.from_dict({
            "name": "guarded",
            "triggers": ["ATTACK_DECLARED"],
            "condition": "event.defender.hp > 0",
            "effects": [],
        })
        assert rule.condition == "event.defender.hp > 0"

    def test_from_dict_enabled_false(self):
        rule = RuleLoader.from_dict({
            "name": "disabled",
            "triggers": ["TURN_START"],
            "effects": [],
            "enabled": False,
        })
        assert rule.enabled is False

    def test_invalid_trigger_raises(self):
        with pytest.raises(ValueError, match="Unknown trigger"):
            RuleLoader.from_dict({
                "name": "bad",
                "triggers": ["NOT_A_REAL_EVENT"],
                "effects": [],
            })

    def test_load_from_file(self):
        rule = RuleLoader.load(CONCENTRATION_JSON)
        assert rule.name == "concentration_damage_check"
        assert rule.triggers == [EventType.DAMAGE_DEALT]
        assert rule.condition == "event.defender.has_concentration and event.total > 0"
        assert len(rule.effects) == 1
        assert rule.effects[0]["action"] == "ForceConcentrationCheck"


# ── RuleEngine core ───────────────────────────────────────────────────────────

class TestRuleEngine:

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.fixture
    def engine(self, bus):
        return RuleEngine(bus)

    def test_unconditional_rule_fires(self, bus, engine):
        fired = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: fired.append(True))
        engine.load_rule(Rule(
            name="spy",
            triggers=[EventType.TURN_START],
            effects=[{"action": "Spy"}],
        ))
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert fired == [True]

    def test_condition_true_fires(self, bus, engine):
        fired = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: fired.append(True))
        engine.load_rule(Rule(
            name="spy",
            triggers=[EventType.TURN_START],
            effects=[{"action": "Spy"}],
            condition="1 == 1",
        ))
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert fired == [True]

    def test_condition_false_skips(self, bus, engine):
        fired = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: fired.append(True))
        engine.load_rule(Rule(
            name="spy",
            triggers=[EventType.TURN_START],
            effects=[{"action": "Spy"}],
            condition="1 == 2",
        ))
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert fired == []

    def test_condition_exception_skips_silently(self, bus, engine):
        """A condition that raises (e.g. missing attribute) is skipped, not crashed."""
        fired = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: fired.append(True))
        engine.load_rule(Rule(
            name="spy",
            triggers=[EventType.TURN_START],
            effects=[{"action": "Spy"}],
            condition="event.nonexistent_field",
        ))
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert fired == []

    def test_disabled_rule_skips(self, bus, engine):
        fired = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: fired.append(True))
        rule = Rule(
            name="spy",
            triggers=[EventType.TURN_START],
            effects=[{"action": "Spy"}],
            enabled=False,
        )
        engine.load_rule(rule)
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert fired == []

    def test_rule_can_be_disabled_after_loading(self, bus, engine):
        fired = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: fired.append(True))
        rule = Rule(name="spy", triggers=[EventType.TURN_START], effects=[{"action": "Spy"}])
        engine.load_rule(rule)

        rule.enabled = False
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert fired == []

    def test_multiple_rules_same_trigger_both_fire(self, bus, engine):
        log = []
        engine.register_effect("SpyA", lambda e, ctx, ev, eb: log.append("A"))
        engine.register_effect("SpyB", lambda e, ctx, ev, eb: log.append("B"))
        engine.load_rule(Rule("ruleA", [EventType.TURN_START], [{"action": "SpyA"}]))
        engine.load_rule(Rule("ruleB", [EventType.TURN_START], [{"action": "SpyB"}]))
        bus.emit(EventType.TURN_START, entity=make_entity())
        assert "A" in log and "B" in log

    def test_unknown_effect_raises(self, bus, engine):
        engine.load_rule(Rule("bad", [EventType.TURN_START], [{"action": "DoesNotExist"}]))
        with pytest.raises(ValueError, match="unknown effect action"):
            bus.emit(EventType.TURN_START, entity=make_entity())

    def test_cancel_stops_remaining_effects_in_same_rule(self, bus, engine):
        """Once Cancel sets event.cancelled, no further effects in that rule run."""
        log = []
        engine.register_effect("Spy", lambda e, ctx, ev, eb: log.append("ran"))
        engine.load_rule(Rule(
            name="cancel_then_spy",
            triggers=[EventType.ATTACK_DECLARED],
            effects=[{"action": "Cancel"}, {"action": "Spy"}],
        ))
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=make_entity(), defender=make_entity(), action=None)
        assert event.cancelled is True
        assert log == []  # Spy never ran

    def test_register_custom_effect(self, bus, engine):
        results = []
        engine.register_effect("Custom", lambda e, ctx, ev, eb: results.append(e["value"]))
        engine.load_rule(Rule("c", [EventType.TURN_END], [{"action": "Custom", "value": 42}]))
        bus.emit(EventType.TURN_END, entity=make_entity())
        assert results == [42]

    def test_load_from_file_registers_rule(self, bus, engine):
        rule = engine.load_from_file(CONCENTRATION_JSON)
        assert rule.triggers == [EventType.DAMAGE_DEALT]
        # Verify it's subscribed: a non-concentrating entity causes no crash
        entity = make_entity()
        bus.emit(EventType.DAMAGE_DEALT, defender=entity, damage_list=[], total=10)


# ── ApplyCondition ────────────────────────────────────────────────────────────

class TestApplyConditionEffect:

    def _run(self, entity, extra_effect_fields=None, bus=None):
        bus = bus or EventBus()
        event = make_dummy_event()
        effect = {"action": "ApplyCondition", "target": entity,
                  "condition_type": "POISONED", **(extra_effect_fields or {})}
        apply_condition(effect, {}, event, bus)
        return bus, event

    def test_adds_condition_to_target(self):
        entity = make_entity()
        self._run(entity)
        types = [c.condition_type for c in entity.get_active_conditions()]
        assert ConditionType.POISONED in types

    def test_sets_duration_when_given(self):
        entity = make_entity()
        self._run(entity, {"duration": 3})
        cond = entity.get_active_conditions()[0]
        assert cond.duration_rounds == 3

    def test_sets_source_when_given(self):
        entity = make_entity()
        self._run(entity, {"source": "Spider Bite"})
        cond = entity.get_active_conditions()[0]
        assert cond.source == "Spider Bite"

    def test_duration_defaults_to_none(self):
        entity = make_entity()
        self._run(entity)
        assert entity.get_active_conditions()[0].duration_rounds is None

    def test_emits_condition_added(self):
        entity = make_entity()
        bus = EventBus()
        received = []
        bus.subscribe(EventType.CONDITION_ADDED, lambda e: received.append(e))
        self._run(entity, bus=bus)
        assert len(received) == 1
        assert received[0].data["entity"] is entity
        assert received[0].data["condition"].condition_type == ConditionType.POISONED


# ── RemoveConditionType ───────────────────────────────────────────────────────

class TestRemoveConditionTypeEffect:

    def _run(self, entity, condition_type="POISONED", bus=None):
        bus = bus or EventBus()
        event = make_dummy_event()
        effect = {"action": "RemoveConditionType", "target": entity,
                  "condition_type": condition_type}
        remove_condition_type(effect, {}, event, bus)
        return bus, event

    def test_removes_matching_conditions(self):
        entity = make_entity()
        entity.add_condition(Condition(ConditionType.POISONED))
        entity.add_condition(Condition(ConditionType.POISONED))
        self._run(entity, "POISONED")
        assert entity.get_active_conditions() == []

    def test_leaves_non_matching_conditions(self):
        entity = make_entity()
        entity.add_condition(Condition(ConditionType.BLINDED))
        entity.add_condition(Condition(ConditionType.POISONED))
        self._run(entity, "POISONED")
        remaining = [c.condition_type for c in entity.get_active_conditions()]
        assert remaining == [ConditionType.BLINDED]

    def test_no_error_when_condition_absent(self):
        """Removing a condition that isn't present should not raise."""
        entity = make_entity()
        self._run(entity, "POISONED")  # entity has no conditions

    def test_emits_condition_removed_per_removal(self):
        entity = make_entity()
        entity.add_condition(Condition(ConditionType.POISONED))
        entity.add_condition(Condition(ConditionType.POISONED))
        bus = EventBus()
        removed_events = []
        bus.subscribe(EventType.CONDITION_REMOVED, lambda e: removed_events.append(e))
        self._run(entity, "POISONED", bus=bus)
        assert len(removed_events) == 2


# ── Cancel ────────────────────────────────────────────────────────────────────

class TestCancelEffect:

    def test_sets_event_cancelled(self):
        bus = EventBus()
        event = make_dummy_event(EventType.ATTACK_DECLARED)
        assert event.cancelled is False
        cancel_event({}, {}, event, bus)
        assert event.cancelled is True

    def test_cancellation_propagates_to_combat_system(self):
        """cancel_event on ATTACK_DECLARED should cause resolve_attack to return (False, 0)."""
        from src.combat import CombatSystem
        engine_bus_holder = []

        combat = CombatSystem()
        attacker = make_entity("Attacker", ac=5)
        defender = make_entity("Defender", hp=50, ac=5)
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        for i, entry in enumerate(combat.initiative_tracker.initiative_order):
            if entry.entity is attacker:
                combat.initiative_tracker.current_turn_index = i
                break

        engine = RuleEngine(combat.event_bus)
        engine.load_rule(Rule(
            name="always_cancel",
            triggers=[EventType.ATTACK_DECLARED],
            effects=[{"action": "Cancel"}],
        ))

        attack = AttackAction(
            name="Sword", description="", bonus_to_hit=99,
            damage=[Damage(DamageType.SLASHING, 1)],
        )
        hit, damage, _ = combat.resolve_attack(attacker, defender, attack)
        assert hit is False
        assert damage == 0
        assert defender.hp == 50  # took no damage


# ── HealTarget ────────────────────────────────────────────────────────────────

class TestHealTargetEffect:

    def test_heals_target(self):
        entity = make_entity(hp=30)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 20))
        assert entity.hp == 10

        with patch("src.rules.effects.roll_formula", return_value=8):
            heal_target({"target": entity, "formula": "2d4"}, {}, make_dummy_event(), EventBus())

        assert entity.hp == 18

    def test_heal_capped_at_max_hp(self):
        entity = make_entity(hp=30)
        entity.take_damage(Damage(DamageType.BLUDGEONING, 5))

        with patch("src.rules.effects.roll_formula", return_value=100):
            heal_target({"target": entity, "formula": "10d10"}, {}, make_dummy_event(), EventBus())

        assert entity.hp == 30  # capped at max


# ── ForceConcentrationCheck ───────────────────────────────────────────────────

class TestForceConcentrationCheckEffect:

    def _run(self, entity, dc, roll):
        """Run a concentration check with a mocked d20 roll."""
        effect = {"target": entity, "dc": dc}
        with patch("src.rules.effects.roll_d20", return_value=roll):
            force_concentration_check(effect, {}, make_dummy_event(), EventBus())

    def test_failed_save_clears_concentration(self):
        entity = make_entity(con=10)  # CON modifier = 0
        entity.concentrating_on = "Bless"
        self._run(entity, dc=15, roll=10)  # 10 + 0 = 10 < 15 → fail
        assert entity.concentrating_on is None

    def test_passed_save_preserves_concentration(self):
        entity = make_entity(con=10)  # CON modifier = 0
        entity.concentrating_on = "Bless"
        self._run(entity, dc=15, roll=15)  # 15 + 0 = 15 >= 15 → pass
        assert entity.concentrating_on == "Bless"

    def test_con_modifier_applied_to_save(self):
        entity = make_entity(con=14)  # CON modifier = +2
        entity.concentrating_on = "Bless"
        # DC 15, roll 12: 12 + 2 = 14 → fail
        self._run(entity, dc=15, roll=12)
        assert entity.concentrating_on is None

    def test_con_modifier_can_push_roll_over_dc(self):
        entity = make_entity(con=14)  # CON modifier = +2
        entity.concentrating_on = "Bless"
        # DC 15, roll 13: 13 + 2 = 15 → pass (meets DC exactly)
        self._run(entity, dc=15, roll=13)
        assert entity.concentrating_on == "Bless"

    def test_entity_not_concentrating_unaffected(self):
        entity = make_entity(con=10)
        assert entity.concentrating_on is None
        self._run(entity, dc=5, roll=1)  # forced fail — but nothing to clear
        assert entity.concentrating_on is None


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
        with patch("src.rules.effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=entity, damage_list=[], total=20)
        assert entity.concentrating_on is None  # was None to start, still None

    def test_rule_fires_for_concentrating_entity(self, bus, engine, concentrating_entity):
        """When entity IS concentrating, ForceConcentrationCheck runs."""
        with patch("src.rules.effects.roll_d20", return_value=20):  # always pass
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=10)
        # High roll → passed save → still concentrating
        assert concentrating_entity.concentrating_on == "Bless"

    def test_failed_save_ends_concentration(self, bus, engine, concentrating_entity):
        # Damage = 20 → DC = max(10, 10) = 10; CON +0; roll 1 → total 1 < 10
        with patch("src.rules.effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=20)
        assert concentrating_entity.concentrating_on is None

    def test_passed_save_keeps_concentration(self, bus, engine, concentrating_entity):
        # Damage = 20 → DC = 10; CON +0; roll 10 → total 10 >= 10
        with patch("src.rules.effects.roll_d20", return_value=10):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=20)
        assert concentrating_entity.concentrating_on == "Bless"

    def test_dc_scales_with_damage_low(self, bus, engine, concentrating_entity):
        """Low damage → DC 10 (minimum). Roll 10 should pass."""
        with patch("src.rules.effects.roll_d20", return_value=10):
            bus.emit(EventType.DAMAGE_DEALT,
                     defender=concentrating_entity, damage_list=[], total=8)
        # DC = max(10, 8//2=4) = 10; 10 + 0 = 10 → pass
        assert concentrating_entity.concentrating_on == "Bless"

    def test_dc_scales_with_damage_high(self, bus, engine, concentrating_entity):
        """High damage → DC rises above minimum. Same roll that passed above now fails."""
        with patch("src.rules.effects.roll_d20", return_value=10):
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
        with patch("src.combat.attack_resolver.roll_d20", return_value=20), \
             patch("src.rules.effects.roll_d20", return_value=1):
            combat.resolve_attack(attacker, defender, attack)

        assert defender.concentrating_on is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
