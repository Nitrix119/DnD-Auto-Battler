from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.combat.events import EventType


@dataclass
class Rule:
    """A declarative combat rule loaded from JSON.

    Attributes:
        name: Human-readable identifier (used in logs / debugging).
        trigger: The event type that activates this rule.
        effects: Ordered list of effect configurations to execute.
        condition: Optional Python expression string. The rule fires only when
            this evaluates to a truthy value. The expression runs with ``event``
            in scope as a SimpleNamespace wrapping the event's data dict.
        enabled: Set to False to temporarily disable without unloading.
    """

    name: str
    trigger: EventType
    effects: List[Dict[str, Any]]
    condition: Optional[str] = None
    enabled: bool = True
