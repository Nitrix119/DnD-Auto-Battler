"""Conditions and status effects for D&D entities."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.models.lifetime import LifetimeScope


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
            for reference; auto-expiry is driven by ``owning_scope``.
        source: What caused the condition (e.g., spell name)
    """

    condition_type: ConditionType
    duration_rounds: Optional[int] = None
    source: str = ""
    effect_name: str = ""  # rule/effect name; used by Entity.remove_effect for cleanup
    # The lifetime scope that owns this condition's marker and its installed reactive
    # rider. Every condition applied through the ``apply_condition`` block has one; it
    # is the sole duration clock, and disposing it tears the condition (and its
    # mechanics) down together — on expiry, concentration loss, or dispel.
    owning_scope: Optional["LifetimeScope"] = field(
        default=None, init=False, repr=False, compare=False
    )

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
