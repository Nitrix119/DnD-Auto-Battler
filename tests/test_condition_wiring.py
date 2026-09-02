"""`apply_condition` installs a condition's reactive mechanics (Phase 3 §3 slice).

A `Condition` marker is inert data; a condition only *does* something through its
reactive rule (`rules/entity_effects/conditions/<name>.json`, e.g. blinded → the
creature attacks at disadvantage and is attacked at advantage). Historically the
`apply_condition` block added only the marker, so every condition except charm was
mechanically dead in production. These tests prove the block now installs the
reactive rule too, owned by a lifetime scope so it ends with the condition — via
expiry, concentration loss, or dispel — and degrades gracefully when unwired.
"""

from src.models import AbilityScores, StatBlock, Entity
from src.models.condition import ConditionType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.combat.spell_resolver import SpellResolver
from src.models.action import SpellAction
from src.rules import RuleEngine
from src.rules.effect_registry import EffectRegistry

import src.spells.blocks  # noqa: F401  (registers the block catalogue)
from src.spells.block import Block, parse_program
from src.spells.context import CastEnv, Invocation, seed_context
from src.spells.runner import run_block


def _ent(name="E", ac=10, hp=30):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=ac,
    )
    return Entity(sb)


def _wire(*entities, with_registry=True):
    bus = EventBus()
    dp = DamageProcessor(bus)
    reg = EffectRegistry() if with_registry else None
    if reg is not None:
        reg.scan_directory("rules/entity_effects")
    engine = RuleEngine(
        bus, entities_getter=lambda: list(entities),
        damage_processor=dp, effect_registry=reg,
    )
    return bus, dp, engine


def _apply_condition(bus, dp, engine, *, caster, target, ctype, **extra):
    """Run an `apply_condition` block on a wired invocation (caster casts on target)."""
    env = CastEnv(action=None, event_bus=bus, damage_processor=dp, rule_engine=engine)
    inv = Invocation(env=env, caster=caster, target=target, context=seed_context(0))
    run_block(Block.from_dict({"block": "apply_condition", "condition_type": ctype, **extra}), inv)


def _declare(bus, attacker, defender):
    return bus.emit(EventType.ATTACK_DECLARED, attacker=attacker, defender=defender, action=None)


# ── The headline: reactive mechanics actually fire ────────────────────────────

class TestConditionMechanicsFire:

    def test_blinded_attacker_gets_disadvantage(self):
        caster, blind = _ent("Caster"), _ent("Blind")
        other = _ent("Other")
        bus, dp, engine = _wire(caster, blind, other)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        ev = _declare(bus, attacker=blind, defender=other)
        assert ev.data.get("disadvantage") is True
        assert ev.data.get("advantage", False) is False

    def test_blinded_defender_gives_attacker_advantage(self):
        caster, blind = _ent("Caster"), _ent("Blind")
        other = _ent("Other")
        bus, dp, engine = _wire(caster, blind, other)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        ev = _declare(bus, attacker=other, defender=blind)
        assert ev.data.get("advantage") is True
        assert ev.data.get("disadvantage", False) is False

    def test_marker_is_still_added(self):
        caster, blind = _ent("Caster"), _ent("Blind")
        bus, dp, engine = _wire(caster, blind)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")
        assert [c.condition_type for c in blind.conditions] == [ConditionType.BLINDED]

    def test_emits_condition_added(self):
        """The block announces the condition on the bus, carrying entity + marker."""
        caster, target = _ent("Caster"), _ent("Target")
        bus, dp, engine = _wire(caster, target)
        received = []
        bus.subscribe(EventType.CONDITION_ADDED, lambda e: received.append(e))

        _apply_condition(bus, dp, engine, caster=caster, target=target, ctype="poisoned")

        assert len(received) == 1
        assert received[0].data["entity"] is target
        assert received[0].data["condition"].condition_type == ConditionType.POISONED

    def test_condition_does_not_affect_bystanders(self):
        caster, blind, a, b = _ent("Caster"), _ent("Blind"), _ent("A"), _ent("B")
        bus, dp, engine = _wire(caster, blind, a, b)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        ev = _declare(bus, attacker=a, defender=b)
        assert ev.data.get("disadvantage", False) is False
        assert ev.data.get("advantage", False) is False


# ── Lifetime: the mechanics end with the condition ────────────────────────────

class TestConditionLifetime:

    def test_expires_after_duration(self):
        caster, blind, other = _ent("Caster"), _ent("Blind"), _ent("Other")
        bus, dp, engine = _wire(caster, blind, other)
        _apply_condition(bus, dp, engine, caster=caster, target=blind,
                         ctype="blinded", duration=2)

        # Still blinded before expiry.
        assert _declare(bus, blind, other).data.get("disadvantage") is True

        blind.tick_lifetimes()  # end of turn 1: 2 → 1
        blind.tick_lifetimes()  # end of turn 2: 1 → 0 → dispose

        assert blind.conditions == []                      # marker gone
        assert _declare(bus, blind, other).data.get("disadvantage", False) is False  # rider gone

    def test_permanent_condition_persists(self):
        caster, blind, other = _ent("Caster"), _ent("Blind"), _ent("Other")
        bus, dp, engine = _wire(caster, blind, other)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        for _ in range(5):
            blind.tick_lifetimes()
        assert _declare(bus, blind, other).data.get("disadvantage") is True

    def test_dispel_removes_marker_and_mechanics(self):
        caster, blind, other = _ent("Caster"), _ent("Blind"), _ent("Other")
        bus, dp, engine = _wire(caster, blind, other)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        blind.remove_condition(0)  # dispel

        assert blind.conditions == []
        assert _declare(bus, blind, other).data.get("disadvantage", False) is False

    def test_removed_when_concentration_drops(self):
        """A condition applied inside a concentration spell ends when it does."""
        caster, blind, other = _ent("Caster"), _ent("Blind"), _ent("Other")
        bus, dp, engine = _wire(caster, blind, other)
        program = parse_program([{
            "block": "lifetime", "concentration": True,
            "then": [{"block": "apply_condition", "condition_type": "blinded"}],
        }])
        from src.spells.evaluator import resolve as resolve_blocks
        resolve_blocks(caster, blind, SpellAction(name="Hold", description="", spell_level=2),
                       program, event_bus=bus, damage_processor=dp, rule_engine=engine)

        assert _declare(bus, blind, other).data.get("disadvantage") is True
        caster.end_concentration()
        assert blind.conditions == []
        assert _declare(bus, blind, other).data.get("disadvantage", False) is False


# ── Graceful degradation + end-to-end cast ────────────────────────────────────

class TestWiringSeams:

    def test_no_registry_still_adds_marker(self):
        caster, blind, other = _ent("Caster"), _ent("Blind"), _ent("Other")
        bus, dp, engine = _wire(caster, blind, other, with_registry=False)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        assert [c.condition_type for c in blind.conditions] == [ConditionType.BLINDED]
        # No rule wired → marker only, no mechanics, no crash.
        assert _declare(bus, blind, other).data.get("disadvantage", False) is False

    def test_marker_only_condition_still_expires(self):
        """A lifetime scope is the clock even with no reactive rule to install.

        Otherwise a marker-only condition's duration would have no clock at all
        once the legacy `RuleEngine._tick_durations` is gone.
        """
        caster, blind = _ent("Caster"), _ent("Blind")
        bus, dp, engine = _wire(caster, blind, with_registry=False)
        _apply_condition(bus, dp, engine, caster=caster, target=blind,
                         ctype="blinded", duration=2)

        assert [c.condition_type for c in blind.conditions] == [ConditionType.BLINDED]
        blind.tick_lifetimes()  # end of turn 1: 2 → 1
        assert blind.conditions != []
        blind.tick_lifetimes()  # end of turn 2: 1 → 0 → dispose
        assert blind.conditions == []

    def test_marker_only_condition_without_duration_is_permanent(self):
        caster, blind = _ent("Caster"), _ent("Blind")
        bus, dp, engine = _wire(caster, blind, with_registry=False)
        _apply_condition(bus, dp, engine, caster=caster, target=blind, ctype="blinded")

        for _ in range(5):
            blind.tick_lifetimes()
        assert [c.condition_type for c in blind.conditions] == [ConditionType.BLINDED]

    def test_charm_binding_cancels_attack_on_the_charmer(self):
        """A `bindings` field carries per-instance closure values (Charmed's charmer),
        so a charm-shaped condition works through `apply_condition` too."""
        charmer, victim, other = _ent("Charmer"), _ent("Victim"), _ent("Other")
        bus, dp, engine = _wire(charmer, victim, other)
        _apply_condition(bus, dp, engine, caster=charmer, target=victim,
                         ctype="charmed", bindings={"charmer": "event.caster"})

        # The charmed victim cannot attack the charmer (event cancelled)...
        assert _declare(bus, attacker=victim, defender=charmer).cancelled is True
        # ...but may attack anyone else.
        assert _declare(bus, attacker=victim, defender=other).cancelled is False

    def test_full_spell_cast_applies_working_condition(self):
        """A spell whose effect is an apply_condition step, cast on the block engine,
        produces a mechanically-functioning condition end-to-end."""
        caster, target, other = _ent("Caster"), _ent("Target"), _ent("Other")
        bus, dp, engine = _wire(caster, target, other)
        resolver = SpellResolver(bus, dp, rule_engine=engine)
        spell = SpellAction(
            name="Blind", description="", spell_level=2,
            pipeline_effects=[{"type": "apply_condition", "condition_type": "blinded"}],
        )
        resolver.resolve(caster, [target], spell)

        assert [c.condition_type for c in target.conditions] == [ConditionType.BLINDED]
        assert _declare(bus, target, other).data.get("disadvantage") is True
