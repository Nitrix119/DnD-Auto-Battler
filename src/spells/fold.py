"""Fold a legacy ``add_entity_effect`` step into a ``lifetime`` block program.

Transitional (removed in Phase 3, when persistent effects are authored as a
``program`` directly). The legacy shape splits a persistent effect across two
files — the spell's ``add_entity_effect`` step (its ``on_apply`` immediate grants
+ concentration flag) and a separate entity-effect **rule** in
``rules/entity_effects/`` (its reactive ``triggers`` + ``effects`` + duration).
This module reunites them into one ``lifetime{ … }`` block:

- ``on_apply`` grants → **state blocks** (``add_modifier`` / ``apply_condition`` /
  ``grant_temporary_hp`` / ``healing`` / ``damage``), owned by the scope.
- the rule's reactive ``triggers`` → **trigger blocks** (§4.3b-2 — not yet folded;
  a rule that declares any trigger is currently reported un-foldable so it stays
  on the legacy engine).
- ``concentration`` / a rounds duration → the ``lifetime`` **kind**.

``foldable`` is the routing gate's check (does this step translate cleanly?);
``to_lifetime_block`` is the translation. Both take the referenced ``rule`` (or
``None`` when it cannot be resolved) so foldability accounts for reactive triggers
we do not yet handle.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Legacy effect target expressions → a state block's ``target`` keyword.
_TARGET_EXPR_TO_BLOCK = {"event.caster": "caster", "event.defender": "defender"}


def _target(legacy_target: Optional[str]) -> str:
    return _TARGET_EXPR_TO_BLOCK.get(legacy_target or "", "defender")


def _add_modifier(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "block": "add_modifier",
        "target": _target(eff.get("target")),
        "stat": eff.get("stat", ""),
        "value": eff.get("value", 0),
        "source": eff.get("source", ""),
        "effect_name": eff.get("effect_name", ""),
    }


def _apply_condition(eff: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "block": "apply_condition",
        "target": _target(eff.get("target")),
        "condition_type": eff.get("condition_type", ""),
        "source": eff.get("source", ""),
        "effect_name": eff.get("effect_name", ""),
    }
    if eff.get("duration") is not None:
        out["duration"] = eff["duration"]
    return out


def _grant_temporary_hp(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "block": "grant_temporary_hp",
        "target": _target(eff.get("target")),
        "amount": eff.get("amount", 0),
    }


def _healing(eff: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "block": "healing",
        "target": _target(eff.get("target")),
        "formula": eff.get("formula", "0"),
    }
    if eff.get("bonus") is not None:
        out["bonus"] = eff["bonus"]
    return out


def _damage(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "block": "damage",
        "target": _target(eff.get("target")),
        "damage_type": eff.get("damage_type", "GENERIC"),
        "formula": eff.get("formula", "0"),
    }


# Legacy BUILTIN_EFFECTS action → state-block translator. Actions absent here
# (AddResource, GrantAction, RemoveEffect, …) are not yet foldable — the spells
# that use them stay on the legacy engine until a later slice adds their blocks.
_ACTION_TO_BLOCK: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "AddModifier": _add_modifier,
    "ApplyCondition": _apply_condition,
    "GrantTemporaryHP": _grant_temporary_hp,
    "HealTarget": _healing,
    "DealDamage": _damage,
}


def _kind(step: Dict[str, Any]) -> str:
    return "concentration" if step.get("concentration") else "rounds"


def is_add_entity_effect(step: Dict[str, Any]) -> bool:
    return step.get("type") == "add_entity_effect"


def foldable(step: Dict[str, Any], rule: Any) -> bool:
    """True if *step* translates cleanly into a ``lifetime`` block right now.

    Conservative: an unresolved rule (can't prove there are no reactive triggers
    to drop), an ``instance_fields`` step, an ``on_apply`` action without a
    state-block translator, or a referenced rule that declares reactive
    ``triggers`` (the §4.3b-2 work) all keep the spell on the legacy engine.
    """
    if not is_add_entity_effect(step):
        return False
    if rule is None:
        # Without the rule we cannot verify the effect has no reactive triggers we
        # would silently drop — stay on legacy.
        return False
    if getattr(rule, "triggers", None):
        return False
    if step.get("instance_fields"):
        return False
    if any(e.get("action") not in _ACTION_TO_BLOCK for e in step.get("on_apply", [])):
        return False
    return True


def to_lifetime_block(step: Dict[str, Any], rule: Any) -> Dict[str, Any]:
    """Translate a foldable ``add_entity_effect`` step into a ``lifetime`` dict.

    Caller must have checked :func:`foldable` first.
    """
    then: List[Dict[str, Any]] = [
        _ACTION_TO_BLOCK[e["action"]](e) for e in step.get("on_apply", [])
    ]
    block: Dict[str, Any] = {
        "block": "lifetime",
        "kind": _kind(step),
        "source": step.get("entity_effect_name", ""),
        "then": then,
    }
    # A step-level condition (e.g. "only on a failed save") gates installation —
    # the evaluator's per-block `condition` guard applies it to the whole lifetime.
    if step.get("condition"):
        block["condition"] = step["condition"]
    return block
