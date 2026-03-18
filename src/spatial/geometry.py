"""3D geometric primitives: Point3D, Vector3D, BoundingBox (AABB).

Coordinate convention (backend)
--------------------------------
  +X  →  east  (grid column increases right)
  +Y  ↑  up    (elevation above ground; Y=0 is the ground plane)
  +Z  ↓  south (grid row increases toward viewer / "down" the map)

The canvas frontend uses Y-down (positive Y = down the screen), which is the
**opposite** sign from the backend's +Y.  For purely 2D play this is harmless
because all distance/overlap maths are sign-symmetric.  If 3D elevation is
ever added, negate the Y coordinate at the API boundary when converting
between canvas space and world space.
"""

import math
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Vector3D:
    """An immutable 3D vector."""

    x: float
    y: float
    z: float

    def dot(self, other: "Vector3D") -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vector3D") -> "Vector3D":
        """Cross product (right-hand rule)."""
        return Vector3D(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def magnitude(self) -> float:
        """Euclidean length."""
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def normalized(self) -> "Vector3D":
        """Return a unit vector in the same direction.

        Raises:
            ValueError: If the vector has zero length.
        """
        m = self.magnitude()
        if m == 0.0:
            raise ValueError("Cannot normalize a zero-length vector")
        return Vector3D(self.x / m, self.y / m, self.z / m)

    def scale(self, scalar: float) -> "Vector3D":
        """Return this vector multiplied by a scalar."""
        return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)

    def __neg__(self) -> "Vector3D":
        return Vector3D(-self.x, -self.y, -self.z)


@dataclass(frozen=True)
class Point3D:
    """An immutable point in 3D space."""

    x: float
    y: float
    z: float

    def distance_to(self, other: "Point3D") -> float:
        """Euclidean distance to another point."""
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )

    def __add__(self, v: Vector3D) -> "Point3D":  # type: ignore[override]
        """Translate this point by a vector."""
        return Point3D(self.x + v.x, self.y + v.y, self.z + v.z)

    def __sub__(self, other: "Point3D") -> Vector3D:  # type: ignore[override]
        """Return the vector from *other* to *self*."""
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box (AABB).

    Convention: ``min_corner`` holds the smallest x/y/z values and
    ``max_corner`` holds the largest.  Both corners are *inclusive*
    (a point exactly on the surface counts as inside).
    """

    min_corner: Point3D
    max_corner: Point3D

    # ------------------------------------------------------------------
    # Core queries
    # ------------------------------------------------------------------

    def overlaps(self, other: "BoundingBox") -> bool:
        """True when this AABB and *other* share any volume (touching counts)."""
        return (
            self.min_corner.x <= other.max_corner.x
            and self.max_corner.x >= other.min_corner.x
            and self.min_corner.y <= other.max_corner.y
            and self.max_corner.y >= other.min_corner.y
            and self.min_corner.z <= other.max_corner.z
            and self.max_corner.z >= other.min_corner.z
        )

    def nearest_point(self, p: Point3D) -> Point3D:
        """Return the point on or inside this AABB closest to *p*."""
        return Point3D(
            x=max(self.min_corner.x, min(p.x, self.max_corner.x)),
            y=max(self.min_corner.y, min(p.y, self.max_corner.y)),
            z=max(self.min_corner.z, min(p.z, self.max_corner.z)),
        )

    def contains_point(self, p: Point3D) -> bool:
        """True when *p* lies inside or on the boundary of this AABB."""
        return (
            self.min_corner.x <= p.x <= self.max_corner.x
            and self.min_corner.y <= p.y <= self.max_corner.y
            and self.min_corner.z <= p.z <= self.max_corner.z
        )

    # ------------------------------------------------------------------
    # Derived geometry
    # ------------------------------------------------------------------

    def center(self) -> Point3D:
        """Centre point of the box."""
        mn, mx = self.min_corner, self.max_corner
        return Point3D(
            (mn.x + mx.x) / 2.0,
            (mn.y + mx.y) / 2.0,
            (mn.z + mx.z) / 2.0,
        )

    def half_extents(self) -> Vector3D:
        """Half-size along each world axis."""
        mn, mx = self.min_corner, self.max_corner
        return Vector3D(
            (mx.x - mn.x) / 2.0,
            (mx.y - mn.y) / 2.0,
            (mx.z - mn.z) / 2.0,
        )

    def corners(self) -> List[Point3D]:
        """All eight corner points of this AABB."""
        mn, mx = self.min_corner, self.max_corner
        return [
            Point3D(mn.x, mn.y, mn.z),
            Point3D(mx.x, mn.y, mn.z),
            Point3D(mn.x, mx.y, mn.z),
            Point3D(mx.x, mx.y, mn.z),
            Point3D(mn.x, mn.y, mx.z),
            Point3D(mx.x, mn.y, mx.z),
            Point3D(mn.x, mx.y, mx.z),
            Point3D(mx.x, mx.y, mx.z),
        ]

    def face_centers(self) -> List[Point3D]:
        """Centre point of each of the six faces."""
        mn, mx = self.min_corner, self.max_corner
        cx = (mn.x + mx.x) / 2.0
        cy = (mn.y + mx.y) / 2.0
        cz = (mn.z + mx.z) / 2.0
        return [
            Point3D(mn.x, cy, cz),  # −X face
            Point3D(mx.x, cy, cz),  # +X face
            Point3D(cx, mn.y, cz),  # −Y face
            Point3D(cx, mx.y, cz),  # +Y face
            Point3D(cx, cy, mn.z),  # −Z face
            Point3D(cx, cy, mx.z),  # +Z face
        ]
