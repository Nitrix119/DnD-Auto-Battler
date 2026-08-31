"""The lifetime clock — tick an entity's duration/concentration scopes on TURN_END.

A block-engine lifetime scope (a rounds duration, a concentration) counts down on
the holder's turn via :meth:`Entity.tick_lifetimes`. That tick used to be driven from
inside ``RuleEngine._tick_durations`` — so the *new* engine's durations only expired
because the *legacy* rule engine happened to be instantiated and subscribed. This is
its own driver: a single ``TURN_END`` subscriber, independent of the rule engine, so
the block engine's clock stands on its own and the legacy dispatch can be retired
without it (Phase 3 §4).

Installed once per battle by :meth:`CombatSystem.start_combat`. Subscribed at a low
priority so scopes expire *after* any ``TURN_END`` riders have reacted to the turn
ending (an effect fires on its final turn, then its scope tears down).
"""

from __future__ import annotations

from typing import Any

from .events import EventType

# Runs after the rider slot (priority -10) and the global slot (0), so lifetime
# teardown is the last thing to happen as a turn ends.
_CLOCK_PRIORITY = -100


def install_lifetime_clock(event_bus: Any) -> None:
    """Subscribe the per-turn lifetime clock to *event_bus*.

    On each ``TURN_END`` it ticks the ending entity's lifetime scopes, disposing any
    that run out (a duration that elapsed, a concentration whose clock reached zero).
    Idempotent behaviour is the scope's own concern; this only routes the turn signal.
    """

    def _tick(event: Any) -> None:
        data = event.data
        entity = data.entity if hasattr(data, "entity") else data.get("entity")
        if entity is not None:
            entity.tick_lifetimes()

    event_bus.subscribe(EventType.TURN_END, _tick, priority=_CLOCK_PRIORITY)
