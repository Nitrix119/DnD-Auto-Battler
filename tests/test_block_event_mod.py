"""Event-modifier blocks — the live-event mutation contract (plan §4.7 step 1).

The first block category that reaches back onto an in-flight ``CombatEvent`` rather
than writing forward state. These tests prove the primitive three ways:

1. **The handle works** — ``modify_damage`` mutates the live event exposed on
   ``Invocation.live_event``.
2. **Parity end-to-end** — a native ``trigger{ modify_damage }`` program installed
   on the bus produces the *same* result as the legacy ``damage_resistance_rule``
   JSON run through the RuleEngine, under one DamageProcessor path on identical
   entities. This is the gate: the new path must match the old exactly.
3. **Fail-safe** — a ``modify_damage`` with no live event (run outside a trigger)
   no-ops instead of crashing.

Plus a fold check: a rule ``ModifyDamage`` effect translates into a ``modify_damage``
block (the ``_ACTION_TO_BLOCK`` entry that lets resistance-style entity effects fold).
"""

import os

from src.models import AbilityScores, StatBlock, Entity, Damage, DamageType
from src.combat.event_bus import EventBus, CombatEvent
from src.combat.event_data import (
    DamageIncomingData,
    AttackRolledData,
    AttackDeclaredData,
)
from src.combat.events import EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleEngine, RuleLoader

import src.spells.blocks  # noqa: F401  (registers the block catalogue)
from src.spells.block import Block
from src.spells.context import CastEnv, Invocation, seed_context
from src.spells.runner import run_block

_GLOBAL = os.path.join(os.path.dirname(__file__), "..", "rules", "global")
RESISTANCE_JSON = os.path.join(_GLOBAL, "damage_resistance_rule.json")
CRIT_HIT_JSON = os.path.join(_GLOBAL, "critical_hit.json")
CRIT_MISS_JSON = os.path.join(_GLOBAL, "critical_miss.json")

# The resistance rule as a native block program: a permanent (lifetime-less)
# trigger that halves matching damage on the in-flight DAMAGE_INCOMING event.
RESISTANCE_TRIGGER = {
    "block": "trigger",
    "event": "DAMAGE_INCOMING",
    "when": (
        "event.damage_list[0].damage_type in "
        "event.defender.stat_block.damage_resistances"
    ),
    "then": [{"block": "modify_damage", "multiplier": 0.5}],
}

# The nat-20 / nat-1 crit rules as native block programs.
CRIT_HIT_TRIGGER = {
    "block": "trigger",
    "event": "ATTACK_ROLLED",
    "when": "event.roll == 20",
    "then": [{"block": "force_critical", "outcome": "hit"}],
}
CRIT_MISS_TRIGGER = {
    "block": "trigger",
    "event": "ATTACK_ROLLED",
    "when": "event.roll == 1",
    "then": [{"block": "force_critical", "outcome": "miss"}],
}


def _stat_block(hp=30, resistances=None):
    return StatBlock(
        name="Tester",
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp,
        armor_class=10,
        damage_resistances=resistances or [],
    )


def _entity(hp=30, resistances=None):
    return Entity(_stat_block(hp=hp, resistances=resistances))


def _new_inv(bus, caster, *, live_event=None, event_data=None):
    env = CastEnv(action=None, event_bus=bus, damage_processor=None)
    return Invocation(
        env=env,
        caster=caster,
        target=caster,
        context=seed_context(0),
        event_data=event_data,
        live_event=live_event,
    )


def _install_native_trigger(bus, block_dict):
    """Run a trigger block once so it subscribes to the bus (a global-rule stand-in)."""
    inv = _new_inv(bus, _entity())
    run_block(Block.from_dict(block_dict), inv)


# ---------------------------------------------------------------------------
# 1. The live-event handle
# ---------------------------------------------------------------------------

class TestModifyDamageHandle:
    def _run(self, multiplier, damage_list, damage_type=None):
        bus = EventBus()
        event = CombatEvent(
            event_type=EventType.DAMAGE_INCOMING,
            data=DamageIncomingData(defender=_entity(), damage_list=damage_list),
        )
        inv = _new_inv(bus, _entity(), live_event=event,
                       event_data=dict(event.data))
        args = {"block": "modify_damage", "multiplier": multiplier}
        if damage_type is not None:
            args["damage_type"] = damage_type.name
        run_block(Block.from_dict(args), inv)

    def test_half_multiplier_halves_live_event(self):
        dmg = Damage(DamageType.COLD, 10)
        self._run(0.5, [dmg])
        assert dmg.amount == 5

    def test_zero_multiplier_zeroes(self):
        dmg = Damage(DamageType.POISON, 10)
        self._run(0, [dmg])
        assert dmg.amount == 0

    def test_double_multiplier_doubles(self):
        dmg = Damage(DamageType.FIRE, 10)
        self._run(2, [dmg])
        assert dmg.amount == 20

    def test_type_filter_only_matching(self):
        fire = Damage(DamageType.FIRE, 10)
        cold = Damage(DamageType.COLD, 10)
        self._run(2, [fire, cold], damage_type=DamageType.FIRE)
        assert fire.amount == 20
        assert cold.amount == 10  # untouched

    def test_no_live_event_is_a_safe_noop(self):
        """Run outside a trigger: no live event to touch, so it must not raise."""
        bus = EventBus()
        inv = _new_inv(bus, _entity())  # live_event=None
        run_block(Block.from_dict({"block": "modify_damage", "multiplier": 0.5}), inv)
        # nothing to assert beyond "did not raise"


# ---------------------------------------------------------------------------
# 2. Parity: native block trigger vs the legacy resistance rule
# ---------------------------------------------------------------------------

class TestResistanceParity:
    # The shipped resistance rule is native now (§5d), so it no longer runs on the
    # legacy dispatch — this parity oracle uses an inline *legacy*-shaped rule (the
    # frozen pre-migration form) so the block trigger is still checked against the
    # legacy handler's numbers. Native-vs-legacy parity for the shipped file itself is
    # pinned in test_native_rules_parity.
    _LEGACY_RESISTANCE = {
        "name": "damage_resistance_rule",
        "triggers": ["DAMAGE_INCOMING"],
        "condition": (
            "event.damage_list[0].damage_type in "
            "event.defender.stat_block.damage_resistances"
        ),
        "effects": [{"action": "ModifyDamage", "multiplier": 0.5}],
    }

    def _legacy_hp(self, resistances, dmg):
        bus = EventBus()
        processor = DamageProcessor(bus)
        engine = RuleEngine(bus, damage_processor=processor)
        engine.load_rule(RuleLoader.from_dict(dict(self._LEGACY_RESISTANCE)))
        entity = _entity(resistances=resistances)
        processor.apply_damage(entity, [dmg])
        return entity.hp

    def _block_hp(self, resistances, dmg):
        bus = EventBus()
        processor = DamageProcessor(bus)
        _install_native_trigger(bus, RESISTANCE_TRIGGER)
        entity = _entity(resistances=resistances)
        processor.apply_damage(entity, [dmg])
        return entity.hp

    def test_resisted_damage_matches_legacy(self):
        legacy = self._legacy_hp([DamageType.COLD], Damage(DamageType.COLD, 10))
        block = self._block_hp([DamageType.COLD], Damage(DamageType.COLD, 10))
        assert block == legacy == 25  # 30 - (10 * 0.5)

    def test_unresisted_damage_matches_legacy(self):
        legacy = self._legacy_hp([DamageType.COLD], Damage(DamageType.FIRE, 10))
        block = self._block_hp([DamageType.COLD], Damage(DamageType.FIRE, 10))
        assert block == legacy == 20  # full 10 damage, condition did not fire


# ---------------------------------------------------------------------------
# 2b. force_critical — the crit-rule primitive
# ---------------------------------------------------------------------------

class TestForceCriticalHandle:
    def _run(self, outcome, roll):
        bus = EventBus()
        event = CombatEvent(
            event_type=EventType.ATTACK_ROLLED,
            data=AttackRolledData(
                attacker=_entity(), defender=_entity(), action=None,
                roll=roll, total=roll,
            ),
        )
        inv = _new_inv(bus, _entity(), live_event=event, event_data=dict(event.data))
        run_block(Block.from_dict({"block": "force_critical", "outcome": outcome}), inv)
        return event.data

    def test_outcome_hit_sets_critical_hit(self):
        data = self._run("hit", 20)
        assert data["critical_hit"] is True
        assert data["critical_miss"] is False

    def test_outcome_miss_sets_critical_miss(self):
        data = self._run("miss", 1)
        assert data["critical_miss"] is True
        assert data["critical_hit"] is False

    def test_default_outcome_is_hit(self):
        bus = EventBus()
        event = CombatEvent(
            event_type=EventType.ATTACK_ROLLED,
            data=AttackRolledData(attacker=_entity(), defender=_entity(),
                                  action=None, roll=20, total=20),
        )
        inv = _new_inv(bus, _entity(), live_event=event, event_data=dict(event.data))
        run_block(Block.from_dict({"block": "force_critical"}), inv)
        assert event.data["critical_hit"] is True

    def test_no_live_event_is_a_safe_noop(self):
        bus = EventBus()
        inv = _new_inv(bus, _entity())  # live_event=None
        run_block(Block.from_dict({"block": "force_critical", "outcome": "hit"}), inv)


class TestForceCriticalParity:
    """A native crit trigger sets the same flag the legacy crit rule does."""

    def _emit(self, roll, *, legacy_json=None, trigger=None):
        bus = EventBus()
        if legacy_json is not None:
            RuleEngine(bus).load_from_file(legacy_json)
        if trigger is not None:
            _install_native_trigger(bus, trigger)
        event = bus.emit(
            EventType.ATTACK_ROLLED,
            AttackRolledData(attacker=_entity(), defender=_entity(),
                             action=None, roll=roll, total=roll),
        )
        return event.data["critical_hit"], event.data["critical_miss"]

    def test_nat_20_forces_crit_matches_legacy(self):
        legacy = self._emit(20, legacy_json=CRIT_HIT_JSON)
        block = self._emit(20, trigger=CRIT_HIT_TRIGGER)
        assert block == legacy == (True, False)

    def test_nat_1_forces_miss_matches_legacy(self):
        legacy = self._emit(1, legacy_json=CRIT_MISS_JSON)
        block = self._emit(1, trigger=CRIT_MISS_TRIGGER)
        assert block == legacy == (False, True)

    def test_ordinary_roll_forces_neither_matches_legacy(self):
        legacy = self._emit(10, legacy_json=CRIT_HIT_JSON)
        block = self._emit(10, trigger=CRIT_HIT_TRIGGER)
        assert block == legacy == (False, False)


# ---------------------------------------------------------------------------
# 3. The condition-library event-modifiers: advantage / disadvantage / cancel
# ---------------------------------------------------------------------------

class TestConditionEventModifiers:
    def _event(self):
        return CombatEvent(
            event_type=EventType.ATTACK_DECLARED,
            data=AttackDeclaredData(
                attacker=_entity(), defender=_entity(), action=None
            ),
        )

    def _run(self, btype):
        bus = EventBus()
        event = self._event()
        inv = _new_inv(bus, _entity(), live_event=event, event_data=dict(event.data))
        run_block(Block.from_dict({"block": btype}), inv)
        return event

    def test_grant_advantage_sets_flag(self):
        assert self._run("grant_advantage").data["advantage"] is True

    def test_grant_disadvantage_sets_flag(self):
        assert self._run("grant_disadvantage").data["disadvantage"] is True

    def test_cancel_sets_event_cancelled(self):
        assert self._run("cancel").cancelled is True

    def test_grant_advantage_matches_legacy_handler(self):
        from src.rules.effects import grant_advantage as legacy

        block_event = self._run("grant_advantage")
        legacy_event = self._event()
        legacy({}, {}, legacy_event, EventBus())
        assert block_event.data["advantage"] == legacy_event.data["advantage"] is True

    def test_grant_disadvantage_matches_legacy_handler(self):
        from src.rules.effects import grant_disadvantage as legacy

        block_event = self._run("grant_disadvantage")
        legacy_event = self._event()
        legacy({}, {}, legacy_event, EventBus())
        assert (
            block_event.data["disadvantage"]
            == legacy_event.data["disadvantage"]
            is True
        )

    def test_cancel_matches_legacy_handler(self):
        from src.rules.effects import cancel_event as legacy

        block_event = self._run("cancel")
        legacy_event = self._event()
        legacy({}, {}, legacy_event, EventBus())
        assert block_event.cancelled == legacy_event.cancelled is True

    def test_no_live_event_is_a_safe_noop(self):
        bus = EventBus()
        inv = _new_inv(bus, _entity())  # live_event=None
        for bt in ("grant_advantage", "grant_disadvantage", "cancel"):
            run_block(Block.from_dict({"block": bt}), inv)
