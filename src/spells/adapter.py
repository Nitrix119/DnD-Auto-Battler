"""Legacy-shape → block-program adapter, and the router's capability check.

Transitional (removed in Phase 3). Reads a legacy ``effects`` list — step dicts
keyed by ``type`` — as a block ``program`` (blocks are keyed by ``block``), so an
instantaneous legacy spell runs on the new engine without being rewritten. An
``add_entity_effect`` step is folded into a ``lifetime`` block via :mod:`.fold`
(§4.3b). ``can_run_on_blocks`` is the check ``SpellResolver`` uses to decide which
engine handles a spell.

A ``rule_lookup`` (``name -> Rule | None``) resolves the entity-effect rule an
``add_entity_effect`` step references, so foldability accounts for reactive
triggers the fold does not yet handle. Without it, ``add_entity_effect`` steps are
treated as un-foldable (the spell stays on legacy).
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from src.models.spell_properties import TargetingType

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from . import fold
from .block import Block
from .registry import REGISTRY

RuleLookup = Optional[Callable[[str], Any]]

# Targeting types whose fan-out is a target *set* — the adapter wraps their steps
# in an implicit ``for_each_target`` so the arity rule holds uniformly (§4.1).
_SET_TARGETING = (TargetingType.AOE, TargetingType.MULTI_TARGET)


def _step_to_block(step: dict, rule_lookup: RuleLookup) -> Block:
    if fold.is_add_entity_effect(step):
        rule = rule_lookup(step.get("entity_effect_name", "")) if rule_lookup else None
        return Block.from_dict(fold.to_lifetime_block(step, rule))
    return Block(type=step["type"], args={k: v for k, v in step.items() if k != "type"})


def to_program(
    effects: List[dict],
    targeting_type: Any = None,
    rule_lookup: RuleLookup = None,
) -> List[Block]:
    """Adapt a legacy ``effects`` step-dict list into a block program.

    Single-target spells become a flat per-target program. Set-targeted spells
    (AoE, multi-target) are wrapped in an implicit ``for_each_target`` iterator so
    fan-out lives in the program and the target-arity rule holds uniformly — the
    iterator owns the shared ``roll_once`` roll. ``add_entity_effect`` steps fold
    into a ``lifetime`` block (see :mod:`.fold`).
    """
    blocks = [_step_to_block(s, rule_lookup) for s in (effects or [])]
    if targeting_type in _SET_TARGETING:
        return [Block(type="for_each_target", args={}, then=tuple(blocks))]
    return blocks


def can_run_on_blocks(action: Any, rule_lookup: RuleLookup = None) -> bool:
    """True if the new engine can resolve *action* identically to the legacy one.

    Scope: single-target, AoE, and multi-target spells whose every step is either
    a ported block or a **foldable** ``add_entity_effect`` (§4.3b — its ``on_apply``
    grants map to state blocks and its referenced rule declares no reactive
    triggers yet). Anything else — an unported step, an un-foldable persistent
    effect, an unsupported targeting type — stays on the legacy engine.
    """
    steps = getattr(action, "pipeline_effects", None) or []
    if not steps:
        return False
    targeting = getattr(action, "targeting_type", None)
    if targeting != TargetingType.SINGLE_TARGET and targeting not in _SET_TARGETING:
        return False
    ported = REGISTRY.types()
    for step in steps:
        if fold.is_add_entity_effect(step):
            name = step.get("entity_effect_name", "")
            rule = rule_lookup(name) if rule_lookup else None
            if not fold.foldable(step, rule):
                return False
        elif step.get("type") not in ported:
            return False
    return True
