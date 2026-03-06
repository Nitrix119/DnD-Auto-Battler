"""Entity class representing a combatant in battle."""

from dataclasses import dataclass, field
from typing import Optional, List
import uuid

from .stat_block import StatBlock
from .condition import Condition, ConditionType
from .damage import Damage


@dataclass
class Entity:
    """A combatant in battle (character or creature).

    Mutable combat state (HP, conditions) lives here.  The underlying
    :class:`StatBlock` is treated as an immutable template so that multiple
    entities can safely share the same stat block.
    """

    stat_block: StatBlock
    entity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    initiative_roll: Optional[int] = None
    is_player_controlled: bool = False
    current_hp: Optional[int] = None  # None → set to max in __post_init__
    conditions: List[Condition] = field(default_factory=list)
    team: Optional[str] = None  # faction/team identifier; None = hostile to everyone
    concentrating_on: Optional[str] = None
    active_effects: dict = field(default_factory=dict)  # {trigger_str: [Rule, ...]}

    def __post_init__(self) -> None:
        """Validate entity and initialize mutable state."""
        if not self.stat_block:
            raise ValueError("Entity must have a stat block")
        if self.current_hp is None:
            self.current_hp = self.stat_block.hit_points_max

    def __hash__(self) -> int:
        return hash(self.entity_id)

    def __eq__(self, other) -> bool:
        if isinstance(other, Entity):
            return self.entity_id == other.entity_id
        return False

    # ------------------------------------------------------------------
    # HP management
    # ------------------------------------------------------------------

    def take_damage(self, damage: Damage) -> int:
        """Reduce hit points and return remaining HP."""
        self.current_hp = max(0, self.current_hp - damage.amount)
        return self.current_hp

    def heal(self, amount: int) -> int:
        """Increase hit points, capped at maximum."""
        self.current_hp = min(self.stat_block.hit_points_max, self.current_hp + amount)
        return self.current_hp

    def is_alive(self) -> bool:
        """Check if entity is conscious and able to act."""
        for c in self.conditions:
            if c.condition_type == ConditionType.UNCONSCIOUS:
                return False
        return self.current_hp > 0

    # ------------------------------------------------------------------
    # Condition management
    # ------------------------------------------------------------------

    def add_condition(self, condition: Condition) -> None:
        """Add a condition to the entity."""
        self.conditions.append(condition)

    def remove_condition(self, condition_index: int) -> None:
        """Remove a condition by index."""
        if 0 <= condition_index < len(self.conditions):
            self.conditions.pop(condition_index)

    def get_active_conditions(self) -> List[Condition]:
        """Get all non-expired conditions."""
        return self.conditions.copy()

    # ------------------------------------------------------------------
    # Effect management (for rule engine)
    # ------------------------------------------------------------------

    def add_effect(self, trigger: str, effect) -> None:
        """Add an effect to the trigger bucket."""
        self.active_effects.setdefault(trigger, []).append(effect)

    def remove_effect(self, name: str) -> None:
        """Remove all effects matching this name across all trigger buckets."""
        for bucket in self.active_effects.values():
            bucket[:] = [e for e in bucket if e.name != name]

    def get_effects_for_trigger(self, trigger: str) -> list:
        """Get all effects for a given trigger string."""
        return self.active_effects.get(trigger, [])

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def has_concentration(self) -> bool:
        return self.concentrating_on is not None

    @property
    def name(self) -> str:
        return self.stat_block.name

    @property
    def hp(self) -> int:
        return self.current_hp

    @property
    def max_hp(self) -> int:
        return self.stat_block.hit_points_max

    @property
    def ac(self) -> int:
        return self.stat_block.armor_class
