"""State blocks: apply_condition, add_modifier, grant_temporary_hp, add_resource,
grant_action.

Each does its work **directly** — mutating the target and emitting the corresponding
event — rather than by the old pipeline's route of building a synthetic ``on_apply``
dict plus a stub SPELL_HIT event and handing it to a separate effect vocabulary. That
bridge, the clearest symptom of the two-vocabulary seam, is gone.
"""

from __future__ import annotations

from src.models.condition import Condition, ConditionType
from src.models.lifetime import LifetimeScope, LifetimeKind
from src.models.stat_modifier import StatModifier
from src.models.action import AttackAction, ActionType
from src.models.action_resources import ACTION_COST
from src.models.damage import Damage, DamageType
from src.combat.events import EventType
from src.combat.event_data import ConditionAddedData
from src.rules.expressions import resolve

from ..contract import BlockContract, Field, TargetArity
from ..context import Invocation, eval_context
from ..block import Block, parse_program
from ..registry import REGISTRY
from ..runner import run_program
from .targeting import TARGET_FIELD as _TARGET, select_target as _target
from .triggers import _capture_bindings

_SOURCE = Field("source", "str", description="Label for what applied this (a spell name).")
_EFFECT_NAME = Field("effect_name", "str",
                     description="Effect name, used to remove this by name later.")
_BINDINGS = Field("bindings", "map_expr",
                  description="Per-application values captured once at install and "
                              "read later as instance_fields.<name>.")


def _own(inv: Invocation, handle) -> None:
    """Register a grant's revoke handle with the open lifetime scope, if any.

    Inside a ``lifetime`` block the scope takes ownership so teardown revokes the
    grant; outside one the grant is instantaneous/permanent (the handle is dropped).
    """
    if inv.active_scope is not None:
        inv.active_scope.add(handle)


def _condition_rule(inv: Invocation, ctype: ConditionType):
    """The reactive rule that gives a condition its mechanics, or None.

    Looked up by name (``ConditionType.value``) in the cast's ``condition_rules``
    catalogue — the same ``EffectRegistry`` ``rules/entity_effects/conditions/*.json``
    is scanned into. None when nothing is wired (a bare block run), so the block
    degrades to a marker-only condition.
    """
    reg = getattr(inv.env, "condition_rules", None)
    if reg is None:
        return None
    try:
        return reg.get(ctype.value) if ctype.value in reg else None
    except Exception:
        return None


def _install_condition_rider(inv, rule, conditioned, bindings, scope) -> None:
    """Subscribe a condition's reactive rule as triggers held by *conditioned*, into *scope*.

    Runs the rule's native ``program`` (its trigger blocks) on a child invocation whose
    **caster and target are the conditioned entity**, so each rider's default
    ``holder: "caster"`` binds ``entity``/``event.caster`` to that entity — the same
    convention :func:`src.spells.entity_effects.install_entity_effect` uses, and the
    reason the condition rule files need no baked ``holder``. Works regardless of whether
    the spell conditioned its target or itself. The child's ``active_scope`` is *scope*,
    so each trigger registers its own unsubscribe as a handle the scope owns — disposing
    the scope (on expiry, concentration loss, or dispel) tears the mechanics down with
    the condition.

    *bindings* are already-resolved values (e.g. Charmed's ``charmer`` → the caster),
    captured against the *cast* invocation before the caster was rebound here, so they
    flow through the trigger's ``_capture_bindings`` pass-through branch unchanged.
    """
    blocks = [dict(b) for b in (rule.program or [])]
    if bindings:
        for tb in blocks:
            tb["bindings"] = bindings
    child = inv.child(caster=conditioned, target=conditioned)
    child.active_scope = scope
    run_program(parse_program(blocks), child)


def apply_condition(block: Block, inv: Invocation) -> None:
    """Add a status condition to the target and install its reactive mechanics.

    The condition's marker (``Condition``) is inert on its own; its behaviour lives
    in a reactive rule (``blinded`` → disadvantage, etc.). This block adds the marker
    **and** installs that rule, both owned by one lifetime scope so they end together:
    an enclosing scope (a concentration spell) when present, else a rounds scope on
    the target keyed to ``duration``, else a permanent scope disposed only on dispel.
    Emits CONDITION_ADDED. Degrades to marker-only when no reactive rule is wired.
    """
    target = _target(block, inv)
    ctype = ConditionType[str(block.get("condition_type", "")).upper()]
    raw_duration = block.get("duration")
    duration = resolve(raw_duration, eval_context(inv)) if raw_duration is not None else None
    condition = Condition(
        condition_type=ctype,
        duration_rounds=duration,
        source=str(block.get("source", "")),
        effect_name=str(block.get("effect_name", "")),
    )
    handle = target.add_condition(condition)

    # One clock for every condition, whether or not it has mechanics to install:
    # an enclosing scope when there is one, else a rounds scope on the target keyed
    # to ``duration``. A marker-only condition (no reactive rule wired) rides the same
    # scope, so its duration has a clock — there is no second one to fall back on.
    if inv.active_scope is not None:
        scope = inv.active_scope  # e.g. a concentration spell (Hold Person)
    else:
        scope = LifetimeScope(
            kind=LifetimeKind.ROUNDS,
            source=condition.source or ctype.value,
            rounds_remaining=duration,  # None → permanent until dispelled
        )
        target.lifetimes.append(scope)
    scope.add(handle)
    condition.owning_scope = scope

    rule = _condition_rule(inv, ctype)
    if rule is not None:
        # `instance_fields` is the legacy-step field name (see the authoring guide);
        # `bindings` is the native block spelling. Accept either — the rider captures
        # them as closure values (Charmed's `charmer`). Resolve them **now**, against
        # this cast invocation (where `event.caster` is the spell caster), before the
        # rider is installed on a child whose caster is the conditioned entity — so a
        # binding like `charmer: "event.caster"` still resolves to the caster.
        raw_bindings = block.get("bindings") or block.get("instance_fields")
        bindings = _capture_bindings(raw_bindings, inv)
        _install_condition_rider(inv, rule, target, bindings, scope)

    inv.event_bus.emit(
        EventType.CONDITION_ADDED,
        ConditionAddedData(entity=target, condition=condition),
    )


def add_modifier(block: Block, inv: Invocation) -> None:
    """Attach a labeled StatModifier to the target."""
    target = _target(block, inv)
    ec = eval_context(inv)
    mod = StatModifier(
        stat=str(block.get("stat", "")),
        value=int(resolve(block.get("value", 0), ec)),
        source=str(block.get("source", "")),
        effect_name=str(block.get("effect_name", "")),
    )
    _own(inv, target.add_stat_modifier(mod))


def grant_temporary_hp(block: Block, inv: Invocation) -> None:
    """Grant temporary hit points to the target (non-stacking, keeps the higher)."""
    target = _target(block, inv)
    try:
        amount = int(resolve(block.get("amount", 0), eval_context(inv)))
    except Exception:
        amount = 0
    if amount > 0:
        _own(inv, target.add_temporary_hp(amount))
        inv.context["temp_hp_granted"] = amount


def add_resource(block: Block, inv: Invocation) -> None:
    """Add to a per-turn resource (movement, actions, …) on the target.

    A *transient* grant, not a durable one: it is re-applied each turn by a
    ``TURN_START`` rider and wiped by the next turn's refill, so it registers **no**
    revoke handle — when the rider's lifetime ends it simply stops being re-added
    (matching the legacy ``AddResource`` entity effect).
    """
    target = _target(block, inv)
    resource = str(block.get("resource", ""))
    try:
        amount = int(resolve(block.get("amount", 0), eval_context(inv)))
    except Exception:
        return
    if resource and amount:
        target.add_resource(resource, amount)


def grant_action(block: Block, inv: Invocation) -> None:
    """Grant a temporary AttackAction to the target (e.g. a concentration's attack).

    Builds the action from the block's ``name``/``bonus_to_hit``/``range_ft``/
    ``damage`` fields and hands the scope its revoke handle, so ending the lifetime
    removes the action.
    """
    target = _target(block, inv)
    ec = eval_context(inv)
    try:
        bonus = int(resolve(block.get("bonus_to_hit", 0), ec))
    except Exception:
        bonus = 0
    damages = [
        Damage(DamageType[str(d.get("type", "GENERIC")).upper()], 0,
               formula=d.get("formula", ""))
        for d in block.get("damage", [])
    ]
    action = AttackAction(
        name=str(block.get("name", "")),
        description=str(block.get("description", "")),
        action_type=ActionType.ATTACK,
        bonus_to_hit=bonus,
        range_ft=float(block.get("range_ft", 5.0)),
        damage=damages,
        cost=ACTION_COST,
    )
    _own(inv, target.grant_action(action))


REGISTRY.register(
    "apply_condition", apply_condition,
    BlockContract(
        fields=(
            _TARGET,
            Field("condition_type", "enum", required=True, enum=ConditionType,
                  description="Which condition to apply."),
            Field("duration", "expr",
                  description="Rounds the condition lasts; omitted = until dispelled."),
            _SOURCE,
            _EFFECT_NAME,
            _BINDINGS,
            Field("instance_fields", "map_expr",
                  description="Deprecated spelling of `bindings`; prefer `bindings`."),
        ),
        target_arity=TargetArity.SINGLE,
        # This block subscribes handlers (the condition's reactive rule), so the
        # evaluator must flush the cast's pending DAMAGE_DEALT before it — otherwise
        # a rider that reacts to damage fires on the very damage that applied it.
        installs_reactions=True,
    ),
)
REGISTRY.register(
    "add_modifier", add_modifier,
    BlockContract(
        fields=(
            _TARGET,
            # `stat` is an open namespace by design (see StatModifier) — not a choice.
            Field("stat", "str", required=True,
                  description="Stat to modify: 'ac', 'spell_save_dc', "
                              "'saving_throw.<ability>', 'max_hp', …"),
            Field("value", "expr", required=True,
                  description="How much to add (negative to subtract)."),
            _SOURCE,
            _EFFECT_NAME,
        ),
        target_arity=TargetArity.SINGLE,
    ),
)
REGISTRY.register(
    "grant_temporary_hp", grant_temporary_hp,
    BlockContract(
        fields=(
            _TARGET,
            Field("amount", "expr", required=True,
                  description="Temporary hit points to grant (non-stacking)."),
        ),
        writes=("temp_hp_granted",),
        target_arity=TargetArity.SINGLE,
    ),
)
REGISTRY.register(
    "add_resource", add_resource,
    BlockContract(
        fields=(
            _TARGET,
            Field("resource", "choice", required=True,
                  choices=("actions", "bonus_actions", "reactions", "movement"),
                  description="Which per-turn resource to top up."),
            Field("amount", "expr", required=True,
                  description="How much to add."),
        ),
        target_arity=TargetArity.SINGLE,
    ),
)
REGISTRY.register(
    "grant_action", grant_action,
    BlockContract(
        fields=(
            _TARGET,
            Field("name", "str", required=True,
                  description="Name of the granted action."),
            Field("description", "str", description="Flavour text for the action."),
            Field("bonus_to_hit", "expr",
                  description="Attack bonus for the granted action."),
            Field("range_ft", "number", description="Reach in feet. Default 5."),
            Field("damage", "list", subfields=(
                Field("type", "enum", enum=DamageType,
                      description="Damage type name. Default GENERIC."),
                Field("formula", "formula", description="Dice formula for this entry."),
            ), description="Damage entries the granted action deals."),
        ),
        target_arity=TargetArity.SINGLE,
    ),
)
