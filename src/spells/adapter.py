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

from . import blocks as _blocks  # noqa: F401  (ensures the block catalogue is registered)
from .block import Block
from .registry import REGISTRY


def to_program(effects: List[dict]) -> List[Block]:
    """Adapt a legacy ``effects`` step-dict list into a block program (flat)."""
    return [
        Block(type=s["type"], args={k: v for k, v in s.items() if k != "type"})
        for s in (effects or [])
    ]


def can_run_on_blocks(action: Any) -> bool:
    """True if the new engine can resolve *action* identically to the legacy one.

    Phase 1 scope: single-target spells whose every step is a ported block and
    which use no ``roll_once`` (AoE) seeding. AoE, multi_target, add_entity_effect
    and anything else stay on the legacy engine until their Phase-2 blocks land.
    """
    steps = getattr(action, "pipeline_effects", None) or []
    if not steps:
        return False
    if getattr(action, "targeting_type", None) != TargetingType.SINGLE_TARGET:
        return False
    ported = REGISTRY.types()
    for step in steps:
        if step.get("type") not in ported:
            return False
        if step.get("roll_once"):
            return False
    return True
