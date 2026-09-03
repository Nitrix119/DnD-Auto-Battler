"""Trigger blocks — subscribe a `then` sub-program to a combat event.

A reactive rider (Colossus Slayer's bonus die on a hit, Vampiric Touch's heal on
the caster's necrotic damage, Armor of Agathys' retaliation) is a ``then``
sub-program bound to an EventBus event. When the ``trigger`` block runs during a
cast it captures its defining caster + collaborators, subscribes a handler, and —
if a lifetime scope is open (a concentration/duration ``lifetime`` block) —
registers the *unsubscribe* as a revoke handle the scope owns. Teardown of the
lifetime then unsubscribes the rider for free: a subscription is just another
grant (design §6.1/§6.5). Outside a lifetime the subscription is permanent (a
racial feature).

When the event fires, the handler builds a **fresh invocation** carrying the
event's data (``event.<field>`` in expressions), evaluates the optional firing
guard ``when`` (a distinct key from the evaluator's install-time ``condition``, so
the guard is checked at *fire* time against the event, not when the trigger is
installed), binds the current target from the optional ``rebind_target`` expression,
and runs ``then``. Re-entrant events (a rider whose damage triggers another rider)
are bounded by a depth guard (design §6.4) so a retaliation loop cannot recurse
without limit.
"""

from __future__ import annotations

from weakref import WeakKeyDictionary

from src.combat.events import EventType
from src.models.lifetime import RevokeHandle
from src.rules.expressions import evaluate

from ..contract import BlockContract, Field, TargetArity
from ..context import Invocation, eval_context
from ..block import Block
from ..registry import REGISTRY
from ..runner import run_program

# Cap on nested trigger firings within one originating event, so a mutual
# retaliation (A hurts B, B's rider hurts A, …) terminates. The depth is tracked
# **per event bus** — i.e. per battle — via a weak-keyed map, not a module global,
# so concurrent battles never share a counter (the E12 per-battle-state rule).
_MAX_TRIGGER_DEPTH = 8
_depth_by_bus: "WeakKeyDictionary[object, int]" = WeakKeyDictionary()


def _passes(expr, fired: Invocation) -> bool:
    if expr is None:
        return True
    try:
        return bool(evaluate(expr, eval_context(fired)))
    except AttributeError:
        # The fired event lacks a field the condition references — skip (matches
        # the rule engine's missing-field semantics), not a crash.
        return False
    except Exception:
        return False


def _capture_bindings(bindings, inv: Invocation):
    """Evaluate a trigger's ``bindings`` once at install, against *inv*.

    Returns a ``{name: value}`` dict (or None when there are no bindings), captured
    so the rider's later firings see them as ``instance_fields.<name>``. A binding
    whose expression fails to evaluate is dropped (the rider still installs), matching
    the legacy ``instance_fields`` evaluation's best-effort behaviour.
    """
    if not bindings:
        return None
    ctx = eval_context(inv)
    captured = {}
    for name, expr in bindings.items():
        # A string binding is an expression evaluated against the installing invocation
        # (native authoring, e.g. Charm Person's ``"charmer": "event.caster"``). A
        # non-string is an already-resolved value passed straight through — the contract
        # of ``apply_entity_rule(instance_fields={"charmer": <Entity>})``, whose
        # values are objects, not expressions.
        if not isinstance(expr, str):
            captured[name] = expr
            continue
        try:
            captured[name] = evaluate(expr, ctx)
        except Exception:
            pass
    return captured


def trigger(block: Block, inv: Invocation) -> None:
    """Subscribe this block's ``then`` to an event; scope it to the open lifetime."""
    event_type = EventType[str(block.get("event", "")).upper()]
    then = list(block.then)
    when = block.get("when")  # firing guard — NOT `condition` (see module docstring)
    target_expr = block.get("rebind_target")
    # Riders fire in the legacy entity-effect slot (priority -10) by default, i.e.
    # after priority-0 global rules like the per-turn resource refill — so a
    # per-turn grant lands after the reset, not before it. Overridable per block.
    priority = int(block.get("priority", -10))
    bus = inv.event_bus

    # The effect-holder owns the rider: its `entity`/`caster` in the firing context.
    # For a self-applied effect that is the caster; for a buff on an ally it is the
    # target the effect was attached to. Captured now (stable for the cast).
    holder = inv.caster if block.get("holder", "caster") == "caster" else inv.target
    # The scope this rider belongs to, so its `then` can end the effect itself.
    owning_scope = inv.active_scope
    # Per-application closure variables (e.g. Charm Person's `charmer`): evaluate the
    # `bindings` expressions **once, now** against the installing cast invocation
    # (where `event.caster` is the spell caster) and capture the results, so the rider
    # sees them later as `instance_fields.<name>`, fixed at cast time.
    bindings = _capture_bindings(block.get("bindings"), inv)

    def handler(event) -> None:
        # The rider runs later, on someone else's turn; `holder` + the captured
        # `inv` supply the action/collaborators for the fresh firing context.
        depth = _depth_by_bus.get(bus, 0)
        if depth >= _MAX_TRIGGER_DEPTH:
            return
        event_fields = dict(event.data)
        fired = inv.child(
            caster=holder,
            target=holder,
            event_data=event_fields,
            live_event=event,
            instance_fields=bindings,
        )
        fired.owning_scope = owning_scope
        # Seed roll-result flags the event carries into the fresh context, so a
        # `damage` block in `then` continues from the attack's outcome — e.g. an
        # on-hit bonus die doubles on a crit exactly as a mid-cast damage block
        # does (5e RAW: extra on-hit dice double on a critical hit). General to
        # any event carrying the flag (ATTACK_HIT), not a per-effect special case.
        if "critical_hit" in event_fields:
            fired.context["critical_hit"] = bool(event_fields["critical_hit"])
        if not _passes(when, fired):
            return
        if target_expr is not None:
            try:
                fired.target = evaluate(target_expr, eval_context(fired))
            except Exception:
                return
        _depth_by_bus[bus] = depth + 1
        try:
            run_program(then, fired)
        finally:
            _depth_by_bus[bus] = depth

    bus.subscribe(event_type, handler, priority=priority)
    if inv.active_scope is not None:
        inv.active_scope.add(
            RevokeHandle(
                lambda: bus.unsubscribe(event_type, handler), label="trigger"
            )
        )


REGISTRY.register(
    "trigger",
    trigger,
    BlockContract(
        fields=(
            Field("event", "enum", required=True, enum=EventType,
                  description="The combat event this rider fires on."),
            Field("when", "expr",
                  description="Guard evaluated at fire time against the event; "
                              "the rider is skipped when falsy."),
            # Unlike the two-value `target` selector on state blocks, this is an
            # expression naming the entity to rebind the current-target slot to when
            # the rider fires — hence the distinct name (SPELL_SYSTEM_REMAINING §4).
            Field("rebind_target", "expr",
                  description="Expression naming the entity the `then` body acts on "
                              "when the rider fires (e.g. 'event.defender')."),
            Field("holder", "choice", choices=("caster", "defender"),
                  description="Whose rider this is — which entity 'entity' resolves to."),
            Field("priority", "int",
                  description="Bus subscription priority; lower runs later."),
            Field("bindings", "map_expr",
                  description="Values captured once at install, read later as "
                              "instance_fields.<name>."),
        ),
        target_arity=TargetArity.SINGLE,
        installs_reactions=True,
        consumes_then=True,
    ),
)
