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
from src.combat.event_data import DamageIncomingData
from src.combat.events import EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleEngine, RuleLoader

import src.spells.blocks  # noqa: F401  (registers the block catalogue)
from src.spells.block import Block
from src.spells.context import CastEnv, Invocation, seed_context
from src.spells.runner import run_block

RESISTANCE_JSON = os.path.join(
    os.path.dirname(__file__), "..", "rules", "global", "damage_resistance_rule.json"
)

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
    def _legacy_hp(self, resistances, dmg):
        bus = EventBus()
        processor = DamageProcessor(bus)
        RuleEngine(bus, damage_processor=processor).load_from_file(RESISTANCE_JSON)
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
# 3. Fold: a rule ModifyDamage effect translates into a modify_damage block
# ---------------------------------------------------------------------------

class TestFoldModifyDamage:
    def test_modify_damage_action_folds(self):
        from src.spells.fold import _ACTION_TO_BLOCK

        block = _ACTION_TO_BLOCK["ModifyDamage"](
            {"action": "ModifyDamage", "multiplier": 0.5}
        )
        assert block["block"] == "modify_damage"
        assert block["multiplier"] == 0.5
        assert "damage_type" not in block

    def test_modify_damage_preserves_type_filter(self):
        from src.spells.fold import _ACTION_TO_BLOCK

        block = _ACTION_TO_BLOCK["ModifyDamage"](
            {"action": "ModifyDamage", "multiplier": 0, "damage_type": "POISON"}
        )
        assert block["damage_type"] == "POISON"
