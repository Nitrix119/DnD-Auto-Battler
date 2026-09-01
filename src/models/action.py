"""Combat actions available to entities."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
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
    cost: ActionCost = field(default_factory=lambda: ACTION_COST)
    source_effect: str = ""  # non-empty → revoked when that entity effect is removed
    pipeline_effects: List[Dict[str, Any]] = field(default_factory=list)
    # Native block program (authored as ``program`` in JSON, keyed by ``block``).
    # When non-empty the action is *native* and resolves via ``parse_program`` with
    # no cast-time adapter translation; when empty the legacy ``pipeline_effects``
    # path runs. Both coexist while spells migrate (Phase 3 §5).
    program: List[Dict[str, Any]] = field(default_factory=list)
    legendary_action_cost: int = 0  # > 0 → usable only as a legendary action

    def __hash__(self) -> int:
        """Make action hashable for use in sets/dicts."""
        return hash(self.name)

    @property
    def primary_damage_type(self) -> Optional[DamageType]:
        """Return the DamageType of this action's first damage, or None.

        Prefers the first ``damage`` step in ``pipeline_effects`` (spells, and a
        weapon whose steps have been compiled). Falls back to the first entry in
        ``damage`` (a weapon attack whose flat damage list is populated but whose
        ``pipeline_effects`` is built on the fly and never assigned to the action),
        so an on-hit rider resolves the weapon's type whether or not the action
        has been compiled into steps.
        """
        for step in self.pipeline_effects:
            if step.get("type") == "damage":
                type_str = step.get("damage_type", "")
                try:
                    return DamageType[type_str.upper()]
                except KeyError:
                    return None
        if self.damage:
            return self.damage[0].damage_type
        return None

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
        for d in self.damage:
            amount = roll_formula(d.formula) if d.formula else d.amount
            rolled.append(Damage(d.damage_type, amount))
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
        spell_range: How far the spell can reach
        targeting_type: Whether the spell hits a single target, an area, or special
        aoe: Area dimensions; required when targeting_type is AOE
        casting_time: How long the spell takes to cast
        duration: How long the spell's effect lasts
        components: Verbal, somatic, and/or material requirements
        higher_level_scaling: Placeholder description of upcast scaling (structured
                              rules will be added in a future task)
        pipeline_effects: Legacy sequential effect steps (authored as ``effects`` in
            JSON, keyed by ``type``), translated by ``adapter.to_program`` into a block
            program at cast time. Used only when ``program`` is empty.
        program: Native block program (authored as ``program`` in JSON, keyed by
            ``block``). When non-empty the spell resolves via ``parse_program`` with no
            cast-time translation — the target authoring form (Phase 3 §5). The two are
            mutually exclusive per spell and coexist across the corpus while it migrates.
    """

    action_type: ActionType = ActionType.SPELL
    spell_level: int = 0
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
    pipeline_effects: List[Dict[str, Any]] = field(default_factory=list)
    program: List[Dict[str, Any]] = field(default_factory=list)

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
