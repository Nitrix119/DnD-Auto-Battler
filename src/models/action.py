"""Combat actions available to entities."""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from .damage import DamageType, Damage
from .spell_properties import (
    SpellRange, RangeType,
    TargetingType,
    AOEProperties,
    CastingTime, CastingTimeType,
    Duration, DurationUnit,
    SpellComponents,
)


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
        spell_level: The spell slot level (0 for cantrip, 1-9 for levelled spells)
        save_dc: DC for saving throws against the spell
        damage: List of damage instances the spell deals
        spell_attack_bonus: Bonus for spell attack rolls (if applicable)
        spell_range: How far the spell can reach
        targeting_type: Whether the spell hits a single target, an area, or special
        aoe: Area dimensions; required when targeting_type is AOE
        casting_time: How long the spell takes to cast
        duration: How long the spell's effect lasts
        components: Verbal, somatic, and/or material requirements
        higher_level_scaling: Placeholder description of upcast scaling (structured
                              rules will be added in a future task)
    """

    action_type: ActionType = ActionType.SPELL
    spell_level: int = 0
    save_dc: int = 0
    damage: List[Damage] = None
    spell_attack_bonus: int = 0
    spell_range: SpellRange = field(default_factory=lambda: SpellRange(RangeType.TOUCH))
    targeting_type: TargetingType = TargetingType.SINGLE_TARGET
    aoe: Optional[AOEProperties] = None
    casting_time: CastingTime = field(default_factory=lambda: CastingTime(CastingTimeType.ACTION))
    duration: Duration = field(default_factory=lambda: Duration(DurationUnit.INSTANTANEOUS))
    components: SpellComponents = field(default_factory=lambda: SpellComponents(verbal=True, somatic=True))
    higher_level_scaling: Optional[str] = None  # TODO: structured scaling rules

    def __post_init__(self) -> None:
        """Initialize default values and validate."""
        if self.damage is None:
            self.damage = []
        if self.spell_level < 0 or self.spell_level > 9:
            raise ValueError("Spell level must be between 0 and 9")
        if self.targeting_type == TargetingType.AOE and self.aoe is None:
            raise ValueError("AOE spells must have aoe (AOEProperties) specified")
