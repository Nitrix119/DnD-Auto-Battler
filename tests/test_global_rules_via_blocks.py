"""Global rules on the block engine (Phase 2.9, §4.7 step 3 — the first repoint).

Proves the small production repoint: the event-modifier global rules (damage
resistance/immunity/vulnerability, the crit rules) install as block-engine triggers
and behave identically to the legacy rule-engine dispatch — and that running the two
paths side by side does not double-apply, provided the handled rules are disabled on
the legacy engine (exactly what ``web/routers/combat.py`` does).
"""

import os

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType, SpellAction
from src.combat.event_bus import EventBus
from src.combat.event_data import AttackRolledData, TurnEventData
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

    def test_forward_side_effect_rules_are_eligible(self):
        # ForceConcentrationCheck / RefillResources now have forward blocks a global
        # trigger can run, so the last two global rules are installable too.
        assert block_eligible(RuleLoader.load(CONCENTRATION))
        assert block_eligible(RuleLoader.load(REFILL))


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
    # A *legacy*-shaped resistance rule (``triggers``/``effects``, not a native block
    # ``program``). The disable discipline this class documents only bites for a rule
    # that is BOTH block-installed and on the legacy dispatch — i.e. an un-migrated rule.
    # The shipped resistance rule migrated to native in §5d (empty triggers → never on
    # legacy dispatch → structurally cannot double-apply), so this uses an inline legacy
    # rule to keep exercising the coexistence discipline that still applies to the
    # remaining legacy globals (crit/concentration/refill).
    _LEGACY_RESISTANCE = {
        "name": "damage_resistance_rule",
        "triggers": ["DAMAGE_INCOMING"],
        "condition": (
            "event.damage_list[0].damage_type in "
            "event.defender.stat_block.damage_resistances"
        ),
        "effects": [{"action": "ModifyDamage", "multiplier": 0.5}],
    }

    def _production_flow(self, *, disable_handled):
        """Mirror web/routers/combat.py: load a legacy global rule into a RuleEngine,
        install it on the block engine, optionally disable it on the rule engine.
        Returns (bus, processor)."""
        bus = EventBus()
        processor = DamageProcessor(bus)
        engine = RuleEngine(bus, damage_processor=processor)
        rule = RuleLoader.from_dict(dict(self._LEGACY_RESISTANCE))
        engine.load_rule(rule)
        rules = [rule]
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

    def test_every_global_rule_is_handled_and_disabled(self):
        """The whole rules/global/ directory now migrates: every rule is
        block-installed and disabled on the legacy engine (nothing double-active)."""
        bus = EventBus()
        processor = DamageProcessor(bus)
        engine = RuleEngine(bus, damage_processor=processor)
        rules = engine.load_from_directory(_GLOBAL)
        handled = install_global_rules(rules, event_bus=bus, damage_processor=processor)
        for r in rules:
            if r.name in handled:
                r.enabled = False
        assert {r.name for r in rules} == handled  # all seven eligible
        assert all(not r.enabled for r in rules)


# ---------------------------------------------------------------------------
# The two forward global rules (concentration break + resource refill)
# ---------------------------------------------------------------------------

class TestForwardGlobalRules:
    def test_refill_resets_resources_via_block_engine(self):
        bus = EventBus()
        install_global_rules([RuleLoader.load(REFILL)], event_bus=bus)
        entity = _entity()
        entity.resources.actions = 0  # spent
        bus.emit(EventType.TURN_START,
                 TurnEventData(entity=entity, round_num=2, turn_num=1))
        assert entity.resources.actions == 1  # refilled to the stat-block default

    def _concentrating_caster(self, bus, dp):
        """A caster holding a real block-engine concentration + a +2 AC buff."""
        from src.spells.evaluator import resolve as resolve_blocks
        from src.spells.block import parse_program

        caster = _entity()
        program = parse_program([{
            "block": "lifetime", "kind": "concentration", "source": "Shield of Faith",
            "then": [{"block": "add_modifier", "target": "caster", "stat": "ac",
                      "value": 2, "source": "Shield of Faith"}],
        }])
        resolve_blocks(caster, caster,
                       SpellAction(name="Shield of Faith", description="", spell_level=1),
                       program, event_bus=bus, damage_processor=dp)
        return caster

    def test_failed_save_breaks_concentration_via_block_engine(self):
        from unittest.mock import patch

        bus = EventBus()
        dp = DamageProcessor(bus)
        install_global_rules([RuleLoader.load(CONCENTRATION)],
                             event_bus=bus, damage_processor=dp)
        caster = self._concentrating_caster(bus, dp)
        base = _entity().ac
        assert caster.has_concentration and caster.ac == base + 2

        with patch("src.spells.blocks.global_effects.roll_d20", return_value=1):
            dp.apply_damage(caster, [Damage(DamageType.GENERIC, 20)])
        assert not caster.has_concentration  # failed CON save
        assert caster.ac == base            # the buff was revoked with the scope

    def test_passed_save_holds_concentration_via_block_engine(self):
        from unittest.mock import patch

        bus = EventBus()
        dp = DamageProcessor(bus)
        install_global_rules([RuleLoader.load(CONCENTRATION)],
                             event_bus=bus, damage_processor=dp)
        caster = self._concentrating_caster(bus, dp)
        base = _entity().ac

        with patch("src.spells.blocks.global_effects.roll_d20", return_value=20):
            dp.apply_damage(caster, [Damage(DamageType.GENERIC, 20)])
        assert caster.has_concentration  # passed CON save
        assert caster.ac == base + 2
