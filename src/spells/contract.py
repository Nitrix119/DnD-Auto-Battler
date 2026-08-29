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
        is_gate: True for pre-effect roll/gate blocks (``attack_roll``,
            ``saving_throw``). The evaluator emits ``SPELL_HIT`` just before the
            first non-gate block, matching the legacy pipeline's ordering.
        installs_reactions: True for blocks that subscribe handlers to future
            events (``lifetime``, ``trigger``). The evaluator flushes the pending
            ``DAMAGE_DEALT`` just before the first such block so a rider does not
            fire on its own cast's damage — matching where the legacy pipeline
            emitted ``DAMAGE_DEALT`` (before the first ``add_entity_effect``).
        mutates_event: True for **event-modifier** blocks (``modify_damage`` and
            its siblings) that reach back onto the in-flight ``CombatEvent`` via
            ``Invocation.live_event`` — resistance multipliers, advantage/critical
            flags, ``cancelled``. They are meaningful only when fired inside a
            ``trigger`` (which supplies the live event); run standalone they have
            nothing to mutate and no-op. The distinguishing mark of the one block
            category that changes a live event rather than writing forward state.
    """

    reads: Tuple[str, ...] = ()
    writes: Tuple[str, ...] = ()
    target_arity: TargetArity = TargetArity.SINGLE
    is_gate: bool = False
    installs_reactions: bool = False
    mutates_event: bool = False
