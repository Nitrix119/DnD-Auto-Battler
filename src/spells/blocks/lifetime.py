"""The lifetime block — wrap a `then` subtree in a scope that owns its grants.

A persistent effect is a lifetime scope around one or more grant blocks (design
§6.3). This block opens a fresh :class:`~src.models.lifetime.LifetimeScope`, makes
it the invocation's active scope while its ``then`` body runs — so every grant
inside registers its revoke handle into the scope — and then binds the scope:

- ``kind: "concentration"`` → the caster's concentration lifetime. Beginning it
  disposes any prior concentration atomically (a new spell drops the old one and
  its entire granted subtree). A failed CON save later disposes it via
  ``Entity.end_concentration`` (the global concentration rule).
- otherwise (a duration) → held on the caster's ``lifetimes`` list. No clock ticks
  durations down yet, so teardown is reserved; the scope still owns its handles.

The grant blocks themselves (``add_modifier``, ``apply_condition``,
``grant_temporary_hp``) are unchanged — they just register their handle with the
open scope when one is active (see ``blocks/state.py``).
"""

from __future__ import annotations

from src.models.lifetime import LifetimeScope, LifetimeKind

from ..contract import BlockContract, TargetArity
from ..context import Invocation
from ..block import Block
from ..registry import REGISTRY
from ..runner import run_program

_KINDS = {
    "concentration": LifetimeKind.CONCENTRATION,
    "rounds": LifetimeKind.ROUNDS,
    "instant": LifetimeKind.INSTANT,
}


def _kind(block: Block) -> LifetimeKind:
    # `concentration: true` is sugar for kind="concentration".
    if block.get("concentration") is True:
        return LifetimeKind.CONCENTRATION
    raw = str(block.get("kind", "rounds")).lower()
    return _KINDS.get(raw, LifetimeKind.ROUNDS)


def lifetime(block: Block, inv: Invocation) -> None:
    """Run ``then`` with a fresh scope open, then bind the scope by its kind."""
    kind = _kind(block)
    source = str(block.get("source", getattr(inv.action, "name", "") or ""))
    raw_rounds = block.get("duration_rounds")
    rounds = int(raw_rounds) if raw_rounds is not None else None
    scope = LifetimeScope(kind=kind, source=source, rounds_remaining=rounds)

    prev = inv.active_scope
    inv.active_scope = scope
    try:
        run_program(list(block.then), inv)
    finally:
        inv.active_scope = prev

    if kind is LifetimeKind.CONCENTRATION:
        # Concentration always belongs to the caster; the current target is the
        # effect-holder, mirrored as concentration_target for consistent reads.
        inv.caster.begin_concentration(scope, target=inv.target)
    else:
        # A duration belongs to the effect-holder (the target it was applied to) —
        # that is whose turn its clock will tick on (§4.3c).
        inv.target.lifetimes.append(scope)


def end_lifetime(block: Block, inv: Invocation) -> None:
    """End the effect whose rider is firing — dispose its owning lifetime scope.

    Used by a self-terminating effect (Armor of Agathys ends when its temp HP is
    gone). Disposing the scope revokes every grant it owns and unsubscribes its
    riders. A no-op outside a trigger firing (no owning scope).
    """
    if inv.owning_scope is not None:
        inv.owning_scope.dispose()


REGISTRY.register(
    "lifetime",
    lifetime,
    BlockContract(target_arity=TargetArity.SINGLE, installs_reactions=True),
)
REGISTRY.register(
    "end_lifetime",
    end_lifetime,
    BlockContract(target_arity=TargetArity.SINGLE),
)
