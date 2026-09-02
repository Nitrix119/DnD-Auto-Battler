"""Load-time validation of native block programs (``validate_program``).

The single loader-boundary gate: every spell, weapon program and rule passes through
it. These pin the unhappy paths a hand- or LLM-authored program must fail loudly on at
load time rather than silently at cast: an unknown block, a missing required arg, a
target-arity category error, a malformed block, a ``context.X`` reference to a key
nothing writes, an ``event.<field>`` a trigger cannot carry, or a malformed
``scaling``.
"""

import pytest

from src.spells.validate import validate_program, ProgramValidationError


# ── Happy paths ─────────────────────────────────────────────────────────────────

def test_valid_single_target_program_passes():
    program = [
        {"block": "attack_roll", "attack_bonus": "use_caster_bonus"},
        {"block": "damage", "damage_type": "FIRE",
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
        {"block": "damage", "damage_type": "NECROTIC",
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


# ── Unknown args ──────────────────────────────────────────────────────────────

class TestUnknownArgs:
    """An arg no block declares is silently ignored at run time — the worst
    outcome for an author, so it must fail at load (CLAUDE.md §2.5)."""

    def test_unknown_arg_raises(self):
        with pytest.raises(ProgramValidationError) as exc:
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "1d6",
                  "wibble": 3}],
                spell_name="Typo")
        msg = str(exc.value)
        assert "wibble" in msg and "Typo" in msg and "damage" in msg

    def test_typo_suggests_the_real_arg(self):
        with pytest.raises(ProgramValidationError) as exc:
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "fomula": "1d6"}],
                spell_name="Typo")
        assert "did you mean 'formula'" in str(exc.value)

    def test_error_lists_the_valid_args(self):
        with pytest.raises(ProgramValidationError) as exc:
            validate_program([{"block": "cancel", "nope": 1}], spell_name="Typo")
        assert "condition" in str(exc.value)  # cancel takes only the universal arg

    def test_universal_condition_arg_is_accepted_everywhere(self):
        validate_program(
            [{"block": "cancel", "condition": "context.hit"}], spell_name="Fine")

    def test_underscore_prefixed_keys_are_allowed_as_commentary(self):
        validate_program(
            [{"block": "damage", "damage_type": "FIRE", "formula": "1d6",
              "_note": "halved on a save; PHB p.241", "_todo": "upcast"}],
            spell_name="Commented")

    def test_unknown_arg_is_caught_inside_a_nested_then(self):
        with pytest.raises(ProgramValidationError, match="wibble"):
            validate_program(
                [{"block": "for_each_target", "then": [
                    {"block": "damage", "damage_type": "FIRE", "formula": "1d6",
                     "wibble": 1}]}],
                spell_name="Nested")

    def test_a_real_arg_on_the_wrong_block_is_rejected(self):
        """`formula` is a damage arg; apply_condition does not take one."""
        with pytest.raises(ProgramValidationError, match="formula"):
            validate_program(
                [{"block": "apply_condition", "condition_type": "blinded",
                  "formula": "1d6"}],
                spell_name="Confused")
