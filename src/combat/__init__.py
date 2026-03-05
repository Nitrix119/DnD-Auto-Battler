"""Combat package initialization."""

from .enums import CombatState, ActionCategory
from .initiative import InitiativeTracker, InitiativeEntry
from .combat_system import CombatSystem, CombatLog
from .event_bus import EventBus, CombatEvent
from .events import EventType
from .damage_processor import DamageProcessor
from .attack_resolver import AttackResolver
from .spell_resolver import SpellResolver
from .turn_manager import TurnManager
from .event_data import (
    EventData,
    RoundEventData,
    TurnEventData,
    AttackDeclaredData,
    AttackHitData,
    AttackMissData,
    SpellCastData,
    SpellHitData,
    DamageIncomingData,
    DamageDealtData,
    EntityDiesData,
    ConditionAddedData,
    ConditionRemovedData,
)

__all__ = [
    "CombatState",
    "ActionCategory",
    "InitiativeTracker",
    "InitiativeEntry",
    "CombatSystem",
    "CombatLog",
    "EventBus",
    "CombatEvent",
    "EventType",
    "DamageProcessor",
    "AttackResolver",
    "SpellResolver",
    "TurnManager",
    "EventData",
    "RoundEventData",
    "TurnEventData",
    "AttackDeclaredData",
    "AttackHitData",
    "AttackMissData",
    "SpellCastData",
    "SpellHitData",
    "DamageIncomingData",
    "DamageDealtData",
    "EntityDiesData",
    "ConditionAddedData",
    "ConditionRemovedData",
]
