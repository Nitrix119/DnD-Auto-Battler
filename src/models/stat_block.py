"""Complete stat block for D&D entities.

A StatBlock is an *immutable template* describing a creature's base
statistics.  Mutable combat state (current HP, active conditions) lives on
the :class:`~src.models.entity.Entity` wrapper instead.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from .ability import AbilityScores
from .skill import Skill, STANDARD_SKILLS
from .action import Action
from .creature_size import CreatureSize

DEFAULT_RESOURCE_DEFAULTS: Dict[str, int] = {
    "actions": 1,
    "bonus_actions": 1,
    "reactions": 1,
    "speed": 30,
}


@dataclass
class StatBlock:
    """Immutable template for a D&D entity's base statistics.

    Attributes:
        name: Entity name
        ability_scores: The six ability scores
        hit_points_max: Maximum hit points
        armor_class: Armor class value
        proficiency_bonus: Proficiency bonus
        skills: Dictionary of skills with proficiency
        actions: List of available combat actions
        saving_throws: Ability scores with saving throw proficiency
        resource_defaults: Per-turn action economy defaults (actions, bonus_actions, reactions, speed)
    """

    name: str
    ability_scores: AbilityScores
    hit_points_max: int
    armor_class: int
    proficiency_bonus: int = 2
    skills: Dict[str, Skill] = field(default_factory=dict)
    actions: List[Action] = field(default_factory=list)
    saving_throws: Dict[str, int] = field(default_factory=dict)
    resource_defaults: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RESOURCE_DEFAULTS))
    size: CreatureSize = field(default=CreatureSize.MEDIUM)

    def __post_init__(self) -> None:
        """Initialize default skills and validate stats."""
        if not self.skills:
            self.skills = STANDARD_SKILLS.copy()

        if self.hit_points_max < 1:
            raise ValueError("Maximum hit points must be at least 1")

        if self.armor_class < 0:
            raise ValueError("Armor class cannot be negative")

    def get_skill_bonus(self, skill_name: str) -> int:
        """Calculate the bonus for a skill check."""
        if skill_name not in self.skills:
            raise ValueError(f"Unknown skill: {skill_name}")

        skill = self.skills[skill_name]
        ability_modifier = self.ability_scores.get_modifier(skill.ability)
        return skill.calculate_bonus(ability_modifier, self.proficiency_bonus)

    def get_saving_throw_bonus(self, ability: str) -> int:
        """Calculate the bonus for a saving throw."""
        ability_modifier = self.ability_scores.get_modifier(ability)
        if ability in self.saving_throws:
            return ability_modifier + self.proficiency_bonus
        return ability_modifier

    def add_action(self, action: Action) -> None:
        """Add an action to available actions."""
        self.actions.append(action)
