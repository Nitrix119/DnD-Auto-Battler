"""Split multi-target spells (design stage 3).

Spells like Magic Missile, Scorching Ray, and Eldritch Blast fire several
independent projectiles, each aimed at a chosen target (repeats allowed). We
model this with the ``multi_target`` targeting type over the existing
per-defender fan-out: ``defenders`` is the per-projectile target assignment, and
each projectile resolves independently — its own attack roll, its own damage
roll — rather than one shared blob. Projectile *count* (and its upcasting) is
deferred to the upcasting-framework work; here the caller supplies the target
list directly.
"""

from unittest.mock import patch

from src.models import (
    AbilityScores, StatBlock, Entity, SpellAction, TargetingType,
)
from src.loaders import StatBlockLoader
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.spell_resolver import SpellResolver

import os
SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


def _entity(name="E", hp=100, ac=10):
    sb = StatBlock(name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
                   hit_points_max=hp, armor_class=ac)
    e = Entity(sb)
    e.refill_resources()
    return e


def _resolver():
    bus = EventBus()
    return SpellResolver(bus, DamageProcessor(bus))


# ── Content loads with the new targeting type ───────────────────────────────────

class TestMultiTargetContent:

    def test_magic_missile_is_multi_target(self):
        spell = StatBlockLoader.load_spell_from_json(os.path.join(SPELLS_DIR, "magic_missile.json"))
        assert spell.targeting_type == TargetingType.MULTI_TARGET
        dmg = next(s for s in spell.pipeline_effects if s.get("type") == "damage")
        assert dmg["formula"] == "1d4+1"

    def test_scorching_ray_loads(self):
        spell = StatBlockLoader.load_spell_from_json(os.path.join(SPELLS_DIR, "scorching_ray.json"))
        assert spell.targeting_type == TargetingType.MULTI_TARGET
        types = [s["type"] for s in spell.pipeline_effects]
        assert types == ["attack_roll", "damage"]

    def test_eldritch_blast_is_multi_target(self):
        spell = StatBlockLoader.load_spell_from_json(os.path.join(SPELLS_DIR, "eldritch_blast.json"))
        assert spell.targeting_type == TargetingType.MULTI_TARGET


# ── Independent per-projectile resolution ───────────────────────────────────────

def _magic_missile():
    return SpellAction(
        name="Magic Missile", description="", spell_level=1,
        targeting_type=TargetingType.MULTI_TARGET,
        pipeline_effects=[{"type": "damage", "damage_type": "FORCE", "formula": "1d4+1"}],
    )


def _scorching_ray():
    return SpellAction(
        name="Scorching Ray", description="", spell_level=2,
        targeting_type=TargetingType.MULTI_TARGET,
        pipeline_effects=[
            {"type": "attack_roll", "attack_bonus": 10},
            {"type": "damage", "damage_type": "FIRE", "formula": "2d6", "requires_hit": True},
        ],
    )


class TestSplitResolution:

    def test_darts_can_stack_on_and_spread_across_targets(self):
        caster, g1, g2 = _entity("C"), _entity("G1"), _entity("G2")
        resolver = _resolver()
        # Two darts at g1, one at g2. Each die rolls its max via a fixed roll of 3.
        with patch("src.utils.dice.roll_dice", lambda n, s: n * 3):  # 1d4 -> 3, +1 -> 4
            results = resolver.resolve(caster, [g1, g2, g1], _magic_missile())
        # 1d4+1 with each die = 3 -> 3 + 1 = 4 per dart.
        assert g1.max_hp - g1.hp == 8   # two darts
        assert g2.max_hp - g2.hp == 4   # one dart
        assert len(results) == 3        # one result per projectile

    def test_each_dart_rolls_independently(self):
        caster, g1, g2 = _entity("C"), _entity("G1"), _entity("G2")
        resolver = _resolver()
        rolls = iter([1, 4])  # first dart's 1d4 -> 1, second dart's 1d4 -> 4
        with patch("src.utils.dice.roll_dice", lambda n, s: next(rolls)):
            resolver.resolve(caster, [g1, g2], _magic_missile())
        assert g1.max_hp - g1.hp == 2   # 1 + 1
        assert g2.max_hp - g2.hp == 5   # 4 + 1

    def test_scorching_ray_rolls_a_separate_attack_per_beam(self):
        caster = _entity("C")
        hit_target = _entity("Hit", ac=5)     # easy to hit
        miss_target = _entity("Miss", ac=99)  # impossible to hit
        resolver = _resolver()
        with patch("src.utils.dice.roll_d20", return_value=10), \
             patch("src.utils.dice.roll_dice", lambda n, s: n * 6):  # 2d6 -> 12
            resolver.resolve(caster, [hit_target, miss_target], _scorching_ray())
        assert hit_target.max_hp - hit_target.hp == 12  # beam hit
        assert miss_target.hp == miss_target.max_hp     # beam missed, no damage
