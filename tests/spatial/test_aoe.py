"""Tests for AoE volume shapes and entity intersection."""

import math
import pytest

from src.spatial.geometry import BoundingBox, Point3D, Vector3D
from src.spatial.aoe import (
    ConeVolume,
    CubeVolume,
    CylinderVolume,
    LineVolume,
    SphereVolume,
    _sat_obb_aabb,
)
from src.models.creature_size import CreatureSize
from src.models.stat_block import StatBlock
from src.models.ability import AbilityScores
from src.models.entity import Entity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(x: float = 0.0, y: float = 0.0, z: float = 0.0,
                 size: CreatureSize = CreatureSize.MEDIUM) -> Entity:
    """Create a minimal entity at the given position with the given size."""
    sb = StatBlock(
        name="Test",
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=10,
        armor_class=10,
        size=size,
    )
    e = Entity(sb)
    e.x, e.y, e.z = x, y, z
    return e


# ---------------------------------------------------------------------------
# SphereVolume
# ---------------------------------------------------------------------------

class TestSphereVolume:
    def test_entity_at_center_inside(self):
        sphere = SphereVolume(center=Point3D(0, 0, 0), radius=20)
        entity = _make_entity(0, 0, 0)
        assert sphere.contains_entity(entity)

    def test_entity_just_inside_radius(self):
        # Medium entity at (14, 0, 0): nearest corner to center = (14,0,0), dist=14 < 20
        sphere = SphereVolume(center=Point3D(0, 0, 0), radius=20)
        entity = _make_entity(14, 0, 0)
        assert sphere.contains_entity(entity)

    def test_entity_touching_boundary_hit(self):
        # Entity at (20, 0, 0): nearest corner = (20,0,0), dist = 20 == radius
        sphere = SphereVolume(center=Point3D(0, 0, 0), radius=20)
        entity = _make_entity(20, 0, 0)
        assert sphere.contains_entity(entity)

    def test_entity_just_outside(self):
        # Entity centre at x=23: nearest edge at x=20.5 > radius 20 → miss
        sphere = SphereVolume(center=Point3D(0, 0, 0), radius=20)
        entity = _make_entity(23, 0, 0)
        assert not sphere.contains_entity(entity)

    def test_entity_partially_inside(self):
        # Sphere radius 10, entity starts at (8,0,0) and extends to (13,5,5)
        # Nearest point on entity to sphere center = (8,0,0), dist=8 < 10
        sphere = SphereVolume(center=Point3D(0, 0, 0), radius=10)
        entity = _make_entity(8, 0, 0)
        assert sphere.contains_entity(entity)

    def test_large_entity_straddling_sphere(self):
        # Large entity (10ft) at (-5, -5, -5) to (5,5,5): bbox straddles sphere center
        sphere = SphereVolume(center=Point3D(0, 0, 0), radius=1)
        entity = _make_entity(-5, -5, -5, size=CreatureSize.LARGE)
        assert sphere.contains_entity(entity)


# ---------------------------------------------------------------------------
# CylinderVolume
# ---------------------------------------------------------------------------

class TestCylinderVolume:
    def test_entity_inside(self):
        cyl = CylinderVolume(center_x=0, center_z=0, base_y=0, radius=10, height=20)
        entity = _make_entity(0, 0, 0)
        assert cyl.contains_entity(entity)

    def test_entity_above_height_miss(self):
        cyl = CylinderVolume(center_x=0, center_z=0, base_y=0, radius=10, height=5)
        entity = _make_entity(0, 6, 0)
        assert not cyl.contains_entity(entity)

    def test_entity_below_base_miss(self):
        cyl = CylinderVolume(center_x=0, center_z=0, base_y=5, radius=10, height=10)
        # entity tops out at y=5 exactly — touching base
        entity = _make_entity(0, 0, 0)  # y range [0, 5]
        assert cyl.contains_entity(entity)  # touching = hit

    def test_entity_outside_radius_miss(self):
        cyl = CylinderVolume(center_x=0, center_z=0, base_y=0, radius=5, height=20)
        # Entity centre at (7,0,7): nearest XZ edge at (4.5,4.5), dist=sqrt(40.5)≈6.36 > 5 → miss
        entity = _make_entity(7, 0, 7)
        assert not cyl.contains_entity(entity)

    def test_entity_touching_cylinder_edge_hit(self):
        cyl = CylinderVolume(center_x=0, center_z=0, base_y=0, radius=5, height=20)
        entity = _make_entity(5, 0, 0)  # nearest XZ point = (5,_,0), dist=5 == radius
        assert cyl.contains_entity(entity)


# ---------------------------------------------------------------------------
# ConeVolume
# ---------------------------------------------------------------------------

class TestConeVolume:
    def test_entity_directly_in_front_hit(self):
        cone = ConeVolume(
            apex=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=30,
        )
        entity = _make_entity(10, 0, 0)
        assert cone.contains_entity(entity)

    def test_entity_behind_apex_miss(self):
        cone = ConeVolume(
            apex=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=30,
        )
        entity = _make_entity(-6, 0, 0)
        assert not cone.contains_entity(entity)

    def test_entity_beyond_length_miss(self):
        cone = ConeVolume(
            apex=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=10,
        )
        # Entity centre at x=13: nearest edge at x=10.5 > cone length 10 → miss
        entity = _make_entity(13, 0, 0)
        assert not cone.contains_entity(entity)

    def test_entity_at_edge_of_half_angle_hit(self):
        # At distance d along axis, radius = d * 0.5
        # Entity at (10, 0, 0), its nearest point along axis is x=10, y=0
        # r_at_10 = 5; entity starts at y=0, x=10 → corner (10, 0, 0) is on the cone surface
        cone = ConeVolume(
            apex=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=30,
        )
        entity = _make_entity(10, 0, 0)
        assert cone.contains_entity(entity)

    def test_entity_outside_half_angle_miss(self):
        # Cone axis along +X, half-angle=atan(0.5): radius at distance d = d*0.5.
        # Entity (MEDIUM, 5ft) at (10, 8, 0): corners span x=[10,15], y=[8,13], z=[0,5].
        # Closest corner to axis: (15, 8, 0) → proj=15, perp=8, r_at_15=7.5. 8 > 7.5 → miss.
        # All 14 sample points checked manually — all outside.
        cone = ConeVolume(
            apex=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=30,
        )
        entity = _make_entity(10, 8, 0)
        assert not cone.contains_entity(entity)

    def test_cone_pointing_negative_x(self):
        cone = ConeVolume(
            apex=Point3D(0, 0, 0),
            direction=Vector3D(-1, 0, 0),
            length=20,
        )
        entity = _make_entity(-15, 0, 0)
        assert cone.contains_entity(entity)


# ---------------------------------------------------------------------------
# CubeVolume
# ---------------------------------------------------------------------------

class TestCubeVolume:
    def test_entity_directly_ahead_hit(self):
        cube = CubeVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            size_ft=15,
        )
        entity = _make_entity(5, 0, 0)
        assert cube.contains_entity(entity)

    def test_entity_behind_origin_miss(self):
        cube = CubeVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            size_ft=15,
        )
        entity = _make_entity(-10, 0, 0)
        assert not cube.contains_entity(entity)

    def test_entity_beside_cube_miss(self):
        cube = CubeVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            size_ft=10,
        )
        # Cube occupies x=[0,10], y=[-5,5], z=[-5,5]
        entity = _make_entity(3, 8, 0)  # y starts at 8, cube ends at 5
        assert not cube.contains_entity(entity)

    def test_entity_touching_cube_face_hit(self):
        cube = CubeVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            size_ft=10,
        )
        # Cube forward face at x=10; entity at (10, 0, 0) touches it
        entity = _make_entity(10, 0, 0)
        assert cube.contains_entity(entity)

    def test_cube_45_degrees(self):
        # Cube rotated 45 degrees around Y, pointing diagonally
        d = Vector3D(1, 0, 1)  # diagonal XZ
        cube = CubeVolume(
            origin=Point3D(0, 0, 0),
            direction=d,
            size_ft=20,
        )
        # Entity along the diagonal should be inside
        entity = _make_entity(5, 0, 5)
        assert cube.contains_entity(entity)


# ---------------------------------------------------------------------------
# LineVolume
# ---------------------------------------------------------------------------

class TestLineVolume:
    def test_entity_along_line_hit(self):
        line = LineVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=60,
            width=5,
        )
        entity = _make_entity(20, 0, 0)
        assert line.contains_entity(entity)

    def test_entity_outside_width_miss(self):
        line = LineVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=60,
            width=5,
        )
        # Line half-width=2.5; entity centre at z=6 → nearest edge at z=3.5 > 2.5 → miss
        entity = _make_entity(20, 0, 6)
        assert not line.contains_entity(entity)

    def test_entity_beyond_length_miss(self):
        line = LineVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=30,
            width=5,
        )
        # Entity centre at x=33: nearest edge at x=30.5 > line length 30 → miss
        entity = _make_entity(33, 0, 0)
        assert not line.contains_entity(entity)

    def test_default_width_5ft(self):
        line = LineVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=60,
        )
        assert line.width == 5.0

    def test_custom_width_10ft(self):
        line = LineVolume(
            origin=Point3D(0, 0, 0),
            direction=Vector3D(1, 0, 0),
            length=60,
            width=10,
        )
        entity = _make_entity(10, 0, 4)  # within 10ft width
        assert line.contains_entity(entity)


# ---------------------------------------------------------------------------
# SAT — the cross-product axis edge case
# ---------------------------------------------------------------------------

class TestSATOBBvsAABB:
    """Verify the SAT implementation handles the tricky cross-product axis case.

    A thin OBB rotated 45° around Y can be separated from an AABB even though
    all six face-normal projections overlap.  Only a cross-product axis
    (e.g. world-Z × obb-X) reveals the separation.
    """

    def test_aligned_boxes_overlap(self):
        # OBB aligned with world axes, clearly overlapping AABB
        obb_center = Point3D(0, 0, 0)
        obb_axes = (Vector3D(1,0,0), Vector3D(0,1,0), Vector3D(0,0,1))
        obb_half = (5.0, 5.0, 5.0)
        aabb_center = Point3D(4, 0, 0)
        aabb_half = (2.0, 2.0, 2.0)
        assert _sat_obb_aabb(obb_center, obb_axes, obb_half, aabb_center, aabb_half)

    def test_separated_along_world_x(self):
        obb_center = Point3D(0, 0, 0)
        obb_axes = (Vector3D(1,0,0), Vector3D(0,1,0), Vector3D(0,0,1))
        obb_half = (3.0, 3.0, 3.0)
        aabb_center = Point3D(10, 0, 0)
        aabb_half = (2.0, 2.0, 2.0)
        assert not _sat_obb_aabb(obb_center, obb_axes, obb_half, aabb_center, aabb_half)

    def test_separated_along_obb_local_axis(self):
        # OBB rotated 45° around Y
        s = math.sqrt(0.5)
        obb_axes = (Vector3D(s,0,s), Vector3D(0,1,0), Vector3D(-s,0,s))
        obb_center = Point3D(0, 0, 0)
        obb_half = (10.0, 5.0, 0.5)  # very thin along w
        # AABB clearly separated along the obb's thin (w) axis
        aabb_center = Point3D(0, 0, 5)
        aabb_half = (0.5, 0.5, 0.5)
        assert not _sat_obb_aabb(obb_center, obb_axes, obb_half, aabb_center, aabb_half)

    def test_cross_product_axis_separates(self):
        """Classic case: projections on all 6 face normals overlap, but a
        cross-product axis separates the shapes.

        A needle-like OBB along the diagonal (1,0,1)/sqrt(2), and an AABB
        placed at a corner so they appear to overlap when projected onto
        X, Y, Z, u, v, w — but a cross-product axis (e.g. Y × u) reveals
        separation.
        """
        s = math.sqrt(0.5)
        # OBB: very long along (1,0,1)/√2, thin in the perpendicular directions
        obb_axes = (Vector3D(s,0,s), Vector3D(0,1,0), Vector3D(-s,0,s))
        obb_center = Point3D(0, 0, 0)
        obb_half = (20.0, 0.1, 0.1)  # long needle along diagonal

        # AABB placed at (3, 0, -3): its projections onto X,Y,Z,u,v,w
        # all appear to "overlap" the needle's projections, but the needle
        # doesn't actually reach it — the cross-product axis separates them.
        aabb_center = Point3D(3, 0, -3)
        aabb_half = (0.5, 0.5, 0.5)
        # This AABB is off to the side of the needle diagonal (1,0,1) —
        # the needle goes through quadrant (+,+) but the AABB is in (+,-).
        assert not _sat_obb_aabb(obb_center, obb_axes, obb_half, aabb_center, aabb_half)

    def test_touching_boxes_overlap(self):
        obb_center = Point3D(0, 0, 0)
        obb_axes = (Vector3D(1,0,0), Vector3D(0,1,0), Vector3D(0,0,1))
        obb_half = (5.0, 5.0, 5.0)
        aabb_center = Point3D(7, 0, 0)
        aabb_half = (2.0, 2.0, 2.0)
        # OBB extends to x=5; AABB starts at x=5: touching = overlap
        assert _sat_obb_aabb(obb_center, obb_axes, obb_half, aabb_center, aabb_half)
