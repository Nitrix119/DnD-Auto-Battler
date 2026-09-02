from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.combat.events import EventType


@dataclass
class Rule:
    """A declarative combat rule loaded from JSON.

    Attributes:
        name: Human-readable identifier (used in logs / debugging).
        triggers: The event types that activate this rule. A rule registered
            with multiple triggers will fire on any of them.
        effects: Ordered list of effect configurations to execute.  Each effect
            may optionally contain an ``"on"`` key specifying which event type(s)
            it responds to, allowing different effects within the same rule to
            fire on different triggers.
        condition: Optional Python expression string. The rule fires only when
            this evaluates to a truthy value. The expression runs with ``event``
            in scope as a SimpleNamespace wrapping the event's data dict.
        enabled: Set to False to temporarily disable without unloading.
    """

    name: str
    triggers: List[EventType]
    effects: List[Dict[str, Any]]
    condition: Optional[str] = None
    enabled: bool = True
    duration_rounds: Optional[int] = None  # None = permanent; set for entity effects that expire
    source: str = ""                       # what applied this effect (spell name, item, etc.)
    # Native block program (authored as ``program`` in JSON, keyed by ``block``).
    # When non-empty the rule is *native*: its reactive behaviour is authored directly
    # as ``trigger`` blocks and the install seams run it via ``parse_program`` with no
    # ``fold`` translation of the legacy ``triggers``/``effects`` shape (Phase 3 §5). A
    # native rule leaves ``triggers``/``effects`` empty — its events live in its blocks —
    # so it is never subscribed to the legacy dispatch. The two shapes coexist per file
    # while the rule corpus migrates.
    program: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self):
        # Validate the condition string against the AST whitelist at load time.
        # This must happen before compile() so that rule conditions — which are
        # later passed to evaluate() as code objects — are still validated.
        if self.condition:
            from src.rules.expressions import _validate_ast  # local import avoids circular
            _validate_ast(self.condition)
        # Pre-compile the condition expression once so eval() uses bytecode on
        # every subsequent trigger rather than re-parsing the string each time.
        self._compiled_condition = (
            compile(self.condition, f"<rule:{self.name}>", "eval")
            if self.condition else None
        )
