"""Initiative and turn order management."""

from dataclasses import dataclass, field
from typing import List, Optional

from src.models.entity import Entity
from src.utils.dice import roll_d20


@dataclass
class InitiativeEntry:
    """An entity's initiative entry.
    
    Attributes:
        entity: The entity in combat
        initiative_total: Total initiative value
    """
    entity: Entity
    initiative_total: int
    
    def __lt__(self, other: "InitiativeEntry") -> bool:
        """Compare entries for sorting (highest first)."""
        if self.initiative_total != other.initiative_total:
            return self.initiative_total > other.initiative_total
        # Tiebreaker: dexterity modifier
        return self.entity.stat_block.ability_scores.get_modifier("dexterity") > \
               other.entity.stat_block.ability_scores.get_modifier("dexterity")


class InitiativeTracker:
    """Manages initiative order for combat.
    
    Attributes:
        initiative_order: Sorted list of entities in initiative order
        current_turn_index: Index of the entity whose turn it is
    """
    
    def __init__(self) -> None:
        """Initialize an empty initiative tracker."""
        self.initiative_order: List[InitiativeEntry] = []
        self.current_turn_index: int = 0
    
    def add_entity(self, entity: Entity, initiative_modifier: int = 0) -> int:
        """Add an entity to the initiative order.
        
        Args:
            entity: The entity to add
            initiative_modifier: Additional modifier to initiative (e.g., from spells)
            
        Returns:
            The entity's total initiative value
        """
        roll = roll_d20()
        dex_mod = entity.stat_block.ability_scores.get_modifier("dexterity")
        total = roll + dex_mod + initiative_modifier
        
        entity.initiative_roll = roll
        entry = InitiativeEntry(entity, total)
        self.initiative_order.append(entry)
        self.initiative_order.sort()
        
        return total
    
    def get_current_entity(self) -> Optional[Entity]:
        """Get the entity whose turn it is.
        
        Returns:
            The current entity or None if no entities
        """
        if not self.initiative_order:
            return None
        return self.initiative_order[self.current_turn_index].entity
    
    def next_turn(self) -> Optional[Entity]:
        """Advance to the next entity's turn.
        
        Returns:
            The entity whose turn it now is
        """
        self.current_turn_index = (self.current_turn_index + 1) % len(self.initiative_order)
        return self.get_current_entity()
    
    def get_turn_order(self) -> List[Entity]:
        """Get the full turn order.
        
        Returns:
            List of entities in initiative order
        """
        return [entry.entity for entry in self.initiative_order]
    
    def get_position(self, entity: Entity) -> int:
        """Get an entity's position in initiative order.
        
        Args:
            entity: The entity to find
            
        Returns:
            The position (0-indexed) or -1 if not found
        """
        for i, entry in enumerate(self.initiative_order):
            if entry.entity == entity:
                return i
        return -1
