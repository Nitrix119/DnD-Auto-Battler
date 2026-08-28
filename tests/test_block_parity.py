"""Parity harness: the new block evaluator vs the legacy pipeline (Phase 1).

The gate for the rewrite: for a given spell and seed, the new evaluator must
produce the *same* observable outcome as the old ``EffectPipeline`` — same hit,
same rolls, same damage, same resulting HP. This harness runs both engines under
one seed on fresh, identical entities and asserts they agree, across many seeds.

Slice 2 ports ``attack_roll`` + ``damage``; Fire Bolt (attack cantrip) is the
first spell proven at parity. Later slices extend the ported blocks and add
spells to ``PARITY_SPELLS``.
"""

import glob
import os

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.models.damage import Damage, DamageType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.effect_pipeline import EffectPipeline
from src.rules.rule_engine import RuleEngine
from src.loaders import StatBlockLoader
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks
from src.spells.adapter import to_program, can_run_on_blocks
from src.utils import dice

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


# ── Fixtures: a caster with a real spell attack bonus, and a target ─────────────

def _caster() -> Entity:
    sb = StatBlock(
        name="Wizard",
        ability_scores=AbilityScores(10, 10, 10, 16, 10, 10),  # INT +3
        hit_points_max=20, armor_class=12,
        proficiency_bonus=2,             # spell attack bonus = 2 + 3 = 5
        spellcasting_ability="intelligence",
    )
    e = Entity(sb)
    e.refill_resources()
    return e


def _target(hp: int = 40, ac: int = 13) -> Entity:
    sb = StatBlock(name="Target", ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
                   hit_points_max=hp, armor_class=ac)
    e = Entity(sb)
    e.refill_resources()
    return e


# ── The parity assertion ────────────────────────────────────────────────────────

_COMPARED = (
    "hit", "damage_dealt", "healing_total", "save_success", "save_roll", "save_dc",
    "attack_roll", "attack_total", "critical_hit", "critical_miss",
    "had_advantage", "had_disadvantage",
)


def _wound(entity, amount):
    if amount:
        entity.take_damage(Damage(DamageType.GENERIC, amount))


def assert_parity(legacy_steps, program_dicts, *, seeds=range(1, 41),
                  spell_level=0, target_hp=40, target_ac=13,
                  pre_damage_target=0, pre_damage_caster=0):
    """Run the same spell on both engines under each seed; assert identical.

    Compares every result field plus the resulting caster and target HP, so
    damage *and* healing are covered.
    """
    program = parse_program(program_dicts)
    for seed in seeds:
        # Legacy engine.
        dice.seed_rng(seed)
        caster_o, target_o = _caster(), _target(target_hp, target_ac)
        _wound(target_o, pre_damage_target)
        _wound(caster_o, pre_damage_caster)
        action_o = SpellAction(name="Spell", description="", spell_level=spell_level,
                               pipeline_effects=legacy_steps)
        bus_o = EventBus()
        old = EffectPipeline(bus_o, DamageProcessor(bus_o), None).run(caster_o, target_o, action_o)

        # New engine.
        dice.seed_rng(seed)
        caster_n, target_n = _caster(), _target(target_hp, target_ac)
        _wound(target_n, pre_damage_target)
        _wound(caster_n, pre_damage_caster)
        action_n = SpellAction(name="Spell", description="", spell_level=spell_level)
        bus_n = EventBus()
        new = resolve_blocks(caster_n, target_n, action_n, program,
                             event_bus=bus_n, damage_processor=DamageProcessor(bus_n))

        for f in _COMPARED:
            assert getattr(new, f) == getattr(old, f), (
                f"seed {seed}: field {f!r} diverged: new={getattr(new, f)} old={getattr(old, f)}"
            )
        assert target_n.hp == target_o.hp, f"seed {seed}: target HP diverged"
        assert caster_n.hp == caster_o.hp, f"seed {seed}: caster HP diverged"


# ── Fire Bolt: attack cantrip ───────────────────────────────────────────────────

def test_fire_bolt_parity():
    legacy = [
        {"type": "attack_roll", "attack_bonus": "use_caster_bonus"},
        {"type": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": True},
    ]
    program = [
        {"block": "attack_roll", "attack_bonus": "use_caster_bonus"},
        {"block": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": True},
    ]
    assert_parity(legacy, program)


def test_fire_bolt_parity_low_ac_mostly_hits():
    # A low-AC target so most seeds land a hit and exercise the damage path.
    legacy = [
        {"type": "attack_roll", "attack_bonus": "use_caster_bonus"},
        {"type": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": True},
    ]
    program = [
        {"block": "attack_roll", "attack_bonus": "use_caster_bonus"},
        {"block": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": True},
    ]
    assert_parity(legacy, program, target_ac=5)


def test_upcast_scaling_reaches_parity():
    # A damage cantrip-style step with slot scaling, cast above base level.
    legacy = [
        {"type": "attack_roll", "attack_bonus": 5},
        {"type": "damage", "damage_type": "FIRE", "formula": "2d6", "requires_hit": True,
         "scaling": {"per_slot_above": 1, "add_dice": "1d6"}},
    ]
    program = [
        {"block": "attack_roll", "attack_bonus": 5},
        {"block": "damage", "damage_type": "FIRE", "formula": "2d6", "requires_hit": True,
         "scaling": {"per_slot_above": 1, "add_dice": "1d6"}},
    ]
    # Both engines default slot_level to the action's spell_level (=3 here).
    assert_parity(legacy, program, spell_level=3, target_ac=5)


# ── Saving throws: save-for-half and save-negates (single target) ───────────────

def test_save_for_half_parity():
    legacy = [
        {"type": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc"},
        {"type": "damage", "damage_type": "FIRE", "formula": "8d6",
         "save_result": {"on_success": "half_damage"}},
    ]
    program = [
        {"block": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc"},
        {"block": "damage", "damage_type": "FIRE", "formula": "8d6",
         "save_result": {"on_success": "half_damage"}},
    ]
    assert_parity(legacy, program, target_hp=80)


def test_save_negates_parity():
    legacy = [
        {"type": "saving_throw", "attribute": "wisdom", "dc": 14},
        {"type": "damage", "damage_type": "PSYCHIC", "formula": "4d8",
         "save_result": {"on_success": "no_damage"}},
    ]
    program = [
        {"block": "saving_throw", "attribute": "wisdom", "dc": 14},
        {"block": "damage", "damage_type": "PSYCHIC", "formula": "4d8",
         "save_result": {"on_success": "no_damage"}},
    ]
    assert_parity(legacy, program, target_hp=60)


# ── Healing: formula+bonus, and an amount expression from prior damage ──────────

def test_cure_wounds_parity():
    legacy = [
        {"type": "healing", "target": "defender", "formula": "1d8",
         "bonus": "event.caster.spellcasting_modifier"},
    ]
    program = [
        {"block": "healing", "target": "defender", "formula": "1d8",
         "bonus": "event.caster.spellcasting_modifier"},
    ]
    # Wound the target first so the heal has room to apply.
    assert_parity(legacy, program, pre_damage_target=25)


def test_vampiric_heal_from_damage_parity():
    # Attack, deal necrotic, heal the caster for half the damage dealt — the
    # instantaneous part of Vampiric Touch (the concentration rider is a later
    # slice). Exercises the amount expression + condition guard + caster target.
    legacy = [
        {"type": "attack_roll", "attack_bonus": 5},
        {"type": "damage", "damage_type": "NECROTIC", "formula": "3d6", "requires_hit": True},
        {"type": "healing", "target": "caster", "amount": "context.damage_dealt // 2",
         "condition": "context.damage_dealt > 0"},
    ]
    program = [
        {"block": "attack_roll", "attack_bonus": 5},
        {"block": "damage", "damage_type": "NECROTIC", "formula": "3d6", "requires_hit": True},
        {"block": "healing", "target": "caster", "amount": "context.damage_dealt // 2",
         "condition": "context.damage_dealt > 0"},
    ]
    # Low AC so most seeds hit; wound the caster so the self-heal lands.
    assert_parity(legacy, program, target_ac=5, pre_damage_caster=15)


# ── State blocks: condition / modifier / temp-HP (compare entity state) ─────────
#
# The legacy pipeline routes apply_condition/add_modifier through the rule engine
# (BUILTIN_EFFECTS via a synthetic stub event); the new blocks do the work
# directly. Parity is checked on the resulting entity state, not roll outcomes.

def _run_old_state(legacy_steps, *, with_rule_engine=False):
    caster, target = _caster(), _target()
    bus = EventBus()
    engine = RuleEngine(bus) if with_rule_engine else None
    action = SpellAction(name="Spell", description="", spell_level=0,
                         pipeline_effects=legacy_steps)
    EffectPipeline(bus, DamageProcessor(bus), engine).run(caster, target, action)
    return caster, target


def _run_new_state(program_dicts):
    caster, target = _caster(), _target()
    bus = EventBus()
    action = SpellAction(name="Spell", description="", spell_level=0)
    resolve_blocks(caster, target, action, parse_program(program_dicts),
                   event_bus=bus, damage_processor=DamageProcessor(bus))
    return caster, target


def test_grant_temporary_hp_parity():
    legacy = [{"type": "grant_temporary_hp", "target": "defender", "amount": 10}]
    program = [{"block": "grant_temporary_hp", "target": "defender", "amount": 10}]
    _, old_t = _run_old_state(legacy)          # direct in old too; no rule engine
    _, new_t = _run_new_state(program)
    assert new_t.temporary_hp == old_t.temporary_hp == 10


def test_apply_condition_parity():
    legacy = [{"type": "apply_condition", "condition_type": "prone", "target": "defender"}]
    program = [{"block": "apply_condition", "condition_type": "prone", "target": "defender"}]
    _, old_t = _run_old_state(legacy, with_rule_engine=True)
    _, new_t = _run_new_state(program)
    old_types = sorted(c.condition_type.value for c in old_t.get_active_conditions())
    new_types = sorted(c.condition_type.value for c in new_t.get_active_conditions())
    assert new_types == old_types == ["prone"]


def test_add_modifier_parity():
    legacy = [{"type": "add_modifier", "target": "defender", "stat": "ac", "value": 2,
               "source": "Shield of Faith"}]
    program = [{"block": "add_modifier", "target": "defender", "stat": "ac", "value": 2,
                "source": "Shield of Faith"}]
    _, old_t = _run_old_state(legacy, with_rule_engine=True)
    _, new_t = _run_new_state(program)
    # AC modifier applied identically (base 13 + 2 = 15).
    assert new_t.ac == old_t.ac == 15


def test_grant_temp_hp_to_caster_parity():
    legacy = [{"type": "grant_temporary_hp", "target": "caster", "amount": 8}]
    program = [{"block": "grant_temporary_hp", "target": "caster", "amount": 8}]
    old_c, _ = _run_old_state(legacy)
    new_c, _ = _run_new_state(program)
    assert new_c.temporary_hp == old_c.temporary_hp == 8


# ── Corpus parity: real shipped spells the router sends to the new engine ───────

def _spell_file_parity(spell, *, seeds=range(1, 26), target_hp=90, pre_damage_target=35):
    program = to_program(spell.pipeline_effects)
    for seed in seeds:
        dice.seed_rng(seed)
        c1, t1 = _caster(), _target(target_hp)
        _wound(t1, pre_damage_target)
        bus1 = EventBus()
        old = EffectPipeline(bus1, DamageProcessor(bus1), None).run(c1, t1, spell)

        dice.seed_rng(seed)
        c2, t2 = _caster(), _target(target_hp)
        _wound(t2, pre_damage_target)
        bus2 = EventBus()
        new = resolve_blocks(c2, t2, spell, program,
                             event_bus=bus2, damage_processor=DamageProcessor(bus2))

        for f in _COMPARED:
            assert getattr(new, f) == getattr(old, f), (
                f"{spell.name} seed {seed}: {f!r} diverged: "
                f"new={getattr(new, f)} old={getattr(old, f)}"
            )
        assert t1.hp == t2.hp, f"{spell.name} seed {seed}: target HP diverged"
        assert c1.hp == c2.hp, f"{spell.name} seed {seed}: caster HP diverged"


def test_expressible_corpus_spells_reach_parity():
    """Every shipped spell the router accepts must resolve identically on both engines."""
    files = sorted(glob.glob(os.path.join(SPELLS_DIR, "*.json")))
    assert files, "no spell files found"
    tested = []
    for f in files:
        spell = StatBlockLoader.load_spell_from_json(f)
        if can_run_on_blocks(spell):
            _spell_file_parity(spell)
            tested.append(spell.name)
    # Sanity: the router is actually sending a meaningful set to the new engine.
    assert len(tested) >= 6, f"expected several expressible spells, got {tested}"
