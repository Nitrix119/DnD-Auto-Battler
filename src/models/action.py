"""Combat actions available to entities."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from .action_resources import ActionCost, ACTION_COST, BONUS_ACTION_COST, REACTION_COST
from .damage import DamageType, Damage
from src.utils.dice import roll_formula
from .spell_properties import (
    SpellRange, RangeType,
    TargetingType,
    AOEProperties,
    CastingTime, CastingTimeType,
    Duration, DurationUnit,
    SpellComponents,
)


class ActionType(Enum):
    """Types of actions in combat."""
    ATTACK = "attack"
    SPELL = "spell"
    ABILITY = "ability"
    ITEM = "item"


@dataclass
class Action:
    """Base class for combat actions.
    
    Attributes:
        name: Name of the action
        description: What the action does
        action_type: The type of action
        recharge: Recharge condition (e.g., "Recharge 5-6")
    """
    
    name: str
    description: str
    action_type: ActionType
    recharge: Optional[str] = None
    damage: List[Damage] = field(default_factory=list)
    bonus_damage: List[Damage] = field(default_factory=list)
    cost: ActionCost = field(default_factory=lambda: ACTION_COST)

    def __hash__(self) -> int:
        """Make action hashable for use in sets/dicts."""
        return hash(self.name)

    def roll_damage(self) -> List[Damage]:
        """Roll all damage formulas and return concrete Damage instances.

        Each entry in damage is rolled independently and returned as a new
        Damage object with a concrete amount and the original damage type.
        Entries without a formula use their fixed amount directly.

        bonus_damage entries are also included and consumed (cleared) so that
        one-shot additions (e.g. Colossus Slayer) don't persist to future attacks.

        Returns:
            List of Damage objects with rolled amounts, one per damage entry.
        """
        rolled = []
        for d in self.damage + self.bonus_damage:
            amount = roll_formula(d.formula) if d.formula else d.amount
            rolled.append(Damage(d.damage_type, amount))
        self.bonus_damage.clear()
        return rolled


@dataclass
class AttackAction(Action):
    """A melee or ranged attack action.
    
    Attributes:
        bonus_to_hit: Bonus applied to attack rolls
        damage: List of damage instances for a hit
        damage_half_on_save: Optional ability and DC for half damage save
    """

    action_type: ActionType = ActionType.ATTACK
    bonus_to_hit: int = 0
    damage_half_on_save: Optional[tuple] = None  # (ability, dc)
    range_ft: float = 5.0


@dataclass
class SpellAction(Action):
    """A spell action.

    Attributes:
        spell_level: The spell slot level (0 for cantrip, 1-9 for levelled spells)
        save_dc: DC for saving throws against the spell
        damage: List of damage instances the spell deals
        spell_attack_bonus: Bonus for spell attack rolls (if applicable)
        spell_range: How far the spell can reach
        targeting_type: Whether the spell hits a single target, an area, or special
        aoe: Area dimensions; required when targeting_type is AOE
        casting_time: How long the spell takes to cast
        duration: How long the spell's effect lasts
        components: Verbal, somatic, and/or material requirements
        higher_level_scaling: Placeholder description of upcast scaling (structured
                              rules will be added in a future task)
    """

    action_type: ActionType = ActionType.SPELL
    spell_level: int = 0
    save_dc: Union[int, str] = 0          # int, or "use_caster_dc" to derive at cast time
    save_ability: str = ""               # ability used for saving throws (e.g. "wisdom", "charisma")
    spell_attack_bonus: Union[int, str] = 0  # int, or "use_caster_bonus" to derive at cast time
    spell_range: SpellRange = field(default_factory=lambda: SpellRange(RangeType.TOUCH))
    targeting_type: TargetingType = TargetingType.SINGLE_TARGET
    aoe: Optional[AOEProperties] = None
    casting_time: CastingTime = field(default_factory=lambda: CastingTime(CastingTimeType.ACTION))
    duration: Duration = field(default_factory=lambda: Duration(DurationUnit.INSTANTANEOUS))
    components: SpellComponents = field(default_factory=lambda: SpellComponents(verbal=True, somatic=True))
    higher_level_scaling: Optional[str] = None  # TODO: structured scaling rules
    can_target_self: bool = False
    cannot_cause_self_damage: bool = False
    animation: List[Any] = field(default_factory=list)
    spell_effects: List[Dict[str, Any]] = field(default_factory=list)
    on_successful_save: List[Dict[str, Any]] = field(default_factory=list)
    on_failed_save: List[Dict[str, Any]] = field(default_factory=list)
    """Entity effects applied to the defender on spell hit.

    Each entry is a dict with:
      ``effect``         (str)  — name of the entity effect (looked up via EffectRegistry)
      ``condition``      (str, optional) — expression evaluated at spell hit time;
                         skipped if falsy.  Context includes ``event`` (SpellHitData
                         fields), ``save_success`` (bool), ``save_roll`` (int | None).
      ``instance_fields`` (dict, optional) — mapping of field name → expression
                         string, each evaluated at spell hit time and passed to
                         ``apply_effect`` as ``instance_fields``.
    """

    _CASTING_TIME_COST_MAP = {
        CastingTimeType.ACTION: ACTION_COST,
        CastingTimeType.BONUS_ACTION: BONUS_ACTION_COST,
        CastingTimeType.REACTION: REACTION_COST,
    }

    def __post_init__(self) -> None:
        """Validate spell properties and derive cost from casting time."""
        if self.spell_level < 0 or self.spell_level > 9:
            raise ValueError("Spell level must be between 0 and 9")
        if self.targeting_type == TargetingType.AOE and self.aoe is None:
            raise ValueError("AOE spells must have aoe (AOEProperties) specified")
        # Auto-derive cost from casting_time when using the default (1 action)
        if self.cost == ACTION_COST:
            self.cost = self._CASTING_TIME_COST_MAP.get(
                self.casting_time.time_type, ACTION_COST
            )
