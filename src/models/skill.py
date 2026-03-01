"""Skills and skill proficiencies for D&D entities."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProficiencyLevel(Enum):
    """Proficiency levels for skills and saving throws."""
    NONE = 0
    PROFICIENT = 1
    EXPERT = 2  # Expertise or Jack of All Trades doubling


@dataclass
class Skill:
    """A skill with proficiency and associated ability.
    
    Attributes:
        name: The skill name
        ability: The ability score it's based on
        proficiency: The proficiency level
    """
    
    name: str
    ability: str  # e.g., "strength", "dexterity"
    proficiency: ProficiencyLevel = ProficiencyLevel.NONE
    
    def calculate_bonus(self, ability_modifier: int, proficiency_bonus: int) -> int:
        """Calculate total skill bonus.
        
        Args:
            ability_modifier: The modifier from the related ability score
            proficiency_bonus: The character's proficiency bonus
            
        Returns:
            Total skill bonus
        """
        bonus = ability_modifier
        if self.proficiency == ProficiencyLevel.PROFICIENT:
            bonus += proficiency_bonus
        elif self.proficiency == ProficiencyLevel.EXPERT:
            bonus += proficiency_bonus * 2
        return bonus


# Standard D&D 5e skills
STANDARD_SKILLS = {
    "acrobatics": Skill("Acrobatics", "dexterity"),
    "animal_handling": Skill("Animal Handling", "wisdom"),
    "arcana": Skill("Arcana", "intelligence"),
    "athletics": Skill("Athletics", "strength"),
    "deception": Skill("Deception", "charisma"),
    "history": Skill("History", "intelligence"),
    "insight": Skill("Insight", "wisdom"),
    "intimidation": Skill("Intimidation", "charisma"),
    "investigation": Skill("Investigation", "intelligence"),
    "medicine": Skill("Medicine", "wisdom"),
    "nature": Skill("Nature", "intelligence"),
    "perception": Skill("Perception", "wisdom"),
    "performance": Skill("Performance", "charisma"),
    "persuasion": Skill("Persuasion", "charisma"),
    "sleight_of_hand": Skill("Sleight of Hand", "dexterity"),
    "stealth": Skill("Stealth", "dexterity"),
    "survival": Skill("Survival", "wisdom"),
}
