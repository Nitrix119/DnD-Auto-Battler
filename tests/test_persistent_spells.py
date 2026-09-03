"""Persistent spells end to end: a lifetime scope that outlives the cast.

The spells whose effect does not finish when the cast does — Longstrider (a per-turn
movement grant), Shield of Faith (a concentration AC buff), Charm Person (a condition
with a captured charmer), Haste (a duration-bound extra action on an ally). Each is a
``lifetime`` block owning grants and/or triggers, and what these prove is the whole
arc: the grant lands, the rider fires on the right turns and for the right entity, and
everything is torn down together when the scope ends — by expiry, by concentration
loss, or by dispel.
"""

import os

from src.models import Entity, AbilityScores, StatBlock, ACTION_COST
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.rules import EffectRegistry
from src.spells.rules import load_rule_file
from src.loaders import StatBlockLoader

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


def _spell(name):
    return StatBlockLoader.load_spell_from_json(os.path.join(SPELLS_DIR, f"{name}.json"))


# NOTE: this file once also asserted the *shape* a translator produced from these
# spells' legacy ``add_entity_effect`` steps. Both the translator and that authoring
# shape are gone — the spells are block programs — so only the behavioural tests below
# remain, which is what CLAUDE.md §4 asks for anyway ("test behaviour, not structure").


class TestLongstriderEndToEnd:

    def test_movement_grant_fires_after_the_refill(self):
        """The rider adds +10 movement *after* the per-turn refill resets it.

        Validates the trigger's -10 priority slot: were it to fire before the
        priority-0 refill, the +10 would be wiped and movement would read base.
        """
        from src.combat.spell_resolver import SpellResolver
        from src.combat.event_data import TurnEventData

        wizard = StatBlockLoader.load_from_json(
            os.path.join(os.path.dirname(__file__), "..", "examples",
                         "creatures", "characters", "wizard.json")
        )
        wizard = Entity(wizard)
        goblin = StatBlockLoader.load_from_json(
            os.path.join(os.path.dirname(__file__), "..", "examples",
                         "creatures", "goblin.json")
        )
        goblin = Entity(goblin)
        base_move = goblin.resources.movement

        bus = EventBus()
        dp = DamageProcessor(bus)
        reg = EffectRegistry()
        reg.scan_directory("rules/entity_effects")
        load_rule_file("rules/global/action_economy_refill.json",
                       event_bus=bus, damage_processor=dp)
        resolver = SpellResolver(bus, dp, condition_rules=reg)

        resolver.resolve(wizard, [goblin], _spell("longstrider"))
        assert len(goblin.lifetimes) == 1  # the spell's lifetime scope is open

        bus.emit(EventType.TURN_START,
                 TurnEventData(entity=goblin, round_num=2, turn_num=1))
        assert goblin.resources.movement == base_move + 10


# ── End-to-end on the new engine, via the real router ───────────────────────────

def _cleric():
    sb = StatBlock(
        name="Cleric",
        ability_scores=AbilityScores(10, 10, 12, 10, 16, 10),
        hit_points_max=30, armor_class=14,
        proficiency_bonus=2, spellcasting_ability="wisdom",
    )
    return Entity(sb)


def _resolver(*entities):
    from src.combat.spell_resolver import SpellResolver

    bus = EventBus()
    dp = DamageProcessor(bus)
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    load_rule_file("rules/global/concentration.json",
                   event_bus=bus, damage_processor=dp)
    return bus, reg, SpellResolver(bus, dp, condition_rules=reg)


class TestShieldOfFaithEndToEnd:

    def test_cast_runs_on_the_new_engine_and_grants_ac(self):
        from unittest.mock import patch

        cleric = _cleric()
        bus, engine, resolver = _resolver(cleric)
        base = cleric.ac
        resolver.resolve(cleric, [cleric], _spell("shield_of_faith"))

        # A real lifetime scope is open on the caster.
        assert cleric.concentration_scope is not None
        assert cleric.has_concentration
        assert cleric.ac == base + 2

        # A failed CON save from damage tears the scope down and restores AC.
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=cleric, damage_list=[], total=20)
        assert not cleric.has_concentration
        assert cleric.concentration_scope is None
        assert cleric.ac == base


class TestCharmPerson:
    """Charm Person on the new engine — the instance_fields closure (charmer)."""

    def _cast(self, resolver, caster, target, *, save_fails):
        from unittest.mock import patch

        roll = (5, False) if save_fails else (20, True)
        with patch("src.spells.blocks.rolls.roll_saving_throw", return_value=roll):
            resolver.resolve(caster, [target], _spell("charm_person"))

    def _declare(self, bus, attacker, defender):
        from src.combat.event_data import AttackDeclaredData

        return bus.emit(
            EventType.ATTACK_DECLARED,
            AttackDeclaredData(attacker=attacker, defender=defender, action=None),
        )

    def test_charmed_target_cannot_attack_the_caster(self):
        caster, target = _cleric(), _cleric()
        bus, engine, resolver = _resolver(caster, target)
        self._cast(resolver, caster, target, save_fails=True)
        assert len(target.lifetimes) == 1
        assert self._declare(bus, target, caster).cancelled is True

    def test_charmed_target_can_attack_others(self):
        caster, target, bystander = _cleric(), _cleric(), _cleric()
        bus, engine, resolver = _resolver(caster, target, bystander)
        self._cast(resolver, caster, target, save_fails=True)
        assert self._declare(bus, target, bystander).cancelled is False

    def test_successful_save_applies_no_charm(self):
        caster, target = _cleric(), _cleric()
        bus, engine, resolver = _resolver(caster, target)
        self._cast(resolver, caster, target, save_fails=False)
        assert len(target.lifetimes) == 0
        assert self._declare(bus, target, caster).cancelled is False

    def test_two_casts_track_their_own_charmer(self):
        """Each cast captures its own charmer — a victim blocks only its charmer."""
        charmer_a, charmer_b = _cleric(), _cleric()
        victim_a, victim_b = _cleric(), _cleric()
        bus, engine, resolver = _resolver(charmer_a, charmer_b, victim_a, victim_b)
        self._cast(resolver, charmer_a, victim_a, save_fails=True)
        self._cast(resolver, charmer_b, victim_b, save_fails=True)

        assert self._declare(bus, victim_a, charmer_a).cancelled is True
        assert self._declare(bus, victim_a, charmer_b).cancelled is False
        assert self._declare(bus, victim_b, charmer_b).cancelled is True
        assert self._declare(bus, victim_b, charmer_a).cancelled is False


class TestHaste:
    """Haste on the new engine — the VT pattern with the rider on a targeted ally."""

    def _setup(self, caster, ally):
        from src.combat.spell_resolver import SpellResolver
        from src.combat.lifetime_clock import install_lifetime_clock

        bus = EventBus()
        install_lifetime_clock(bus)  # ticks concentration/duration on TURN_END
        dp = DamageProcessor(bus)
        reg = EffectRegistry()
        reg.scan_directory("rules/entity_effects")
        for rule_path in ("rules/global/action_economy_refill.json",
                          "rules/global/concentration.json"):
            load_rule_file(rule_path, event_bus=bus, damage_processor=dp)
        return bus, reg, SpellResolver(bus, dp, condition_rules=reg)

    def _turn_start(self, bus, entity, round_num=2):
        from src.combat.event_data import TurnEventData

        bus.emit(EventType.TURN_START,
                 TurnEventData(entity=entity, round_num=round_num, turn_num=1))

    def _turn_end(self, bus, entity, round_num=1):
        from src.combat.event_data import TurnEventData

        bus.emit(EventType.TURN_END,
                 TurnEventData(entity=entity, round_num=round_num, turn_num=1))

    def test_grants_extra_action_on_the_ally_after_refill(self):
        caster, ally = _cleric(), _cleric()
        bus, engine, resolver = self._setup(caster, ally)
        resolver.resolve(caster, [ally], _spell("haste"))

        # Runs on the new engine: the caster concentrates, targeting the ally.
        assert caster.concentration_scope is not None
        assert caster.concentration_target is ally

        base = ally.resources.actions
        ally.spend_resources(ACTION_COST)  # actions -> 0
        self._turn_start(bus, ally)
        # Refilled to base, then the rider adds +1 (it fires at -10, after refill).
        assert ally.resources.actions == base + 1

    def test_breaking_concentration_stops_the_bonus(self):
        from unittest.mock import patch

        caster, ally = _cleric(), _cleric()
        bus, engine, resolver = self._setup(caster, ally)
        resolver.resolve(caster, [ally], _spell("haste"))

        # A failed CON save from damage to the caster breaks concentration.
        with patch("src.spells.blocks.global_effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=caster, damage_list=[], total=20)
        assert not caster.has_concentration

        ally.spend_resources(ACTION_COST)
        self._turn_start(bus, ally)
        assert ally.resources.actions == 1  # only the refill; the rider is revoked

    def test_duration_expires_on_the_casters_turns(self):
        """Accepted deviation: the 10-round clock lives on the caster's concentration
        scope, so it ticks on the *caster's* turns, not the ally's
        (a carried deviation — see docs/SPELL_SYSTEM_REMAINING.md §2)."""
        caster, ally = _cleric(), _cleric()
        bus, engine, resolver = self._setup(caster, ally)
        resolver.resolve(caster, [ally], _spell("haste"))

        for r in range(1, 11):
            assert caster.has_concentration, f"round {r}: still concentrating"
            self._turn_end(bus, caster, round_num=r)
        assert not caster.has_concentration  # expired after 10 caster turns

        ally.spend_resources(ACTION_COST)
        self._turn_start(bus, ally, round_num=11)
        assert ally.resources.actions == 1  # the bonus is gone
