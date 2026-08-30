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
an ``instance_fields`` step, or any ``on_apply``/rule action without a block
translator.

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


def _end_lifetime(eff: Dict[str, Any]) -> Dict[str, Any]:
    # A rule's ``RemoveEffect`` on itself → end the effect's own lifetime scope.
    return {"block": "end_lifetime"}


def _modify_damage(eff: Dict[str, Any]) -> Dict[str, Any]:
    # An event-modifier: scales the in-flight DAMAGE_INCOMING event. Belongs inside
    # a trigger (which supplies the live event) — the fold always emits these
    # under a ``trigger`` block, never at cast time.
    out = {"block": "modify_damage", "multiplier": eff.get("multiplier", 1)}
    if eff.get("damage_type") is not None:
        out["damage_type"] = eff["damage_type"]
    return out


# Event-modifiers used by the condition library — targetless flags on the live roll
# event. Their per-effect ``when`` / ``on`` are applied by ``_triggers_from_rule``
# (as the block's fire-time ``condition`` and its event routing), so the translators
# only name the block.
def _grant_advantage(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "grant_advantage"}


def _grant_disadvantage(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "grant_disadvantage"}


def _cancel(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "cancel"}


def _force_critical_hit(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "force_critical", "outcome": "hit"}


def _force_critical_miss(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "force_critical", "outcome": "miss"}


# Forward global-rule effects (the concentration-break and per-turn refill rules).
def _force_concentration_check(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "force_concentration_check", "dc": eff.get("dc", 0)}


def _refill_resources(eff: Dict[str, Any]) -> Dict[str, Any]:
    return {"block": "refill_resources"}


# Legacy BUILTIN_EFFECTS action → block translator. Actions absent here are not
# yet foldable — the spells/effects that use them stay on the legacy engine until a
# later slice.
_ACTION_TO_BLOCK: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "AddModifier": _add_modifier,
    "ApplyCondition": _apply_condition,
    "GrantTemporaryHP": _grant_temporary_hp,
    "HealTarget": _healing,
    "DealDamage": _damage,
    "AddResource": _add_resource,
    "GrantAction": _grant_action,
    "RemoveEffect": _end_lifetime,
    "ModifyDamage": _modify_damage,
    "GrantAdvantage": _grant_advantage,
    "GrantDisadvantage": _grant_disadvantage,
    "Cancel": _cancel,
    "ForceCriticalHit": _force_critical_hit,
    "ForceCriticalMiss": _force_critical_miss,
    "ForceConcentrationCheck": _force_concentration_check,
    "RefillResources": _refill_resources,
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


# Effect target expressions that name an entity *of the event* (not the holder or
# spell caster/defender). A trigger whose effects hit one rebinds its current
# target to it, and those effects then address the rebound target ("defender").
_EVENT_REBIND = {
    "event.attacker", "event.defender", "event.source", "event.target",
    "event.entity",  # the per-turn refill rule targets whose turn it is
}


def rule_to_trigger_blocks(
    rule: Any,
    *,
    holder: Optional[str] = None,
    priority: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """One ``trigger`` block per event the rule reacts to, holding its effects.

    The single translation of a JSON ``Rule``'s reactive ``triggers``/``effects``
    into ``trigger`` blocks, shared by both migration paths:

    - **entity effects** (the ``add_entity_effect`` fold) pass ``holder`` so the
      rider's ``entity``/``caster`` resolves to the effect-holder;
    - **global rules** (``global_rules.install_global_rules``) pass ``priority=0``
      and no holder — a global rule has no holder, and its event-modifier effects
      ignore caster/target, reaching the live event instead.

    The rule's ``condition`` becomes each trigger's ``when`` firing guard; effects
    gated by ``on`` are routed to their event; a per-effect ``when`` becomes that
    effect block's fire-time ``condition``; an effect that hits an event entity
    rebinds the trigger's target to it.
    """
    blocks: List[Dict[str, Any]] = []
    for event_type in getattr(rule, "triggers", []) or []:
        event_name = event_type.name
        effs = [e for e in rule.effects if _effect_fires_on(e, event_name)]
        if not effs:
            continue
        # If this event's effects hit an event entity (e.g. the attacker), the
        # trigger rebinds its current target to it once.
        rebinds = {e.get("target") for e in effs if e.get("target") in _EVENT_REBIND}
        trigger_target = rebinds.pop() if len(rebinds) == 1 else None

        then = []
        for e in effs:
            eff_block = _ACTION_TO_BLOCK[e["action"]](e)
            if trigger_target and e.get("target") in _EVENT_REBIND:
                eff_block["target"] = "defender"  # the rebound current target
            # A per-effect `when` becomes the effect block's own `condition`, which
            # run_block evaluates at *fire* time inside the trigger — a per-effect
            # fire guard (e.g. Armor of Agathys retaliating only while temp HP > 0).
            if e.get("when"):
                eff_block["condition"] = e["when"]
            then.append(eff_block)

        tb: Dict[str, Any] = {
            "block": "trigger",
            "event": event_name,
            "then": then,
        }
        if holder is not None:
            tb["holder"] = holder
        if priority is not None:
            tb["priority"] = priority
        if trigger_target:
            tb["target"] = trigger_target
        if rule.condition:
            tb["when"] = rule.condition
        blocks.append(tb)
    return blocks


def _triggers_from_rule(step: Dict[str, Any], rule: Any) -> List[Dict[str, Any]]:
    """Entity-effect fold: trigger blocks holder-scoped from the step's ``on_caster``.

    A step's ``instance_fields`` (per-application closure values, e.g. Charm Person's
    ``charmer``) ride each trigger as its ``bindings`` — captured at install and
    exposed to the rider as ``instance_fields.<name>``.
    """
    blocks = rule_to_trigger_blocks(rule, holder=_holder(step))
    instance_fields = step.get("instance_fields")
    if instance_fields:
        for tb in blocks:
            tb["bindings"] = instance_fields
    return blocks


def is_add_entity_effect(step: Dict[str, Any]) -> bool:
    return step.get("type") == "add_entity_effect"


def foldable(step: Dict[str, Any], rule: Any) -> bool:
    """True if *step* translates cleanly into a ``lifetime`` block right now.

    Kept on the legacy engine (conservative) when: the rule can't be resolved
    (can't prove what reactive behaviour would be dropped), or an ``on_apply`` /
    rule effect has no block translator. Reactive ``triggers``, per-effect ``when``
    guards, and ``instance_fields`` (captured as a rider's ``bindings``) *are* folded.

    A concentration effect on a *targeted ally* (Haste — ``concentration`` +
    ``duration_rounds``, not ``on_caster``) folds like Vampiric Touch: the
    concentration scope carries the duration clock, so it ticks on the **caster's**
    turn rather than the effect-holder's. That is a deliberate, accepted deviation
    from legacy (both count the same number of rounds; identical when a caster
    targets itself) — the split-holder machinery it would take to tick on the ally's
    turn is rejected debt in this transitional module (decided 2026-08-30).
    """
    if not is_add_entity_effect(step):
        return False
    if rule is None:
        # Without the rule we cannot verify what reactive behaviour we would drop.
        return False
    if any(e.get("action") not in _ACTION_TO_BLOCK for e in step.get("on_apply", [])):
        return False
    # Reactive effects: every rule effect must map to a block (a per-effect `when`
    # is now folded, as the effect block's fire-time condition).
    for eff in getattr(rule, "effects", []) or []:
        if eff.get("action") not in _ACTION_TO_BLOCK:
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
