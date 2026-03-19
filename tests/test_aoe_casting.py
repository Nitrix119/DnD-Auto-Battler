"""Integration tests for AoE spell casting: target point, range clamping, and auto-targeting."""

import math
import pytest
from unittest.mock import patch

from src.combat import CombatSystem
from src.models import Entity, SpellAction, Damage, DamageType
from src.models.ability import AbilityScores
from src.models.action_resources import ACTION_COST, BONUS_ACTION_COST
from src.models.creature_size import CreatureSize
from src.models.spell_properties import (
    AOEProperties, AOEShape, CastingTime, CastingTimeType,
    Duration, DurationUnit, RangeType, SpellComponents, SpellRange,
    TargetingType,
)
from src.models.stat_block import StatBlock
from src.spatial.geometry import Point3D, Vector3D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(
    name: str = "Creature",
    hp: int = 20,
    ac: int = 10,
    size: CreatureSize = CreatureSize.MEDIUM,
    speed: int = 30,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    team: str = None,
) -> Entity:
    sb = StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
        size=size,
        resource_defaults={"actions": 1, "bonus_actions": 1, "reactions": 1, "speed": speed},
    )
    e = Entity(sb, team=team)
    e.x, e.y, e.z = x, y, z
    return e


def _fireball(
    range_ft: int = 150,
    radius_ft: int = 20,
    save_dc: int = 15,
) -> SpellAction:
    """A Fireball-style sphere AoE spell with a Dex save."""
    return SpellAction(
        name="Fireball",
        description="",
        spell_level=3,
        save_dc=save_dc,
        save_ability="dexterity",
        spell_attack_bonus=0,
        damage=[Damage(DamageType.FIRE, 28, formula="8d6")],
        spell_range=SpellRange(RangeType.FEET, distance_ft=range_ft),
        targeting_type=TargetingType.AOE,
        aoe=AOEProperties(AOEShape.SPHERE, size_ft=radius_ft),
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=True),
    )


def _cone_spell(range_type: RangeType = RangeType.SELF, length_ft: int = 15) -> SpellAction:
    return SpellAction(
        name="Burning Hands",
        description="",
        spell_level=1,
        save_dc=13,
        save_ability="dexterity",
        spell_attack_bonus=0,
        damage=[Damage(DamageType.FIRE, 10, formula="3d6")],
        spell_range=SpellRange(range_type),
        targeting_type=TargetingType.AOE,
        aoe=AOEProperties(AOEShape.CONE, size_ft=length_ft),
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=True),
    )


def _line_spell(range_type: RangeType = RangeType.SELF, length_ft: int = 60) -> SpellAction:
    return SpellAction(
        name="Lightning Bolt",
        description="",
        spell_level=3,
        save_dc=15,
        save_ability="dexterity",
        spell_attack_bonus=0,
        damage=[Damage(DamageType.LIGHTNING, 28, formula="8d6")],
        spell_range=SpellRange(range_type),
        targeting_type=TargetingType.AOE,
        aoe=AOEProperties(AOEShape.LINE, size_ft=length_ft),
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=True),
    )


def _touch_spell() -> SpellAction:
    return SpellAction(
        name="Inflict Wounds",
        description="",
        spell_level=1,
        save_dc=0,
        save_ability="",
        spell_attack_bonus=5,
        damage=[Damage(DamageType.NECROTIC, 15, formula="3d10")],
        spell_range=SpellRange(RangeType.TOUCH),
        targeting_type=TargetingType.SINGLE_TARGET,
        aoe=None,
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=True),
    )


def _ranged_spell(range_ft: int = 120) -> SpellAction:
    return SpellAction(
        name="Fire Bolt",
        description="",
        spell_level=0,
        save_dc=0,
        save_ability="",
        spell_attack_bonus=7,
        damage=[Damage(DamageType.FIRE, 5, formula="1d10")],
        spell_range=SpellRange(RangeType.FEET, distance_ft=range_ft),
        targeting_type=TargetingType.SINGLE_TARGET,
        aoe=None,
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=True),
    )


def _sight_spell() -> SpellAction:
    return SpellAction(
        name="Scrying",
        description="",
        spell_level=5,
        save_dc=15,
        save_ability="wisdom",
        spell_attack_bonus=0,
        damage=[],
        spell_range=SpellRange(RangeType.SIGHT),
        targeting_type=TargetingType.SINGLE_TARGET,
        aoe=None,
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=True),
    )


def _make_combat(*entities) -> CombatSystem:
    cs = CombatSystem()
    for e in entities:
        cs.add_combatant(e, initiative_modifier=0)
    cs.combatants = list(entities)
    return cs


# ---------------------------------------------------------------------------
# AOE requires a target
# ---------------------------------------------------------------------------

class TestAoERequiresTarget:
    def test_aoe_without_target_raises(self):
        caster = _make_entity("Wizard")
        target = _make_entity("Goblin", x=10.0)
        combat = _make_combat(caster, target)
        spell = _fireball()

        with pytest.raises(ValueError, match="requires a target point"):
            combat.resolve_spell(caster, [target], spell)

    def test_aoe_with_target_succeeds(self):
        caster = _make_entity("Wizard")
        target = _make_entity("Goblin", x=10.0)
        combat = _make_combat(caster, target)
        spell = _fireball()

        # Should not raise
        results = combat.resolve_spell(caster, [], spell, target=Point3D(10.0, 0.0, 0.0))
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Auto-targeting
# ---------------------------------------------------------------------------

class TestAoEAutoTargeting:
    def test_sphere_hits_entities_in_radius(self):
        caster = _make_entity("Wizard", x=0.0)
        inside = _make_entity("Inside", x=10.0, hp=100)
        outside = _make_entity("Outside", x=60.0, hp=100)
        combat = _make_combat(caster, inside, outside)
        spell = _fireball(radius_ft=20)

        initial_inside = inside.hp
        initial_outside = outside.hp

        # Blast centred at (25, 0, 0); inside's bbox [7.5,12.5] is within 20ft, outside is not
        combat.resolve_spell(caster, [], spell, target=Point3D(25.0, 0.0, 0.0))

        assert inside.hp < initial_inside, "Entity inside radius should take damage"
        assert outside.hp == initial_outside, "Entity outside radius should be unaffected"

    def test_caster_can_be_caught_in_own_aoe(self):
        caster = _make_entity("Wizard", x=0.0, hp=50)
        combat = _make_combat(caster)
        spell = _fireball(radius_ft=20)

        initial_hp = caster.hp
        # Blast at origin — caster is inside
        combat.resolve_spell(caster, [], spell, target=Point3D(0.0, 0.0, 0.0))

        assert caster.hp < initial_hp

    def test_no_targets_in_area_returns_empty(self):
        caster = _make_entity("Wizard", x=0.0)
        combat = _make_combat(caster)
        spell = _fireball(radius_ft=5)

        # Blast far from the caster
        results = combat.resolve_spell(caster, [], spell, target=Point3D(200.0, 0.0, 0.0))
        assert results == []

    def test_dead_entities_not_targeted(self):
        # Caster at x=-30 so its bbox [-32.5,-27.5] is well outside the 20ft sphere
        caster = _make_entity("Wizard", x=-30.0)
        corpse = _make_entity("Dead", x=5.0, hp=1)
        corpse.current_hp = 0
        combat = _make_combat(caster, corpse)
        spell = _fireball(radius_ft=20)

        results = combat.resolve_spell(caster, [], spell, target=Point3D(5.0, 0.0, 0.0))
        assert results == []


# ---------------------------------------------------------------------------
# Range clamping
# ---------------------------------------------------------------------------

class TestRangeClamping:
    def test_target_beyond_range_is_clamped(self):
        """Blast target 200 ft away with a 150 ft range spell — sphere is at 150 ft.

        Range is measured from the caster's bbox centre (0, 2.5, 0) for a MEDIUM caster
        at origin.  Aiming to (200, 0, 0) the clamped sphere centre is approximately
        (149.98, 0.625, 0).

        at_150 (bbox [142.5,147.5]) → nearest point ~(147.5, 0.625, 0), dist ≈ 2.5 → inside
        beyond  (bbox [172.5,177.5]) → nearest point ~(172.5, 0.625, 0), dist ≈ 22.5  → outside
        """
        caster = _make_entity("Wizard", x=0.0)
        at_150 = _make_entity("At150", x=145.0, hp=100)
        beyond = _make_entity("Beyond", x=175.0, hp=100)
        combat = _make_combat(caster, at_150, beyond)
        spell = _fireball(range_ft=150, radius_ft=20)

        initial_150 = at_150.hp
        initial_beyond = beyond.hp

        # Aim 200 ft away — clamped to 150 ft from caster centre
        combat.resolve_spell(caster, [], spell, target=Point3D(200.0, 0.0, 0.0))

        assert at_150.hp < initial_150, "Entity at clamped range should be hit"
        assert beyond.hp == initial_beyond, "Entity beyond clamped range should be unaffected"

    def test_target_within_range_not_clamped(self):
        """Target within range stays unchanged."""
        caster = _make_entity("Wizard", x=0.0)
        target_entity = _make_entity("Target", x=40.0, hp=100)
        combat = _make_combat(caster, target_entity)
        spell = _fireball(range_ft=150, radius_ft=20)

        initial_hp = target_entity.hp
        combat.resolve_spell(caster, [], spell, target=Point3D(45.0, 0.0, 0.0))
        # Sphere at (45, 0, 0) radius 20; entity bbox [37.5,42.5] nearest pt to sphere = (42.5,0,0) dist=2.5 → hit
        assert target_entity.hp < initial_hp

    def test_caster_center_is_used_for_range_not_corner(self):
        """Range is measured from the caster's bounding box centre, not corner."""
        # MEDIUM caster at origin: bbox [-2.5,2.5]x[0,5]x[-2.5,2.5], centre at (0, 2.5, 0)
        caster = _make_entity("Wizard", x=0.0)
        # Target at 150 ft from centre (0, 2.5, 0) along X: x = 150
        target_pt = Point3D(150.0, 2.5, 0.0)
        entity = _make_entity("Target", x=144.0, hp=100)  # inside 20ft of target_pt
        combat = _make_combat(caster, entity)
        spell = _fireball(range_ft=150, radius_ft=20)

        initial_hp = entity.hp
        # Should NOT clamp (target is exactly at range from caster centre)
        combat.resolve_spell(caster, [], spell, target=target_pt)
        assert entity.hp < initial_hp


# ---------------------------------------------------------------------------
# Cone and line: origin always at caster
# ---------------------------------------------------------------------------

class TestConeAndLineOrigin:
    def test_cone_origin_is_caster_center(self):
        """Cone always starts at the caster; a very distant target just sets direction."""
        caster = _make_entity("Caster", x=0.0)
        # Entity right in front of the caster (inside 15ft cone)
        nearby = _make_entity("Near", x=10.0, hp=50)
        # Entity far away in a different direction — should not be hit
        far_off = _make_entity("Far", x=0.0, y=100.0, hp=50)
        combat = _make_combat(caster, nearby, far_off)
        spell = _cone_spell(length_ft=15)

        initial_near = nearby.hp
        initial_far = far_off.hp

        # Aim far to the right — cone still starts at caster
        combat.resolve_spell(caster, [], spell, target=Point3D(1000.0, 0.0, 0.0))

        assert nearby.hp < initial_near, "Entity within cone should be hit"
        assert far_off.hp == initial_far, "Entity outside cone should be unaffected"

    def test_line_origin_is_caster_center(self):
        """Line always starts at the caster; target just sets direction."""
        caster = _make_entity("Caster", x=0.0)
        in_line = _make_entity("InLine", x=20.0, hp=50)
        off_line = _make_entity("OffLine", x=20.0, z=20.0, hp=50)
        combat = _make_combat(caster, in_line, off_line)
        spell = _line_spell(length_ft=60)

        initial_in = in_line.hp
        initial_off = off_line.hp

        # Aim along X axis
        combat.resolve_spell(caster, [], spell, target=Point3D(100.0, 0.0, 0.0))

        assert in_line.hp < initial_in, "Entity in line should be hit"
        assert off_line.hp == initial_off, "Entity off the line should be unaffected"

    def test_cone_self_range_accepts_any_target_distance(self):
        """SELF-range cone doesn't clamp regardless of target distance."""
        caster = _make_entity("Caster", x=0.0)
        nearby = _make_entity("Near", x=5.0, hp=50)
        combat = _make_combat(caster, nearby)
        spell = _cone_spell(range_type=RangeType.SELF, length_ft=15)

        initial = nearby.hp
        # Target arbitrarily far — should not raise and cone still hits nearby
        combat.resolve_spell(caster, [], spell, target=Point3D(9999.0, 0.0, 0.0))
        assert nearby.hp < initial


# ---------------------------------------------------------------------------
# Single-target range checking
# ---------------------------------------------------------------------------

class TestSingleTargetRange:
    def test_in_range_target_succeeds(self):
        caster = _make_entity("Wizard", x=0.0)
        target = _make_entity("Goblin", x=50.0, hp=20)
        combat = _make_combat(caster, target)
        spell = _ranged_spell(range_ft=120)

        initial = target.hp
        combat.resolve_spell(caster, [target], spell, target=Point3D(50.0, 0.0, 0.0))
        # May hit or miss based on dice; just verify no exception and hp may change
        assert isinstance(target.hp, int)

    def test_out_of_range_target_raises(self):
        caster = _make_entity("Wizard", x=0.0)
        target = _make_entity("Goblin", x=200.0)
        combat = _make_combat(caster, target)
        spell = _ranged_spell(range_ft=120)

        with pytest.raises(ValueError, match="out of range"):
            combat.resolve_spell(caster, [target], spell, target=Point3D(200.0, 0.0, 0.0))

    def test_touch_spell_succeeds_at_4ft(self):
        caster = _make_entity("Cleric", x=0.0)
        # Caster centre at (0, 2.5, 0); target centred at x=4, nearest edge at x=1.5 → dist=1.5 ≤ 5 ft touch
        target = _make_entity("Goblin", x=4.0, hp=20)
        combat = _make_combat(caster, target)
        spell = _touch_spell()

        # Should not raise (nearest point is within 5 ft touch range)
        assert isinstance(combat.resolve_spell(caster, [target], spell, target=Point3D(4.0, 0.0, 0.0)), list)

    def test_touch_spell_fails_beyond_5ft(self):
        caster = _make_entity("Cleric", x=0.0)
        # Caster centre at (0, 2.5, 0); target centred at x=11, nearest edge at (8.5, 2.5, 0)
        # Distance = 8.5 > 5
        target = _make_entity("Goblin", x=11.0, hp=20)
        combat = _make_combat(caster, target)
        spell = _touch_spell()

        with pytest.raises(ValueError, match="out of range"):
            combat.resolve_spell(caster, [target], spell, target=Point3D(11.0, 0.0, 0.0))

    def test_sight_range_never_fails(self):
        """SIGHT range imposes no distance limit."""
        caster = _make_entity("Wizard", x=0.0)
        target = _make_entity("Target", x=10000.0, hp=20)
        combat = _make_combat(caster, target)
        spell = _sight_spell()

        # Should not raise regardless of distance
        assert isinstance(combat.resolve_spell(caster, [target], spell, target=Point3D(10000.0, 0.0, 0.0)), list)

    def test_no_target_kwarg_skips_range_check(self):
        """Backward compat: omitting target= skips range check for single-target."""
        caster = _make_entity("Wizard", x=0.0)
        far_target = _make_entity("Far", x=500.0, hp=20)
        combat = _make_combat(caster, far_target)
        spell = _ranged_spell(range_ft=120)

        # Without target= kwarg, no range check; should not raise
        assert isinstance(combat.resolve_spell(caster, [far_target], spell), list)


# ---------------------------------------------------------------------------
# Zero-vector edge case
# ---------------------------------------------------------------------------

class TestZeroVectorEdgeCase:
    def test_target_at_caster_position_does_not_crash(self):
        """Targeting exactly the caster's position (zero-length vector) uses fallback direction."""
        caster = _make_entity("Wizard", x=0.0)
        combat = _make_combat(caster)
        spell = _cone_spell(length_ft=15)

        # Target coincides with caster position — must not raise
        caster_pos = Point3D(caster.x, caster.y, caster.z)
        results = combat.resolve_spell(caster, [], spell, target=caster_pos)
        assert isinstance(results, list)
