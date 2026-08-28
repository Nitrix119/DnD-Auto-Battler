"""Static arity check for block programs.

Every block declares a :class:`~src.spells.contract.TargetArity`; the linter walks
a program tracking whether the *current target* is a single entity or a set, and
turns "damage a list of targets" into a load-time category error rather than a
silent degrade (build plan §3.6 D1).

The rule (design §3.6 D1):

- A **SET** block (an iterator such as ``for_each_target``) requires a set to
  consume; inside its ``then`` the current target is a single element.
- A **SINGLE** block requires a single current target — reaching one while the
  current target is still a set is the error the whole arity system exists to
  catch.
- A **CASTER** block acts on the caster regardless of the current target, so it is
  valid under either cardinality.

The evaluator runs this before resolving (a runtime assertion); it is also the
load-time gate content validation calls as spells migrate to ``program`` form.
"""

from __future__ import annotations

from typing import Sequence

from .block import Block
from .contract import TargetArity
from .registry import BlockRegistry, REGISTRY


class ProgramArityError(ValueError):
    """A block program violates the target-arity rules (a category error)."""


def lint_program(
    program: Sequence[Block],
    *,
    target_is_set: bool,
    registry: BlockRegistry = REGISTRY,
) -> None:
    """Validate *program* under the given current-target cardinality.

    Args:
        program: the blocks to check (a program or a ``then`` sub-program).
        target_is_set: True if the current target is a set at this point (the top
            level of an AoE/multi-target program), False if it is a single entity.

    Raises:
        ProgramArityError: a single-target block is reached under a set current
            target, or a set-consuming block is reached with no set to consume.
    """
    for block in program:
        arity = registry.get(block.type).contract.target_arity

        if arity is TargetArity.SET:
            if not target_is_set:
                raise ProgramArityError(
                    f"block {block.type!r} consumes a target set but the current "
                    f"target is a single entity — it has no set to iterate."
                )
            # An iterator reduces the set to one element for its `then` body.
            lint_program(block.then, target_is_set=False, registry=registry)
        elif arity is TargetArity.SINGLE:
            if target_is_set:
                raise ProgramArityError(
                    f"block {block.type!r} is single-target but the current target "
                    f"is a set — wrap it in an iterator (e.g. for_each_target)."
                )
            lint_program(block.then, target_is_set=False, registry=registry)
        else:  # CASTER — valid under either cardinality.
            lint_program(block.then, target_is_set=False, registry=registry)
