"""Tests for entity-scoped effects (poison, colossus slayer, durations, etc.)."""

import os
import pytest
from unittest.mock import patch

from src.models import (
    AbilityScores, StatBlock, Entity, Damage, DamageType, AttackAction,
)
from src.combat import EventBus, CombatEvent, EventType
from src.rules import Rule, RuleEngine, RuleLoader
from src.rules.effects import deal_damage

ENTITY_EFFECTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "rules", "entity_effects")
CONDITIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "rules", "entity_effects", "conditions")


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_entity(name="Tester", hp=30, ac=10, con=10):
    stat_block = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, con, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
    )
    return Entity(stat_block)


def load_poison_rule(duration=None):
    rule = RuleLoader.load(os.path.join(CONDITIONS_DIR, "spider_bite_poison.json"))
    if duration is not None:
        rule.duration_rounds = duration
    return rule


def load_colossus_slayer_rule():
    return RuleLoader.load(os.path.join(ENTITY_EFFECTS_DIR, "colossus_slayer.json"))


def make_attack_action(damage_type=DamageType.PIERCING):
    return AttackAction(
        name="Test Attack",
        description="",
        damage=[Damage(damage_type, formula="1d6")],
    )


# ── Entity effect storage ────────────────────────────────────────────────────

class TestEntityEffectStorage:

    def test_add_effect(self):
        entity = make_entity()
        rule = load_poison_rule()
        entity.add_effect("turn_start", rule)
        assert entity.get_effects_for_trigger("turn_start") == [rule]

    def test_add_multiple_effects_same_trigger(self):
        entity = make_entity()
        r1 = load_poison_rule()
        r2 = load_poison_rule()
        r2.name = "burning"
        entity.add_effect("turn_start", r1)
        entity.add_effect("turn_start", r2)
        assert len(entity.get_effects_for_trigger("turn_start")) == 2

    def test_get_effects_empty_trigger(self):
        entity = make_entity()
        assert entity.get_effects_for_trigger("turn_start") == []

    def test_remove_effect_by_name(self):
        entity = make_entity()
        rule = load_poison_rule()
        entity.add_effect("turn_start", rule)
        entity.remove_effect("spider_bite_poison")
        assert entity.get_effects_for_trigger("turn_start") == []

    def test_remove_effect_leaves_others(self):
        entity = make_entity()
        r1 = load_poison_rule()
        r2 = load_poison_rule()
        r2.name = "burning"
        entity.add_effect("turn_start", r1)
        entity.add_effect("turn_start", r2)
        entity.remove_effect("spider_bite_poison")
        assert len(entity.get_effects_for_trigger("turn_start")) == 1
        assert entity.get_effects_for_trigger("turn_start")[0].name == "burning"


# ── RuleEngine.apply_effect / remove_effect ──────────────────────────────────

class TestRuleEngineEntityAPI:

    def test_apply_effect_adds_to_entity(self):
        bus = EventBus()
        engine = RuleEngine(bus)
        entity = make_entity()
        rule = load_poison_rule()
        engine.apply_effect(entity, rule)
        assert len(entity.get_effects_for_trigger("turn_start")) == 1
        assert entity.get_effects_for_trigger("turn_start")[0].rule == rule

    def test_remove_effect_removes_from_entity(self):
        bus = EventBus()
        engine = RuleEngine(bus)
        entity = make_entity()
        rule = load_poison_rule()
        engine.apply_effect(entity, rule)
        engine.remove_effect(entity, "spider_bite_poison")
        assert entity.get_effects_for_trigger("turn_start") == []


# ── Entity effect dispatch ───────────────────────────────────────────────────

class TestEntityEffectDispatch:

    @patch("src.rules.effects.roll_formula", return_value=4)
    def test_poison_fires_on_turn_start(self, mock_roll):
        victim = make_entity(hp=30)
        entities = [victim]
        bus = EventBus()
        engine = RuleEngine(bus, entities_getter=lambda: entities)

        rule = load_poison_rule()
        engine.apply_effect(victim, rule)

        bus.emit(EventType.TURN_START, entity=victim, round_num=1)
        assert victim.hp == 26  # 30 - 4 poison

    @patch("src.rules.effects.roll_formula", return_value=4)
    def test_poison_does_not_fire_for_other_entity(self, mock_roll):
        victim = make_entity("Victim", hp=30)
        bystander = make_entity("Bystander", hp=30)
        entities = [victim, bystander]
        bus = EventBus()
        engine = RuleEngine(bus, entities_getter=lambda: entities)

        rule = load_poison_rule()
        engine.apply_effect(victim, rule)

        # Emit TURN_START for the bystander — poison should NOT fire
        bus.emit(EventType.TURN_START, entity=bystander, round_num=1)
        assert victim.hp == 30
        assert bystander.hp == 30

    # Colossus Slayer's on-hit behaviour (fires only on a wounded target, only for its
    # own attacker, once per attack, no cross-target leak) is now a native block trigger
    # and is proven end-to-end through a real AttackResolver in
    # tests/rules/entity_effects/test_colossus_slayer.py. The former legacy-dispatch tests
    # here were retired with the §5d migration: a native rule has empty ``triggers`` and
    # installs on the block engine, so ``apply_effect`` files no legacy EffectInstance and
    # the old ``bus.emit(ATTACK_HIT, …)`` path exercised nothing.


# ── Duration ticking ─────────────────────────────────────────────────────────

class TestDurationTicking:

    @patch("src.rules.effects.roll_formula", return_value=3)
    def test_effect_expires_after_duration(self, mock_roll):
        victim = make_entity(hp=50)
        entities = [victim]
        bus = EventBus()
        engine = RuleEngine(bus, entities_getter=lambda: entities)

        rule = load_poison_rule(duration=2)
        engine.apply_effect(victim, rule)

        # Turn 1: poison fires on TURN_START, then TURN_END ticks duration (2→1)
        bus.emit(EventType.TURN_START, entity=victim, round_num=1)
        assert victim.hp == 47
        bus.emit(EventType.TURN_END, entity=victim, round_num=1)

        # Turn 2: poison fires again, then TURN_END ticks (1→0, expired & removed)
        bus.emit(EventType.TURN_START, entity=victim, round_num=2)
        assert victim.hp == 44
        bus.emit(EventType.TURN_END, entity=victim, round_num=2)
        assert victim.get_effects_for_trigger("turn_start") == []

        # Turn 3: no more poison
        bus.emit(EventType.TURN_START, entity=victim, round_num=3)
        assert victim.hp == 44  # unchanged

    def test_permanent_effect_never_expires(self):
        """A legacy effect with duration_rounds=None should persist indefinitely.

        Uses a permanent poison (a still-legacy ``action``-verb rule) rather than
        Colossus Slayer, which migrated to a native block trigger in §5d and so no longer
        files a legacy EffectInstance to tick — its permanence lives in a LifetimeScope.
        """
        victim = make_entity(hp=40)
        entities = [victim]
        bus = EventBus()
        engine = RuleEngine(bus, entities_getter=lambda: entities)

        rule = load_poison_rule()
        rule.duration_rounds = None  # make it permanent
        assert rule.duration_rounds is None
        engine.apply_effect(victim, rule)

        # Tick several TURN_ENDs — effect should remain
        for i in range(5):
            bus.emit(EventType.TURN_END, entity=victim, round_num=i)

        assert len(victim.get_effects_for_trigger("turn_start")) == 1
        assert victim.get_effects_for_trigger("turn_start")[0].rule == rule


# ── DealDamage effect handler ────────────────────────────────────────────────

class TestDealDamageEffect:

    @patch("src.rules.effects.roll_formula", return_value=7)
    def test_deals_correct_damage(self, mock_roll):
        target = make_entity(hp=20)
        bus = EventBus()
        ctx = {"entity": target, "event": target,
               "max": max, "min": min, "abs": abs, "int": int,
               "round": round, "bool": bool, "len": len, "hasattr": hasattr}
        effect = {"action": "DealDamage", "target": "entity",
                  "formula": "2d6", "damage_type": "FIRE"}
        event = CombatEvent(event_type=EventType.TURN_START, data={})

        deal_damage(effect, ctx, event, bus)

        assert target.hp == 13  # 20 - 7
        mock_roll.assert_called_once_with("2d6")

    @patch("src.rules.effects.roll_formula", return_value=5)
    def test_emits_damage_dealt_event(self, mock_roll):
        target = make_entity(hp=20)
        bus = EventBus()
        received = []
        bus.subscribe(EventType.DAMAGE_DEALT, lambda e: received.append(e))

        ctx = {"entity": target, "event": target,
               "max": max, "min": min, "abs": abs, "int": int,
               "round": round, "bool": bool, "len": len, "hasattr": hasattr}
        effect = {"action": "DealDamage", "target": "entity",
                  "formula": "1d8", "damage_type": "POISON"}
        event = CombatEvent(event_type=EventType.TURN_START, data={})

        deal_damage(effect, ctx, event, bus)

        assert len(received) == 1
        assert received[0].data["defender"] is target
        assert received[0].data["total"] == 5


# ── Global rules still work with entities_getter ─────────────────────────────

class TestGlobalRulesWithEntitiesGetter:

    def test_global_rule_fires_alongside_entity_effects(self):
        """Global rules must still work when entities_getter is provided."""
        entity = make_entity(hp=30)
        entity.concentrating_on = "Bless"
        entities = [entity]
        bus = EventBus()
        engine = RuleEngine(bus, entities_getter=lambda: entities)

        # Load concentration check as a global rule
        conc_rule = RuleLoader.from_dict({
            "name": "concentration_check",
            "triggers": ["DAMAGE_DEALT"],
            "condition": "event.defender.has_concentration",
            "effects": [{"action": "ForceConcentrationCheck",
                         "target": "event.defender",
                         "dc": "max(10, event.total // 2)"}],
        })
        engine.load_rule(conc_rule)

        # Force a failed concentration save
        with patch("src.rules.effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=entity,
                     damage_list=[], total=20)

        assert entity.concentrating_on is None  # lost concentration


# ── JSON loading of entity effect files ──────────────────────────────────────

class TestEntityEffectJSONLoading:

    def test_load_spider_bite_poison_json(self):
        path = os.path.join(CONDITIONS_DIR, "spider_bite_poison.json")
        rule = RuleLoader.load(path)
        assert rule.name == "spider_bite_poison"
        assert rule.triggers == [EventType.TURN_START]
        assert rule.duration_rounds == 3
        assert rule.source == "Spider Bite"

    def test_load_colossus_slayer_json(self):
        # Colossus Slayer is a *native* rule now (Phase 3 §5d): its reactive rider is
        # authored as a block ``program``, so it carries no legacy ``triggers``/``effects``
        # and is installed on the block engine (never the legacy dispatch). Its behaviour
        # is covered end-to-end by tests/rules/entity_effects/test_colossus_slayer.py.
        path = os.path.join(ENTITY_EFFECTS_DIR, "colossus_slayer.json")
        rule = RuleLoader.load(path)
        assert rule.name == "colossus_slayer"
        assert rule.triggers == []  # native: events live inside the program's trigger blocks
        assert rule.program and rule.program[0]["event"] == "ATTACK_HIT"
        assert rule.duration_rounds is None
        assert rule.source == "Colossus Slayer"


# ── DAMAGE_INCOMING and ModifyDamage ────────────────────────────────────────

class TestDamageIncoming:

    def test_damage_incoming_fires_before_hp_reduction(self):
        """DAMAGE_INCOMING fires before take_damage, allowing modification."""
        from src.combat import CombatSystem
        from src.rules.effects import modify_damage

        attacker = make_entity("Attacker", hp=30, ac=5)
        defender = make_entity("Defender", hp=50, ac=5)

        combat = CombatSystem()
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        for i, entry in enumerate(combat.initiative_tracker.initiative_order):
            if entry.entity is attacker:
                combat.initiative_tracker.current_turn_index = i
                break

        engine = RuleEngine(combat.event_bus)
        # Register a global resistance rule: halve all incoming damage
        engine.load_rule(Rule(
            name="fire_resistance",
            triggers=[EventType.DAMAGE_INCOMING],
            effects=[{"action": "ModifyDamage", "multiplier": 0.5}],
        ))

        attack = AttackAction(
            name="Sword", description="",
            bonus_to_hit=99,
            damage=[Damage(DamageType.SLASHING, 20)],
        )

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            hit, total, _ = combat.resolve_attack(attacker, defender, attack)

        assert hit is True
        assert total == 10  # 20 halved to 10
        assert defender.hp == 40  # 50 - 10

    def test_damage_incoming_cancel_prevents_all_damage(self):
        """Cancelling DAMAGE_INCOMING prevents any HP reduction."""
        from src.combat import CombatSystem

        attacker = make_entity("Attacker", hp=30, ac=5)
        defender = make_entity("Defender", hp=50, ac=5)

        combat = CombatSystem()
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        for i, entry in enumerate(combat.initiative_tracker.initiative_order):
            if entry.entity is attacker:
                combat.initiative_tracker.current_turn_index = i
                break

        engine = RuleEngine(combat.event_bus)
        engine.load_rule(Rule(
            name="immunity",
            triggers=[EventType.DAMAGE_INCOMING],
            effects=[{"action": "Cancel"}],
        ))

        attack = AttackAction(
            name="Sword", description="",
            bonus_to_hit=99,
            damage=[Damage(DamageType.SLASHING, 20)],
        )

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            hit, total, _ = combat.resolve_attack(attacker, defender, attack)

        assert hit is True
        assert total == 0
        assert defender.hp == 50  # no damage taken

    def test_modify_damage_with_type_filter(self):
        """ModifyDamage can target specific damage types."""
        target = make_entity(hp=50)
        bus = EventBus()
        ctx = {"entity": target, "event": target,
               "max": max, "min": min, "abs": abs, "int": int,
               "round": round, "bool": bool, "len": len, "hasattr": hasattr}

        fire_dmg = Damage(DamageType.FIRE, 20)
        slash_dmg = Damage(DamageType.SLASHING, 10)
        event = CombatEvent(
            event_type=EventType.DAMAGE_INCOMING,
            data={"defender": target, "damage_list": [fire_dmg, slash_dmg]},
        )

        from src.rules.effects import modify_damage
        effect = {"action": "ModifyDamage", "multiplier": 0, "damage_type": "FIRE"}
        modify_damage(effect, ctx, event, bus)

        assert fire_dmg.amount == 0  # fire immune
        assert slash_dmg.amount == 10  # slashing untouched
