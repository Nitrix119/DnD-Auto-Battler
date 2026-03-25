"""Main combat simulation system."""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

from src.models.entity import Entity
from src.models.action import Action, AttackAction, SpellAction
from .spell_registry import SpellRegistry
from src.models.action_resources import ActionCost
from src.models.spell_properties import AOEProperties, AOEShape, RangeType, TargetingType
from src.utils.dice import roll_d20
from src.spatial.geometry import BoundingBox, Point3D, Vector3D
from src.spatial.aoe import (
    AOEVolume, SphereVolume, CylinderVolume, ConeVolume, CubeVolume, LineVolume,
)
from .enums import CombatState
from .event_bus import EventBus
from .initiative import InitiativeTracker
from .damage_processor import DamageProcessor
from .attack_resolver import AttackResolver
from .spell_resolver import SpellResolver
from .turn_manager import TurnManager


@dataclass
class CombatLog:
    """A single entry in the combat log.

    Attributes:
        round_num: The round this occurred
        turn_num: The turn within the round
        actor: The entity performing the action
        action: Description of what happened
    """
    round_num: int
    turn_num: int
    actor: Entity
    action: str


class CombatSystem:
    """Main combat simulator for D&D battles.

    Manages turn order, action resolution, and damage calculation.
    Delegates to focused collaborators for specific concerns.
    """

    def __init__(self) -> None:
        """Initialize a new combat encounter."""
        self.state: CombatState = CombatState.SETUP
        self.initiative_tracker: InitiativeTracker = InitiativeTracker()
        self.combatants: List[Entity] = []
        self.log: List[CombatLog] = []
        self._turn_manager: Optional[TurnManager] = None
        self._spell_registry = None
        self.event_bus: EventBus = EventBus()

    @property
    def event_bus(self) -> EventBus:
        """The event bus for this combat."""
        return self._event_bus

    @event_bus.setter
    def event_bus(self, bus: EventBus) -> None:
        self._event_bus = bus
        self._damage_processor = DamageProcessor(bus)
        self._attack_resolver = AttackResolver(bus, self._damage_processor)
        self._spell_resolver = SpellResolver(bus, self._damage_processor, self._attack_resolver)
        # Preserve any previously set rule_engine across bus re-assignments
        if hasattr(self, "_rule_engine") and self._rule_engine is not None:
            self._spell_resolver.rule_engine = self._rule_engine

    @property
    def spell_registry(self):
        """The spell registry used to look up spells by name."""
        return self._spell_registry

    @spell_registry.setter
    def spell_registry(self, registry) -> None:
        self._spell_registry = registry

    def get_spell_for_entity(self, entity: Entity, spell_name: str) -> SpellAction:
        """Return the SpellAction for *spell_name* if *entity* knows it.

        Args:
            entity: The entity attempting to cast the spell.
            spell_name: The name of the spell to look up.

        Returns:
            The SpellAction from the registry.

        Raises:
            RuntimeError: If no spell registry has been configured.
            ValueError: If *entity* does not know the spell.
            KeyError: If the spell is not found in the registry.
        """
        if self._spell_registry is None:
            raise RuntimeError(
                "No spell registry configured on CombatSystem; "
                "set combat.spell_registry before looking up spells"
            )
        if spell_name not in entity.stat_block.known_spells:
            raise ValueError(
                f"{entity.name} does not know the spell {spell_name!r}"
            )
        return self._spell_registry.get(spell_name)

    @property
    def rule_engine(self):
        """The rule engine used for spell effect application."""
        return getattr(self, "_rule_engine", None)

    @rule_engine.setter
    def rule_engine(self, engine) -> None:
        self._rule_engine = engine
        self._spell_resolver.rule_engine = engine

    @property
    def round(self) -> int:
        """Current round number."""
        return self._turn_manager.round if self._turn_manager else 0

    @property
    def turn(self) -> int:
        """Current turn number within the round."""
        return self._turn_manager.turn if self._turn_manager else 0

    def add_combatant(self, entity: Entity, initiative_modifier: int = 0) -> None:
        """Add an entity to combat.

        Args:
            entity: The entity to add
            initiative_modifier: Optional modifier to initiative
        """
        if self.state != CombatState.SETUP:
            raise RuntimeError("Cannot add combatants after combat has started")

        self.combatants.append(entity)
        self.initiative_tracker.add_entity(entity, initiative_modifier)

    def start_combat(self) -> None:
        """Begin combat with all added entities."""
        if self.state != CombatState.SETUP:
            raise RuntimeError("Combat already started")
        if len(self.combatants) < 2:
            raise ValueError("Need at least 2 combatants")

        self.state = CombatState.ACTIVE
        self._turn_manager = TurnManager(
            self.event_bus, self.initiative_tracker, self.combatants,
        )
        self._log_action(self.initiative_tracker.get_current_entity(),
                        "Combat started!")
        self._turn_manager.start()

    def resolve_attack(self, attacker: Entity, defender: Entity,
                       action: AttackAction) -> Tuple[bool, int]:
        """Resolve an attack roll and damage.

        Args:
            attacker: Entity making the attack
            defender: Entity being attacked
            action: The attack action

        Returns:
            Tuple of (hit, total_damage)

        Raises:
            ValueError: If it is not the attacker's turn.
            ValueError: If the attacker cannot afford the action's cost.
            ValueError: If the defender is out of the attack's range.
        """
        self._assert_active(attacker)
        self._check_attack_range(attacker, defender, action)

        if not attacker.can_afford(action.cost):
            raise ValueError(
                f"{attacker.name} cannot afford {action.name}: "
                f"have {attacker.resources}, need {action.cost}"
            )
        attacker.spend_resources(action.cost)

        hit, total_damage, log_msg, roll_detail = self._attack_resolver.resolve(
            attacker, defender, action,
        )
        if log_msg:
            self._log_action(attacker, log_msg)
        return hit, total_damage, roll_detail

    def resolve_spell(
        self,
        caster: Entity,
        defenders: List[Entity],
        action: SpellAction,
        *,
        target: Optional[Point3D] = None,
    ) -> List[Tuple[Entity, bool, int]]:
        """Resolve a spell action against one or more targets.

        For **AOE spells**, *target* (the point the caster aimed at) is
        required.  The system derives the AoE origin and direction from that
        point, clamps the origin to the spell's range when it is too far away,
        then automatically determines every alive entity whose bounding box
        overlaps the area.  The provided *defenders* list is ignored for AOE
        spells when *target* is supplied.

        For **single-target spells**, *defenders* is used as-is but every
        defender is range-checked against the caster.

        Args:
            caster: Entity casting the spell.
            defenders: Entities to target.  Ignored for AOE when *target* is
                given; required for single-target spells.
            action: The spell action being resolved.
            target: Point the caster aimed at.  Required for AOE spells.

        Returns:
            List of (hit, damage_dealt) per defender.

        Raises:
            ValueError: If it is not the caster's turn.
            ValueError: If the caster cannot afford the spell's cost.
            ValueError: If an AOE spell is cast without a *target*.
            ValueError: If a single-target defender is out of range.
        """
        self._assert_active(caster)
        if not caster.can_afford(action.cost):
            raise ValueError(
                f"{caster.name} cannot afford {action.name}: "
                f"have {caster.resources}, need {action.cost}"
            )
        caster.spend_resources(action.cost)

        origin: Optional[Point3D] = None

        if action.targeting_type == TargetingType.AOE:
            if target is None:
                raise ValueError(
                    f"{action.name} is an AOE spell and requires a target point"
                )
            origin, direction = self._derive_aoe_origin(caster, action, target)
            defenders = self.get_targets_in_aoe(origin, action.aoe, direction)
            if action.cannot_cause_self_damage:
                defenders = [d for d in defenders if d is not caster]
        else:
            # Single-target (or SPECIAL): range-check each defender if target given
            if target is not None:
                for defender in defenders:
                    self._check_single_target_range(caster, defender, action)

        results = self._spell_resolver.resolve(caster, defenders, action, origin=origin)
        for _, _, log_msg, _, _, _ in results:
            if log_msg:
                self._log_action(caster, log_msg)
        return [
            (defenders[i], hit, damage, roll_detail, healing, healed)
            for i, (hit, damage, _, roll_detail, healing, healed) in enumerate(results)
        ]

    def resolve_saving_throw(self, defender: Entity, ability: str,
                            dc: int) -> Tuple[int, bool]:
        """Resolve a saving throw.

        Args:
            defender: Entity making the save
            ability: The ability for the save
            dc: The DC of the save

        Returns:
            Tuple of (save_roll_total, success)
        """
        roll = roll_d20()
        bonus = defender.stat_block.get_saving_throw_bonus(ability)
        total = roll + bonus

        success = total >= dc
        return total, success

    def end_turn(self, entity_id: Optional[str] = None) -> None:
        """End the current entity's turn and advance to the next.

        Args:
            entity_id: When provided, the entity requesting the end of
                turn is validated against the active set.  Pass ``None``
                (default) to skip the check — preserves backward
                compatibility with tests and the AI loop.

        Raises:
            ValueError: If *entity_id* is provided but not active.
        """
        if entity_id is not None:
            entity = next(
                (e for e in self.combatants if e.entity_id == entity_id),
                None,
            )
            if entity is None:
                raise ValueError(f"Unknown entity_id: {entity_id!r}")
            self._assert_active(entity)
        should_continue = self._turn_manager.end_turn()
        if not should_continue:
            self.end_combat()
        else:
            self._log_action(self._turn_manager.get_current_entity(), "takes turn")

    def end_combat(self) -> None:
        """End the combat encounter."""
        self.state = CombatState.ENDED
        alive = [c for c in self.combatants if c.is_alive()]

        if len(alive) == 1:
            self._log_action(alive[0], f"wins the battle!")
        elif len(alive) == 0:
            self._log_action(None, "Combat ended with no survivors")
        else:
            self._log_action(None, "Combat ended")

    def get_current_entity(self) -> Optional[Entity]:
        """Get the entity whose turn it is."""
        return self.initiative_tracker.get_current_entity()

    @property
    def active_entity_ids(self) -> frozenset:
        """IDs of entities that may act this turn.

        Phase 1: always a singleton containing the entity at
        ``current_turn_index``.

        Phase 2 (future — simultaneous allied turns): replace this body
        with logic that collects all consecutive same-team entities from
        ``current_turn_index`` forward.  Every enforcement call site
        (``_assert_active``) is unchanged; only this property changes.
        """
        current = self.initiative_tracker.get_current_entity()
        if current is None:
            return frozenset()
        return frozenset({current.entity_id})

    def _assert_active(self, entity: Entity) -> None:
        """Raise ValueError if *entity* is not in the active turn group.

        Args:
            entity: The entity attempting to act.

        Raises:
            ValueError: When it is not *entity*'s turn.
        """
        if entity.entity_id not in self.active_entity_ids:
            current = self.initiative_tracker.get_current_entity()
            whose = current.name if current else "nobody"
            raise ValueError(
                f"It is not {entity.name}'s turn (active: {whose})"
            )

    def get_alive_entities(self) -> List[Entity]:
        """Get all entities still in the fight."""
        return [e for e in self.combatants if e.is_alive()]

    def get_affordable_actions(self, entity: Entity) -> List[Action]:
        """Return actions the entity can currently afford."""
        return [a for a in entity.stat_block.actions if entity.can_afford(a.cost)]

    def get_enemies(self, entity: Entity) -> List[Entity]:
        """Get all alive enemies of a given entity.

        When *entity.team* is set, enemies are entities on a different team
        (or with no team).  When *entity.team* is ``None``, all other alive
        entities are considered enemies.
        """
        if entity.team is None:
            return [e for e in self.get_alive_entities() if e != entity]
        return [e for e in self.get_alive_entities()
                if e != entity and e.team != entity.team]

    def get_allies(self, entity: Entity) -> List[Entity]:
        """Get all alive allies of a given entity (same team, excluding self).

        Returns an empty list if *entity.team* is ``None``.
        """
        if entity.team is None:
            return []
        return [e for e in self.get_alive_entities()
                if e != entity and e.team == entity.team]

    # ------------------------------------------------------------------
    # Spell range and AoE helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _caster_center(entity: Entity) -> Point3D:
        """Return the centre of the entity's bounding box."""
        return entity.bounding_box.center()

    @staticmethod
    def _effective_range_ft(action: SpellAction) -> Optional[float]:
        """Return the numeric spell range in feet, or None when unlimited.

        SELF and directed shapes (CONE/LINE) return None so no clamping is
        applied.  TOUCH uses the standard 5 ft melee reach.
        """
        rt = action.spell_range.range_type
        if rt == RangeType.FEET:
            return float(action.spell_range.distance_ft)
        if rt == RangeType.TOUCH:
            return 5.0
        return None  # SELF, SIGHT, UNLIMITED, SPECIAL → no clamping

    @staticmethod
    def _clamp_to_range(
        caster_center: Point3D,
        target: Point3D,
        range_ft: float,
    ) -> Point3D:
        """Return *target* clamped so it is at most *range_ft* from *caster_center*.

        If the target is already within range it is returned unchanged.
        If the target coincides with the caster centre (zero-length vector)
        the caster centre itself is returned.
        """
        dist = caster_center.distance_to(target)
        if dist <= range_ft:
            return target
        if dist == 0.0:
            return caster_center
        v = target - caster_center  # Vector3D
        return caster_center + v.scale(range_ft / dist)

    def _derive_aoe_origin(
        self,
        caster: Entity,
        action: SpellAction,
        target: Point3D,
    ) -> Tuple[Point3D, Optional[Vector3D]]:
        """Derive the AoE volume origin and direction from the target point.

        For CONE and LINE the origin is always the caster's centre; the target
        merely supplies the direction the volume faces.

        For SPHERE, CYLINDER, and CUBE the target IS the origin (after
        clamping to range when needed).

        Returns:
            (origin, direction) — direction is None for SPHERE/CYLINDER since
            those volumes are symmetric and need no orientation.
        """
        caster_center = self._caster_center(caster)
        shape = action.aoe.shape

        # Compute direction from caster toward target
        diff = target - caster_center
        try:
            direction: Optional[Vector3D] = diff.normalized()
        except ValueError:
            # target == caster_center: choose an arbitrary forward direction
            direction = Vector3D(1.0, 0.0, 0.0)

        # Offset directed shapes to the caster's token edge so the AOE begins
        # where the caster's reach ends rather than at their centre.
        half_size = caster.stat_block.size.size_ft / 2.0

        if shape in (AOEShape.CONE, AOEShape.LINE):
            edge_origin = caster_center + direction.scale(half_size)
            return edge_origin, direction

        # SPHERE, CYLINDER, CUBE: origin is the (possibly clamped) target.
        # Range is measured from the caster's edge, so allow half_size extra
        # from centre when clamping.
        range_ft = self._effective_range_ft(action)
        if range_ft is not None:
            origin = self._clamp_to_range(caster_center, target, range_ft + half_size)
        else:
            origin = target

        # SPHERE and CYLINDER are rotationally symmetric — no direction needed
        if shape in (AOEShape.SPHERE, AOEShape.CYLINDER):
            return origin, None

        # CUBE needs direction so the face faces toward the caster
        return origin, direction

    def _check_attack_range(
        self,
        attacker: Entity,
        defender: Entity,
        action: AttackAction,
    ) -> None:
        """Raise ValueError when *defender* is beyond the attack's range.

        Range is measured edge-to-edge between the two bounding boxes, so a
        creature's own footprint does not eat into its reach.  The gap on each
        axis is ``max(0, a_min - b_max, b_min - a_max)``; the 3-D distance is
        the Euclidean length of the per-axis gaps.
        """
        a = attacker.bounding_box
        d = defender.bounding_box
        gap_x = max(0.0, a.min_corner.x - d.max_corner.x, d.min_corner.x - a.max_corner.x)
        gap_y = max(0.0, a.min_corner.y - d.max_corner.y, d.min_corner.y - a.max_corner.y)
        gap_z = max(0.0, a.min_corner.z - d.max_corner.z, d.min_corner.z - a.max_corner.z)
        dist = math.sqrt(gap_x ** 2 + gap_y ** 2 + gap_z ** 2)
        if dist > action.range_ft:
            raise ValueError(
                f"{attacker.name} cannot use {action.name}: "
                f"{defender.name} is out of range "
                f"({dist:.1f} ft, max {action.range_ft:.0f} ft)"
            )

    def _check_single_target_range(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
    ) -> None:
        """Raise ValueError when *defender* is out of the spell's range.

        Uses the nearest point on the defender's bounding box for the distance
        measurement, which is the most generous (and D&D-compliant) approach.
        """
        range_ft = self._effective_range_ft(action)
        if range_ft is None:
            return  # unlimited range
        caster_center = self._caster_center(caster)
        nearest = defender.bounding_box.nearest_point(caster_center)
        dist = caster_center.distance_to(nearest)
        # Range is measured from the caster's edge: allow half_size extra from centre.
        half_size = caster.stat_block.size.size_ft / 2.0
        if dist > range_ft + half_size:
            raise ValueError(
                f"{action.name}: {defender.name} is out of range "
                f"({dist:.1f} ft, max {range_ft:.0f} ft)"
            )

    # ------------------------------------------------------------------
    # Spatial movement
    # ------------------------------------------------------------------

    def move_entity(
        self,
        entity: Entity,
        new_x: float,
        new_y: float,
        new_z: float = 0.0,
    ) -> None:
        """Move *entity* to a new position, consuming movement resources.

        The movement cost is the ceiling of the straight-line Euclidean
        distance to the destination (in feet).

        Args:
            entity: The entity to move.
            new_x: Destination x coordinate.
            new_y: Destination y coordinate.
            new_z: Destination z coordinate (default 0.0).

        Raises:
            ValueError: If it is not the entity's turn.
            ValueError: If the entity lacks sufficient movement resources.
            ValueError: If the destination overlaps an alive entity.
        """
        self._assert_active(entity)
        distance = math.sqrt(
            (new_x - entity.x) ** 2
            + (new_y - entity.y) ** 2
            + (new_z - entity.z) ** 2
        )
        cost_ft = round(distance, 1)
        movement_cost = ActionCost(movement=cost_ft)

        if not entity.can_afford(movement_cost):
            raise ValueError(
                f"{entity.name} cannot afford to move {cost_ft} ft "
                f"(has {entity.resources.movement} ft remaining)"
            )

        self._check_movement_overlap(entity, new_x, new_y, new_z)

        entity.spend_resources(movement_cost)
        entity.x = new_x
        entity.y = new_y
        entity.z = new_z

    def push_entity(
        self,
        entity: Entity,
        new_x: float,
        new_y: float,
        new_z: float = 0.0,
    ) -> None:
        """Forcibly move *entity* without spending movement resources.

        Use this for knockback, spell-driven displacement, or any other
        involuntary movement that does *not* consume the entity's speed.

        Args:
            entity: The entity being pushed.
            new_x: Destination x coordinate.
            new_y: Destination y coordinate.
            new_z: Destination z coordinate (default 0.0).

        Raises:
            ValueError: If the destination overlaps an alive entity.
        """
        self._check_movement_overlap(entity, new_x, new_y, new_z)
        entity.x = new_x
        entity.y = new_y
        entity.z = new_z

    def _check_movement_overlap(
        self,
        moving: Entity,
        new_x: float,
        new_y: float,
        new_z: float,
    ) -> None:
        """Raise ValueError if placing *moving* at the new position overlaps any alive entity.

        Dead entities (corpses) do not block movement and are skipped.
        """
        s = moving.stat_block.size.size_ft
        half = s / 2.0
        new_bbox = BoundingBox(
            min_corner=Point3D(new_x - half, new_y, new_z - half),
            max_corner=Point3D(new_x + half, new_y + s, new_z + half),
        )
        for other in self.get_alive_entities():
            if other is moving:
                continue
            if new_bbox.overlaps(other.bounding_box):
                raise ValueError(
                    f"{moving.name} cannot move to ({new_x}, {new_y}, {new_z}): "
                    f"destination overlaps {other.name}"
                )

    # ------------------------------------------------------------------
    # AoE targeting
    # ------------------------------------------------------------------

    def get_targets_in_aoe(
        self,
        origin: Point3D,
        aoe: AOEProperties,
        direction: Optional[Vector3D] = None,
    ) -> List[Entity]:
        """Return all alive entities whose AABB overlaps the described AoE volume.

        Args:
            origin: Point of origin for the AoE.
                    SPHERE/CYLINDER: centre point.
                    CONE: apex.
                    CUBE: centre of the caster-facing face.
                    LINE: start point.
            aoe: Shape and size of the area.
            direction: Required for CONE, CUBE, and LINE.  Ignored for
                       SPHERE and CYLINDER.

        Returns:
            List of alive :class:`Entity` objects whose bounding boxes
            overlap the volume.

        Raises:
            ValueError: If *direction* is required but not provided.
            ValueError: If *aoe.shape* is SPECIAL (not spatially modelled).
        """
        volume = self._build_aoe_volume(origin, aoe, direction)
        return [e for e in self.get_alive_entities() if volume.contains_entity(e)]

    def _build_aoe_volume(
        self,
        origin: Point3D,
        aoe: AOEProperties,
        direction: Optional[Vector3D],
    ) -> AOEVolume:
        """Instantiate the :class:`AOEVolume` matching *aoe*."""
        shape = aoe.shape

        if shape == AOEShape.SPHERE:
            return SphereVolume(center=origin, radius=float(aoe.size_ft))

        if shape == AOEShape.CYLINDER:
            height = float(aoe.height_ft if aoe.height_ft is not None else aoe.size_ft)
            return CylinderVolume(
                center_x=origin.x,
                center_z=origin.z,
                base_y=origin.y,
                radius=float(aoe.size_ft),
                height=height,
            )

        if shape == AOEShape.SPECIAL:
            raise ValueError(f"AoE shape {shape.value!r} is not spatially modelled")

        if direction is None:
            raise ValueError(
                f"AoE shape {shape.value!r} requires a direction vector"
            )

        if shape == AOEShape.CONE:
            return ConeVolume(apex=origin, direction=direction, length=float(aoe.size_ft))

        if shape == AOEShape.CUBE:
            return CubeVolume(origin=origin, direction=direction, size_ft=float(aoe.size_ft))

        if shape == AOEShape.LINE:
            width = float(aoe.width_ft if aoe.width_ft is not None else 5)
            return LineVolume(
                origin=origin,
                direction=direction,
                length=float(aoe.size_ft),
                width=width,
            )

        raise ValueError(f"AoE shape {shape.value!r} is not supported")

    def _log_action(self, actor: Optional[Entity], action: str) -> None:
        """Log an action to the combat log.

        Args:
            actor: The entity performing the action
            action: Description of the action
        """
        entry = CombatLog(self.round, self.turn, actor, action)
        self.log.append(entry)

    def get_combat_log(self) -> List[str]:
        """Get a formatted combat log.

        Returns:
            List of formatted log entries
        """
        formatted = []
        for entry in self.log:
            actor_name = entry.actor.name if entry.actor else "System"
            formatted.append(f"R{entry.round_num}T{entry.turn_num} [{actor_name}] {entry.action}")
        return formatted
