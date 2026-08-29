"""Global rules on the block engine (Phase 2.9, §4.7 step 3 — the first repoint).

Proves the small production repoint: the event-modifier global rules (damage
resistance/immunity/vulnerability, the crit rules) install as block-engine triggers
and behave identically to the legacy rule-engine dispatch — and that running the two
paths side by side does not double-apply, provided the handled rules are disabled on
the legacy engine (exactly what ``web/routers/combat.py`` does).
"""

import os

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType
from src.combat.event_bus import EventBus
from src.combat.event_data import AttackRolledData
from src.combat.events import EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleEngine, RuleLoader

from src.spells.global_rules import block_eligible, install_global_rules

_GLOBAL = os.path.join(os.path.dirname(__file__), "..", "rules", "global")
RESISTANCE = os.path.join(_GLOBAL, "damage_resistance_rule.json")
IMMUNITY = os.path.join(_GLOBAL, "damage_immunity_rule.json")
VULN = os.path.join(_GLOBAL, "damage_vulnerability_rule.json")
CRIT_HIT = os.path.join(_GLOBAL, "critical_hit.json")
CRIT_MISS = os.path.join(_GLOBAL, "critical_miss.json")
CONCENTRATION = os.path.join(_GLOBAL, "concentration.json")
REFILL = os.path.join(_GLOBAL, "action_economy_refill.json")


def _entity(hp=30, resistances=None, immunities=None, vulnerabilities=None):
    return Entity(
        StatBlock(
            name="Tester",
            ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
            hit_points_max=hp,
            armor_class=10,
            damage_resistances=resistances or [],
            damage_immunities=immunities or [],
            damage_vulnerabilities=vulnerabilities or [],
        )
    )


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class TestBlockEligible:
    def test_event_modifier_rules_are_eligible(self):
        for path in (RESISTANCE, IMMUNITY, VULN, CRIT_HIT, CRIT_MISS):
            assert block_eligible(RuleLoader.load(path)), path

    def test_side_effecting_rules_are_not_eligible(self):
        # ForceConcentrationCheck / RefillResources are forward effects, not event
        # mutations — they stay on the legacy engine.
        assert not block_eligible(RuleLoader.load(CONCENTRATION))
        assert not block_eligible(RuleLoader.load(REFILL))


# ---------------------------------------------------------------------------
# End-to-end via the block engine (parity with the legacy numbers)
# ---------------------------------------------------------------------------

class TestGlobalRulesEndToEnd:
    def _install(self, *paths):
        bus = EventBus()
        processor = DamageProcessor(bus)
        rules = [RuleLoader.load(p) for p in paths]
        handled = install_global_rules(
            rules, event_bus=bus, damage_processor=processor
        )
        return bus, processor, handled

    def test_resistance_halves_via_block_engine(self):
        bus, processor, handled = self._install(RESISTANCE)
        assert handled == {"damage_resistance_rule"}
        entity = _entity(resistances=[DamageType.COLD])
        processor.apply_damage(entity, [Damage(DamageType.COLD, 10)])
        assert entity.hp == 25  # halved once — matches the legacy rule

    def test_immunity_and_vulnerability_via_block_engine(self):
        bus, processor, _ = self._install(IMMUNITY, VULN)
        immune = _entity(immunities=[DamageType.POISON])
        processor.apply_damage(immune, [Damage(DamageType.POISON, 10)])
        assert immune.hp == 30  # no damage

        vuln = _entity(vulnerabilities=[DamageType.FIRE])
        processor.apply_damage(vuln, [Damage(DamageType.FIRE, 10)])
        assert vuln.hp == 10  # doubled

    def test_unmatched_type_is_untouched(self):
        bus, processor, _ = self._install(RESISTANCE)
        entity = _entity(resistances=[DamageType.COLD])
        processor.apply_damage(entity, [Damage(DamageType.FIRE, 10)])
        assert entity.hp == 20  # full damage, condition did not fire

    def test_crit_rules_via_block_engine(self):
        bus = EventBus()
        install_global_rules(
            [RuleLoader.load(CRIT_HIT), RuleLoader.load(CRIT_MISS)], event_bus=bus
        )

        def roll(r):
            ev = bus.emit(
                EventType.ATTACK_ROLLED,
                AttackRolledData(attacker=_entity(), defender=_entity(),
                                 action=None, roll=r, total=r),
            )
            return ev.data["critical_hit"], ev.data["critical_miss"]

        assert roll(20) == (True, False)
        assert roll(1) == (False, True)
        assert roll(12) == (False, False)


# ---------------------------------------------------------------------------
# The production flow: install on the block engine, disable on the rule engine
# ---------------------------------------------------------------------------

class TestNoDoubleApplication:
    def _production_flow(self, *, disable_handled):
        """Mirror web/routers/combat.py: load global rules into a RuleEngine,
        install the eligible ones on the block engine, optionally disable them on
        the rule engine. Returns (bus, processor)."""
        bus = EventBus()
        processor = DamageProcessor(bus)
        engine = RuleEngine(bus, damage_processor=processor)
        rules = [engine.load_from_file(RESISTANCE)]
        handled = install_global_rules(
            rules, event_bus=bus, damage_processor=processor
        )
        if disable_handled:
            for r in rules:
                if r.name in handled:
                    r.enabled = False
        return bus, processor

    def test_disabling_handled_rules_prevents_double_application(self):
        bus, processor = self._production_flow(disable_handled=True)
        entity = _entity(resistances=[DamageType.COLD])
        processor.apply_damage(entity, [Damage(DamageType.COLD, 10)])
        assert entity.hp == 25  # halved exactly once (block engine only)

    def test_without_disabling_the_rule_double_applies(self):
        """Documents *why* the disable is load-bearing: both paths fire, so the
        resistance is applied twice (legacy ×0.5 then block ×0.5 → 10→5→2)."""
        bus, processor = self._production_flow(disable_handled=False)
        entity = _entity(resistances=[DamageType.COLD])
        processor.apply_damage(entity, [Damage(DamageType.COLD, 10)])
        assert entity.hp == 28  # 30 - int(int(10*0.5)*0.5) = 30 - 2
