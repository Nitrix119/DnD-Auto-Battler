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
        duration_rounds: Number of rounds the condition lasts (None = indefinite)
        source: What caused the condition (e.g., spell name)
    """
    
    condition_type: ConditionType
    duration_rounds: Optional[int] = None
    source: str = ""
    
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
