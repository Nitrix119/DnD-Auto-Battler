"""Target-arity linting for block programs (Phase 2, §4.1).

The arity rule turns "damage a list of targets" into a load-time category error:
a SINGLE block reached while the current target is a set is rejected; a set
consumer (``for_each_target``) reduces the set to one element for its ``then``
body. See :mod:`src.spells.lint`.
"""

import pytest

from src.spells.block import parse_program
from src.spells.lint import lint_program, ProgramArityError


def _prog(dicts):
    return parse_program(dicts)


class TestArityLint:

    def test_single_program_at_single_cardinality_ok(self):
        prog = _prog(
            [
                {"block": "attack_roll", "attack_bonus": 5},
                {"block": "damage", "formula": "1d10", "damage_type": "FIRE"},
            ]
        )
        lint_program(prog, target_is_set=False)  # must not raise

    def test_single_block_under_set_is_rejected(self):
        # A bare damage block with the current target still a set — the category
        # error the arity system exists to catch.
        prog = _prog([{"block": "damage", "formula": "8d6", "damage_type": "FIRE"}])
        with pytest.raises(ProgramArityError):
            lint_program(prog, target_is_set=True)

    def test_iterator_consumes_the_set_and_body_is_single(self):
        prog = _prog(
            [
                {
                    "block": "for_each_target",
                    "then": [
                        {"block": "saving_throw", "attribute": "dexterity", "dc": 15},
                        {
                            "block": "damage",
                            "formula": "8d6",
                            "damage_type": "FIRE",
                            "roll_once": True,
                            "save_result": {"on_success": "half_damage"},
                        },
                    ],
                }
            ]
        )
        lint_program(prog, target_is_set=True)  # must not raise

    def test_iterator_with_no_set_to_consume_is_rejected(self):
        prog = _prog(
            [
                {
                    "block": "for_each_target",
                    "then": [
                        {"block": "damage", "formula": "1d6", "damage_type": "FIRE"}
                    ],
                }
            ]
        )
        with pytest.raises(ProgramArityError):
            lint_program(prog, target_is_set=False)

    def test_single_block_inside_iterator_body_is_ok(self):
        # Same single blocks that fail bare at set cardinality are fine once the
        # iterator has reduced the set.
        prog = _prog(
            [
                {
                    "block": "for_each_target",
                    "then": [
                        {"block": "damage", "formula": "2d6", "damage_type": "FIRE"}
                    ],
                }
            ]
        )
        lint_program(prog, target_is_set=True)
