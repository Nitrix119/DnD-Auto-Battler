"""AoE volume shapes and entity intersection tests.

Each concrete :class:`AOEVolume` subclass tests whether an entity's
axis-aligned bounding box (AABB) overlaps a specific D&D area-of-effect
shape.  Shapes are:

* :class:`SphereVolume`   — exact nearest-point distance test
* :class:`CylinderVolume` — exact 2D circle + 1D height range test
* :class:`ConeVolume`     — point sampling (8 corners + 6 face centres)
* :class:`CubeVolume`     — OBB vs AABB Separating Axis Theorem (SAT)
* :class:`LineVolume`     — OBB vs AABB SAT (thin oriented box)
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Tuple

from .geometry import BoundingBox, Point3D, Vector3D

if TYPE_CHECKING:
    from src.models.entity import Entity


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class AOEVolume(ABC):
    """Abstract base class for area-of-effect volumes."""

    @abstractmethod
    def contains_entity(self, entity: "Entity") -> bool:
        """Return True if the entity's AABB overlaps this volume."""
        ...


# ---------------------------------------------------------------------------
# SAT helper for OBB vs AABB
# ---------------------------------------------------------------------------

def _sat_obb_aabb(
    obb_center: Point3D,
    obb_axes: Tuple[Vector3D, Vector3D, Vector3D],
    obb_half: Tuple[float, float, float],
    aabb_center: Point3D,
    aabb_half: Tuple[float, float, float],
) -> bool:
    """Separating Axis Theorem test between an OBB and an AABB.

    Tests all 15 potential separating axes:
      - 3 world (AABB face normals): X, Y, Z
      - 3 OBB local face normals: u, v, w
      - 9 cross products: each world axis × each OBB axis

    Returns True when the shapes overlap (no separating axis exists).

    Args:
        obb_center: Centre of the oriented bounding box.
        obb_axes: Three orthonormal unit vectors (u, v, w) forming the OBB's
            local coordinate frame.
        obb_half: Half-extents of the OBB along (u, v, w).
        aabb_center: Centre of the axis-aligned bounding box.
        aabb_half: Half-extents of the AABB along (X, Y, Z).
    """
    EPSILON = 1e-6

    # Translation between centres in world space
    tx = aabb_center.x - obb_center.x
    ty = aabb_center.y - obb_center.y
    tz = aabb_center.z - obb_center.z
    T_world = (tx, ty, tz)

    # R[i][j] = dot(obb_axes[i], world_axis[j])
    # world axes: (1,0,0), (0,1,0), (0,0,1) → components are just x, y, z
    R = (
        (obb_axes[0].x, obb_axes[0].y, obb_axes[0].z),
        (obb_axes[1].x, obb_axes[1].y, obb_axes[1].z),
        (obb_axes[2].x, obb_axes[2].y, obb_axes[2].z),
    )
    absR = tuple(
        tuple(abs(R[i][j]) + EPSILON for j in range(3))
        for i in range(3)
    )

    # --- Test 3 AABB face normals (world X, Y, Z) ---
    for i in range(3):
        ra = aabb_half[i]
        rb = (
            obb_half[0] * absR[0][i]
            + obb_half[1] * absR[1][i]
            + obb_half[2] * absR[2][i]
        )
        if abs(T_world[i]) > ra + rb:
            return False

    # Project translation onto OBB local axes
    T_local = tuple(
        tx * R[i][0] + ty * R[i][1] + tz * R[i][2]
        for i in range(3)
    )

    # --- Test 3 OBB face normals (local u, v, w) ---
    for i in range(3):
        ra = (
            aabb_half[0] * absR[i][0]
            + aabb_half[1] * absR[i][1]
            + aabb_half[2] * absR[i][2]
        )
        rb = obb_half[i]
        if abs(T_local[i]) > ra + rb:
            return False

    # --- Test 9 cross-product axes: world_axis[i] × obb_axes[j] ---
    # For axis A = e_i × u_j the projections reduce to expressions involving
    # the pre-computed R and absR matrices.  Index cycling:
    #   i=0 → (p,q)=(1,2);  i=1 → (p,q)=(2,0);  i=2 → (p,q)=(0,1)
    cross_idx = ((1, 2), (2, 0), (0, 1))

    for i in range(3):
        ip, iq = cross_idx[i]
        for j in range(3):
            jp, jq = cross_idx[j]
            t_proj = abs(T_local[jp] * R[jq][i] - T_local[jq] * R[jp][i])
            ra = aabb_half[ip] * absR[j][iq] + aabb_half[iq] * absR[j][ip]
            rb = obb_half[jp] * absR[jq][i] + obb_half[jq] * absR[jp][i]
            if t_proj > ra + rb:
                return False

    return True  # no separating axis found → overlap


# ---------------------------------------------------------------------------
# OBB builder helper (shared by Cube and Line)
# ---------------------------------------------------------------------------

def _build_obb_frame(
    direction: Vector3D,
) -> Tuple[Vector3D, Vector3D, Vector3D]:
    """Return three orthonormal axes (forward, right, up) for an OBB.

    *forward* is the normalised *direction*.  *right* and *up* are chosen
    to form a right-handed frame, avoiding degeneracy with the world Y-up
    vector.
    """
    fwd = direction.normalized()
    world_up = Vector3D(0.0, 1.0, 0.0)
    if abs(fwd.dot(world_up)) > 0.999:
        world_up = Vector3D(0.0, 0.0, 1.0)
    right = fwd.cross(world_up).normalized()
    up = right.cross(fwd).normalized()
    return fwd, right, up


# ---------------------------------------------------------------------------
# Concrete volumes
# ---------------------------------------------------------------------------

class SphereVolume(AOEVolume):
    """A sphere centred on *center* with the given *radius*.

    Overlap test: distance from *center* to the nearest point on the entity's
    AABB is less than or equal to *radius*.  This is exact.
    """

    def __init__(self, center: Point3D, radius: float) -> None:
        self.center = center
        self.radius = radius

    def contains_entity(self, entity: "Entity") -> bool:
        nearest = entity.bounding_box.nearest_point(self.center)
        dist_sq = (
            (nearest.x - self.center.x) ** 2
            + (nearest.y - self.center.y) ** 2
            + (nearest.z - self.center.z) ** 2
        )
        return dist_sq <= self.radius ** 2


class CylinderVolume(AOEVolume):
    """A vertical cylinder.

    The cylinder is upright (its axis runs parallel to the world Y axis).
    *center_x* and *center_z* give the horizontal centre; *base_y* is the
    bottom of the cylinder; *radius* is the horizontal radius; *height* is
    the vertical extent.

    Overlap test uses an exact 2D circle test in the XZ plane combined with
    a 1D range test along Y.
    """

    def __init__(
        self,
        center_x: float,
        center_z: float,
        base_y: float,
        radius: float,
        height: float,
    ) -> None:
        self.center_x = center_x
        self.center_z = center_z
        self.base_y = base_y
        self.radius = radius
        self.height = height

    def contains_entity(self, entity: "Entity") -> bool:
        bbox = entity.bounding_box

        # Y-range check first (cheaper)
        top_y = self.base_y + self.height
        if bbox.max_corner.y < self.base_y or bbox.min_corner.y > top_y:
            return False

        # 2D nearest-point test in the XZ plane
        nearest_x = max(bbox.min_corner.x, min(self.center_x, bbox.max_corner.x))
        nearest_z = max(bbox.min_corner.z, min(self.center_z, bbox.max_corner.z))
        dx = nearest_x - self.center_x
        dz = nearest_z - self.center_z
        return dx * dx + dz * dz <= self.radius ** 2


class ConeVolume(AOEVolume):
    """A D&D cone: apex at *apex*, pointing in *direction*, length *length*.

    Per D&D 5e rules the cone's full width at any point equals the distance
    from the apex, so the half-angle is ``atan(0.5)`` ≈ 26.57°.

    Overlap test: samples all 8 corners and 6 face-centres of the entity's
    AABB.  If *any* sample point lies inside the cone the entity is considered
    hit.  This approximation is excellent for D&D grid scales (minimum entity
    size 2.5 ft).
    """

    # D&D half-angle: width = length  →  radius at distance d = d/2
    # tan(half_angle) = 0.5
    _TAN_HALF_ANGLE: float = 0.5

    def __init__(self, apex: Point3D, direction: Vector3D, length: float) -> None:
        self.apex = apex
        self.axis = direction.normalized()
        self.length = length

    def _point_in_cone(self, p: Point3D) -> bool:
        vx = p.x - self.apex.x
        vy = p.y - self.apex.y
        vz = p.z - self.apex.z

        # Projection along the cone axis
        proj = vx * self.axis.x + vy * self.axis.y + vz * self.axis.z
        if proj < 0.0 or proj > self.length:
            return False

        # Perpendicular distance from the axis
        perp_x = vx - proj * self.axis.x
        perp_y = vy - proj * self.axis.y
        perp_z = vz - proj * self.axis.z
        perp_dist_sq = perp_x * perp_x + perp_y * perp_y + perp_z * perp_z

        r_at_proj = proj * self._TAN_HALF_ANGLE
        return perp_dist_sq <= r_at_proj * r_at_proj

    def contains_entity(self, entity: "Entity") -> bool:
        bbox = entity.bounding_box
        sample_points = bbox.corners() + bbox.face_centers()
        return any(self._point_in_cone(pt) for pt in sample_points)


class CubeVolume(AOEVolume):
    """A cube-shaped AoE (an oriented bounding box, OBB).

    *origin* is the centre of the face closest to the caster.  The cube
    extends *size_ft* in the *direction* from that face.

    Overlap test uses the 15-axis SAT algorithm for OBB vs AABB.
    """

    def __init__(
        self,
        origin: Point3D,
        direction: Vector3D,
        size_ft: float,
    ) -> None:
        self.origin = origin
        self.direction = direction
        self.size_ft = size_ft
        self._build()

    def _build(self) -> None:
        fwd, right, up = _build_obb_frame(self.direction)
        half = self.size_ft / 2.0
        # OBB centre is half the side-length forward from the origin face
        self._obb_center = Point3D(
            self.origin.x + fwd.x * half,
            self.origin.y + fwd.y * half,
            self.origin.z + fwd.z * half,
        )
        self._obb_axes: Tuple[Vector3D, Vector3D, Vector3D] = (fwd, right, up)
        self._obb_half: Tuple[float, float, float] = (half, half, half)

    def contains_entity(self, entity: "Entity") -> bool:
        bbox = entity.bounding_box
        he = bbox.half_extents()
        return _sat_obb_aabb(
            self._obb_center,
            self._obb_axes,
            self._obb_half,
            bbox.center(),
            (he.x, he.y, he.z),
        )


class LineVolume(AOEVolume):
    """A line AoE: a long, thin oriented bounding box.

    The line originates at *origin*, extends *length* feet in *direction*,
    and has a square cross-section of side *width* feet (D&D default: 5 ft).

    Overlap test uses the 15-axis SAT algorithm for OBB vs AABB.
    """

    def __init__(
        self,
        origin: Point3D,
        direction: Vector3D,
        length: float,
        width: float = 5.0,
    ) -> None:
        self.origin = origin
        self.direction = direction
        self.length = length
        self.width = width
        self._build()

    def _build(self) -> None:
        fwd, right, up = _build_obb_frame(self.direction)
        half_len = self.length / 2.0
        half_w = self.width / 2.0
        self._obb_center = Point3D(
            self.origin.x + fwd.x * half_len,
            self.origin.y + fwd.y * half_len,
            self.origin.z + fwd.z * half_len,
        )
        self._obb_axes: Tuple[Vector3D, Vector3D, Vector3D] = (fwd, right, up)
        self._obb_half: Tuple[float, float, float] = (half_len, half_w, half_w)

    def contains_entity(self, entity: "Entity") -> bool:
        bbox = entity.bounding_box
        he = bbox.half_extents()
        return _sat_obb_aabb(
            self._obb_center,
            self._obb_axes,
            self._obb_half,
            bbox.center(),
            (he.x, he.y, he.z),
        )
