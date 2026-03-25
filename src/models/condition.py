"""Conditions and status effects for D&D entities."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ConditionType(Enum):
    """Standard D&D 5e conditions."""
    BLINDED = "blinded"
    CHARMED = "charmed"
    DEAFENED = "deafened"
    EXHAUSTION = "exhaustion"
    FRIGHTENED = "frightened"
    GRAPPLED = "grappled"
    INCAPACITATED = "incapacitated"
    INVISIBLE = "invisible"
    PARALYZED = "paralyzed"
    PETRIFIED = "petrified"
    POISONED = "poisoned"
    PRONE = "prone"
    RESTRAINED = "restrained"
    STUNNED = "stunned"
    UNCONSCIOUS = "unconscious"


@dataclass
class Condition:
    """A condition affecting an entity.

    Attributes:
        condition_type: The type of condition
        duration_rounds: Initial duration in rounds (None = indefinite).  Kept
            for reference; auto-expiry is driven by ``rounds_remaining``.
        rounds_remaining: Countdown ticked by ``RuleEngine._tick_durations`` at
            the end of the conditioned entity's turn.  Initialised from
            ``duration_rounds`` automatically.  ``None`` means the condition
            persists until explicitly removed.
        source: What caused the condition (e.g., spell name)
    """

    condition_type: ConditionType
    duration_rounds: Optional[int] = None
    rounds_remaining: Optional[int] = field(default=None, init=False)
    source: str = ""
    effect_name: str = ""  # rule/effect name; used by Entity.remove_effect for cleanup

    def __post_init__(self) -> None:
        self.rounds_remaining = self.duration_rounds

    def is_expired(self, rounds_elapsed: int) -> bool:
        """Check if the condition has expired.

        Args:
            rounds_elapsed: Number of rounds that have passed

        Returns:
            True if the condition has expired
        """
        if self.duration_rounds is None:
            return False
        return rounds_elapsed >= self.duration_rounds
