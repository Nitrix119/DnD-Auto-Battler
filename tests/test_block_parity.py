"""Parity harness: the new block evaluator vs the legacy pipeline (Phase 1).

The gate for the rewrite: for a given spell and seed, the new evaluator must
produce the *same* observable outcome as the old ``EffectPipeline`` — same hit,
same rolls, same damage, same resulting HP. This harness runs both engines under
one seed on fresh, identical entities and asserts they agree, across many seeds.

Slice 2 ports ``attack_roll`` + ``damage``; Fire Bolt (attack cantrip) is the
first spell proven at parity. Later slices extend the ported blocks and add
spells to ``PARITY_SPELLS``.
"""

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.effect_pipeline import EffectPipeline
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks
from src.utils import dice


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
    "hit", "damage_dealt", "save_success", "save_roll", "save_dc",
    "attack_roll", "attack_total", "critical_hit", "critical_miss",
    "had_advantage", "had_disadvantage",
)


def assert_parity(legacy_steps, program_dicts, *, seeds=range(1, 41),
                  spell_level=0, target_hp=40, target_ac=13):
    """Run the same spell on both engines under each seed; assert identical."""
    program = parse_program(program_dicts)
    for seed in seeds:
        # Legacy engine.
        dice.seed_rng(seed)
        caster_o, target_o = _caster(), _target(target_hp, target_ac)
        action_o = SpellAction(name="Spell", description="", spell_level=spell_level,
                               pipeline_effects=legacy_steps)
        bus_o = EventBus()
        old = EffectPipeline(bus_o, DamageProcessor(bus_o), None).run(caster_o, target_o, action_o)

        # New engine.
        dice.seed_rng(seed)
        caster_n, target_n = _caster(), _target(target_hp, target_ac)
        action_n = SpellAction(name="Spell", description="", spell_level=spell_level)
        bus_n = EventBus()
        new = resolve_blocks(caster_n, target_n, action_n, program,
                             event_bus=bus_n, damage_processor=DamageProcessor(bus_n))

        for f in _COMPARED:
            assert getattr(new, f) == getattr(old, f), (
                f"seed {seed}: field {f!r} diverged: new={getattr(new, f)} old={getattr(old, f)}"
            )
        assert target_n.hp == target_o.hp, f"seed {seed}: HP diverged"


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
