"""Range checking and AoE origin derivation helpers.

These functions were originally private methods on CombatSystem.  They live
here so the spatial logic can be tested independently and reused without
importing the combat subsystem.

Keeping them in a dedicated file (rather than geometry.py) avoids a circular
import: geometry.py is imported by Entity, and Entity is imported here.
"""

import math
from typing import Optional, Tuple, TYPE_CHECKING

from src.spatial.geometry import BoundingBox, Point3D, Vector3D
from src.models.spell_properties import AOEShape, RangeType
from src.models.action import AttackAction, SpellAction

if TYPE_CHECKING:
    from src.models.entity import Entity

# Standard melee / touch reach in feet (D&D 5e default for Medium/Small creatures).
TOUCH_REACH_FT: float = 5.0


def effective_range_ft(action: SpellAction) -> Optional[float]:
    """Return the numeric spell range in feet, or None when unlimited.

    SELF and directed shapes (CONE/LINE) return None so no clamping is
    applied.  TOUCH uses the standard 5 ft melee reach.
    """
    rt = action.spell_range.range_type
    if rt == RangeType.FEET:
        return float(action.spell_range.distance_ft)
    if rt == RangeType.TOUCH:
        return TOUCH_REACH_FT
    return None  # SELF, SIGHT, UNLIMITED, SPECIAL → no clamping


def clamp_to_range(
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
    v = target - caster_center
    return caster_center + v.scale(range_ft / dist)


def check_attack_range(
    attacker: "Entity",
    defender: "Entity",
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


def check_single_target_range(
    caster: "Entity",
    defender: "Entity",
    action: SpellAction,
) -> None:
    """Raise ValueError when *defender* is out of the spell's range.

    Uses the nearest point on the defender's bounding box for the distance
    measurement, which is the most generous (and D&D-compliant) approach.
    """
    range_ft = effective_range_ft(action)
    if range_ft is None:
        return  # unlimited range
    caster_center = caster.bounding_box.center()
    nearest = defender.bounding_box.nearest_point(caster_center)
    dist = caster_center.distance_to(nearest)
    # Range is measured from the caster's edge: allow half_size extra from centre.
    half_size = caster.stat_block.size.size_ft / 2.0
    if dist > range_ft + half_size:
        raise ValueError(
            f"{action.name}: {defender.name} is out of range "
            f"({dist:.1f} ft, max {range_ft:.0f} ft)"
        )


def derive_aoe_origin(
    caster: "Entity",
    action: SpellAction,
    target: Point3D,
) -> Tuple[Point3D, Optional[Vector3D]]:
    """Derive the AoE volume origin and direction from the target point.

    For CONE and LINE the origin is always the caster's centre; the target
    merely supplies the direction the volume faces.

    For SPHERE, CYLINDER, and CUBE the target IS the origin (after
    clamping to range when needed).

    Returns:
        ``(origin, direction)`` — direction is None for SPHERE/CYLINDER since
        those volumes are symmetric and need no orientation.
    """
    caster_center = caster.bounding_box.center()
    shape = action.aoe.shape

    diff = target - caster_center
    try:
        direction: Optional[Vector3D] = diff.normalized()
    except ValueError:
        direction = Vector3D(1.0, 0.0, 0.0)

    half_size = caster.stat_block.size.size_ft / 2.0

    if shape in (AOEShape.CONE, AOEShape.LINE):
        edge_origin = caster_center + direction.scale(half_size)
        return edge_origin, direction

    range_ft = effective_range_ft(action)
    if range_ft is not None:
        origin = clamp_to_range(caster_center, target, range_ft + half_size)
    else:
        origin = target

    if shape in (AOEShape.SPHERE, AOEShape.CYLINDER):
        return origin, None

    return origin, direction
