"""Turn and round lifecycle management."""

from typing import List, Optional

from src.models.condition import ConditionType
from src.models.entity import Entity
from .event_bus import EventBus
from .event_data import RoundEventData, TurnEventData
from .events import EventType
from .initiative import InitiativeTracker

# Conditions that prevent an entity from taking any meaningful action.
# Entities with any of these conditions have their turn skipped automatically.
_SKIP_CONDITIONS: frozenset[ConditionType] = frozenset({
    ConditionType.UNCONSCIOUS,
    ConditionType.INCAPACITATED,
    ConditionType.PARALYZED,
    ConditionType.STUNNED,
    ConditionType.PETRIFIED,
})


def _should_skip(entity: Entity) -> bool:
    """Return True if the entity's conditions prevent them from acting."""
    return any(c.condition_type in _SKIP_CONDITIONS for c in entity.conditions)


class TurnManager:
    """Manages turn advancement, round tracking, and dead-entity skipping."""

    def __init__(
        self,
        event_bus: EventBus,
        initiative_tracker: InitiativeTracker,
        combatants: List[Entity],
    ) -> None:
        self._event_bus = event_bus
        self._initiative_tracker = initiative_tracker
        self._combatants = combatants
        self.round: int = 0
        self.turn: int = 0

    def start(self) -> None:
        """Begin the first round."""
        self.round = 1
        self.turn = 1
        self._event_bus.emit(EventType.ROUND_START, RoundEventData(round_num=self.round))
        self._event_bus.emit(
            EventType.TURN_START,
            TurnEventData(
                entity=self._initiative_tracker.get_current_entity(),
                round_num=self.round,
                turn_num=self.turn,
            ),
        )

    def end_turn(self) -> bool:
        """End the current turn and advance.

        Returns:
            True if combat should continue, False if <=1 combatant alive.
        """
        current = self._initiative_tracker.get_current_entity()
        self._event_bus.emit(
            EventType.TURN_END,
            TurnEventData(entity=current, round_num=self.round, turn_num=self.turn),
        )

        next_entity = self._initiative_tracker.next_turn()
        self.turn += 1

        if self._initiative_tracker.current_turn_index == 0:
            self._event_bus.emit(EventType.ROUND_END, RoundEventData(round_num=self.round))
            self.round += 1
            self.turn = 1
            self._event_bus.emit(EventType.ROUND_START, RoundEventData(round_num=self.round))

        alive = [c for c in self._combatants if c.is_alive()]
        if len(alive) <= 1:
            return False

        # Skip entities whose conditions prevent acting (unconscious, stunned, etc.).
        # Guard against the degenerate case where every remaining entity is incapacitated.
        skips = 0
        max_skips = len(self._combatants)
        while next_entity is not None and _should_skip(next_entity):
            if skips >= max_skips:
                return False  # All entities are incapacitated; end combat.
            next_entity = self._initiative_tracker.next_turn()
            self.turn += 1
            skips += 1
            if self._initiative_tracker.current_turn_index == 0:
                self._event_bus.emit(EventType.ROUND_END, RoundEventData(round_num=self.round))
                self.round += 1
                self.turn = 1
                self._event_bus.emit(EventType.ROUND_START, RoundEventData(round_num=self.round))

        self._event_bus.emit(
            EventType.TURN_START,
            TurnEventData(entity=next_entity, round_num=self.round, turn_num=self.turn),
        )
        return True

    def get_current_entity(self) -> Optional[Entity]:
        """Get the entity whose turn it is."""
        return self._initiative_tracker.get_current_entity()
