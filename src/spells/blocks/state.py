"""State blocks: apply_condition, add_modifier, grant_temporary_hp, add_resource,
grant_action.

These fold three legacy twins into one catalogue and, crucially, do the work
**directly** instead of the old pipeline's route (build a synthetic ``on_apply``
dict + a stub SPELL_HIT event, then call the rule engine's ``BUILTIN_EFFECTS``
handler). That bridge — the clearest symptom of the two-vocabulary seam — is gone
here: a state block just mutates the target and emits the same event.
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

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context
from ..block import Block, parse_program
from ..fold import rule_to_trigger_blocks
from ..registry import REGISTRY
from ..runner import run_program


def _target(block: Block, inv: Invocation):
    return inv.caster if block.get("target") == "caster" else inv.target


def _own(inv: Invocation, handle) -> None:
    """Register a grant's revoke handle with the open lifetime scope, if any.

    Inside a ``lifetime`` block the scope takes ownership so teardown revokes the
    grant; outside one the grant is instantaneous/permanent (the handle is dropped).
    """
    if inv.active_scope is not None:
        inv.active_scope.add(handle)


def _condition_rule(inv: Invocation, ctype: ConditionType):
    """The reactive rule that gives a condition its mechanics, or None.

    Looked up by name (``ConditionType.value``) in the rule engine's effect
    registry — the same registry ``rules/entity_effects/conditions/*.json`` is
    scanned into. None when nothing is wired (a bare block run), so the block
    degrades to a marker-only condition.
    """
    engine = getattr(inv.env, "rule_engine", None)
    reg = getattr(engine, "effect_registry", None)
    if reg is None:
        return None
    try:
        return reg.get(ctype.value) if ctype.value in reg else None
    except Exception:
        return None


def _install_condition_rider(inv, rule, holder, bindings, scope) -> None:
    """Subscribe a condition's reactive rule as holder-scoped triggers into *scope*.

    Folds the rule to ``trigger`` blocks and runs them on a child invocation whose
    ``active_scope`` is *scope*, so each trigger registers its own unsubscribe as a
    handle the scope owns — disposing the scope (on expiry, concentration loss, or
    dispel) then tears the mechanics down with the condition. The child keeps this
    cast's caster/target, so ``holder`` resolves to the conditioned entity and any
    ``bindings`` (e.g. Charmed's ``charmer``) evaluate against the caster's context.

    A **native** condition rule authors its trigger blocks directly (with ``holder``
    baked in); a legacy one is folded from its ``triggers``/``effects`` with *holder*
    supplied here. Both run identically on the child — the fold is retired once every
    condition is native (Phase 3 §5).
    """
    if getattr(rule, "program", None) is not None:
        blocks = [dict(b) for b in rule.program]
    else:
        blocks = rule_to_trigger_blocks(rule, holder=holder)
    if bindings:
        for tb in blocks:
            tb["bindings"] = bindings
    child = inv.child()
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

    rule = _condition_rule(inv, ctype)
    if rule is None:
        # No reactive rule wired: today's behaviour — the marker alone, owned by any
        # enclosing lifetime (else instantaneous/permanent).
        _own(inv, handle)
    else:
        holder = "caster" if block.get("target") == "caster" else "defender"
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
        condition.rounds_remaining = None  # the scope is the sole duration clock
        # `instance_fields` is the legacy-step field name (see the authoring guide);
        # `bindings` is the native block spelling. Accept either — the rider captures
        # them as closure values (Charmed's `charmer`).
        bindings = block.get("bindings") or block.get("instance_fields")
        _install_condition_rider(inv, rule, holder, bindings, scope)

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
    BlockContract(required_args=("condition_type",), target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "add_modifier", add_modifier,
    BlockContract(required_args=("stat", "value"), target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "grant_temporary_hp", grant_temporary_hp,
    BlockContract(writes=("temp_hp_granted",), required_args=("amount",),
                  target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "add_resource", add_resource,
    BlockContract(required_args=("resource", "amount"),
                  target_arity=TargetArity.SINGLE),
)
REGISTRY.register(
    "grant_action", grant_action,
    BlockContract(required_args=("name",), target_arity=TargetArity.SINGLE),
)
