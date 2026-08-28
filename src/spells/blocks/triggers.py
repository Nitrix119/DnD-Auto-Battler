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
installed), binds the current target from the optional ``target`` expression, and
runs ``then``. Re-entrant events (a rider whose damage triggers another rider)
are bounded by a depth guard (design §6.4) so a retaliation loop cannot recurse
without limit.
"""

from __future__ import annotations

from src.combat.events import EventType
from src.models.lifetime import RevokeHandle
from src.rules.expressions import evaluate

from ..contract import BlockContract, TargetArity
from ..context import Invocation, eval_context, seed_context
from ..block import Block
from ..registry import REGISTRY

# Cap on nested trigger firings within one originating event, so a mutual
# retaliation (A hurts B, B's rider hurts A, A's rider hurts B, …) terminates.
_MAX_TRIGGER_DEPTH = 8
_depth = 0


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


def trigger(block: Block, inv: Invocation) -> None:
    """Subscribe this block's ``then`` to an event; scope it to the open lifetime."""
    from ..evaluator import run_program

    event_type = EventType[str(block.get("event", "")).upper()]
    then = list(block.then)
    when = block.get("when")  # firing guard — NOT `condition` (see module docstring)
    target_expr = block.get("target")

    # Capture the defining scope — the rider runs later, on someone else's turn.
    caster = inv.caster
    action = inv.action
    bus = inv.event_bus
    damage_processor = inv.damage_processor
    rule_engine = inv.rule_engine
    slot_level = inv.slot_level

    def handler(event) -> None:
        global _depth
        if _depth >= _MAX_TRIGGER_DEPTH:
            return
        fired = Invocation(
            caster=caster,
            target=caster,
            action=action,
            event_bus=bus,
            damage_processor=damage_processor,
            rule_engine=rule_engine,
            slot_level=slot_level,
            context=seed_context(slot_level or 0),
            event_data=dict(event.data),
        )
        if not _passes(when, fired):
            return
        if target_expr is not None:
            try:
                fired.target = evaluate(target_expr, eval_context(fired))
            except Exception:
                return
        _depth += 1
        try:
            run_program(then, fired)
        finally:
            _depth -= 1

    bus.subscribe(event_type, handler)
    if inv.active_scope is not None:
        inv.active_scope.add(
            RevokeHandle(
                lambda: bus.unsubscribe(event_type, handler), label="trigger"
            )
        )


REGISTRY.register(
    "trigger",
    trigger,
    BlockContract(target_arity=TargetArity.SINGLE),
)
