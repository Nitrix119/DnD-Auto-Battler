"""Regression tests for InjectPipelineDamageStep mutating a shared action.

The ``InjectPipelineDamageStep`` handler (used by e.g. Colossus Slayer) appends a
damage step to the triggering action's ``pipeline_effects`` from an ATTACK_HIT
handler, so the bonus damage lands in the same pipeline run. That mechanism is
fine for weapon attacks because ``AttackResolver`` runs on a *copy* of the action
with a freshly built step list.

For **spells**, however, ``SpellResolver`` runs the pipeline on the shared
``SpellAction`` from the registry. Before this fix, the injected step was appended
to that shared list and never removed, so:

  * casting the same spell twice compounded the bonus damage (the injected step
    accumulated), and
  * within one AoE cast, later targets saw injected steps from earlier targets.

These tests reproduce both symptoms and pin the invariant: a pipeline run must not
leave the action's ``pipeline_effects`` mutated, and repeated casts must be
identical.
"""

from unittest.mock import patch

from src.models import AbilityScores, StatBlock, Entity, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.spell_resolver import SpellResolver
from src.rules.rule_engine import RuleEngine
from src.rules.effect_registry import EffectRegistry


# -- Helpers ------------------------------------------------------------------

def _make_entity(name="Caster", hp=30, ac=10):
    sb = StatBlock(
        name=name,
        ability_scores=AbilityScores(14, 14, 14, 10, 10, 10),
        hit_points_max=hp,
        armor_class=ac,
    )
    entity = Entity(sb)
    entity.refill_resources()
    return entity


def _setup(*entities):
    """Wire an EventBus + RuleEngine (with entity-effects scanned) + SpellResolver."""
    entity_list = list(entities)
    bus = EventBus()
    damage_proc = DamageProcessor(bus)
    registry = EffectRegistry()
    registry.scan_directory("rules/entity_effects")
    engine = RuleEngine(
        bus,
        entities_getter=lambda: entity_list,
        damage_processor=damage_proc,
        effect_registry=registry,
    )
    spell_res = SpellResolver(bus, damage_proc, rule_engine=engine)
    return engine, spell_res


def _attack_spell():
    """A minimal attack-roll spell: to-hit then a fixed-type damage step."""
    return SpellAction(
        name="Test Bolt",
        description="A test attack-roll spell.",
        spell_level=1,
        pipeline_effects=[
            {"type": "attack_roll", "attack_bonus": 10},
            {"type": "damage", "damage_type": "FIRE", "formula": "1d6", "requires_hit": True},
        ],
    )


def _apply_colossus(engine, caster):
    """Give the caster the Colossus Slayer ATTACK_HIT injection effect."""
    from src.rules.rule_loader import RuleLoader
    rule = RuleLoader.load("rules/entity_effects/colossus_slayer.json")
    engine.apply_effect(caster, rule)


# -- Tests --------------------------------------------------------------------

class TestInjectDoesNotMutateSharedAction:

    def test_run_restores_action_pipeline_effects(self):
        """After a cast, the spell's own pipeline_effects list is unchanged."""
        caster = _make_entity("Caster")
        target = _make_entity("Target", hp=40)
        # Pre-wound so Colossus Slayer's condition (hp < max_hp) holds.
        from src.models.damage import Damage, DamageType
        target.take_damage(Damage(DamageType.BLUDGEONING, 5))

        engine, spell_res = _setup(caster, target)
        _apply_colossus(engine, caster)
        spell = _attack_spell()
        original_len = len(spell.pipeline_effects)

        with patch("src.combat.effect_pipeline.roll_d20", return_value=20), \
             patch("src.combat.effect_pipeline.roll_formula", return_value=3):
            spell_res.resolve(caster, [target], spell)

        assert len(spell.pipeline_effects) == original_len

    def test_two_casts_deal_identical_damage(self):
        """Casting the same spell twice must not compound the injected bonus damage."""
        caster = _make_entity("Caster")
        target = _make_entity("Target", hp=100)
        from src.models.damage import Damage, DamageType
        target.take_damage(Damage(DamageType.BLUDGEONING, 5))  # wound it

        engine, spell_res = _setup(caster, target)
        _apply_colossus(engine, caster)
        spell = _attack_spell()

        with patch("src.combat.effect_pipeline.roll_d20", return_value=20), \
             patch("src.combat.effect_pipeline.roll_formula", return_value=3):
            hp_before_1 = target.hp
            spell_res.resolve(caster, [target], spell)
            dealt_1 = hp_before_1 - target.hp

            hp_before_2 = target.hp
            spell_res.resolve(caster, [target], spell)
            dealt_2 = hp_before_2 - target.hp

        # base 1d6 (3) + colossus 1d8 (3) = 6 each cast, both times.
        assert dealt_1 == 6
        assert dealt_2 == dealt_1

    def test_aoe_targets_are_not_compounded(self):
        """Within one cast, an injection on an earlier target must not leak to a later one."""
        caster = _make_entity("Caster")
        t1 = _make_entity("T1", hp=100)
        t2 = _make_entity("T2", hp=100)
        from src.models.damage import Damage, DamageType
        t1.take_damage(Damage(DamageType.BLUDGEONING, 5))
        t2.take_damage(Damage(DamageType.BLUDGEONING, 5))

        engine, spell_res = _setup(caster, t1, t2)
        _apply_colossus(engine, caster)
        spell = _attack_spell()

        with patch("src.combat.effect_pipeline.roll_d20", return_value=20), \
             patch("src.combat.effect_pipeline.roll_formula", return_value=3):
            hp1_before, hp2_before = t1.hp, t2.hp
            spell_res.resolve(caster, [t1, t2], spell)

        assert hp1_before - t1.hp == 6
        assert hp2_before - t2.hp == 6
