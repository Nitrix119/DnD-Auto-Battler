"""Combat system enums and related types."""

from enum import Enum


class CombatState(Enum):
    """State of a combat encounter."""
    SETUP = "setup"
    ACTIVE = "active"
    ENDED = "ended"


class ActionCategory(Enum):
    """Categories of actions in a turn."""
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    MOVEMENT = "movement"
