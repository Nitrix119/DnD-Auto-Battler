from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from .events import EventType


@dataclass
class CombatEvent:
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False  # set True in a handler to abort the triggering action


class EventBus:
    def __init__(self):
        self._handlers: Dict[EventType, List[Callable[[CombatEvent], None]]] = {}

    def subscribe(self, event_type: EventType, handler: Callable[[CombatEvent], None]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[[CombatEvent], None]) -> None:
        if event_type in self._handlers:
            self._handlers[event_type].remove(handler)

    def emit(self, event_type: EventType, **data) -> CombatEvent:
        """Fire an event. Returns the event so callers can check event.cancelled."""
        event = CombatEvent(event_type=event_type, data=data)
        for handler in self._handlers.get(event_type, []):
            handler(event)
            if event.cancelled:
                break
        return event
