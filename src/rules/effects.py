"""Built-in effect handlers for the rule engine.

Writing a new effect handler
-----------------------------
An effect handler is any callable with this exact signature::

    def my_effect(
        effect: dict,
        ctx: dict,
        event: CombatEvent,
        event_bus: EventBus,
    ) -> None:
        ...

Parameters
~~~~~~~~~~
effect
    The raw JSON object for this particular effect, as a Python dict.  Every
    key defined in the JSON is available here.  For example, the JSON fragment::

        { "action": "MyEffect", "target": "event.attacker", "amount": 5 }

    arrives as ``{"action": "MyEffect", "target": "event.attacker", "amount": 5}``.

ctx
    The expression-evaluation namespace built by ``RuleEngine._make_context``.
    Pass this to ``_resolve()`` when reading any field that might contain a
    Python expression string (see below).

event
    The live ``CombatEvent`` that triggered the rule.  Set
    ``event.cancelled = True`` inside a handler to abort the action that fired
    the event (only meaningful for ``ATTACK_DECLARED`` and similar pre-action
    events that ``CombatSystem`` checks after emitting).

event_bus
    The ``EventBus`` for this combat.  Call ``event_bus.emit(EventType.X, ...)``
    if your effect should itself raise further events (e.g. emitting
    ``CONDITION_ADDED`` after adding a condition).

Using ``_resolve(expr, ctx)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Effect fields in JSON can be either literal values or Python expression
strings that reference the triggering event.  Always use ``_resolve`` when
reading fields that may be expressions::

    target = _resolve(effect["target"], ctx)  # "event.target" → Entity object
    dc     = _resolve(effect["dc"],     ctx)  # "max(10, event.total // 2)" → int
    source = effect.get("source", "")         # plain string literal — no eval needed

``_resolve`` checks ``isinstance(expr, str)``.  If the value *is* a string it
runs ``eval(expr, {"__builtins__": {}}, ctx)``; otherwise it returns the value
unchanged.  This means ``"duration": 3`` (an int) and ``"duration": "event.round_num"``
(a string expression) both work correctly.

Registering a handler
~~~~~~~~~~~~~~~~~~~~~
After defining a handler, register it with the ``RuleEngine`` before loading
any rule that uses it::

    engine.register_effect("MyEffect", my_effect)

Full example — Thorns retaliation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Python::

    from src.models.damage import Damage, DamageType
    from src.utils.dice import roll_formula

    def thorns_retaliation(
        effect: dict,
        ctx: dict,
        event: CombatEvent,
        event_bus: EventBus,
    ) -> None:
        attacker = _resolve(effect["attacker"], ctx)
        amount   = roll_formula(effect["formula"])
        attacker.take_damage(Damage(DamageType.PIERCING, amount))

    engine.register_effect("ThornsRetaliation", thorns_retaliation)

Matching JSON rule (``rules/thorns.json``)::

    {
      "name": "thorns_retaliation",
      "trigger": "ATTACK_HIT",
      "condition": "hasattr(event, 'defender') and event.defender.has_thorns",
      "effects": [
        {
          "action": "ThornsRetaliation",
          "attacker": "event.attacker",
          "formula": "1d6"
        }
      ]
    }
"""

from src.combat.event_bus import CombatEvent, EventBus
from src.combat.event_data import ConditionAddedData, ConditionRemovedData, DamageDealtData, HealingAppliedData
from src.combat.events import EventType
from src.models.action import AttackAction, ActionType
from src.models.action_resources import ACTION_COST
from src.models.condition import Condition, ConditionType
from src.models.damage import Damage, DamageType
from src.models.stat_modifier import StatModifier
from src.utils.dice import roll_d20, roll_formula

from .expressions import resolve as _resolve


# ---------------------------------------------------------------------------
# Built-in effects
# ---------------------------------------------------------------------------

def apply_condition(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Add a condition to a target entity.

    Required keys:  target (expr), condition_type (str)
    Optional keys:  duration (int or expr, default None), source (str, default ""),
                    effect_name (str, default derived from ``_effect_name`` in ctx)
    """
    target = _resolve(effect["target"], ctx)
    ctype = ConditionType[effect["condition_type"].upper()]
    duration = _resolve(effect.get("duration"), ctx) if "duration" in effect else None
    source = effect.get("source", "")
    effect_name = effect.get("effect_name", ctx.get("_effect_name", ""))
    condition = Condition(condition_type=ctype, duration_rounds=duration, source=source,
                          effect_name=effect_name)
    target.add_condition(condition)
    event_bus.emit(EventType.CONDITION_ADDED, ConditionAddedData(entity=target, condition=condition))


def remove_condition_type(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Remove all conditions of a given type from a target.

    Required keys:  target (expr), condition_type (str)
    """
    target = _resolve(effect["target"], ctx)
    ctype = ConditionType[effect["condition_type"].upper()]
    indices = [
        i for i, c in enumerate(target.get_active_conditions())
        if c.condition_type == ctype
    ]
    for i in reversed(indices):  # remove back-to-front to keep indices valid
        target.remove_condition(i)
        event_bus.emit(EventType.CONDITION_REMOVED, ConditionRemovedData(entity=target, condition_type=ctype))


def force_concentration_check(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Force a CON saving throw to maintain concentration.

    Required keys:  target (expr), dc (expr → int)

    On a failed save, ``target.concentrating_on`` and
    ``target.concentration_target`` are cleared, and the concentrated spell's
    effect (including any :class:`StatModifier` entries) is removed from the
    concentration target entity.
    """
    target = _resolve(effect["target"], ctx)
    dc = int(_resolve(effect["dc"], ctx))
    con_bonus = target.stat_block.get_saving_throw_bonus("constitution")
    roll = roll_d20() + con_bonus
    if roll < dc:
        spell_name = target.concentrating_on
        conc_target = target.concentration_target
        target.concentrating_on = None
        target.concentration_target = None
        if conc_target is not None and spell_name:
            conc_target.remove_effect(spell_name)


def cancel_event(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Cancel the triggering event, aborting the action that caused it.

    No required keys.
    """
    event.cancelled = True


def heal_target(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Heal a target by a dice formula plus an optional bonus.

    Required keys:  target (expr), formula (str, e.g. "1d6" or "2d4+2")
    Optional keys:  bonus (int or expr, default 0)
    """
    target = _resolve(effect["target"], ctx)
    bonus = int(_resolve(effect.get("bonus", 0), ctx))
    amount = roll_formula(effect["formula"]) + bonus
    target.heal(amount)
    event_bus.emit(EventType.HEALING_APPLIED, HealingAppliedData(target=target, amount=amount))


def _resolve_damage_type(raw, ctx: dict) -> DamageType:
    """Resolve a damage_type value to a DamageType enum member.

    Accepts three forms:
    - A ``DamageType`` instance already (returned as-is).
    - A plain string name such as ``"POISON"`` or ``"fire"`` (looked up directly).
    - A Python expression string such as ``"event.action.damage[0].damage_type"``
      (evaluated via ``_resolve``; the result is then coerced to ``DamageType``).

    Falls back to ``DamageType.GENERIC`` if none of the above succeed.
    """
    if isinstance(raw, DamageType):
        return raw
    if isinstance(raw, str):
        # Try as a literal enum name first to avoid eval on simple strings.
        try:
            return DamageType[raw.upper()]
        except KeyError:
            pass
        # Must be an expression — evaluate it.
        try:
            resolved = _resolve(raw, ctx)
            return resolved if isinstance(resolved, DamageType) else DamageType[resolved.upper()]
        except (AttributeError, KeyError, NameError):
            pass
    return DamageType.GENERIC


def deal_damage(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Deal damage to a target by dice formula.

    Required keys:  target (expr), formula (str), damage_type (str)

    When a ``_damage_processor`` is available in *ctx* (injected by the
    RuleEngine), damage is routed through :class:`DamageProcessor` so that
    ``DAMAGE_INCOMING`` handlers (resistance, immunity, vulnerability) apply.
    """
    target = _resolve(effect["target"], ctx)
    amount = roll_formula(effect["formula"])
    dtype = _resolve_damage_type(effect["damage_type"], ctx)
    dmg = Damage(dtype, amount)

    processor = ctx.get("_damage_processor")
    if processor is not None:
        processor.apply_damage(target, [dmg])
    else:
        target.take_damage(dmg)
        event_bus.emit(EventType.DAMAGE_DEALT,
                       DamageDealtData(defender=target, damage_list=[dmg], total=amount))


def grant_advantage(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Set the advantage flag on the triggering event.

    Meaningful for ATTACK_DECLARED events. The CombatSystem checks
    event.data["advantage"] after emitting ATTACK_DECLARED to decide
    how to roll the d20.

    No required keys.
    """
    event.data["advantage"] = True


def grant_disadvantage(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Set the disadvantage flag on the triggering event.

    See grant_advantage for details.
    """
    event.data["disadvantage"] = True


def force_critical_hit(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Force the triggering attack to resolve as a critical hit.

    Meaningful for ATTACK_DECLARED and ATTACK_ROLLED events. Sets event.data["critical_hit"] = True,
    which CombatSystem checks after emitting both.

    No required keys.
    """
    event.data["critical_hit"] = True


def force_critical_miss(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Force the triggering attack to resolve as a critical miss.

    Meaningful for ATTACK_DECLARED and ATTACK_ROLLED events events. Sets event.data["critical_miss"] = True,
    which CombatSystem checks after emitting both.

    No required keys.
    """
    event.data["critical_miss"] = True


def inject_pipeline_damage_step(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Append a damage step to the triggering action's pipeline_effects.

    Intended for ATTACK_HIT handlers. Because ATTACK_HIT fires mid-pipeline
    (during the attack_roll step), Python's list iteration picks up the appended
    step in the same pipeline run. Crit doubling applies automatically.

    Required keys: attack_action (expr → Action), formula (str), damage_type (str or expr)
    """
    action = _resolve(effect["attack_action"], ctx)
    dtype = _resolve_damage_type(effect["damage_type"], ctx)
    action.pipeline_effects.append({
        "type": "damage",
        "formula": effect["formula"],
        "damage_type": dtype.name,
        "requires_hit": True,
    })


def modify_damage(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Modify incoming damage amounts (resistance, immunity, vulnerability).

    Meaningful for DAMAGE_INCOMING events.  Iterates the damage_list on the
    event and multiplies each matching entry's amount by *multiplier*.

    Required keys:  multiplier (float — 0.5 for resistance, 0 for immunity,
                    2.0 for vulnerability)
    Optional keys:  damage_type (str — if given, only modify damages of that type)
    """
    multiplier = float(_resolve(effect["multiplier"], ctx))
    filter_type = effect.get("damage_type")
    if filter_type is not None:
        filter_type = _resolve_damage_type(filter_type, ctx)

    for dmg in event.data.get("damage_list", []):
        if filter_type is not None and dmg.damage_type != filter_type:
            continue
        dmg.amount = int(dmg.amount * multiplier)


# ---------------------------------------------------------------------------
# Action economy effects
# ---------------------------------------------------------------------------

def refill_resources(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Reset an entity's action resources to its stat block defaults.

    Required keys:  target (expr)
    """
    target = _resolve(effect["target"], ctx)
    target.refill_resources()


def grant_temporary_hp(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Grant temporary hit points to a target entity.

    Required keys:  target (expr), amount (int or expr)
    """
    target = _resolve(effect["target"], ctx)
    amount = int(_resolve(effect["amount"], ctx))
    target.add_temporary_hp(amount)


def remove_effect(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Remove a named entity effect from the target.

    Required keys:  target (expr), effect_name (str)
    """
    target = _resolve(effect["target"], ctx)
    effect_name = effect["effect_name"]
    target.remove_effect(effect_name)


def add_modifier(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Attach a labeled :class:`StatModifier` to a target entity.

    Required keys:  target (expr), stat (str), value (int or expr)
    Optional keys:  source (str, default "Unknown"), effect_name (str, default "")

    The ``stat`` field is an open namespace string (e.g. ``"ac"``,
    ``"saving_throw.wisdom"``, ``"spell_attack_bonus"``).  The modifier is
    automatically removed when ``entity.remove_effect(effect_name)`` is called.
    """
    target = _resolve(effect["target"], ctx)
    mod = StatModifier(
        stat=str(effect["stat"]),
        value=int(_resolve(effect["value"], ctx)),
        source=str(effect.get("source", "Unknown")),
        effect_name=str(effect.get("effect_name", "")),
    )
    target.add_stat_modifier(mod)


def modify_ac(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Modify a target's AC.

    Deprecated — prefer ``AddModifier`` with ``"stat": "ac"`` so that the
    change is labeled and tracked in the breakdown.  This shim delegates to
    ``add_modifier`` with source "Unknown" and no owning effect so that
    existing rule JSON continues to work.

    Required keys:  target (expr), amount (int or expr)
    """
    add_modifier(
        {**effect, "stat": "ac", "value": effect["amount"],
         "source": effect.get("source", "Unknown"), "effect_name": ""},
        ctx, event, event_bus,
    )


def add_resource(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Add bonus resources to an entity (can exceed defaults).

    Required keys:  target (expr), resource (str), amount (int or expr)

    ``resource`` must be one of: "actions", "bonus_actions", "reactions", "movement".
    """
    target = _resolve(effect["target"], ctx)
    resource = effect["resource"]
    amount = int(_resolve(effect.get("amount", 1), ctx))
    target.add_resource(resource, amount)


def grant_action(effect: dict, ctx: dict, event: CombatEvent, event_bus: EventBus) -> None:
    """Grant a temporary AttackAction to an entity for the duration of an entity effect.

    Required keys:  target (expr), name (str)
    Optional keys:  bonus_to_hit (int or expr, default 0), range_ft (float, default 5.0),
                    damage (list of {type, formula}), source_effect (str, default "")
                    description (str, default "")

    The granted action is tagged with ``source_effect`` so that it is automatically
    revoked when :meth:`Entity.remove_effect` is called with that name.
    """
    target = _resolve(effect["target"], ctx)
    name = effect["name"]
    bonus_to_hit = int(_resolve(effect.get("bonus_to_hit", 0), ctx))
    range_ft = float(effect.get("range_ft", 5.0))
    source_eff = effect.get("source_effect", "")
    description = effect.get("description", "")

    damages = []
    for d in effect.get("damage", []):
        dtype = DamageType[d["type"].upper()]
        formula = d.get("formula", "")
        amount = int(_resolve(d.get("amount", 0), ctx))
        damages.append(Damage(dtype, amount, formula=formula))

    action = AttackAction(
        name=name,
        description=description,
        action_type=ActionType.ATTACK,
        bonus_to_hit=bonus_to_hit,
        range_ft=range_ft,
        damage=damages,
        cost=ACTION_COST,
        source_effect=source_eff,
    )
    target.grant_action(action)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BUILTIN_EFFECTS = {
    "ApplyCondition": apply_condition,
    "RemoveConditionType": remove_condition_type,
    "ForceConcentrationCheck": force_concentration_check,
    "Cancel": cancel_event,
    "HealTarget": heal_target,
    "DealDamage": deal_damage,
    "AddDamageToAttackHit": inject_pipeline_damage_step,  # legacy alias
    "InjectPipelineDamageStep": inject_pipeline_damage_step,
    "GrantAdvantage": grant_advantage,
    "GrantDisadvantage": grant_disadvantage,
    "ForceCriticalHit": force_critical_hit,
    "ForceCriticalMiss": force_critical_miss,
    "ModifyDamage": modify_damage,
    "GrantTemporaryHP": grant_temporary_hp,
    "RemoveEffect": remove_effect,
    "RefillResources": refill_resources,
    "AddResource": add_resource,
    "AddModifier": add_modifier,
    "ModifyAC": modify_ac,  # deprecated — use AddModifier
    "GrantAction": grant_action,
}
