"""Spell slot tracking for spellcasting entities."""

from dataclasses import dataclass, field


@dataclass
class SpellSlots:
    """Tracks available and remaining spell slots per level.

    Attributes:
        max_slots: Maximum number of slots at each spell level {level: count}.
        remaining: Currently available slots {level: count}.
    """

    max_slots: dict  # {int level: int count}
    remaining: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.remaining:
            self.remaining = dict(self.max_slots)

    @classmethod
    def from_dict(cls, data: dict) -> "SpellSlots":
        """Construct from a JSON dict like ``{"1": 4, "2": 3, "3": 2}``."""
        max_slots = {int(k): int(v) for k, v in data.items()}
        return cls(max_slots=max_slots)

    def can_afford(self, level: int) -> bool:
        """Return True if at least one slot of *level* remains."""
        return self.remaining.get(level, 0) > 0

    def spend(self, level: int) -> None:
        """Consume one slot of *level*.

        Raises:
            ValueError: If no slots of that level remain.
        """
        if not self.can_afford(level):
            raise ValueError(f"No spell slots remaining at level {level}")
        self.remaining[level] -= 1

    def refill(self) -> None:
        """Restore all slots to their maximum (long rest)."""
        self.remaining = dict(self.max_slots)
