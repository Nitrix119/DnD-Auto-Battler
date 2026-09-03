"""Global rules on the block engine (Phase 2.9, §4.7 step 3 — the first repoint).

Proves the small production repoint: the event-modifier global rules (damage
resistance/immunity/vulnerability, the crit rules) install as block-engine triggers
and behave identically to the legacy rule-engine dispatch — and that running the two
paths side by side does not double-apply, provided the handled rules are disabled on
the legacy engine (exactly what ``web/routers/combat.py`` does).
"""

import os

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType, SpellAction
from src.models.action import AttackAction
from src.combat.event_bus import EventBus
from src.combat.event_data import AttackRolledData, TurnEventData
from src.combat.events import EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleLoader
from src.spells.rules import load_rules_from_directory

from src.spells.global_rules import block_eligible, install_global_rules

_GLOBAL = os.path.join(os.path.dirname(__file__), "..", "rules", "global")
RESISTANCE = os.path.join(_GLOBAL, "damage_resistance_rule.json")
IMMUNITY = os.path.join(_GLOBAL, "damage_immunity_rule.json")
VULN = os.path.join(_GLOBAL, "damage_vulnerability_rule.json")
CRIT_HIT = os.path.join(_GLOBAL, "critical_hit.json")
CRIT_MISS = os.path.join(_GLOBAL, "critical_miss.json")
CONCENTRATION = os.path.join(_GLOBAL, "concentration.json")
REFILL = os.path.join(_GLOBAL, "action_economy_refill.json")


def _entity(hp=30, resistances=None, immunities=None, vulnerabilities=None,
            con=10, ac=10):
    return Entity(
        StatBlock(
            name="Tester",
            ability_scores=AbilityScores(10, 10, con, 10, 10, 10),
            hit_points_max=hp,
            armor_class=ac,
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
# The production flow: load_rules_from_directory installs them on the block engine
# ---------------------------------------------------------------------------

class TestNativeGlobalInstall:
    """Loading a rule *is* installing it on the block engine — its single resolution
    path — so ``load_rules_from_directory`` wires every global rule for library and
    `CombatSystem` usage with no separate install step. Each installs exactly once."""

    def test_load_from_directory_installs_all_natives_once(self):
        bus = EventBus()
        processor = DamageProcessor(bus)
        rules = load_rules_from_directory(
            _GLOBAL, event_bus=bus, damage_processor=processor)
        assert len(rules) == 7  # every shipped global rule loaded
        # Resistance fires exactly once (halved, not doubled) — no explicit install call.
        entity = _entity(resistances=[DamageType.COLD])
        processor.apply_damage(entity, [Damage(DamageType.COLD, 10)])
        assert entity.hp == 25


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

    def _concentrating_caster(self, bus, dp, con=10, hp=30):
        """A caster holding a real block-engine concentration + a +2 AC buff."""
        from src.spells.evaluator import resolve as resolve_blocks
        from src.spells.block import parse_program

        caster = _entity(hp=hp, con=con)
        program = parse_program([{
            "block": "lifetime", "kind": "concentration", "source": "Shield of Faith",
            "then": [{"block": "add_modifier", "target": "self", "stat": "ac",
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

    def _damage_a_concentrating_caster(self, roll, con=14, amount=30):
        """Damage a concentrating caster for *amount* on a fixed d20 *roll*.

        30 damage sets the rule's DC to ``max(10, 30 // 2)`` = 15.
        """
        from unittest.mock import patch

        bus = EventBus()
        dp = DamageProcessor(bus)
        install_global_rules([RuleLoader.load(CONCENTRATION)],
                             event_bus=bus, damage_processor=dp)
        caster = self._concentrating_caster(bus, dp, con=con, hp=100)
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=roll):
            dp.apply_damage(caster, [Damage(DamageType.GENERIC, amount)])
        return caster

    def test_con_modifier_is_applied_to_the_save(self):
        """The save adds the target's CON modifier: 12 + 2 = 14 misses DC 15."""
        assert not self._damage_a_concentrating_caster(roll=12).has_concentration

    def test_con_modifier_can_push_the_roll_over_the_dc(self):
        """Meets-DC-exactly passes: 13 + 2 = 15 against DC 15 holds.

        The same roll without the +2 (CON 10) fails — which is what proves the
        modifier, not the roll, is doing the work.
        """
        assert self._damage_a_concentrating_caster(roll=13).has_concentration
        assert not self._damage_a_concentrating_caster(roll=13, con=10).has_concentration


# ---------------------------------------------------------------------------
# Cancelling an in-flight action from a global rule
# ---------------------------------------------------------------------------

class TestCancelViaGlobalRule:
    """A native global rule can cancel the action that raised the event.

    The `cancel` block sets the flag on the live `CombatEvent`; what makes it
    meaningful is that the *emitter* honours it, so this is asserted end-to-end
    through `CombatSystem.resolve_attack` rather than on the event alone.
    """

    _PACIFISM = {
        "name": "pacifism",
        "program": [
            {
                "block": "trigger",
                "event": "ATTACK_DECLARED",
                "then": [{"block": "cancel"}],
            },
        ],
    }

    def _combat(self):
        from src.combat import CombatSystem

        combat = CombatSystem()
        attacker = _entity(hp=30, ac=5)
        defender = _entity(hp=50, ac=5)
        combat.add_combatant(attacker)
        combat.add_combatant(defender)
        combat.start_combat()
        for i, entry in enumerate(combat.initiative_tracker.initiative_order):
            if entry.entity is attacker:
                combat.initiative_tracker.current_turn_index = i
                break
        # bonus_to_hit 99 against AC 5: this attack cannot miss on its own merits,
        # so a (False, 0) result can only come from the cancellation.
        attack = AttackAction(
            name="Sword", description="", bonus_to_hit=99,
            damage=[Damage(DamageType.SLASHING, 1)],
        )
        return combat, attacker, defender, attack

    def test_uncancelled_attack_hits(self):
        """The control: without the rule the same attack lands and deals damage."""
        combat, attacker, defender, attack = self._combat()
        hit, damage, _ = combat.resolve_attack(attacker, defender, attack)
        assert hit is True and damage > 0
        assert defender.hp < 50

    def test_cancel_on_attack_declared_stops_the_attack(self):
        combat, attacker, defender, attack = self._combat()
        install_global_rules([RuleLoader.from_dict(dict(self._PACIFISM))],
                             event_bus=combat.event_bus)

        hit, damage, _ = combat.resolve_attack(attacker, defender, attack)
        assert hit is False
        assert damage == 0
        assert defender.hp == 50  # took no damage
