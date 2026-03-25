"""Legendary action economy for boss creatures."""

from dataclasses import dataclass, field


@dataclass
class LegendaryActions:
    """Tracks legendary action uses for a creature.

    Per D&D 5e rules, a creature with legendary actions can take a set number
    of special actions outside its normal turn.  The pool recharges at the
    start of the creature's own turn.

    Attributes:
        count_per_round: Maximum legendary actions per round.
        remaining: Currently available legendary actions.
    """

    count_per_round: int
    remaining: int = field(init=False)

    def __post_init__(self) -> None:
        self.remaining = self.count_per_round

    @classmethod
    def from_dict(cls, data: dict) -> "LegendaryActions":
        """Construct from a JSON dict like ``{"count_per_round": 3}``."""
        return cls(count_per_round=int(data.get("count_per_round", 3)))

    def can_use(self, cost: int = 1) -> bool:
        """Return True if *cost* legendary actions are available."""
        return self.remaining >= cost

    def spend(self, cost: int = 1) -> None:
        """Consume *cost* legendary actions.

        Raises:
            ValueError: If insufficient legendary actions remain.
        """
        if not self.can_use(cost):
            raise ValueError(
                f"Not enough legendary actions remaining "
                f"({self.remaining} available, {cost} needed)"
            )
        self.remaining -= cost

    def refill(self) -> None:
        """Restore all legendary actions (called at start of own turn)."""
        self.remaining = self.count_per_round
