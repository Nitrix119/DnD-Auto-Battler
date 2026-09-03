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
        {"block": "healing", "target": "self", "amount": "context.damage_dealt // 2",
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
            [{"block": "healing", "target": "self",
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


# ── Field kinds and domains ───────────────────────────────────────────────────

class TestFieldKinds:
    """Each declared field states a kind; a value of the wrong shape is an
    authoring error the engine would otherwise crash on or silently ignore."""

    def test_bool_kind_rejects_a_number(self):
        with pytest.raises(ProgramValidationError, match="requires_hit"):
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "1d6",
                  "requires_hit": 4}],
                spell_name="Bad")

    def test_int_kind_rejects_a_string(self):
        with pytest.raises(ProgramValidationError, match="priority"):
            validate_program(
                [{"block": "trigger", "event": "TURN_END", "priority": "high"}],
                spell_name="Bad")

    def test_int_kind_rejects_a_bool(self):
        """True is an int in Python; that must not sneak through."""
        with pytest.raises(ProgramValidationError, match="priority"):
            validate_program(
                [{"block": "trigger", "event": "TURN_END", "priority": True}],
                spell_name="Bad")

    def test_formula_kind_rejects_a_non_formula(self):
        with pytest.raises(ProgramValidationError, match="formula"):
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "1d"}],
                spell_name="Bad")

    def test_enum_kind_rejects_an_unknown_member(self):
        with pytest.raises(ProgramValidationError) as exc:
            validate_program(
                [{"block": "damage", "damage_type": "FIREE", "formula": "1d6"}],
                spell_name="Bad")
        assert "FIREE" in str(exc.value) and "FIRE" in str(exc.value)

    def test_choice_kind_rejects_a_non_choice(self):
        with pytest.raises(ProgramValidationError) as exc:
            validate_program(
                [{"block": "saving_throw", "attribute": "wisdumb", "dc": 15}],
                spell_name="Bad")
        assert "wisdumb" in str(exc.value) and "wisdom" in str(exc.value)

    def test_sentinel_is_accepted_in_place_of_the_kind(self):
        validate_program(
            [{"block": "attack_roll", "attack_bonus": "use_caster_bonus"}],
            spell_name="Fine")
        validate_program(
            [{"block": "saving_throw", "attribute": "dexterity",
              "dc": "use_caster_dc"}],
            spell_name="Fine")

    def test_a_non_sentinel_string_still_fails_an_int_field(self):
        with pytest.raises(ProgramValidationError, match="attack_bonus"):
            validate_program(
                [{"block": "attack_roll", "attack_bonus": "use_caster_bonuss"}],
                spell_name="Bad")

    def test_damage_type_also_accepts_an_expression(self):
        """The one hybrid field: a rider dealing the weapon's own damage type."""
        validate_program(
            [{"block": "trigger", "event": "ATTACK_HIT", "then": [
                {"block": "damage", "formula": "1d8",
                 "damage_type": "event.action.primary_damage_type"}]}],
            spell_name="Colossus")

    def test_resource_choice_rejects_a_typo(self):
        with pytest.raises(ProgramValidationError, match="action"):
            validate_program(
                [{"block": "add_resource", "resource": "action", "amount": 1}],
                spell_name="Bad")


class TestNestedFieldShapes:
    """`save_result`, `scaling` and `grant_action.damage` have internal shapes."""

    def test_save_result_choice_is_checked(self):
        with pytest.raises(ProgramValidationError, match="quarter_damage"):
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "8d6",
                  "save_result": {"on_success": "quarter_damage"}}],
                spell_name="Bad")

    def test_save_result_unknown_subfield_is_rejected(self):
        with pytest.raises(ProgramValidationError, match="on_failure"):
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "8d6",
                  "save_result": {"on_success": "half_damage", "on_failure": "x"}}],
                spell_name="Bad")

    def test_object_kind_rejects_a_scalar(self):
        with pytest.raises(ProgramValidationError, match="save_result"):
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "8d6",
                  "save_result": "half_damage"}],
                spell_name="Bad")

    def test_list_kind_checks_each_entry(self):
        with pytest.raises(ProgramValidationError, match="SLASHNG"):
            validate_program(
                [{"block": "grant_action", "name": "Bite",
                  "damage": [{"type": "SLASHNG", "formula": "1d6"}]}],
                spell_name="Bad")

    def test_list_kind_rejects_a_non_list(self):
        with pytest.raises(ProgramValidationError, match="damage"):
            validate_program(
                [{"block": "grant_action", "name": "Bite",
                  "damage": {"type": "SLASHING", "formula": "1d6"}}],
                spell_name="Bad")

    def test_a_valid_nested_shape_passes(self):
        validate_program(
            [{"block": "grant_action", "name": "Bite",
              "damage": [{"type": "PIERCING", "formula": "1d6"}]}],
            spell_name="Fine")


# ── Expressions ───────────────────────────────────────────────────────────────

class TestExpressionArgs:
    """An expression arg is only evaluated at cast (or fire) time, and inside a
    trigger guard a failure is swallowed as "did not fire" — so a broken one must
    be caught at load or it is invisible."""

    def test_syntax_error_raises(self):
        with pytest.raises(ProgramValidationError, match="condition"):
            validate_program(
                [{"block": "cancel", "condition": "event.total >"}],
                spell_name="Bad")

    def test_banned_node_raises(self):
        """The sandbox forbids lambdas, comprehensions and the like."""
        with pytest.raises(ProgramValidationError):
            validate_program(
                [{"block": "cancel", "condition": "[x for x in (1, 2)]"}],
                spell_name="Bad")

    def test_disallowed_call_raises(self):
        with pytest.raises(ProgramValidationError):
            validate_program(
                [{"block": "cancel", "condition": "open('/etc/passwd')"}],
                spell_name="Bad")

    def test_unknown_root_name_raises(self):
        """`caster` is not in the namespace — `entity` is. A NameError at run time."""
        with pytest.raises(ProgramValidationError) as exc:
            validate_program(
                [{"block": "grant_temporary_hp", "amount": "caster.level * 2"}],
                spell_name="Bad")
        assert "caster" in str(exc.value)

    def test_known_roots_pass(self):
        validate_program(
            [{"block": "grant_temporary_hp",
              "amount": "max(1, context.damage_dealt // 2)"}],
            spell_name="Fine")
        validate_program(
            [{"block": "cancel", "condition": "entity.hp > 0"}], spell_name="Fine")

    def test_a_plain_number_is_accepted_for_an_expression_field(self):
        validate_program(
            [{"block": "grant_temporary_hp", "amount": 5}], spell_name="Fine")

    def test_binding_values_are_checked_as_expressions(self):
        with pytest.raises(ProgramValidationError, match="charmerr|caster"):
            validate_program(
                [{"block": "trigger", "event": "ATTACK_DECLARED",
                  "bindings": {"charmer": "caster.self"}, "then": []}],
                spell_name="Bad")


# ── `then` where nothing runs it ──────────────────────────────────────────────

class TestThenPlacement:
    """Only for_each_target / lifetime / trigger execute a `then`. Anywhere else
    the sub-program is silently dead."""

    def test_then_on_a_leaf_block_raises(self):
        with pytest.raises(ProgramValidationError) as exc:
            validate_program(
                [{"block": "damage", "damage_type": "FIRE", "formula": "1d6",
                  "then": [{"block": "cancel"}]}],
                spell_name="Bad")
        msg = str(exc.value)
        assert "then" in msg and "damage" in msg

    def test_then_is_fine_on_the_blocks_that_run_it(self):
        validate_program(
            [{"block": "for_each_target", "then": [
                {"block": "lifetime", "then": [
                    {"block": "trigger", "event": "TURN_START", "then": [
                        {"block": "cancel"}]}]}]}],
            spell_name="Fine")

    def test_an_empty_then_on_a_leaf_block_is_still_rejected(self):
        """`then: []` is as dead as a populated one, and just as misleading."""
        with pytest.raises(ProgramValidationError, match="then"):
            validate_program(
                [{"block": "cancel", "then": []}], spell_name="Bad")
