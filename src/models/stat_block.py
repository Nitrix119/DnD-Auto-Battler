"""Complete stat block for D&D entities."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .ability import AbilityScores
from .skill import Skill, STANDARD_SKILLS
from .condition import Condition
from .damage import Damage
from .action import Action


@dataclass
class StatBlock:
    """Complete stat block for a D&D entity.
    
    Attributes:
        name: Entity name
        ability_scores: The six ability scores
        hit_points: Current hit points
        hit_points_max: Maximum hit points
        armor_class: Armor class value
        proficiency_bonus: Proficiency bonus
        skills: Dictionary of skills with proficiency
        actions: List of available combat actions
        saving_throws: Ability scores with saving throw proficiency
    """
    
    name: str
    ability_scores: AbilityScores
    hit_points: int
    hit_points_max: int
    armor_class: int
    proficiency_bonus: int = 2
    skills: Dict[str, Skill] = field(default_factory=dict)
    actions: List[Action] = field(default_factory=list)
    saving_throws: Dict[str, int] = field(default_factory=dict)
    conditions: List[Condition] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Initialize default skills and validate stats."""
        # Initialize with standard skills if not provided
        if not self.skills:
            self.skills = STANDARD_SKILLS.copy()
        
        # Validate HP
        if self.hit_points < 0:
            self.hit_points = 0
        if self.hit_points_max < 1:
            raise ValueError("Maximum hit points must be at least 1")
        if self.hit_points > self.hit_points_max:
            self.hit_points = self.hit_points_max
        
        # Validate AC
        if self.armor_class < 0:
            raise ValueError("Armor class cannot be negative")
    
    def get_skill_bonus(self, skill_name: str) -> int:
        """Calculate the bonus for a skill check.
        
        Args:
            skill_name: The skill to check
            
        Returns:
            The total bonus for that skill
        """
        if skill_name not in self.skills:
            raise ValueError(f"Unknown skill: {skill_name}")
        
        skill = self.skills[skill_name]
        ability_modifier = self.ability_scores.get_modifier(skill.ability)
        return skill.calculate_bonus(ability_modifier, self.proficiency_bonus)
    
    def get_saving_throw_bonus(self, ability: str) -> int:
        """Calculate the bonus for a saving throw.
        
        Args:
            ability: The ability for the save
            
        Returns:
            The total saving throw bonus
        """
        ability_modifier = self.ability_scores.get_modifier(ability)
        if ability in self.saving_throws:
            return ability_modifier + self.proficiency_bonus
        return ability_modifier
    
    def take_damage(self, damage: Damage) -> int:
        """Reduce hit points and return remaining HP.

        Args:
            damage: The damage to apply

        Returns:
            Current hit points after damage
        """
        self.hit_points = max(0, self.hit_points - damage.amount)
        return self.hit_points
    
    def heal(self, amount: int) -> int:
        """Increase hit points.
        
        Args:
            amount: The healing amount
            
        Returns:
            Current hit points after healing
        """
        self.hit_points = min(self.hit_points_max, self.hit_points + amount)
        return self.hit_points
    
    def is_alive(self) -> bool:
        """Check if entity is still alive."""
        return self.hit_points > 0
    
    def add_action(self, action: Action) -> None:
        """Add an action to available actions.
        
        Args:
            action: The action to add
        """
        self.actions.append(action)
    
    def add_condition(self, condition: Condition) -> None:
        """Add a condition to the entity.
        
        Args:
            condition: The condition to add
        """
        self.conditions.append(condition)
