"""Iterator blocks — fan a ``then`` sub-program over a target set.

``for_each_target`` is where all spell fan-out lives in the new engine: AoE and
multi-target casts are one iterator wrapping the per-target program, replacing the
loop that used to sit in ``SpellResolver``. The iterator owns the set (from the
root invocation), runs its ``then`` body once per element against a fresh child
invocation (rebinding the current target), and collects one result each.

``roll_once`` (deviation #5 in the Phase-2 plan) is an iterator property, not a
``damage`` property: an AoE shares *one* rolled total across every target (Fireball
rolls 8d6 once). The iterator pre-rolls each ``roll_once`` damage block in its
``then`` body a single time — with slot scaling, exactly as the legacy pre-roll did
— and seeds every child invocation with the shared totals (keyed by ``id(block)``).
The ``damage`` block only *consumes* that seed; the sharing is here.
"""

from __future__ import annotations

from typing import Dict, List

from src.utils.dice import roll_formula

from ..scaling import effective_damage_formula

from ..contract import BlockContract, TargetArity
from ..context import Invocation
from ..block import Block
from ..registry import REGISTRY
from ..runner import run_target


def _preroll_shared(then: List[Block], slot_level) -> Dict[int, int]:
    """Roll each ``roll_once`` damage block in *then* once; key by ``id(block)``.

    Only top-level ``then`` blocks are scanned, matching the legacy pre-roll which
    seeded top-level steps. The result seeds every element's invocation so an AoE
    deals the same rolled total to each target.
    """
    seed: Dict[int, int] = {}
    for b in then:
        if b.type == "damage" and b.get("roll_once"):
            formula = effective_damage_formula(
                {"formula": b.get("formula", ""), "scaling": b.get("scaling")},
                slot_level,
            )
            seed[id(b)] = roll_formula(formula) if formula else 0
    return seed


def for_each_target(block: Block, inv: Invocation) -> None:
    """Run ``then`` once per target in the set, collecting a result per element.

    Reads the set from the root invocation's ``targets`` and appends each
    element's :class:`~src.spells.context.InvocationResult` to ``results``.
    """
    then = list(block.then)
    shared_rolls = _preroll_shared(then, inv.slot_level)

    for element in inv.targets:
        child = inv.child(target=element, shared_rolls=shared_rolls)
        inv.results.append(run_target(child, then))


REGISTRY.register(
    "for_each_target",
    for_each_target,
    BlockContract(target_arity=TargetArity.SET, consumes_then=True),
)
