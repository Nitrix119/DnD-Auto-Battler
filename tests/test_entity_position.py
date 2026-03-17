"""Tests for entity position and bounding box."""

import pytest

from src.models.creature_size import CreatureSize
from src.models.entity import Entity
from src.models.stat_block import StatBlock
from src.models.ability import AbilityScores
from src.spatial.geometry import BoundingBox, Point3D


def _make_stat_block(size: CreatureSize = CreatureSize.MEDIUM) -> StatBlock:
    return StatBlock(
        name="Test",
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=10,
        armor_class=10,
        size=size,
    )


class TestCreatureSize:
    def test_tiny_footprint(self):
        assert CreatureSize.TINY.size_ft == pytest.approx(2.5)

    def test_small_footprint(self):
        assert CreatureSize.SMALL.size_ft == pytest.approx(5.0)

    def test_medium_footprint(self):
        assert CreatureSize.MEDIUM.size_ft == pytest.approx(5.0)

    def test_large_footprint(self):
        assert CreatureSize.LARGE.size_ft == pytest.approx(10.0)

    def test_huge_footprint(self):
        assert CreatureSize.HUGE.size_ft == pytest.approx(15.0)

    def test_gargantuan_footprint(self):
        assert CreatureSize.GARGANTUAN.size_ft == pytest.approx(20.0)


class TestEntityPosition:
    def test_default_position_is_origin(self):
        sb = _make_stat_block()
        entity = Entity(sb)
        assert entity.x == 0.0
        assert entity.y == 0.0
        assert entity.z == 0.0

    def test_position_can_be_set_on_creation(self):
        sb = _make_stat_block()
        entity = Entity(sb, x=10.0, y=5.0, z=2.0)
        assert entity.x == 10.0
        assert entity.y == 5.0
        assert entity.z == 2.0

    def test_position_is_mutable(self):
        sb = _make_stat_block()
        entity = Entity(sb)
        entity.x = 7.0
        entity.y = 3.0
        entity.z = 1.0
        assert entity.x == 7.0
        assert entity.y == 3.0
        assert entity.z == 1.0


class TestEntityBoundingBox:
    def test_medium_bbox_at_origin(self):
        sb = _make_stat_block(CreatureSize.MEDIUM)
        entity = Entity(sb)
        bbox = entity.bounding_box
        assert bbox.min_corner == Point3D(0.0, 0.0, 0.0)
        assert bbox.max_corner == Point3D(5.0, 5.0, 5.0)

    def test_large_bbox(self):
        sb = _make_stat_block(CreatureSize.LARGE)
        entity = Entity(sb)
        bbox = entity.bounding_box
        assert bbox.max_corner == Point3D(10.0, 10.0, 10.0)

    def test_huge_bbox(self):
        sb = _make_stat_block(CreatureSize.HUGE)
        entity = Entity(sb)
        bbox = entity.bounding_box
        assert bbox.max_corner == Point3D(15.0, 15.0, 15.0)

    def test_gargantuan_bbox(self):
        sb = _make_stat_block(CreatureSize.GARGANTUAN)
        entity = Entity(sb)
        bbox = entity.bounding_box
        assert bbox.max_corner == Point3D(20.0, 20.0, 20.0)

    def test_bbox_moves_with_entity(self):
        sb = _make_stat_block()
        entity = Entity(sb)
        entity.x = 10.0
        entity.y = 20.0
        entity.z = 5.0
        bbox = entity.bounding_box
        assert bbox.min_corner == Point3D(10.0, 20.0, 5.0)
        assert bbox.max_corner == Point3D(15.0, 25.0, 10.0)

    def test_stat_block_defaults_to_medium(self):
        sb = StatBlock(
            name="NoSize",
            ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
            hit_points_max=10,
            armor_class=10,
        )
        assert sb.size == CreatureSize.MEDIUM
