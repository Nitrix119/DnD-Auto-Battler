"""Execution test for the `grant_temporary_hp` block.

Regression coverage for a bug where the step called a non-existent
`Entity.gain_temporary_hp`, so any spell using the documented
`grant_temporary_hp` step crashed with AttributeError at runtime.  The existing
armor_of_agathys test only asserted JSON structure and never executed this
branch, so it did not catch the crash. Runs the block engine (the only engine),
covering a literal amount, an expression amount, and current vs self targeting.
"""

from src.combat.damage_processor import DamageProcessor
from src.combat.event_bus import EventBus
from src.models import Entity
from src.models.ability import AbilityScores
from src.models.action import SpellAction
from src.models.spell_properties import (
    CastingTime, CastingTimeType,
    Duration, DurationUnit,
    RangeType, SpellComponents, SpellRange,
    TargetingType,
)
from src.models.stat_block import StatBlock


def _entity(name: str) -> Entity:
    return Entity(StatBlock(
        name=name,
        ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=30,
        armor_class=10,
    ))


def _temp_hp_spell(amount, target="self") -> SpellAction:
    return SpellAction(
        name="Test Temp HP",
        description="",
        spell_range=SpellRange(RangeType.SELF),
        targeting_type=TargetingType.SINGLE_TARGET,
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=False),
        program=[
            {"block": "grant_temporary_hp", "target": target, "amount": amount},
        ],
    )


def _run(action, caster, defender):
    from src.spells.evaluator import resolve as resolve_blocks
    from src.spells.block import parse_program

    bus = EventBus()
    program = parse_program(action.program)
    return resolve_blocks(
        caster, defender, action, program,
        event_bus=bus, damage_processor=DamageProcessor(bus),
    )


def test_grant_temporary_hp_step_grants_temp_hp():
    caster, defender = _entity("Caster"), _entity("Defender")
    _run(_temp_hp_spell(10), caster, defender)
    assert caster.temporary_hp == 10  # step executed without AttributeError


def test_grant_temporary_hp_accepts_expression_amount():
    caster, defender = _entity("Caster"), _entity("Defender")
    _run(_temp_hp_spell("5 + 5"), caster, defender)
    assert caster.temporary_hp == 10


def test_grant_temporary_hp_can_target_defender():
    caster, defender = _entity("Caster"), _entity("Defender")
    _run(_temp_hp_spell(7, target="current"), caster, defender)
    assert defender.temporary_hp == 7
    assert caster.temporary_hp == 0
