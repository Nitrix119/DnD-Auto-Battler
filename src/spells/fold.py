"""Fold a legacy ``add_entity_effect`` step into a ``lifetime`` block program.

Transitional (removed in Phase 3, when persistent effects are authored as a
``program`` directly). The legacy shape splits a persistent effect across two
files — the spell's ``add_entity_effect`` step (its ``on_apply`` immediate grants
+ concentration flag) and a separate entity-effect **rule** in
``rules/entity_effects/`` (its reactive ``triggers`` + ``effects`` + duration).
This module reunites them into one ``lifetime{ … }`` block:

- ``on_apply`` grants → **state blocks** (``add_modifier`` / ``apply_condition`` /
  ``grant_temporary_hp`` / ``healing`` / ``damage`` / ``add_resource``), owned by
  the scope.
- the rule's reactive ``triggers`` + ``effects`` → **trigger blocks** (one per
  event), holder-scoped and guarded by the rule's ``condition``.
- ``concentration`` / a rounds duration → the ``lifetime`` **kind**.

Still deferred (kept on legacy by :func:`foldable`): a *concentration* duration on
a non-``on_caster`` effect (its clock would tick on the wrong turn — e.g. Haste),
a per-effect ``when`` guard, an ``instance_fields`` step, or any ``on_apply``/rule
action without a block translator (``RemoveEffect``, ``InjectPipelineDamageStep``).

``foldable`` is the routing gate's check (does this step translate cleanly?);
``to_lifetime_block`` is the translation. Both take the referenced ``rule`` (or
``None`` when it cannot be resolved) so foldability accounts for reactive triggers
we do not yet handle.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Legacy effect target expressions → a state block's ``target`` keyword. In a
# reactive rule's effects the target is ``entity`` (the effect-holder); in a firing
# rider the invocation's caster *is* the holder, so ``entity`` maps to ``caster``.
_TARGET_EXPR_TO_BLOCK = {
    "event.caster": "caster",
    "event.defender": "defender",
    "entity": "caster",
}


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


def _add_resource(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "block": "add_resource",
        "target": _target(eff.get("target")),
        "resource": eff.get("resource", ""),
        "amount": eff.get("amount", 0),
    }


def _grant_action(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "block": "grant_action",
        "target": _target(eff.get("target")),
        "name": eff.get("name", ""),
        "description": eff.get("description", ""),
        "bonus_to_hit": eff.get("bonus_to_hit", 0),
        "range_ft": eff.get("range_ft", 5.0),
        "damage": eff.get("damage", []),
    }


# Legacy BUILTIN_EFFECTS action → block translator. Actions absent here
# (GrantAction, RemoveEffect, InjectPipelineDamageStep, …) are not yet foldable —
# the spells that use them stay on the legacy engine until a later slice.
_ACTION_TO_BLOCK: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "AddModifier": _add_modifier,
    "ApplyCondition": _apply_condition,
    "GrantTemporaryHP": _grant_temporary_hp,
    "HealTarget": _healing,
    "DealDamage": _damage,
    "AddResource": _add_resource,
    "GrantAction": _grant_action,
}


def _kind(step: Dict[str, Any]) -> str:
    return "concentration" if step.get("concentration") else "rounds"


def _holder(step: Dict[str, Any]) -> str:
    """Which entity the effect (and so its riders) belongs to: caster or defender."""
    return "caster" if step.get("on_caster") else "defender"


def _effect_fires_on(eff: Dict[str, Any], event_name: str) -> bool:
    """True if a rule effect (optionally gated by ``on``) applies to *event_name*."""
    on = eff.get("on")
    if on is None:
        return True
    on_list = [on] if isinstance(on, str) else on
    return event_name in {str(x).upper() for x in on_list}


def _triggers_from_rule(step: Dict[str, Any], rule: Any) -> List[Dict[str, Any]]:
    """One ``trigger`` block per event the rule reacts to, holding its effects.

    The rule's ``condition`` (over ``entity``/``event``) becomes the trigger's
    ``when`` firing guard; effects gated by ``on`` are routed to their event.
    """
    holder = _holder(step)
    blocks: List[Dict[str, Any]] = []
    for event_type in getattr(rule, "triggers", []) or []:
        event_name = event_type.name
        then = [
            _ACTION_TO_BLOCK[e["action"]](e)
            for e in rule.effects
            if _effect_fires_on(e, event_name)
        ]
        if not then:
            continue
        tb: Dict[str, Any] = {
            "block": "trigger",
            "event": event_name,
            "holder": holder,
            "then": then,
        }
        if rule.condition:
            tb["when"] = rule.condition
        blocks.append(tb)
    return blocks


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
        # Without the rule we cannot verify what reactive behaviour we would drop.
        return False
    if step.get("instance_fields"):
        return False
    if any(e.get("action") not in _ACTION_TO_BLOCK for e in step.get("on_apply", [])):
        return False
    # A concentration duration ticks on the caster's turn (its scope lives on the
    # caster), but legacy ticks it on the effect-holder's turn. Those match only
    # when the holder IS the caster (on_caster) — otherwise defer (e.g. Haste,
    # concentration on a targeted ally). A rounds duration lives on the holder and
    # ticks on the holder's turn either way, so it is always safe.
    if (
        getattr(rule, "duration_rounds", None)
        and step.get("concentration")
        and not step.get("on_caster")
    ):
        return False
    # Reactive effects: every rule effect must map to a block, and per-effect fire
    # guards (`when`) are not folded yet.
    for eff in getattr(rule, "effects", []) or []:
        if eff.get("action") not in _ACTION_TO_BLOCK:
            return False
        if eff.get("when"):
            return False
    return True


def to_lifetime_block(step: Dict[str, Any], rule: Any) -> Dict[str, Any]:
    """Translate a foldable ``add_entity_effect`` step into a ``lifetime`` dict.

    Caller must have checked :func:`foldable` first.
    """
    then: List[Dict[str, Any]] = [
        _ACTION_TO_BLOCK[e["action"]](e) for e in step.get("on_apply", [])
    ]
    then.extend(_triggers_from_rule(step, rule))
    block: Dict[str, Any] = {
        "block": "lifetime",
        "kind": _kind(step),
        "source": step.get("entity_effect_name", ""),
        "then": then,
    }
    if getattr(rule, "duration_rounds", None):
        block["duration_rounds"] = rule.duration_rounds
    # A step-level condition (e.g. "only on a failed save") gates installation —
    # the evaluator's per-block `condition` guard applies it to the whole lifetime.
    if step.get("condition"):
        block["condition"] = step["condition"]
    return block
