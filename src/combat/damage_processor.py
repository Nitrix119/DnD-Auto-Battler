"""Centralized damage application with event hooks."""

from typing import List, Optional

from src.models.entity import Entity
from src.models.damage import Damage
from .event_bus import EventBus
from .event_data import DamageIncomingData, DamageDealtData, EntityDiesData
from .events import EventType


class DamageProcessor:
    """Applies damage to entities with DAMAGE_INCOMING/DEALT/ENTITY_DIES hooks."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def apply_damage(
        self,
        defender: Entity,
        damage_list: List[Damage],
        source: Optional[Entity] = None,
        action_name: Optional[str] = None,
    ) -> int:
        """Apply damage to defender, emitting events. Returns total damage dealt.

        Emits DAMAGE_INCOMING (allows modification/cancellation),
        DAMAGE_DEALT, and ENTITY_DIES if applicable.
        """
        was_alive = defender.is_alive()

        incoming = self._event_bus.emit(
            EventType.DAMAGE_INCOMING,
            DamageIncomingData(defender=defender, damage_list=damage_list),
        )

        total_damage = 0
        if not incoming.cancelled:
            for d in damage_list:
                defender.take_damage(d)
                total_damage += d.amount

        self._event_bus.emit(
            EventType.DAMAGE_DEALT,
            DamageDealtData(
                defender=defender, damage_list=damage_list, total=total_damage,
                source=source, action_name=action_name,
            ),
        )

        if was_alive and not defender.is_alive():
            self._event_bus.emit(
                EventType.ENTITY_DIES,
                EntityDiesData(entity=defender, killer=source),
            )

        return total_damage
