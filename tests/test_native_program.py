"""Native ``program`` authoring — parity with the legacy ``effects`` path.

Phase 3 §5's foundation + pilot. Three shipped spells are now authored as native
block ``program``s (Fire Bolt, Fireball, Vampiric Touch) instead of legacy
``effects``. These tests prove the migration is behaviour-preserving: for each, the
native program (as loaded from the shipped JSON) resolves **field-for-field
identically** to the old legacy shape run through the adapter/fold, under one seed.

They are the safety net Phase 3 §8 asks for per migration. Vampiric Touch also
proves the vision's inlining — its granted repeatable action and its concentration
heal-rider, formerly a second file (``rules/entity_effects/vampiric_touch.json``,
now deleted), live inline in the one program.
"""

import os

import pytest

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.models.spell_properties import TargetingType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.loaders import StatBlockLoader
from src.rules.rule_loader import RuleLoader
from src.spells.block import parse_program
from src.spells.adapter import to_program
from src.spells.evaluator import resolve as resolve_blocks
from src.spells.evaluator import resolve_program
from src.utils import dice

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


# ── Fixtures (mirror test_block_parity's caster/target) ──────────────────────────

def _caster() -> Entity:
    sb = StatBlock(
        name="Wizard",
        ability_scores=AbilityScores(10, 10, 10, 16, 10, 10),  # INT +3
        hit_points_max=20, armor_class=12,
        proficiency_bonus=2,             # spell attack bonus = 5, spell DC = 13
        spellcasting_ability="intelligence",
    )
    e = Entity(sb)
    e.refill_resources()
    return e


def _target(hp: int = 60, ac: int = 13) -> Entity:
    sb = StatBlock(name="Target", ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
                   hit_points_max=hp, armor_class=ac)
    e = Entity(sb)
    e.refill_resources()
    return e


def _load(name: str) -> SpellAction:
    return StatBlockLoader.load_spell_from_json(os.path.join(SPELLS_DIR, f"{name}.json"))


def _fields(result):
    """The observable per-defender fields a spell resolution produces."""
    return (
        result.hit,
        result.damage_dealt,
        result.healing_total,
        result.save_success,
        result.attack_roll,
    )


# ── Legacy shapes captured before migration (the parity oracle) ─────────────────

_FIREBOLT_LEGACY = [
    {"type": "attack_roll", "attack_bonus": "use_caster_bonus", "target": "defender"},
    {"type": "damage", "target": "defender", "damage_type": "FIRE",
     "formula": "1d10", "requires_hit": True},
]

_FIREBALL_LEGACY = [
    {"type": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc"},
    {"type": "damage", "damage_type": "FIRE", "formula": "8d6", "roll_once": True,
     "save_result": {"on_success": "half_damage"}},
]

_VT_LEGACY_EFFECTS = [
    {"type": "attack_roll", "attack_bonus": "use_caster_bonus", "target": "defender"},
    {"type": "damage", "target": "defender", "damage_type": "NECROTIC",
     "formula": "3d6", "requires_hit": True},
    {"type": "healing", "target": "caster", "amount": "context.damage_dealt // 2",
     "condition": "context.damage_dealt > 0"},
    {"type": "add_entity_effect", "entity_effect_name": "vampiric_touch",
     "on_caster": True, "concentration": True,
     "on_apply": [
         {"action": "GrantAction", "target": "event.caster", "name": "Vampiric Touch",
          "description": "Melee spell attack granted by Vampiric Touch concentration.",
          "bonus_to_hit": "event.caster.spell_attack_bonus", "range_ft": 5,
          "damage": [{"type": "NECROTIC", "formula": "3d6"}],
          "source_effect": "vampiric_touch"}]},
]

_VT_LEGACY_RULE = {
    "name": "vampiric_touch",
    "triggers": ["DAMAGE_DEALT"],
    "condition": "event.source == entity and event.action_name == 'Vampiric Touch'",
    "effects": [{"action": "HealTarget", "target": "entity", "formula": "0",
                 "bonus": "event.total // 2"}],
    "duration_rounds": 10,
    "source": "Vampiric Touch",
}


def _vt_rule_lookup():
    rule = RuleLoader.from_dict(_VT_LEGACY_RULE)
    return lambda name: rule if name == "vampiric_touch" else None


# ── Single-target parity: Fire Bolt ─────────────────────────────────────────────

@pytest.mark.parametrize("seed", [1, 7, 13, 21, 99])
def test_firebolt_native_matches_legacy(seed):
    action = _load("firebolt")
    assert action.program and not action.pipeline_effects  # loaded native

    dice.seed_rng(seed)
    c1, t1 = _caster(), _target()
    bus1 = EventBus()
    native = resolve_blocks(c1, t1, action, parse_program(action.program),
                            event_bus=bus1, damage_processor=DamageProcessor(bus1))

    dice.seed_rng(seed)
    c2, t2 = _caster(), _target()
    bus2 = EventBus()
    legacy = resolve_blocks(c2, t2, action, to_program(_FIREBOLT_LEGACY),
                            event_bus=bus2, damage_processor=DamageProcessor(bus2))

    assert _fields(native) == _fields(legacy)
    assert t1.current_hp == t2.current_hp


# ── AoE parity (shared roll + save-for-half): Fireball ──────────────────────────

@pytest.mark.parametrize("seed", [1, 7, 13, 21, 99])
def test_fireball_native_matches_legacy(seed):
    action = _load("fireball")
    assert action.program and not action.pipeline_effects
    assert action.targeting_type == TargetingType.AOE

    dice.seed_rng(seed)
    c1 = _caster()
    ts1 = [_target(90) for _ in range(4)]
    bus1 = EventBus()
    native = resolve_program(c1, ts1, action, parse_program(action.program),
                             event_bus=bus1, damage_processor=DamageProcessor(bus1),
                             slot_level=action.spell_level)

    dice.seed_rng(seed)
    c2 = _caster()
    ts2 = [_target(90) for _ in range(4)]
    bus2 = EventBus()
    legacy = resolve_program(c2, ts2, action,
                             to_program(_FIREBALL_LEGACY, TargetingType.AOE),
                             event_bus=bus2, damage_processor=DamageProcessor(bus2),
                             slot_level=action.spell_level)

    assert [_fields(r) for r in native] == [_fields(r) for r in legacy]
    assert [t.current_hp for t in ts1] == [t.current_hp for t in ts2]


# ── Persistent + concentration parity (the inlining proof): Vampiric Touch ──────

@pytest.mark.parametrize("seed", [1, 7, 13, 21, 99])
def test_vampiric_touch_native_matches_legacy(seed):
    action = _load("vampiric_touch")
    assert action.program and not action.pipeline_effects

    def run(program):
        c, t = _caster(), _target()
        bus = EventBus()
        res = resolve_blocks(c, t, action, program,
                             event_bus=bus, damage_processor=DamageProcessor(bus))
        return res, c, t

    dice.seed_rng(seed)
    native, cn, tn = run(parse_program(action.program))

    dice.seed_rng(seed)
    legacy, cl, tl = run(to_program(_VT_LEGACY_EFFECTS, TargetingType.SINGLE_TARGET,
                                    _vt_rule_lookup()))

    # Same immediate resolution (attack, necrotic damage, self-heal for half).
    assert _fields(native) == _fields(legacy)
    assert tn.current_hp == tl.current_hp
    # Same persistent install: the granted repeat action and the concentration.
    assert [a.name for a in cn.granted_actions] == [a.name for a in cl.granted_actions]
    assert cn.concentrating_on == cl.concentrating_on == "vampiric_touch"
