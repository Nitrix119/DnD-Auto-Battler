"""Combat actions available to entities."""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

from .damage import DamageType, Damage


class ActionType(Enum):
    """Types of actions in combat."""
    ATTACK = "attack"
    SPELL = "spell"
    ABILITY = "ability"
    ITEM = "item"


@dataclass
class Action:
    """Base class for combat actions.
    
    Attributes:
        name: Name of the action
        description: What the action does
        action_type: The type of action
        recharge: Recharge condition (e.g., "Recharge 5-6")
    """
    
    name: str
    description: str
    action_type: ActionType
    recharge: Optional[str] = None
    
    def __hash__(self) -> int:
        """Make action hashable for use in sets/dicts."""
        return hash(self.name)


@dataclass
class AttackAction(Action):
    """A melee or ranged attack action.
    
    Attributes:
        bonus_to_hit: Bonus applied to attack rolls
        damage: List of damage instances for a hit
        damage_half_on_save: Optional ability and DC for half damage save
    """

    action_type: ActionType = ActionType.ATTACK
    bonus_to_hit: int = 0
    damage: List[Damage] = None
    damage_half_on_save: Optional[tuple] = None  # (ability, dc)
    
    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.damage is None:
            self.damage = []


@dataclass
class SpellAction(Action):
    """A spell action.
    
    Attributes:
        spell_level: The spell slot level (0-9)
        save_dc: DC for saving throws against the spell
        damage: List of damage instances the spell deals
        spell_attack_bonus: Bonus for spell attack rolls (if applicable)
    """
    
    action_type: ActionType = ActionType.SPELL
    spell_level: int = 0
    save_dc: int = 0
    damage: List[Damage] = None
    spell_attack_bonus: int = 0
    
    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.damage is None:
            self.damage = []
        if self.spell_level < 0 or self.spell_level > 9:
            raise ValueError("Spell level must be between 0 and 9")
