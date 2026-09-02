"""Tests for damage vulnerability, resistance, and immunity."""

import os
import pytest

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType
from src.combat.event_bus import EventBus, CombatEvent
from src.combat.event_data import DamageIncomingData
from src.combat.events import EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleLoader

GLOBAL_RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules", "global")
VULNERABILITY_JSON = os.path.join(GLOBAL_RULES_DIR, "damage_vulnerability_rule.json")
RESISTANCE_JSON = os.path.join(GLOBAL_RULES_DIR, "damage_resistance_rule.json")
IMMUNITY_JSON = os.path.join(GLOBAL_RULES_DIR, "damage_immunity_rule.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stat_block(name="Tester", hp=30, ac=10,
                    vulnerabilities=None, resistances=None, immunities=None):
    return StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
        damage_vulnerabilities=vulnerabilities or [],
        damage_resistances=resistances or [],
        damage_immunities=immunities or [],
    )


def make_entity(**kwargs):
    return Entity(make_stat_block(**kwargs))


def make_dummy_effect_ctx_event(damage_list):
    """Return (effect, ctx, event, bus) for a DAMAGE_INCOMING event."""
    bus = EventBus()
    event = CombatEvent(
        event_type=EventType.DAMAGE_INCOMING,
        data=DamageIncomingData(defender=make_entity(), damage_list=damage_list),
    )
    ctx = {"_event": event, **{k: getattr(event.data, k) for k in event.data.keys()}}
    effect_dict = {}
    return effect_dict, ctx, event, bus


# ---------------------------------------------------------------------------
# StatBlock: field defaults
# ---------------------------------------------------------------------------

class TestStatBlockDefaults:
    def test_vulnerability_defaults_empty(self):
        sb = make_stat_block()
        assert sb.damage_vulnerabilities == []

    def test_resistance_defaults_empty(self):
        sb = make_stat_block()
        assert sb.damage_resistances == []

    def test_immunity_defaults_empty(self):
        sb = make_stat_block()
        assert sb.damage_immunities == []

    def test_lists_are_independent_across_instances(self):
        """Each StatBlock should have its own list, not a shared default."""
        sb1 = make_stat_block()
        sb2 = make_stat_block()
        sb1.damage_vulnerabilities.append(DamageType.FIRE)
        assert DamageType.FIRE not in sb2.damage_vulnerabilities


# ---------------------------------------------------------------------------
# StatBlock: construction with values
# ---------------------------------------------------------------------------

class TestStatBlockConstruction:
    def test_single_vulnerability(self):
        sb = make_stat_block(vulnerabilities=[DamageType.FIRE])
        assert DamageType.FIRE in sb.damage_vulnerabilities

    def test_multiple_resistances(self):
        sb = make_stat_block(resistances=[DamageType.COLD, DamageType.LIGHTNING])
        assert DamageType.COLD in sb.damage_resistances
        assert DamageType.LIGHTNING in sb.damage_resistances

    def test_multiple_immunities(self):
        sb = make_stat_block(immunities=[DamageType.POISON, DamageType.NECROTIC])
        assert DamageType.POISON in sb.damage_immunities
        assert DamageType.NECROTIC in sb.damage_immunities

    def test_all_three_fields_coexist(self):
        sb = make_stat_block(
            vulnerabilities=[DamageType.FIRE],
            resistances=[DamageType.COLD],
            immunities=[DamageType.POISON],
        )
        assert DamageType.FIRE in sb.damage_vulnerabilities
        assert DamageType.COLD in sb.damage_resistances
        assert DamageType.POISON in sb.damage_immunities


# ---------------------------------------------------------------------------
# Stat block damage modifier membership
# ---------------------------------------------------------------------------

class TestStatBlockDamageModifierMembership:
    @pytest.fixture
    def stat_block(self):
        return make_stat_block(
            vulnerabilities=[DamageType.FIRE],
            resistances=[DamageType.COLD],
            immunities=[DamageType.POISON],
        )

    def test_vulnerability_membership_match(self, stat_block):
        assert DamageType.FIRE in stat_block.damage_vulnerabilities

    def test_vulnerability_membership_no_match(self, stat_block):
        assert DamageType.COLD not in stat_block.damage_vulnerabilities

    def test_resistance_membership_match(self, stat_block):
        assert DamageType.COLD in stat_block.damage_resistances

    def test_resistance_membership_no_match(self, stat_block):
        assert DamageType.FIRE not in stat_block.damage_resistances

    def test_immunity_membership_match(self, stat_block):
        assert DamageType.POISON in stat_block.damage_immunities

    def test_immunity_membership_no_match(self, stat_block):
        assert DamageType.FIRE not in stat_block.damage_immunities

    def test_no_overlap_between_categories(self, stat_block):
        assert DamageType.POISON not in stat_block.damage_resistances
        assert DamageType.COLD not in stat_block.damage_immunities
        assert DamageType.POISON not in stat_block.damage_vulnerabilities

    def test_empty_lists_for_plain_stat_block(self):
        sb = make_stat_block()
        assert DamageType.FIRE not in sb.damage_vulnerabilities
        assert DamageType.FIRE not in sb.damage_resistances
        assert DamageType.FIRE not in sb.damage_immunities


# The `modify_damage` block itself (multipliers, the damage-type filter) is unit
# tested in tests/test_block_event_mod.py::TestModifyDamageHandle.


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------

class TestDamageModifierRuleLoading:
    """The damage-modifier globals are native block rules now (§5d): a single
    DAMAGE_INCOMING ``trigger`` running a ``modify_damage`` block. Their structural
    parity with the frozen legacy shape is pinned in ``test_native_rules_parity``."""

    def _trigger(self, rule):
        assert rule.program and len(rule.program) == 1
        tb = rule.program[0]
        assert tb["block"] == "trigger" and tb["event"] == "DAMAGE_INCOMING"
        assert tb["when"]
        (effect,) = tb["then"]
        assert effect["block"] == "modify_damage"
        return effect

    def test_vulnerability_rule_loads(self):
        rule = RuleLoader.load(VULNERABILITY_JSON)
        assert rule.name == "damage_vulnerability_rule"
        assert self._trigger(rule)["multiplier"] == 2

    def test_resistance_rule_loads(self):
        rule = RuleLoader.load(RESISTANCE_JSON)
        assert rule.name == "damage_resistance_rule"
        assert self._trigger(rule)["multiplier"] == 0.5

    def test_immunity_rule_loads(self):
        rule = RuleLoader.load(IMMUNITY_JSON)
        assert rule.name == "damage_immunity_rule"
        assert self._trigger(rule)["multiplier"] == 0


# ---------------------------------------------------------------------------
# End-to-end via DamageProcessor + the installed global rules
# ---------------------------------------------------------------------------

class TestDamageModifierEndToEnd:
    """
    These tests exercise the full pipeline: entity with a modifier, rule loaded,
    damage applied via DamageProcessor, result checked.
    """

    def _setup(self, vulnerability_json=None, resistance_json=None, immunity_json=None):
        # The damage-modifier globals are native block rules (§5d) — install them on
        # the block engine, the production resolution path (web/routers/combat.py).
        from src.spells.global_rules import install_global_rules

        bus = EventBus()
        processor = DamageProcessor(bus)
        paths = [p for p in (vulnerability_json, resistance_json, immunity_json) if p]
        rules = [RuleLoader.load(p) for p in paths]
        install_global_rules(rules, event_bus=bus, damage_processor=processor)
        return bus, processor, None

    def test_fire_vulnerable_entity_takes_doubled_damage(self):
        bus, processor, engine = self._setup(vulnerability_json=VULNERABILITY_JSON)
        entity = make_entity(vulnerabilities=[DamageType.FIRE])
        processor.apply_damage(entity, [Damage(DamageType.FIRE, 10)])
        assert entity.hp == 10  # 30 - (10 * 2) = 10

    def test_cold_resistant_entity_takes_halved_damage(self):
        bus, processor, engine = self._setup(resistance_json=RESISTANCE_JSON)
        entity = make_entity(resistances=[DamageType.COLD])
        processor.apply_damage(entity, [Damage(DamageType.COLD, 10)])
        assert entity.hp == 25  # 30 - (10 * 0.5) = 25

    def test_poison_immune_entity_takes_no_damage(self):
        bus, processor, engine = self._setup(immunity_json=IMMUNITY_JSON)
        entity = make_entity(immunities=[DamageType.POISON])
        processor.apply_damage(entity, [Damage(DamageType.POISON, 10)])
        assert entity.hp == 30  # no damage

    def test_modifier_does_not_affect_unrelated_damage_type(self):
        bus, processor, engine = self._setup(vulnerability_json=VULNERABILITY_JSON)
        entity = make_entity(vulnerabilities=[DamageType.FIRE])
        processor.apply_damage(entity, [Damage(DamageType.COLD, 10)])
        assert entity.hp == 20  # 30 - 10, no doubling
