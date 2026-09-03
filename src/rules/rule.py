from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Rule:
    """A declarative combat rule loaded from JSON.

    A rule's reactive behaviour is authored as a block ``program``: a list of
    ``trigger`` blocks naming the events they fire on and the sub-program each runs.
    The events live *inside* the program, so a rule carries no separate trigger list.

    Attributes:
        name: Human-readable identifier (used in logs / debugging, and as the key a
            lifetime scope is named by so ``remove_effect`` can dispose the rider).
        program: The block program — the rule's trigger blocks.
        duration_rounds: None = permanent; set for entity effects that expire.
        source: What applied this effect (spell name, item, etc.).
    """

    name: str
    program: List[Dict[str, Any]]
    duration_rounds: Optional[int] = None
    source: str = ""
