"""Action economy resources for D&D combat turns."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionCost:
    """Immutable resource cost for performing an action.

    All fields default to 0 — only specify the resources consumed.
    """

    actions: int = 0
    bonus_actions: int = 0
    reactions: int = 0
    movement: int = 0


# Common cost constants
ACTION_COST = ActionCost(actions=1)
BONUS_ACTION_COST = ActionCost(bonus_actions=1)
REACTION_COST = ActionCost(reactions=1)
NO_COST = ActionCost()


@dataclass
class ActionResources:
    """Mutable per-turn action economy budget for an entity."""

    actions: int = 1
    bonus_actions: int = 1
    reactions: int = 1
    movement: int = 30

    def can_afford(self, cost: ActionCost) -> bool:
        """Check whether the entity has enough resources to pay *cost*."""
        return (
            self.actions >= cost.actions
            and self.bonus_actions >= cost.bonus_actions
            and self.reactions >= cost.reactions
            and self.movement >= cost.movement
        )

    def spend(self, cost: ActionCost) -> None:
        """Deduct *cost* from current resources.

        Raises:
            ValueError: If any resource is insufficient.
        """
        if not self.can_afford(cost):
            raise ValueError(
                f"Insufficient resources: have {self}, need {cost}"
            )
        self.actions -= cost.actions
        self.bonus_actions -= cost.bonus_actions
        self.reactions -= cost.reactions
        self.movement -= cost.movement
