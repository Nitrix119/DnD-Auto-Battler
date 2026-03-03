"""Spell property types: range, targeting, casting time, duration, and components."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List


# ---------------------------------------------------------------------------
# Range
# ---------------------------------------------------------------------------

class RangeType(Enum):
    """How a spell's range is measured."""
    SELF = "self"
    TOUCH = "touch"
    FEET = "feet"
    SIGHT = "sight"
    UNLIMITED = "unlimited"
    SPECIAL = "special"


@dataclass
class SpellRange:
    """Range of a spell.

    Attributes:
        range_type: Category of range
        distance_ft: Distance in feet; required when range_type is FEET
    """
    range_type: RangeType
    distance_ft: Optional[int] = None

    def __post_init__(self) -> None:
        if self.range_type == RangeType.FEET:
            if self.distance_ft is None or self.distance_ft < 0:
                raise ValueError("distance_ft must be a non-negative int when range_type is FEET")

    def __str__(self) -> str:
        if self.range_type == RangeType.FEET:
            return f"{self.distance_ft} ft."
        return self.range_type.value.capitalize()


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------

class TargetingType(Enum):
    """How a spell selects its targets."""
    SINGLE_TARGET = "single_target"
    AOE = "aoe"
    SPECIAL = "special"


class AOEShape(Enum):
    """Geometric shapes for area-of-effect spells."""
    SPHERE = "sphere"
    CONE = "cone"
    CYLINDER = "cylinder"
    CUBE = "cube"
    LINE = "line"
    SPECIAL = "special"


@dataclass
class AOEProperties:
    """Dimensions of an area-of-effect spell.

    Attributes:
        shape: Geometric shape of the area
        size_ft: Radius for sphere/cylinder, side length for cube,
                 length for cone/line (in feet)
    """
    shape: AOEShape
    size_ft: int

    def __post_init__(self) -> None:
        if self.size_ft <= 0:
            raise ValueError("AOE size_ft must be positive")

    def __str__(self) -> str:
        label = "radius" if self.shape in (AOEShape.SPHERE, AOEShape.CYLINDER) else "length"
        if self.shape == AOEShape.CUBE:
            label = "side"
        return f"{self.shape.value.capitalize()} ({self.size_ft} ft. {label})"


# ---------------------------------------------------------------------------
# Casting time
# ---------------------------------------------------------------------------

class CastingTimeType(Enum):
    """Categories of spell casting time."""
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    INSTANT = "instant"
    MINUTE = "minute"
    HOUR = "hour"
    SPECIAL = "special"


@dataclass
class CastingTime:
    """How long it takes to cast a spell.

    Attributes:
        time_type: Category of casting time
        count: Number of actions/minutes/hours (ignored for BONUS_ACTION,
               REACTION, INSTANT, and SPECIAL)
        reaction_trigger: Description of what triggers this reaction cast
        special_description: Free-text description when time_type is SPECIAL
    """
    time_type: CastingTimeType
    count: int = 1
    reaction_trigger: Optional[str] = None
    special_description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("Casting time count must be at least 1")

    def __str__(self) -> str:
        t = self.time_type
        if t == CastingTimeType.ACTION:
            return f"{self.count} action{'s' if self.count > 1 else ''}"
        if t == CastingTimeType.BONUS_ACTION:
            return "1 bonus action"
        if t == CastingTimeType.REACTION:
            trigger = f" ({self.reaction_trigger})" if self.reaction_trigger else ""
            return f"1 reaction{trigger}"
        if t == CastingTimeType.INSTANT:
            return "Instant"
        if t == CastingTimeType.MINUTE:
            return f"{self.count} minute{'s' if self.count > 1 else ''}"
        if t == CastingTimeType.HOUR:
            return f"{self.count} hour{'s' if self.count > 1 else ''}"
        # SPECIAL
        return self.special_description or "Special"


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

class DurationUnit(Enum):
    """Units of time for spell duration."""
    INSTANTANEOUS = "instantaneous"
    ROUND = "round"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    UNTIL_DISPELLED = "until_dispelled"
    SPECIAL = "special"


_TIMED_UNITS = {DurationUnit.ROUND, DurationUnit.MINUTE, DurationUnit.HOUR, DurationUnit.DAY}


@dataclass
class Duration:
    """How long a spell's effect lasts.

    Attributes:
        unit: Unit of duration
        count: Number of units; used only for ROUND/MINUTE/HOUR/DAY
        concentration: Whether the spell requires concentration to maintain
        special_description: Free-text description when unit is SPECIAL
    """
    unit: DurationUnit
    count: int = 1
    concentration: bool = False
    special_description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.unit == DurationUnit.INSTANTANEOUS and self.concentration:
            raise ValueError("Instantaneous spells cannot require concentration")
        if self.unit in _TIMED_UNITS and self.count < 1:
            raise ValueError("Duration count must be at least 1")

    def __str__(self) -> str:
        prefix = "Concentration, up to " if self.concentration else ""
        u = self.unit
        if u == DurationUnit.INSTANTANEOUS:
            return "Instantaneous"
        if u == DurationUnit.ROUND:
            return f"{prefix}{self.count} round{'s' if self.count > 1 else ''}"
        if u == DurationUnit.MINUTE:
            return f"{prefix}{self.count} minute{'s' if self.count > 1 else ''}"
        if u == DurationUnit.HOUR:
            return f"{prefix}{self.count} hour{'s' if self.count > 1 else ''}"
        if u == DurationUnit.DAY:
            return f"{prefix}{self.count} day{'s' if self.count > 1 else ''}"
        if u == DurationUnit.UNTIL_DISPELLED:
            return f"{prefix}Until dispelled"
        # SPECIAL
        return self.special_description or "Special"


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

@dataclass
class SpellComponents:
    """Components required to cast a spell.

    Attributes:
        verbal: Whether the spell requires a verbal (V) component
        somatic: Whether the spell requires a somatic (S) component
        material: List of material component descriptions (empty if none)
    """
    verbal: bool
    somatic: bool
    material: List[str] = field(default_factory=list)

    @property
    def requires_material(self) -> bool:
        return bool(self.material)

    def __str__(self) -> str:
        parts = []
        if self.verbal:
            parts.append("V")
        if self.somatic:
            parts.append("S")
        if self.material:
            parts.append(f"M ({'; '.join(self.material)})")
        return ", ".join(parts) if parts else "None"
