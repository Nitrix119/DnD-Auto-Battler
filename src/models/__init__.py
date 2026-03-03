"""D&D models package containing data structures for entities and combat."""

from .ability import AbilityScores
from .skill import Skill, ProficiencyLevel
from .condition import Condition, ConditionType
from .damage import DamageType, Damage
from .spell_properties import (
    RangeType, SpellRange,
    TargetingType,
    AOEShape, AOEProperties,
    CastingTimeType, CastingTime,
    DurationUnit, Duration,
    SpellComponents,
)
from .action import ActionType, Action, AttackAction, SpellAction
from .stat_block import StatBlock
from .entity import Entity

__all__ = [
    "AbilityScores",
    "Skill",
    "ProficiencyLevel",
    "Condition",
    "ConditionType",
    "DamageType",
    "Damage",
    "RangeType",
    "SpellRange",
    "TargetingType",
    "AOEShape",
    "AOEProperties",
    "CastingTimeType",
    "CastingTime",
    "DurationUnit",
    "Duration",
    "SpellComponents",
    "ActionType",
    "Action",
    "AttackAction",
    "SpellAction",
    "StatBlock",
    "Entity",
]
