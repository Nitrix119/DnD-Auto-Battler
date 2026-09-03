"""Condition riders install on the conditioned entity, holder-agnostic.

SPELL_SYSTEM_REMAINING §3.2: the reactive rule for a condition no longer bakes
``holder: "defender"`` into its trigger. ``apply_condition`` installs the rider on a
child invocation whose caster/target *are* the conditioned entity, so the default
``holder: "caster"`` binds ``entity`` correctly whether the spell conditions its target
or itself. Two things this must not break, and one it must newly get right:

- **Regression guard** — Charm Person's ``bindings: {charmer: "event.caster"}`` must
  still resolve to the *caster*, even though the rider now installs with caster = the
  charmed creature. The bindings are pre-resolved against the cast invocation.
- **The previously-latent case** — a condition applied to the caster itself
  (``target: "self"``) must bind the rider to the caster.
"""

import os

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus, EventType
from src.combat.damage_processor import DamageProcessor
from src.rules import RuleLoader
from src.rules.effect_registry import EffectRegistry
from src.spells.block import parse_program
from src.spells.evaluator import resolve as resolve_blocks

CONDITIONS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "rules", "entity_effects", "conditions"
)


def _entity(name="E", hp=100):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=10,
    )
    return Entity(sb)


def _condition_rules(*names):
    """An EffectRegistry holding the real shipped rule for each named condition."""
    reg = EffectRegistry()
    for name in names:
        reg._effects[name] = RuleLoader.load(
            os.path.join(CONDITIONS_DIR, f"{name}.json")
        )
    return reg


def _cast(caster, target, program, condition_rules):
    bus = EventBus()
    resolve_blocks(
        caster, target, SpellAction(name="Cast", description="", spell_level=1),
        parse_program(program), event_bus=bus,
        damage_processor=DamageProcessor(bus), condition_rules=condition_rules,
    )
    return bus


# ── Regression guard: Charmed's charmer still resolves to the caster ───────────

def test_charmed_binding_resolves_to_the_caster():
    """Casting charmed at a target binds ``charmer`` to the caster, not the target.

    The rider now installs with caster = the charmed creature, so this only works
    because the binding is pre-resolved against the cast invocation.
    """
    caster, target, bystander = _entity("Caster"), _entity("Target"), _entity("Bystander")
    program = [{
        "block": "apply_condition", "condition_type": "charmed",
        "target": "current", "bindings": {"charmer": "event.caster"},
    }]
    bus = _cast(caster, target, program, _condition_rules("charmed"))

    # The charmed target cannot attack its charmer (the caster)…
    ev = bus.emit(EventType.ATTACK_DECLARED, attacker=target, defender=caster, action=None)
    assert ev.cancelled is True
    # …but can attack anyone else.
    ev2 = bus.emit(EventType.ATTACK_DECLARED, attacker=target, defender=bystander, action=None)
    assert ev2.cancelled is False


# ── The previously-latent case: a condition applied to the caster itself ───────

def test_condition_applied_to_self_binds_rider_to_caster():
    """``apply_condition`` with ``target: "self"`` installs the rider on the caster.

    Blinded grants disadvantage on the blinded creature's own attacks. Applied to the
    caster, the rider's ``entity`` must be the caster — the case the old baked
    ``holder: "defender"`` would have resolved wrong.
    """
    caster, other = _entity("Caster"), _entity("Other")
    program = [{
        "block": "apply_condition", "condition_type": "blinded", "target": "self",
    }]
    bus = _cast(caster, other, program, _condition_rules("blinded"))

    # The blinded caster attacks → disadvantage flagged on its own attack.
    ev = bus.emit(EventType.ATTACK_DECLARED, attacker=caster, defender=other, action=None)
    assert ev.data.get("disadvantage") is True
    # An unrelated attacker is unaffected.
    ev2 = bus.emit(EventType.ATTACK_DECLARED, attacker=other, defender=caster, action=None)
    assert ev2.data.get("disadvantage") is not True
