"""Load-time validation of native block programs (``validate_program``).

The ``program`` counterpart of ``test_step_schema.py`` (which covers the legacy
``effects`` validator). These pin the unhappy paths a hand- or LLM-authored
program must fail loudly on at load time rather than silently at cast: an unknown
block, a missing required arg, a target-arity category error, a malformed block, or
a ``context.X`` reference to a key nothing writes.
"""

import pytest

from src.spells.validate import validate_program, ProgramValidationError


# ── Happy paths ─────────────────────────────────────────────────────────────────

def test_valid_single_target_program_passes():
    program = [
        {"block": "attack_roll", "attack_bonus": "use_caster_bonus", "target": "defender"},
        {"block": "damage", "target": "defender", "damage_type": "FIRE",
         "formula": "1d10", "requires_hit": True},
    ]
    assert [b.type for b in validate_program(program, spell_name="Fire Bolt")] == [
        "attack_roll", "damage",
    ]


def test_valid_aoe_program_with_iterator_passes():
    program = [{
        "block": "for_each_target",
        "then": [
            {"block": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc"},
            {"block": "damage", "damage_type": "FIRE", "formula": "8d6",
             "roll_once": True, "save_result": {"on_success": "half_damage"}},
        ],
    }]
    validate_program(program, spell_name="Fireball")  # does not raise


def test_context_ref_to_a_written_key_passes():
    # ``damage_dealt`` is a real context key a damage block writes.
    program = [
        {"block": "damage", "target": "defender", "damage_type": "NECROTIC",
         "formula": "3d6"},
        {"block": "healing", "target": "caster", "amount": "context.damage_dealt // 2",
         "condition": "context.damage_dealt > 0"},
    ]
    validate_program(program, spell_name="Drain")  # does not raise


# ── Unhappy paths ───────────────────────────────────────────────────────────────

def test_unknown_block_type_raises():
    with pytest.raises(ProgramValidationError, match="unknown block type 'zap'"):
        validate_program([{"block": "zap"}], spell_name="Bad")


def test_missing_required_arg_raises():
    # A damage block with no ``formula`` is an authoring error, not a silent zero.
    with pytest.raises(ProgramValidationError, match="missing required arg"):
        validate_program(
            [{"block": "damage", "damage_type": "FIRE"}], spell_name="Bad")


def test_bad_context_ref_raises():
    with pytest.raises(ProgramValidationError, match=r"context\.dammage_dealt"):
        validate_program(
            [{"block": "healing", "target": "caster",
              "formula": "context.dammage_dealt"}],  # typo
            spell_name="Bad")


def test_single_block_at_set_cardinality_raises():
    # A bare single-target block beside an iterator — the arity category error.
    program = [
        {"block": "for_each_target",
         "then": [{"block": "damage", "damage_type": "FIRE", "formula": "1d6"}]},
        {"block": "damage", "damage_type": "FIRE", "formula": "1d6"},
    ]
    with pytest.raises(ProgramValidationError):
        validate_program(program, spell_name="Bad")


def test_malformed_block_missing_type_key_raises():
    with pytest.raises(ProgramValidationError):
        validate_program([{"attack_bonus": 5}], spell_name="Bad")


def test_program_must_be_a_list():
    with pytest.raises(ProgramValidationError):
        validate_program({"block": "damage"}, spell_name="Bad")
