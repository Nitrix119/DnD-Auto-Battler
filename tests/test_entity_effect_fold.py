"""Folding legacy add_entity_effect into a lifetime block (§4.3b).

The adapter now translates a foldable ``add_entity_effect`` step into a
``lifetime{ … }`` program, so a persistent-effect spell can run on the new engine.
4.3b folds the **state-only** case (an ``on_apply`` grant + a rule with no reactive
triggers) — Shield of Faith. Spells whose entity-effect rule declares triggers stay
on the legacy engine until 4.3b-2 folds the trigger side.
"""

import os

from src.models import Entity, AbilityScores, StatBlock, SpellAction
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.rules import EffectRegistry, RuleEngine
from src.loaders import StatBlockLoader
from src.spells.adapter import can_run_on_blocks, to_program

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


def _rules():
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    return lambda name: reg.get(name) if name in reg else None


def _spell(name):
    return StatBlockLoader.load_spell_from_json(os.path.join(SPELLS_DIR, f"{name}.json"))


# ── Routing boundary ────────────────────────────────────────────────────────────

class TestFoldRouting:

    def test_shield_of_faith_is_foldable_with_the_rule_lookup(self):
        assert can_run_on_blocks(_spell("shield_of_faith"), _rules()) is True

    def test_add_entity_effect_stays_legacy_without_a_rule_lookup(self):
        # No rule to prove the effect has no reactive triggers → not foldable.
        assert can_run_on_blocks(_spell("shield_of_faith"), None) is False

    def test_still_un_foldable_effects_stay_on_legacy(self):
        # Each stays on legacy for a specific reason (§4.3b-2): Vampiric Touch uses
        # GrantAction (no block) + a duration; Haste has a duration_rounds (needs
        # the §4.3c clock); Armor of Agathys uses RemoveEffect + per-effect `when`.
        rules = _rules()
        for name in ("vampiric_touch", "haste", "armor_of_agathys"):
            assert can_run_on_blocks(_spell(name), rules) is False, name

    def test_instance_fields_effect_stays_on_legacy(self):
        # Charm Person carries instance_fields (charmer) — not yet foldable.
        assert can_run_on_blocks(_spell("charm_person"), _rules()) is False


# ── Fold shape ────────────────────────────────────────────────────────────────

class TestFoldShape:

    def test_shield_of_faith_folds_to_a_concentration_lifetime(self):
        spell = _spell("shield_of_faith")
        program = to_program(spell.pipeline_effects, spell.targeting_type, _rules())
        assert len(program) == 1
        life = program[0]
        assert life.type == "lifetime"
        assert life.get("kind") == "concentration"
        assert [b.type for b in life.then] == ["add_modifier"]
        mod = life.then[0]
        assert mod.get("stat") == "ac" and mod.get("value") == 2
        assert mod.get("target") == "defender"

    def test_longstrider_folds_to_a_rounds_lifetime_with_a_turn_start_rider(self):
        spell = _spell("longstrider")
        program = to_program(spell.pipeline_effects, spell.targeting_type, _rules())
        assert len(program) == 1
        life = program[0]
        assert life.type == "lifetime" and life.get("kind") == "rounds"
        assert [b.type for b in life.then] == ["trigger"]
        rider = life.then[0]
        assert rider.get("event") == "TURN_START"
        assert rider.get("holder") == "defender"  # applied to the target, not caster
        assert [b.type for b in rider.then] == ["add_resource"]
        grant = rider.then[0]
        assert grant.get("resource") == "movement" and grant.get("amount") == 10


class TestLongstriderFoldEndToEnd:

    def test_movement_grant_fires_after_the_refill(self):
        """The rider adds +10 movement *after* the per-turn refill resets it.

        Validates the trigger's -10 priority slot: were it to fire before the
        priority-0 refill, the +10 would be wiped and movement would read base.
        """
        from src.combat.spell_resolver import SpellResolver
        from src.combat.event_data import TurnEventData

        wizard = StatBlockLoader.load_from_json(
            os.path.join(os.path.dirname(__file__), "..", "examples",
                         "creatures", "characters", "wizard.json")
        )
        wizard = Entity(wizard)
        goblin = StatBlockLoader.load_from_json(
            os.path.join(os.path.dirname(__file__), "..", "examples",
                         "creatures", "goblin.json")
        )
        goblin = Entity(goblin)
        base_move = goblin.resources.movement

        bus = EventBus()
        dp = DamageProcessor(bus)
        reg = EffectRegistry()
        reg.scan_directory("rules/entity_effects")
        engine = RuleEngine(bus, entities_getter=lambda: [wizard, goblin],
                            damage_processor=dp, effect_registry=reg)
        engine.load_from_file("rules/global/action_economy_refill.json")
        resolver = SpellResolver(bus, dp, rule_engine=engine)

        resolver.resolve(wizard, [goblin], _spell("longstrider"))
        assert len(goblin.lifetimes) == 1  # ran through the fold, not legacy

        bus.emit(EventType.TURN_START,
                 TurnEventData(entity=goblin, round_num=2, turn_num=1))
        assert goblin.resources.movement == base_move + 10


# ── End-to-end on the new engine, via the real router ───────────────────────────

def _cleric():
    sb = StatBlock(
        name="Cleric",
        ability_scores=AbilityScores(10, 10, 12, 10, 16, 10),
        hit_points_max=30, armor_class=14,
        proficiency_bonus=2, spellcasting_ability="wisdom",
    )
    return Entity(sb)


def _resolver(*entities):
    from src.combat.spell_resolver import SpellResolver

    bus = EventBus()
    dp = DamageProcessor(bus)
    reg = EffectRegistry()
    reg.scan_directory("rules/entity_effects")
    engine = RuleEngine(bus, entities_getter=lambda: list(entities),
                        damage_processor=dp, effect_registry=reg)
    engine.load_from_file("rules/global/concentration.json")
    return bus, engine, SpellResolver(bus, dp, rule_engine=engine)


class TestFoldEndToEnd:

    def test_cast_runs_on_the_new_engine_and_grants_ac(self):
        from unittest.mock import patch

        cleric = _cleric()
        bus, engine, resolver = _resolver(cleric)
        base = cleric.ac
        resolver.resolve(cleric, [cleric], _spell("shield_of_faith"))

        # Went through the fold, not legacy: a real lifetime scope is open.
        assert cleric.concentration_scope is not None
        assert cleric.has_concentration
        assert cleric.ac == base + 2

        # A failed CON save from damage tears the scope down and restores AC.
        with patch("src.rules.effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=cleric, damage_list=[], total=20)
        assert not cleric.has_concentration
        assert cleric.concentration_scope is None
        assert cleric.ac == base
