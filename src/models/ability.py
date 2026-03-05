"""Ability scores and modifiers for D&D entities."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class AbilityScores:
    """Core ability scores for a D&D entity.
    
    Attributes:
        strength: Ability to apply force
        dexterity: Agility and reflexes
        constitution: Health and endurance
        intelligence: Reasoning and memory
        wisdom: Awareness and insight
        charisma: Force of personality
    """
    
    strength: int
    dexterity: int
    constitution: int
    intelligence: int
    wisdom: int
    charisma: int
    
    def __post_init__(self) -> None:
        """Validate ability scores are in valid D&D range."""
        for ability_name in ["strength", "dexterity", "constitution", 
                             "intelligence", "wisdom", "charisma"]:
            score = getattr(self, ability_name)
            if score < 1 or score > 30:
                raise ValueError(f"{ability_name} must be between 1 and 30")
    
    def get_modifier(self, ability: str) -> int:
        """Calculate the modifier for a given ability.
        
        Args:
            ability: Name of the ability (lowercase)
            
        Returns:
            The modifier value (ability_score - 10) // 2
        """
        score = getattr(self, ability.lower())
        return (score - 10) // 2
    
    def get_all_modifiers(self) -> Dict[str, int]:
        """Get modifiers for all abilities.
        
        Returns:
            Dictionary mapping ability names to modifiers
        """
        return {
            "strength": self.get_modifier("strength"),
            "dexterity": self.get_modifier("dexterity"),
            "constitution": self.get_modifier("constitution"),
            "intelligence": self.get_modifier("intelligence"),
            "wisdom": self.get_modifier("wisdom"),
            "charisma": self.get_modifier("charisma"),
        }
