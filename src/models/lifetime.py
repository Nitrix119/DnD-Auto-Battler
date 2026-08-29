"""Lifetime scopes and grant handles — first-class ownership of revocation.

The rewrite retires the ``source_effect`` / ``effect_name`` string-tag cleanup
(design §6.3 / §6.5). Instead, **every grant returns a revoke handle**, and a
**lifetime scope** *owns* an ordered list of those handles. Teardown walks the
handles in reverse and disposes each — no name matching, no scan-and-remove, no
under/over-removal when two effects share a name or one effect grants two things.

- :class:`RevokeHandle` wraps one revoke closure. Disposing it is idempotent
  (a second dispose is a no-op) so a scope teardown can never double-remove.
- :class:`LifetimeScope` owns the handles produced under it. ``dispose()`` runs
  them in reverse insertion order, once. Concentration is one ``kind`` of
  lifetime; rounds/minutes are others (a duration clock is future work — nothing
  ticks scopes down yet, matching the current engine).

Scopes are **per-battle state**: they live on an :class:`~src.models.entity.Entity`
(concentration) or are held against the entity a lifetime buffs, never in the
process-global block ``REGISTRY`` (which is code — the block vocabulary). This is
what keeps the E12 per-session-isolation concern from biting: the block *type*
catalogue is shared, but every scope *instance* belongs to one battle's entities.

This is a pure domain primitive (no combat/engine imports) so ``Entity`` can hold
it without a ``models → spells`` dependency; the new spell engine imports it from
here.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, List, Optional


class LifetimeKind(Enum):
    """What ends a lifetime scope.

    - ``CONCENTRATION``: ends when the caster loses concentration (a new
      concentration spell, a failed CON save, or death). Exactly one per caster.
    - ``ROUNDS``: a fixed duration (no clock ticks it down yet — reserved).
    - ``INSTANT``: no persistence; disposed as soon as it is created (used for
      symmetry / testing).
    """

    CONCENTRATION = "concentration"
    ROUNDS = "rounds"
    INSTANT = "instant"


class RevokeHandle:
    """One owned revoke closure. Disposing is idempotent."""

    __slots__ = ("_revoke", "label", "_disposed")

    def __init__(self, revoke: Callable[[], None], label: str = "") -> None:
        self._revoke = revoke
        self.label = label
        self._disposed = False

    @property
    def disposed(self) -> bool:
        return self._disposed

    def dispose(self) -> None:
        """Run the revoke closure once; further calls are no-ops."""
        if self._disposed:
            return
        self._disposed = True
        self._revoke()


class LifetimeScope:
    """Owns the grant handles produced under one lifetime; tears them down together.

    Grants made while this scope is active register their revoke handle here via
    :meth:`add`. :meth:`dispose` revokes them in reverse insertion order (last
    granted, first revoked) exactly once — so replacing or breaking a lifetime
    removes precisely what it granted, and nothing else.
    """

    __slots__ = ("kind", "source", "rounds_remaining", "_handles", "_disposed")

    def __init__(
        self,
        kind: LifetimeKind = LifetimeKind.ROUNDS,
        source: str = "",
        rounds_remaining: Optional[int] = None,
    ) -> None:
        self.kind = kind
        self.source = source
        # Rounds left before the scope expires on its holder's turn; None = no
        # timed expiry (ends only by concentration break, self-dispose, or never).
        self.rounds_remaining = rounds_remaining
        self._handles: List[RevokeHandle] = []
        self._disposed = False

    @property
    def disposed(self) -> bool:
        return self._disposed

    @property
    def handles(self) -> List[RevokeHandle]:
        """The owned handles, in insertion order (read-only view copy)."""
        return list(self._handles)

    def add(self, handle: Optional[RevokeHandle]) -> Optional[RevokeHandle]:
        """Take ownership of a grant's revoke handle (ignores ``None``).

        Returns the handle so a caller can hold it too. A grant made after the
        scope is disposed is revoked immediately (the lifetime is already over),
        keeping "grant under a dead scope" from leaking.
        """
        if handle is None:
            return None
        if self._disposed:
            handle.dispose()
            return handle
        self._handles.append(handle)
        return handle

    def tick(self) -> bool:
        """Count down one round; return True when the timer has run out.

        No-op (returns False) for a scope with no timed expiry. Ticking a disposed
        scope also returns False. The caller disposes on a True result.
        """
        if self._disposed or self.rounds_remaining is None:
            return False
        self.rounds_remaining -= 1
        return self.rounds_remaining <= 0

    def dispose(self) -> None:
        """Revoke every owned handle in reverse order, once."""
        if self._disposed:
            return
        self._disposed = True
        for handle in reversed(self._handles):
            handle.dispose()
        self._handles.clear()
