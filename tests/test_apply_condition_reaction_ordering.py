"""`apply_condition` installs reactions, so it must flush DAMAGE_DEALT first.

The evaluator emits the cast's pending `DAMAGE_DEALT` just *before* any block that
subscribes handlers to future events, so a rider that block installs does not fire on
the very damage that cast it (`runner.run_target`). `lifetime` and `trigger` declare
`installs_reactions=True` for exactly this reason.

`apply_condition` also subscribes handlers — it installs the condition's reactive
rule — but declared `installs_reactions=False`. Latent today, because no shipped
condition rider listens on DAMAGE_DEALT and no shipped spell both damages and applies
a condition. It stops being latent the moment someone writes a bleed-style condition,
so this pins the ordering with exactly that shape.
"""

from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleEngine, RuleLoader
from src.rules.effect_registry import EffectRegistry
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks

# A condition whose mechanics react to DAMAGE_DEALT — the shape that makes the
# ordering observable. Registered under a real ConditionType name so
# `apply_condition` finds it.
_BLEEDING_RULE = {
    "name": "poisoned",
    "program": [
        {
            "block": "trigger", "event": "DAMAGE_DEALT", "holder": "defender",
            "then": [{"block": "damage", "formula": "1d1", "damage_type": "NECROTIC"}],
        },
    ],
}


def _entity(name="E", hp=100):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=10,
    )
    return Entity(sb)


def _registry_with_reactive_condition() -> EffectRegistry:
    reg = EffectRegistry()
    reg._effects["poisoned"] = RuleLoader.from_dict(dict(_BLEEDING_RULE))
    return reg


def test_a_condition_rider_does_not_fire_on_its_own_casts_damage():
    """Damage, then apply the condition: the rider must not see that damage.

    Without the flush the pending DAMAGE_DEALT is emitted *after* the rider is
    subscribed, so the condition immediately retaliates against the damage that
    applied it — a rider firing on its own cast.
    """
    caster, target = _entity("Caster"), _entity("Target")
    bus = EventBus()
    dp = DamageProcessor(bus)
    engine = RuleEngine(bus, damage_processor=dp,
                        effect_registry=_registry_with_reactive_condition())

    program = parse_program([
        {"block": "damage", "formula": "10", "damage_type": "FIRE"},
        {"block": "apply_condition", "condition_type": "poisoned"},
    ])
    with patch("src.spells.blocks.damage.roll_formula", return_value=10):
        resolve_blocks(caster, target, SpellAction(name="Blight", description="",
                                                   spell_level=2),
                       program, event_bus=bus, damage_processor=dp,
                       rule_engine=engine)

    # The spell's own 10 fire damage, and nothing from the rider it just installed.
    assert target.hp == 100 - 10
