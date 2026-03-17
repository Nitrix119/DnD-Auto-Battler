"""Tests for Point3D, Vector3D, and BoundingBox."""

import math
import pytest

from src.spatial.geometry import BoundingBox, Point3D, Vector3D


# ---------------------------------------------------------------------------
# Point3D
# ---------------------------------------------------------------------------

class TestPoint3D:
    def test_distance_to_self_is_zero(self):
        p = Point3D(1.0, 2.0, 3.0)
        assert p.distance_to(p) == pytest.approx(0.0)

    def test_distance_3_4_5_triangle(self):
        a = Point3D(0.0, 0.0, 0.0)
        b = Point3D(3.0, 4.0, 0.0)
        assert a.distance_to(b) == pytest.approx(5.0)

    def test_distance_3d(self):
        a = Point3D(0, 0, 0)
        b = Point3D(1, 2, 2)  # sqrt(1+4+4) = 3
        assert a.distance_to(b) == pytest.approx(3.0)

    def test_add_vector(self):
        p = Point3D(1.0, 2.0, 3.0)
        v = Vector3D(4.0, 5.0, 6.0)
        result = p + v
        assert result == Point3D(5.0, 7.0, 9.0)

    def test_subtract_points_gives_vector(self):
        a = Point3D(5.0, 3.0, 1.0)
        b = Point3D(2.0, 1.0, 0.0)
        v = a - b
        assert v == Vector3D(3.0, 2.0, 1.0)


# ---------------------------------------------------------------------------
# Vector3D
# ---------------------------------------------------------------------------

class TestVector3D:
    def test_dot_perpendicular_is_zero(self):
        x = Vector3D(1.0, 0.0, 0.0)
        y = Vector3D(0.0, 1.0, 0.0)
        assert x.dot(y) == pytest.approx(0.0)

    def test_dot_parallel(self):
        v = Vector3D(3.0, 0.0, 0.0)
        assert v.dot(v) == pytest.approx(9.0)

    def test_cross_product_xy(self):
        x = Vector3D(1.0, 0.0, 0.0)
        y = Vector3D(0.0, 1.0, 0.0)
        z = x.cross(y)
        assert z == Vector3D(0.0, 0.0, 1.0)

    def test_cross_product_anticommutative(self):
        u = Vector3D(1.0, 2.0, 3.0)
        v = Vector3D(4.0, 5.0, 6.0)
        assert u.cross(v) == Vector3D(
            u.y * v.z - u.z * v.y,
            u.z * v.x - u.x * v.z,
            u.x * v.y - u.y * v.x,
        )

    def test_magnitude(self):
        v = Vector3D(3.0, 4.0, 0.0)
        assert v.magnitude() == pytest.approx(5.0)

    def test_normalize_unit_vector_unchanged(self):
        v = Vector3D(1.0, 0.0, 0.0)
        assert v.normalized() == v

    def test_normalize_general(self):
        v = Vector3D(3.0, 4.0, 0.0)
        n = v.normalized()
        assert n.magnitude() == pytest.approx(1.0)
        assert n.x == pytest.approx(0.6)
        assert n.y == pytest.approx(0.8)

    def test_normalize_raises_on_zero(self):
        with pytest.raises(ValueError, match="zero-length"):
            Vector3D(0.0, 0.0, 0.0).normalized()

    def test_scale(self):
        v = Vector3D(1.0, 2.0, 3.0)
        assert v.scale(2.0) == Vector3D(2.0, 4.0, 6.0)

    def test_negate(self):
        v = Vector3D(1.0, -2.0, 3.0)
        assert -v == Vector3D(-1.0, 2.0, -3.0)


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------

def _box(x0, y0, z0, x1, y1, z1) -> BoundingBox:
    return BoundingBox(Point3D(x0, y0, z0), Point3D(x1, y1, z1))


class TestBoundingBox:
    def test_overlaps_identical_boxes(self):
        b = _box(0, 0, 0, 5, 5, 5)
        assert b.overlaps(b)

    def test_overlaps_touching_edge(self):
        a = _box(0, 0, 0, 5, 5, 5)
        b = _box(5, 0, 0, 10, 5, 5)
        assert a.overlaps(b)

    def test_no_overlap_separated_x(self):
        a = _box(0, 0, 0, 5, 5, 5)
        b = _box(6, 0, 0, 11, 5, 5)
        assert not a.overlaps(b)

    def test_no_overlap_separated_y(self):
        a = _box(0, 0, 0, 5, 5, 5)
        b = _box(0, 6, 0, 5, 11, 5)
        assert not a.overlaps(b)

    def test_no_overlap_separated_z(self):
        a = _box(0, 0, 0, 5, 5, 5)
        b = _box(0, 0, 6, 5, 5, 11)
        assert not a.overlaps(b)

    def test_partial_overlap(self):
        a = _box(0, 0, 0, 5, 5, 5)
        b = _box(3, 3, 3, 8, 8, 8)
        assert a.overlaps(b)

    def test_nearest_point_when_inside(self):
        b = _box(0, 0, 0, 10, 10, 10)
        p = Point3D(5.0, 5.0, 5.0)
        assert b.nearest_point(p) == p

    def test_nearest_point_when_outside_x(self):
        b = _box(0, 0, 0, 10, 10, 10)
        p = Point3D(15.0, 5.0, 5.0)
        assert b.nearest_point(p) == Point3D(10.0, 5.0, 5.0)

    def test_nearest_point_corner(self):
        b = _box(0, 0, 0, 5, 5, 5)
        p = Point3D(-1.0, -1.0, -1.0)
        assert b.nearest_point(p) == Point3D(0.0, 0.0, 0.0)

    def test_contains_point_interior(self):
        b = _box(0, 0, 0, 10, 10, 10)
        assert b.contains_point(Point3D(5.0, 5.0, 5.0))

    def test_contains_point_boundary(self):
        b = _box(0, 0, 0, 10, 10, 10)
        assert b.contains_point(Point3D(0.0, 0.0, 0.0))
        assert b.contains_point(Point3D(10.0, 10.0, 10.0))

    def test_contains_point_outside(self):
        b = _box(0, 0, 0, 10, 10, 10)
        assert not b.contains_point(Point3D(11.0, 5.0, 5.0))

    def test_corners_count(self):
        b = _box(0, 0, 0, 1, 1, 1)
        assert len(b.corners()) == 8

    def test_corners_all_distinct(self):
        b = _box(0, 0, 0, 1, 1, 1)
        corners = b.corners()
        assert len(set(corners)) == 8

    def test_face_centers_count(self):
        b = _box(0, 0, 0, 2, 2, 2)
        assert len(b.face_centers()) == 6

    def test_center(self):
        b = _box(0, 0, 0, 4, 6, 8)
        c = b.center()
        assert c == Point3D(2.0, 3.0, 4.0)

    def test_half_extents(self):
        b = _box(0, 0, 0, 4, 6, 8)
        he = b.half_extents()
        assert he == Vector3D(2.0, 3.0, 4.0)
