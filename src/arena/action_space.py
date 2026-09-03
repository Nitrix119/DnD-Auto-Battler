"""Assemble the set of actions an entity may legally take right now.

Nothing in the engine assembles this today: :meth:`CombatSystem.get_affordable_actions`
reads only ``stat_block.actions`` (missing ``granted_actions``) and does not range-check,
check spell slots, or expand ``known_spells`` into castable spells. This module fills that
gap by combining the existing pieces —

* attacks/abilities from ``stat_block.actions`` + ``granted_actions``, filtered by
  :meth:`Entity.can_afford`;
* spells from ``stat_block.known_spells``, resolved through the combat's spell registry and
  filtered by action-economy cost *and* remaining spell slots;
* targets from :meth:`CombatSystem.get_alive_entities`, each range-checked via
  :mod:`src.spatial.range_check`;
* the remaining movement budget.

The result is a **hint**, embedded in an agent's observation so it can see its options; the
engine's ``resolve_*`` methods remain the authority that actually enforces legality.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

from src.models.action import Action, AttackAction, SpellAction
from src.models.action_resources import ActionCost
from src.models.entity import Entity
from src.models.spell_properties import TargetingType
from src.spatial.range_check import (
    check_attack_range,
    check_single_target_range,
    effective_range_ft,
)

if TYPE_CHECKING:  # avoid importing the whole combat stack at module load
    from src.combat.combat_system import CombatSystem


@dataclass(frozen=True)
class TargetOption:
    """A single entity an action may be aimed at."""

    entity_id: str
    name: str

    def to_dict(self) -> dict:
        return {"entity_id": self.entity_id, "name": self.name}


@dataclass(frozen=True)
class AttackOption:
    """A weapon/attack action the entity can afford, and who it can reach."""

    name: str
    cost: dict
    range_ft: float
    targets: List[TargetOption]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cost": self.cost,
            "range_ft": self.range_ft,
            "targets": [t.to_dict() for t in self.targets],
        }


@dataclass(frozen=True)
class SpellOption:
    """A spell the entity knows, can afford, and has a slot for.

    Attributes:
        targeting: The spell's targeting mode (``single_target``/``aoe``/…).
        targets: In-range entities for single-target spells; empty for AoE and
            multi-target spells, which are aimed at a point (``target_point``) or
            assigned per projectile by the caster.
        range_ft: Numeric range in feet, or ``None`` when unlimited/self.
        castable_levels: Slot levels this spell may be cast at right now (its base
            level and any higher level with a remaining slot). ``[0]`` for a cantrip.
    """

    name: str
    cost: dict
    spell_level: int
    targeting: str
    range_ft: Optional[float]
    castable_levels: List[int]
    targets: List[TargetOption]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cost": self.cost,
            "spell_level": self.spell_level,
            "targeting": self.targeting,
            "range_ft": self.range_ft,
            "castable_levels": self.castable_levels,
            "targets": [t.to_dict() for t in self.targets],
        }


@dataclass(frozen=True)
class LegalActions:
    """Everything *entity* may legally attempt on its turn, as a menu.

    A hint for the agent, not an enforcement boundary — the engine still validates
    each chosen action. ``can_end_turn`` is always True (ending a turn is always legal).
    """

    entity_id: str
    movement_remaining_ft: float
    attacks: List[AttackOption] = field(default_factory=list)
    spells: List[SpellOption] = field(default_factory=list)
    can_end_turn: bool = True

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "movement_remaining_ft": self.movement_remaining_ft,
            "attacks": [a.to_dict() for a in self.attacks],
            "spells": [s.to_dict() for s in self.spells],
            "can_end_turn": self.can_end_turn,
        }


def _cost_to_dict(cost: ActionCost) -> dict:
    return {
        "actions": cost.actions,
        "bonus_actions": cost.bonus_actions,
        "reactions": cost.reactions,
        "movement": cost.movement,
    }


def _attack_targets(
    combat: "CombatSystem", attacker: Entity, action: AttackAction
) -> List[TargetOption]:
    """Alive entities (other than *attacker*) within the attack's range."""
    reachable: List[TargetOption] = []
    for other in combat.get_alive_entities():
        if other is attacker:
            continue
        try:
            check_attack_range(attacker, other, action)
        except ValueError:
            continue
        reachable.append(TargetOption(other.entity_id, other.name))
    return reachable


def _spell_targets(
    combat: "CombatSystem", caster: Entity, action: SpellAction
) -> List[TargetOption]:
    """In-range entities for a single-target spell.

    AoE / multi-target / special spells are aimed at a point or assigned per
    projectile, so no fixed target list is produced for them.
    """
    if action.targeting_type != TargetingType.SINGLE_TARGET:
        return []
    reachable: List[TargetOption] = []
    for other in combat.get_alive_entities():
        if other is caster and not action.can_target_self:
            continue
        try:
            check_single_target_range(caster, other, action)
        except ValueError:
            continue
        reachable.append(TargetOption(other.entity_id, other.name))
    return reachable


def _castable_levels(caster: Entity, action: SpellAction) -> List[int]:
    """Slot levels *action* can be cast at right now.

    A cantrip (level 0) needs no slot and is always ``[0]``. A levelled spell can
    be cast at its base level or any higher level for which a slot remains.
    """
    base = action.spell_level
    if base == 0:
        return [0]
    if caster.spell_slots is None:
        return []
    max_level = max(caster.spell_slots.max_slots) if caster.spell_slots.max_slots else 0
    return [
        level
        for level in range(base, max_level + 1)
        if caster.spell_slots.can_afford(level)
    ]


def _owned_attacks(entity: Entity) -> List[Action]:
    """Attack/ability actions the entity carries directly (innate + granted)."""
    return list(entity.stat_block.actions) + list(entity.granted_actions)


def legal_actions(combat: "CombatSystem", entity: Entity) -> LegalActions:
    """Assemble the legal-action menu for *entity* in *combat*.

    Read-only: it inspects resources, slots, and ranges but changes nothing. Spells
    are skipped when the combat has no spell registry configured, or a known spell is
    absent from it (the engine would raise at cast time — the menu simply omits it).
    """
    result = LegalActions(
        entity_id=entity.entity_id,
        movement_remaining_ft=entity.resources.movement,
    )
    attacks: List[AttackOption] = []
    spells: List[SpellOption] = []

    for action in _owned_attacks(entity):
        if not isinstance(action, AttackAction):
            continue
        if not entity.can_afford(action.cost):
            continue
        attacks.append(
            AttackOption(
                name=action.name,
                cost=_cost_to_dict(action.cost),
                range_ft=action.range_ft,
                targets=_attack_targets(combat, entity, action),
            )
        )

    registry = combat.spell_registry
    if registry is not None:
        for spell_name in entity.stat_block.known_spells:
            if spell_name not in registry:
                continue
            action = registry.get(spell_name)
            if not entity.can_afford(action.cost):
                continue
            levels = _castable_levels(entity, action)
            if not levels:
                continue
            spells.append(
                SpellOption(
                    name=action.name,
                    cost=_cost_to_dict(action.cost),
                    spell_level=action.spell_level,
                    targeting=action.targeting_type.value,
                    range_ft=effective_range_ft(action),
                    castable_levels=levels,
                    targets=_spell_targets(combat, entity, action),
                )
            )

    return LegalActions(
        entity_id=result.entity_id,
        movement_remaining_ft=result.movement_remaining_ft,
        attacks=attacks,
        spells=spells,
    )
