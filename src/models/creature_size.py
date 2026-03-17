"""Creature size categories and their spatial footprints."""

from enum import Enum


_SIZE_TO_FEET = {
    "tiny": 2.5,
    "small": 5.0,
    "medium": 5.0,
    "large": 10.0,
    "huge": 15.0,
    "gargantuan": 20.0,
}


class CreatureSize(Enum):
    """D&D creature size categories.

    Each size maps to the side length (in feet) of the square space the
    creature occupies on the combat grid.  Both SMALL and MEDIUM creatures
    occupy a single 5-ft square, as per the rules.  GARGANTUAN represents
    the minimum 20×20 ft footprint; truly larger creatures still use this
    value as a floor.
    """

    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HUGE = "huge"
    GARGANTUAN = "gargantuan"

    @property
    def size_ft(self) -> float:
        """Side length in feet of the creature's square footprint."""
        return _SIZE_TO_FEET[self.value]
