"""Block-engine resolution tests (formerly the legacy-parity harness).

The block evaluator is now the only engine, so these are block-only: the state
blocks pin their outcomes directly, the iterator proves the shared-roll property,
the arity guard fires on a malformed set program, and a corpus smoke test resolves
every expressible shipped spell on the block engine. Roll-outcome coverage (attack,
save-for-half, upcast, AoE fan-out) lives in `test_attack_parity.py`,
`test_critical_hits.py`, `test_save_outcomes.py`, `test_upcasting.py`,
`test_multi_target.py`, `test_aoe_casting.py`, and `test_spells.py`.
"""

import glob
import os

import pytest

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.models.damage import Damage, DamageType
from src.models.spell_properties import TargetingType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.loaders import StatBlockLoader
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks
from src.spells.evaluator import resolve_program
from src.utils import dice

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


# ── Fixtures ─────────────────────────────────────────────────────────────────

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


def _run_state(program_dicts):
    caster, target = _caster(), _target()
    bus = EventBus()
    action = SpellAction(name="Spell", description="", spell_level=0)
    resolve_blocks(caster, target, action, parse_program(program_dicts),
                   event_bus=bus, damage_processor=DamageProcessor(bus))
    return caster, target


# ── State blocks: condition / modifier / temp-HP (assert entity state) ──────────

def test_grant_temporary_hp_to_defender():
    _, target = _run_state(
        [{"block": "grant_temporary_hp", "target": "current", "amount": 10}])
    assert target.temporary_hp == 10


def test_grant_temporary_hp_to_caster():
    caster, _ = _run_state(
        [{"block": "grant_temporary_hp", "target": "self", "amount": 8}])
    assert caster.temporary_hp == 8


def test_apply_condition_adds_the_marker():
    _, target = _run_state(
        [{"block": "apply_condition", "condition_type": "prone", "target": "current"}])
    assert sorted(c.condition_type.value for c in target.get_active_conditions()) == ["prone"]


def test_add_modifier_changes_the_stat():
    _, target = _run_state([{"block": "add_modifier", "target": "current", "stat": "ac",
                             "value": 2, "source": "Shield of Faith"}])
    assert target.ac == 15  # base 13 + 2


# ── Iterator: shared roll + arity guard (block-only behaviour proofs) ───────────

def test_iterator_shares_one_roll_across_targets():
    """A ``roll_once`` AoE deals the *same* rolled total to every target.

    With every target failing its save (an impossible DC), each takes the full
    shared total, so all damage_dealt values are identical — the defining property
    of the shared roll.
    """
    program = parse_program([{
        "block": "for_each_target",
        "then": [
            {"block": "saving_throw", "attribute": "dexterity", "dc": 999},
            {"block": "damage", "damage_type": "FIRE", "formula": "8d6",
             "roll_once": True, "save_result": {"on_success": "half_damage"}},
        ],
    }])
    dice.seed_rng(7)
    caster = _caster()
    targets = [_target(200) for _ in range(5)]
    action = SpellAction(name="Boom", description="", spell_level=3)
    bus = EventBus()
    results = resolve_program(caster, targets, action, program,
                              event_bus=bus, damage_processor=DamageProcessor(bus))
    dealt = {r.damage_dealt for r in results}
    assert len(dealt) == 1, f"targets took differing damage: {dealt}"
    assert dealt.pop() > 0


def test_resolve_program_rejects_single_block_beside_iterator():
    """The runtime arity assertion fires on a malformed set program."""
    from src.spells.lint import ProgramArityError

    program = parse_program([
        {"block": "for_each_target",
         "then": [{"block": "damage", "formula": "1d6", "damage_type": "FIRE"}]},
        # A bare single-target block at set cardinality — the category error.
        {"block": "damage", "formula": "1d6", "damage_type": "FIRE"},
    ])
    action = SpellAction(name="Bad", description="", spell_level=0)
    bus = EventBus()
    with pytest.raises(ProgramArityError):
        resolve_program(_caster(), [_target()], action, program,
                        event_bus=bus, damage_processor=DamageProcessor(bus))


# ── Corpus smoke: every expressible shipped spell resolves on the block engine ──

def _corpus_program(spell):
    """The block program for a shipped spell.

    Every spell carries one (the loader rejects a spell without), so this is just
    ``parse_program`` — kept as a named helper so the two corpus smoke tests read
    the same way.
    """
    return parse_program(spell.program)


def test_single_target_corpus_resolves_on_blocks():
    """Every shipped single-target instantaneous spell resolves without error and
    returns a result — a regression net against a spell that stops resolving."""
    files = sorted(glob.glob(os.path.join(SPELLS_DIR, "*.json")))
    assert files, "no spell files found"
    tested = []
    for f in files:
        spell = StatBlockLoader.load_spell_from_json(f)
        program = _corpus_program(spell)
        if program is not None and spell.targeting_type == TargetingType.SINGLE_TARGET:
            dice.seed_rng(7)
            caster, target = _caster(), _target(90)
            target.take_damage(Damage(DamageType.GENERIC, 35))  # room to hit/heal
            bus = EventBus()
            result = resolve_blocks(caster, target, spell, program,
                                    event_bus=bus, damage_processor=DamageProcessor(bus))
            assert result.hit in (True, False)
            tested.append(spell.name)
    assert len(tested) >= 6, f"expected several expressible spells, got {tested}"


def test_set_targeted_corpus_resolves_on_blocks():
    """Every AoE/multi-target shipped spell resolves to one result per defender."""
    files = sorted(glob.glob(os.path.join(SPELLS_DIR, "*.json")))
    tested = []
    for f in files:
        spell = StatBlockLoader.load_spell_from_json(f)
        program = _corpus_program(spell)
        if program is not None and spell.targeting_type in (
            TargetingType.AOE, TargetingType.MULTI_TARGET
        ):
            dice.seed_rng(7)
            caster = _caster()
            targets = [_target(90) for _ in range(4)]
            bus = EventBus()
            results = resolve_program(caster, targets, spell, program,
                                      event_bus=bus, damage_processor=DamageProcessor(bus),
                                      slot_level=spell.spell_level)
            assert len(results) == 4
            tested.append(spell.name)
    assert len(tested) >= 6, f"expected AoE+multi_target spells, got {tested}"
