"""Damage types and damage calculations."""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class DamageType(Enum):
    """D&D 5e damage types."""
    ACID = "acid"
    BLUDGEONING = "bludgeoning"
    COLD = "cold"
    FIRE = "fire"
    FORCE = "force"
    LIGHTNING = "lightning"
    NECROTIC = "necrotic"
    PIERCING = "piercing"
    POISON = "poison"
    PSYCHIC = "psychic"
    RADIANT = "radiant"
    SLASHING = "slashing"
    THUNDER = "thunder"


@dataclass
class Damage:
    """Represents damage of a specific type and amount.
    
    Attributes:
        damage_type: The type of damage
        amount: The amount of damage dealt
        formula: Optional dice formula for damage (e.g., "2d6+3")
    """
    
    damage_type: DamageType
    amount: int
    formula: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate damage amount."""
        if self.amount < 0:
            raise ValueError("Damage amount cannot be negative")
