import bisect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Union

from .event_data import EventData
from .events import EventType


@dataclass
class CombatEvent:
    event_type: EventType
    data: Union[EventData, Dict[str, Any]] = field(default_factory=dict)
    cancelled: bool = False  # set True in a handler to abort the triggering action


class EventBus:
    """Publish/subscribe event bus with optional handler priority.

    Handlers with a higher *priority* value fire first.  Handlers at the
    same priority fire in subscription order (FIFO).
    """

    def __init__(self):
        # Each entry is (-priority, insertion_order, handler).
        # Sorted ascending so that the *highest* priority (most negative
        # negated value) comes first; ties broken by insertion order.
        self._handlers: Dict[EventType, List[Tuple[int, int, Callable]]] = {}
        self._insertion_counter = 0

    def subscribe(self, event_type: EventType,
                  handler: Callable[[CombatEvent], None],
                  priority: int = 0) -> None:
        """Register a handler for *event_type*.

        Args:
            event_type: The event to listen for.
            handler: Callable invoked with a :class:`CombatEvent`.
            priority: Higher values fire first.  Default ``0``.
        """
        entry = (-priority, self._insertion_counter, handler)
        self._insertion_counter += 1
        bucket = self._handlers.setdefault(event_type, [])
        bisect.insort(bucket, entry)

    def unsubscribe(self, event_type: EventType,
                    handler: Callable[[CombatEvent], None]) -> None:
        if event_type in self._handlers:
            self._handlers[event_type] = [
                e for e in self._handlers[event_type] if e[2] is not handler
            ]

    def emit(self, event_type: EventType, data: EventData = None, **kwargs) -> CombatEvent:
        """Fire an event with typed EventData or legacy **kwargs.

        Preferred:  ``emit(EventType.X, SomeData(field=val))``
        Legacy:     ``emit(EventType.X, field=val, ...)``
        """
        if data is None:
            data = kwargs
        event = CombatEvent(event_type=event_type, data=data)
        for _, _, handler in self._handlers.get(event_type, []):
            handler(event)
            if event.cancelled:
                break
        return event
