"""Block contracts — what a block reads, writes, and how it addresses targets.

Every block type registers a :class:`BlockContract` alongside its handler. The
contract is the single source of truth used by (a) the linter, to validate a
program before it runs, and (b) the evaluator, to know each block's shape. It
generalises the stage-1 ``STEP_SCHEMAS`` (context reads/writes) with the target
**arity** that makes "damage a list of targets" an unrepresentable category
error rather than a silent degrade (build plan §3.6 D1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class TargetArity(Enum):
    """How a block relates to the evaluator's *current target*.

    - ``SINGLE``: acts on the current target, which must be exactly one entity
      (``damage``, ``attack_roll``, ``saving_throw``, ``apply_condition``, …).
      Reaching a SINGLE block while the current target is a *set* is an error.
    - ``CASTER``: acts on the caster regardless of the current target
      (heal-self, grant-temp-HP-to-caster).
    - ``SET``: consumes a target set — iterator blocks (``for_each_target``) that
      rebind the current target per element for their ``then`` sub-program, or a
      rare aggregate that genuinely operates over the whole set.
    """

    SINGLE = "single"
    CASTER = "caster"
    SET = "set"


@dataclass(frozen=True)
class BlockContract:
    """The declared contract for one block type.

    Args:
        reads: context keys the block may read (for the linter's flow check).
        writes: context keys the block writes.
        target_arity: how the block addresses targets (see :class:`TargetArity`).
    """

    reads: Tuple[str, ...] = ()
    writes: Tuple[str, ...] = ()
    target_arity: TargetArity = TargetArity.SINGLE
