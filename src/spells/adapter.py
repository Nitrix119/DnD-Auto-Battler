"""Legacy-shape → block-program adapter, and the router's capability check.

Transitional (removed in Phase 3). Reads a legacy ``effects`` list — step dicts
keyed by ``type`` — as a block ``program`` (blocks are keyed by ``block``), so an
instantaneous legacy spell runs on the new engine without being rewritten.
``can_run_on_blocks`` is the check ``SpellResolver`` uses to decide which engine
handles a spell.
"""

from __future__ import annotations

from typing import Any, List

from src.models.spell_properties import TargetingType

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .block import Block
from .registry import REGISTRY

# Targeting types whose fan-out is a target *set* — the adapter wraps their steps
# in an implicit ``for_each_target`` so the arity rule holds uniformly (§4.1).
_SET_TARGETING = (TargetingType.AOE, TargetingType.MULTI_TARGET)


def _flat_blocks(effects: List[dict]) -> List[Block]:
    return [
        Block(type=s["type"], args={k: v for k, v in s.items() if k != "type"})
        for s in (effects or [])
    ]


def to_program(effects: List[dict], targeting_type: Any = None) -> List[Block]:
    """Adapt a legacy ``effects`` step-dict list into a block program.

    Single-target spells become a flat per-target program. Set-targeted spells
    (AoE, multi-target) are wrapped in an implicit ``for_each_target`` iterator so
    fan-out lives in the program and the target-arity rule holds uniformly — the
    iterator owns the shared ``roll_once`` roll.
    """
    flat = _flat_blocks(effects)
    if targeting_type in _SET_TARGETING:
        return [Block(type="for_each_target", args={}, then=tuple(flat))]
    return flat


def can_run_on_blocks(action: Any) -> bool:
    """True if the new engine can resolve *action* identically to the legacy one.

    Phase-2 (§4.1) scope: single-target, AoE, and multi-target spells whose every
    step is a ported block. Fan-out and ``roll_once`` sharing now live in the
    ``for_each_target`` iterator, so AoE/multi-target are accepted. Anything using
    an unported step (e.g. ``add_entity_effect``) or a non-set/SINGLE targeting
    type stays on the legacy engine until its Phase-2 blocks land.
    """
    steps = getattr(action, "pipeline_effects", None) or []
    if not steps:
        return False
    targeting = getattr(action, "targeting_type", None)
    if targeting != TargetingType.SINGLE_TARGET and targeting not in _SET_TARGETING:
        return False
    ported = REGISTRY.types()
    return all(step.get("type") in ported for step in steps)
