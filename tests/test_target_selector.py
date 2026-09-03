"""The two-value target selector is ``self``/``current`` and enforced at load.

Guards the rename from the old ``caster``/``defender`` values (SPELL_SYSTEM_REMAINING
§3.1). The old names must now *fail validation* — proving the rename is enforced, not
silently aliased — while ``self``/``current`` both load and resolve to the right entity.
"""

import pytest

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks
from src.spells.validate import validate_program, ProgramValidationError


def _entity(name="E", hp=100):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=10,
    )
    return Entity(sb)


# ── The old names are rejected at load ────────────────────────────────────────

@pytest.mark.parametrize("old_value", ["caster", "defender"])
def test_old_selector_values_fail_validation(old_value):
    program = [{"block": "healing", "target": old_value, "amount": "5"}]
    with pytest.raises(ProgramValidationError) as exc:
        validate_program(program, spell_name="Heal")
    # The message points at the valid set so an author can fix it.
    assert "self" in str(exc.value) and "current" in str(exc.value)


# ── The new names load and resolve ────────────────────────────────────────────

@pytest.mark.parametrize("value", ["self", "current"])
def test_new_selector_values_validate(value):
    validate_program(
        [{"block": "healing", "target": value, "amount": "5"}], spell_name="Heal"
    )  # does not raise


def _run_heal(target_value):
    caster, defender = _entity("Caster"), _entity("Defender")
    caster.current_hp = 90  # leave headroom so a heal is observable
    defender.current_hp = 90
    bus = EventBus()
    program = parse_program([{"block": "healing", "target": target_value, "amount": "5"}])
    resolve_blocks(
        caster, defender, SpellAction(name="Heal", description="", spell_level=1),
        program, event_bus=bus, damage_processor=DamageProcessor(bus),
    )
    return caster, defender


def test_self_heals_the_caster():
    caster, defender = _run_heal("self")
    assert caster.hp == 95
    assert defender.hp == 90


def test_current_heals_the_target():
    caster, defender = _run_heal("current")
    assert defender.hp == 95
    assert caster.hp == 90
