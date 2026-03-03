"""Entity class representing a combatant in battle."""

from dataclasses import dataclass, field
from typing import Optional, List
import uuid

from .stat_block import StatBlock
from .condition import Condition
from .damage import Damage


@dataclass
class Entity:
    """A combatant in battle (character or creature).
    
    Attributes:
        stat_block: The entity's stat block
        entity_id: Unique identifier for the entity
        initiative_roll: Initiative roll result (set during combat)
        is_player_controlled: Whether this is player-controlled
    """
    
    stat_block: StatBlock
    entity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    initiative_roll: Optional[int] = None
    is_player_controlled: bool = False
    concentrating_on: Optional[str] = None  # spell name if currently concentrating
    
    def __post_init__(self) -> None:
        """Validate entity."""
        if not self.stat_block:
            raise ValueError("Entity must have a stat block")
    
    def __hash__(self) -> int:
        """Use entity_id for hashing."""
        return hash(self.entity_id)
    
    def __eq__(self, other) -> bool:
        """Compare entities by ID."""
        if isinstance(other, Entity):
            return self.entity_id == other.entity_id
        return False
    
    def take_damage(self, damage: Damage) -> int:
        """Damage the entity.

        Args:
            damage: The damage to apply

        Returns:
            Current hit points
        """
        return self.stat_block.take_damage(damage)
    
    def heal(self, amount: int) -> int:
        """Heal the entity.
        
        Args:
            amount: Amount to heal
            
        Returns:
            Current hit points
        """
        return self.stat_block.heal(amount)
    
    def is_alive(self) -> bool:
        """Check if entity is conscious and able to act."""
        # Check for unconscious condition
        unconscious_conditions = [
            c for c in self.stat_block.conditions 
            if c.condition_type.value == "unconscious"
        ]
        if unconscious_conditions:
            return False
        return self.stat_block.is_alive()
    
    def add_condition(self, condition: Condition) -> None:
        """Add a condition to the entity.
        
        Args:
            condition: The condition to add
        """
        self.stat_block.add_condition(condition)
    
    def remove_condition(self, condition_index: int) -> None:
        """Remove a condition by index.
        
        Args:
            condition_index: Index of the condition to remove
        """
        if 0 <= condition_index < len(self.stat_block.conditions):
            self.stat_block.conditions.pop(condition_index)
    
    def get_active_conditions(self) -> List[Condition]:
        """Get all non-expired conditions.
        
        Returns:
            List of active conditions
        """
        return self.stat_block.conditions.copy()
    
    @property
    def has_concentration(self) -> bool:
        """True if the entity is currently concentrating on a spell."""
        return self.concentrating_on is not None

    @property
    def name(self) -> str:
        """Get entity name from stat block."""
        return self.stat_block.name
    
    @property
    def hp(self) -> int:
        """Get current hit points."""
        return self.stat_block.hit_points
    
    @property
    def max_hp(self) -> int:
        """Get maximum hit points."""
        return self.stat_block.hit_points_max
    
    @property
    def ac(self) -> int:
        """Get armor class."""
        return self.stat_block.armor_class
