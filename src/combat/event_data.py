"""Typed event data classes for each EventType.

Each dataclass defines the exact fields an event type carries, replacing the
untyped ``Dict[str, Any]`` bag.  The ``EventData`` base class provides
dict-like access (``__getitem__``, ``__setitem__``, ``get``, ``keys``) so that
existing code using ``event.data["key"]``, ``event.data.get("key")``, and
``SimpleNamespace(**event.data)`` continues to work unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Iterator, List, Optional

if TYPE_CHECKING:
    from src.models.action import Action, SpellAction
    from src.models.condition import Condition, ConditionType
    from src.models.damage import Damage
    from src.models.entity import Entity
    from src.spatial.geometry import Point3D


class EventData:
    """Base providing dict-like access over dataclass fields + dynamic attrs.

    Supports:
    - ``data["key"]`` / ``data["key"] = val`` via __getitem__/__setitem__
    - ``data.get("key", default)``
    - ``**data`` unpacking (keys() + __getitem__)
    - ``"key" in data``
    """

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> list:
        result = [f.name for f in fields(self)]
        for k in self.__dict__:
            if k not in result and not k.startswith("_"):
                result.append(k)
        return result

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())


# ── Turn lifecycle ────────────────────────────────────────────────────────────

@dataclass
class RoundEventData(EventData):
    """Data for ROUND_START and ROUND_END events."""
    round_num: int


@dataclass
class TurnEventData(EventData):
    """Data for TURN_START and TURN_END events."""
    entity: Entity
    round_num: int
    turn_num: int


# ── Attack flow ───────────────────────────────────────────────────────────────

@dataclass
class AttackDeclaredData(EventData):
    """Data for ATTACK_DECLARED events.

    ``advantage`` and ``disadvantage`` default to False and may be set to True
    by effect handlers (e.g. GrantAdvantage, GrantDisadvantage).
    """
    attacker: Entity
    defender: Entity
    action: Action
    advantage: bool = False
    disadvantage: bool = False

@dataclass
class AttackRolledData(EventData):
    """Data for ATTACK_ROLLED events."""
    attacker: Entity
    defender: Entity
    action: Action
    roll: int
    total: int

@dataclass
class AttackHitData(EventData):
    """Data for ATTACK_HIT events."""
    attacker: Entity
    defender: Entity
    action: Action
    roll: int


@dataclass
class AttackMissData(EventData):
    """Data for ATTACK_MISS events."""
    attacker: Entity
    defender: Entity
    action: Action
    roll: int


# ── Spell flow ────────────────────────────────────────────────────────────────

@dataclass
class SpellCastData(EventData):
    """Data for SPELL_CAST events."""
    caster: Entity
    defenders: List[Entity]
    action: SpellAction
    origin: Optional[Point3D] = None  # AoE centre/apex; None for single-target spells


@dataclass
class SpellHitData(EventData):
    """Data for SPELL_HIT events."""
    caster: Entity
    defender: Entity
    action: SpellAction
    roll: Optional[int]
    save_success: bool = True   # True when no save required or defender succeeded
    save_roll: Optional[int] = None  # d20 total for the saving throw, if one was made


# ── Saving throw flow ─────────────────────────────────────────────────────────

@dataclass
class SavingThrowDeclaredData(EventData):
    """Data for SAVING_THROW_DECLARED events.

    Emitted just before a saving throw is rolled.  ``advantage`` and
    ``disadvantage`` default to False and may be set True by effect handlers
    (e.g. a Restrained creature has disadvantage on Dexterity saving throws).
    Per D&D 5e, if both are set they cancel to a normal roll.
    """
    defender: Entity
    ability: str
    dc: int
    advantage: bool = False
    disadvantage: bool = False


# ── Damage flow ───────────────────────────────────────────────────────────────

@dataclass
class DamageIncomingData(EventData):
    """Data for DAMAGE_INCOMING events."""
    defender: Entity
    damage_list: List[Damage]


@dataclass
class DamageDealtData(EventData):
    """Data for DAMAGE_DEALT events."""
    defender: Entity
    damage_list: List[Damage]
    total: int
    source: Optional[Entity] = None      # entity that caused the damage
    action_name: Optional[str] = None    # name of the action that caused the damage



# ── Healing flow ──────────────────────────────────────────────────────────────

@dataclass
class HealingAppliedData(EventData):
    """Data for HEALING_APPLIED events."""
    target: Entity
    amount: int


# ── Entity lifecycle ─────────────────────────────────────────────────────────

@dataclass
class EntityDiesData(EventData):
    """Data for ENTITY_DIES events."""
    entity: Entity
    killer: Optional[Entity]


@dataclass
class ConditionAddedData(EventData):
    """Data for CONDITION_ADDED events."""
    entity: Entity
    condition: Condition


@dataclass
class ConditionRemovedData(EventData):
    """Data for CONDITION_REMOVED events."""
    entity: Entity
    condition_type: ConditionType
