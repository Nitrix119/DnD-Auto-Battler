"""Tests for entity movement (willing and forced) and AoE targeting."""

import math
import pytest

from src.combat.combat_system import CombatSystem
from src.models.ability import AbilityScores
from src.models.creature_size import CreatureSize
from src.models.entity import Entity
from src.models.stat_block import StatBlock
from src.models.spell_properties import AOEProperties, AOEShape
from src.spatial.geometry import Point3D, Vector3D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(
    name: str = "Fighter",
    size: CreatureSize = CreatureSize.MEDIUM,
    speed: int = 30,
    hp: int = 20,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    team: str = None,
) -> Entity:
    sb = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp,
        armor_class=10,
        size=size,
        resource_defaults={"actions": 1, "bonus_actions": 1, "reactions": 1, "speed": speed},
    )
    e = Entity(sb, x=x, y=y, z=z, team=team)
    return e


def _make_combat(*entities) -> CombatSystem:
    """Create a minimal CombatSystem with the given entities (no rule engine)."""
    combat = CombatSystem()
    for i, e in enumerate(entities):
        # Give the first entity a high initiative modifier so it is always
        # the active entity, keeping tests deterministic.
        combat.add_combatant(e, initiative_modifier=(100 if i == 0 else 0))
    # Don't call start_combat to avoid needing a full rule engine
    # Movement methods work without combat being started
    combat.combatants = list(entities)
    return combat


# ---------------------------------------------------------------------------
# move_entity (willing movement)
# ---------------------------------------------------------------------------

class TestMoveEntity:
    def test_successful_move_deducts_movement(self):
        mover = _make_entity(speed=30)
        combat = _make_combat(mover)

        combat.move_entity(mover, 10.0, 0.0, 0.0)

        assert mover.x == 10.0
        assert mover.resources.movement == 20  # 30 - 10

    def test_move_cost_is_ceiling_of_euclidean_distance(self):
        # 3-4-5 triangle: dist=5, cost=5
        mover = _make_entity(speed=30)
        combat = _make_combat(mover)

        combat.move_entity(mover, 3.0, 4.0, 0.0)

        assert mover.x == 3.0
        assert mover.y == 4.0
        assert mover.resources.movement == 25  # 30 - 5

    def test_move_fails_insufficient_movement(self):
        mover = _make_entity(speed=5)
        combat = _make_combat(mover)

        with pytest.raises(ValueError, match="cannot afford to move"):
            combat.move_entity(mover, 20.0, 0.0, 0.0)

        # Position unchanged
        assert mover.x == 0.0

    def test_move_fails_on_overlap(self):
        mover = _make_entity("Mover", x=0.0)
        blocker = _make_entity("Blocker", x=10.0)
        combat = _make_combat(mover, blocker)

        with pytest.raises(ValueError, match="overlaps"):
            combat.move_entity(mover, 10.0, 0.0, 0.0)

        assert mover.x == 0.0

    def test_move_zero_distance_costs_nothing(self):
        mover = _make_entity(speed=30)
        combat = _make_combat(mover)

        combat.move_entity(mover, 0.0, 0.0, 0.0)

        assert mover.resources.movement == 30

    def test_dead_entity_does_not_block_movement(self):
        mover = _make_entity("Mover")
        corpse = _make_entity("Corpse", x=10.0)
        corpse.current_hp = 0  # dead
        combat = _make_combat(mover, corpse)

        # Should succeed — dead entities don't block
        combat.move_entity(mover, 10.0, 0.0, 0.0)
        assert mover.x == 10.0

    def test_large_entity_blocks_more_space(self):
        # Large entity centred at x=20: box [15,25]×[0,10]×[-5,5]
        mover = _make_entity("Mover", size=CreatureSize.MEDIUM)
        large = _make_entity("Dragon", size=CreatureSize.LARGE, x=20.0)
        combat = _make_combat(mover, large)

        # Try to move mover to (15, 0, 0): mover box [12.5,17.5]×[0,5]×[-2.5,2.5]
        # large box [15,25]×[0,10]×[-5,5] — overlap at x=[15,17.5] → raises
        with pytest.raises(ValueError, match="overlaps"):
            combat.move_entity(mover, 15.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# push_entity (forced movement)
# ---------------------------------------------------------------------------

class TestPushEntity:
    def test_push_does_not_consume_movement(self):
        mover = _make_entity(speed=30)
        combat = _make_combat(mover)

        combat.push_entity(mover, 50.0, 0.0, 0.0)

        assert mover.x == 50.0
        assert mover.resources.movement == 30  # unchanged

    def test_push_still_checks_overlap(self):
        pusher = _make_entity("Pusher", x=0.0)
        wall = _make_entity("Wall", x=20.0)
        combat = _make_combat(pusher, wall)

        with pytest.raises(ValueError, match="overlaps"):
            combat.push_entity(pusher, 20.0, 0.0, 0.0)

        assert pusher.x == 0.0

    def test_push_into_dead_entity_ok(self):
        mover = _make_entity("Mover")
        corpse = _make_entity("Corpse", x=30.0)
        corpse.current_hp = 0
        combat = _make_combat(mover, corpse)

        combat.push_entity(mover, 30.0, 0.0, 0.0)
        assert mover.x == 30.0

    def test_push_updates_all_three_axes(self):
        mover = _make_entity()
        combat = _make_combat(mover)

        combat.push_entity(mover, 3.0, 7.0, 1.0)

        assert mover.x == 3.0
        assert mover.y == 7.0
        assert mover.z == 1.0


# ---------------------------------------------------------------------------
# get_targets_in_aoe
# ---------------------------------------------------------------------------

class TestGetTargetsInAoe:
    def test_fireball_hits_entities_in_radius(self):
        caster = _make_entity("Wizard", x=0.0, team="heroes")
        # Goblin A centred at x=5: bbox [2.5,7.5], nearest pt to (10,0,0) is (7.5,0,0), dist=2.5 < 20 → hit
        target_a = _make_entity("Goblin A", x=5.0, team="monsters")
        # Goblin B centred at x=35: bbox [32.5,37.5], nearest pt to (10,0,0) is (32.5,0,0), dist=22.5 > 20 → miss
        target_b = _make_entity("Goblin B", x=35.0, team="monsters")
        combat = _make_combat(caster, target_a, target_b)

        aoe = AOEProperties(shape=AOEShape.SPHERE, size_ft=20)
        origin = Point3D(10.0, 0.0, 0.0)  # blast centre 10ft ahead
        targets = combat.get_targets_in_aoe(origin, aoe)

        assert target_a in targets
        assert target_b not in targets

    def test_fireball_hits_caster_in_blast(self):
        # Caster can be caught in their own AoE
        caster = _make_entity("Wizard", x=5.0)
        enemy = _make_entity("Orc", x=40.0)
        combat = _make_combat(caster, enemy)

        aoe = AOEProperties(shape=AOEShape.SPHERE, size_ft=20)
        origin = Point3D(10.0, 0.0, 0.0)
        targets = combat.get_targets_in_aoe(origin, aoe)

        assert caster in targets
        assert enemy not in targets

    def test_sphere_no_direction_required(self):
        entity = _make_entity(x=5.0)
        combat = _make_combat(entity)
        aoe = AOEProperties(shape=AOEShape.SPHERE, size_ft=20)
        # Must not raise even without direction
        targets = combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)
        assert entity in targets

    def test_cylinder_no_direction_required(self):
        entity = _make_entity(x=0.0)
        combat = _make_combat(entity)
        aoe = AOEProperties(shape=AOEShape.CYLINDER, size_ft=10, height_ft=20)
        targets = combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)
        assert entity in targets

    def test_cone_hits_targets_in_front(self):
        caster = _make_entity("Caster", x=0.0)
        front = _make_entity("Front", x=10.0)
        behind = _make_entity("Behind", x=-10.0)
        combat = _make_combat(caster, front, behind)

        aoe = AOEProperties(shape=AOEShape.CONE, size_ft=30)
        direction = Vector3D(1, 0, 0)
        targets = combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe, direction)

        assert front in targets
        assert behind not in targets

    def test_cone_requires_direction(self):
        entity = _make_entity()
        combat = _make_combat(entity)
        aoe = AOEProperties(shape=AOEShape.CONE, size_ft=30)

        with pytest.raises(ValueError, match="direction"):
            combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)

    def test_cube_requires_direction(self):
        entity = _make_entity()
        combat = _make_combat(entity)
        aoe = AOEProperties(shape=AOEShape.CUBE, size_ft=15)

        with pytest.raises(ValueError, match="direction"):
            combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)

    def test_line_requires_direction(self):
        entity = _make_entity()
        combat = _make_combat(entity)
        aoe = AOEProperties(shape=AOEShape.LINE, size_ft=60)

        with pytest.raises(ValueError, match="direction"):
            combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)

    def test_line_hits_targets_along_path(self):
        a = _make_entity("A", x=10.0)
        b = _make_entity("B", x=20.0)
        off_path = _make_entity("Off", x=10.0, z=10.0)  # to the side, outside 5ft width
        combat = _make_combat(a, b, off_path)

        aoe = AOEProperties(shape=AOEShape.LINE, size_ft=60, width_ft=5)
        direction = Vector3D(1, 0, 0)
        targets = combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe, direction)

        assert a in targets
        assert b in targets
        assert off_path not in targets

    def test_special_shape_raises(self):
        entity = _make_entity()
        combat = _make_combat(entity)
        aoe = AOEProperties(shape=AOEShape.SPECIAL, size_ft=10)

        with pytest.raises(ValueError, match="not spatially modelled"):
            combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)

    def test_returns_only_alive_entities(self):
        alive = _make_entity("Alive", x=5.0)
        dead = _make_entity("Dead", x=5.0, y=10.0)
        dead.current_hp = 0
        combat = _make_combat(alive, dead)

        aoe = AOEProperties(shape=AOEShape.SPHERE, size_ft=30)
        targets = combat.get_targets_in_aoe(Point3D(0, 0, 0), aoe)

        assert alive in targets
        assert dead not in targets
