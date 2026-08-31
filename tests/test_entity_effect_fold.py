"""Folding legacy add_entity_effect into a lifetime block (§4.3b).

The adapter now translates a foldable ``add_entity_effect`` step into a
``lifetime{ … }`` program, so a persistent-effect spell can run on the new engine.
4.3b folds the **state-only** case (an ``on_apply`` grant + a rule with no reactive
triggers) — Shield of Faith. Spells whose entity-effect rule declares triggers stay
on the legacy engine until 4.3b-2 folds the trigger side.
"""

import os

from src.models import Entity, AbilityScores, StatBlock, SpellAction, ACTION_COST
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

    def test_haste_folds_onto_blocks(self):
        # Haste folds like Vampiric Touch: a concentration lifetime carrying the
        # duration clock, whose TURN_START rider grants the ally +1 action.
        assert can_run_on_blocks(_spell("haste"), _rules()) is True
        spell = _spell("haste")
        program = to_program(spell.pipeline_effects, spell.targeting_type, _rules())
        life = program[-1]
        assert life.type == "lifetime"
        assert life.get("kind") == "concentration"
        assert life.get("duration_rounds") == 10
        trig = life.then[0]
        assert trig.type == "trigger"
        assert trig.get("event") == "TURN_START"
        assert trig.get("holder") == "defender"  # the hasted ally
        add = trig.then[0]
        assert add.type == "add_resource"
        assert add.get("resource") == "actions"

    def test_charm_person_folds_with_instance_field_bindings(self):
        # Charm Person's instance_fields (charmer) fold as the rider's captured
        # ``bindings``; the charmed Cancel keeps its per-effect ``when`` as a
        # fire-time condition referencing ``instance_fields.charmer``.
        assert can_run_on_blocks(_spell("charm_person"), _rules()) is True
        spell = _spell("charm_person")
        program = to_program(spell.pipeline_effects, spell.targeting_type, _rules())
        life = program[-1]
        assert life.type == "lifetime"
        trig = life.then[0]
        assert trig.type == "trigger"
        assert trig.get("event") == "ATTACK_DECLARED"
        assert trig.get("bindings") == {"charmer": "event.caster"}
        cancel = trig.then[0]
        assert cancel.type == "cancel"
        assert cancel.get("condition") == "event.defender == instance_fields.charmer"


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

    def test_armor_of_agathys_folds_with_retaliation_and_self_dispose(self):
        spell = _spell("armor_of_agathys")
        assert can_run_on_blocks(spell, _rules()) is True
        program = to_program(spell.pipeline_effects, spell.targeting_type, _rules())
        life = program[-1]
        assert life.type == "lifetime"
        kinds = [b.type for b in life.then]
        assert kinds[0] == "grant_temporary_hp"
        triggers = [b for b in life.then if b.type == "trigger"]
        by_event = {t.get("event"): t for t in triggers}
        # Retaliation: on a hit, damage the attacker, only while temp HP remain.
        hit = by_event["ATTACK_HIT"]
        assert hit.get("target") == "event.attacker"  # rebinds to the attacker
        assert hit.then[0].type == "damage"
        assert hit.then[0].get("condition") == "entity.temporary_hp > 0"
        # Self-dispose: when temp HP are gone, end the effect.
        dealt = by_event["DAMAGE_DEALT"]
        assert dealt.then[0].type == "end_lifetime"
        assert dealt.then[0].get("condition") == "entity.temporary_hp <= 0"

    def test_vampiric_touch_folds_with_a_granted_action_and_a_heal_rider(self):
        spell = _spell("vampiric_touch")
        assert can_run_on_blocks(spell, _rules()) is True
        program = to_program(spell.pipeline_effects, spell.targeting_type, _rules())
        # attack_roll, damage, healing (instantaneous), then the lifetime.
        assert [b.type for b in program] == [
            "attack_roll", "damage", "healing", "lifetime",
        ]
        life = program[-1]
        assert life.get("kind") == "concentration"
        assert life.get("duration_rounds") == 10  # ticks via the clock, on_caster
        assert [b.type for b in life.then] == ["grant_action", "trigger"]
        rider = life.then[1]
        assert rider.get("event") == "DAMAGE_DEALT" and rider.get("holder") == "caster"
        assert [b.type for b in rider.then] == ["healing"]

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


class TestCharmPersonFold:
    """Charm Person on the new engine — the instance_fields closure (charmer)."""

    def _cast(self, resolver, caster, target, *, save_fails):
        from unittest.mock import patch

        roll = (5, False) if save_fails else (20, True)
        with patch("src.spells.blocks.rolls.roll_saving_throw", return_value=roll):
            resolver.resolve(caster, [target], _spell("charm_person"))

    def _declare(self, bus, attacker, defender):
        from src.combat.event_data import AttackDeclaredData

        return bus.emit(
            EventType.ATTACK_DECLARED,
            AttackDeclaredData(attacker=attacker, defender=defender, action=None),
        )

    def test_charmed_target_cannot_attack_the_caster(self):
        caster, target = _cleric(), _cleric()
        bus, engine, resolver = _resolver(caster, target)
        self._cast(resolver, caster, target, save_fails=True)
        assert len(target.lifetimes) == 1  # folded onto the new engine
        assert self._declare(bus, target, caster).cancelled is True

    def test_charmed_target_can_attack_others(self):
        caster, target, bystander = _cleric(), _cleric(), _cleric()
        bus, engine, resolver = _resolver(caster, target, bystander)
        self._cast(resolver, caster, target, save_fails=True)
        assert self._declare(bus, target, bystander).cancelled is False

    def test_successful_save_applies_no_charm(self):
        caster, target = _cleric(), _cleric()
        bus, engine, resolver = _resolver(caster, target)
        self._cast(resolver, caster, target, save_fails=False)
        assert len(target.lifetimes) == 0
        assert self._declare(bus, target, caster).cancelled is False

    def test_two_casts_track_their_own_charmer(self):
        """Each cast captures its own charmer — a victim blocks only its charmer."""
        charmer_a, charmer_b = _cleric(), _cleric()
        victim_a, victim_b = _cleric(), _cleric()
        bus, engine, resolver = _resolver(charmer_a, charmer_b, victim_a, victim_b)
        self._cast(resolver, charmer_a, victim_a, save_fails=True)
        self._cast(resolver, charmer_b, victim_b, save_fails=True)

        assert self._declare(bus, victim_a, charmer_a).cancelled is True
        assert self._declare(bus, victim_a, charmer_b).cancelled is False
        assert self._declare(bus, victim_b, charmer_b).cancelled is True
        assert self._declare(bus, victim_b, charmer_a).cancelled is False


class TestHasteFold:
    """Haste on the new engine — the VT pattern with the rider on a targeted ally."""

    def _setup(self, caster, ally):
        from src.combat.spell_resolver import SpellResolver
        from src.combat.lifetime_clock import install_lifetime_clock

        bus = EventBus()
        install_lifetime_clock(bus)  # ticks concentration/duration on TURN_END
        dp = DamageProcessor(bus)
        reg = EffectRegistry()
        reg.scan_directory("rules/entity_effects")
        engine = RuleEngine(bus, entities_getter=lambda: [caster, ally],
                            damage_processor=dp, effect_registry=reg)
        engine.load_from_file("rules/global/action_economy_refill.json")
        engine.load_from_file("rules/global/concentration.json")
        return bus, engine, SpellResolver(bus, dp, rule_engine=engine)

    def _turn_start(self, bus, entity, round_num=2):
        from src.combat.event_data import TurnEventData

        bus.emit(EventType.TURN_START,
                 TurnEventData(entity=entity, round_num=round_num, turn_num=1))

    def _turn_end(self, bus, entity, round_num=1):
        from src.combat.event_data import TurnEventData

        bus.emit(EventType.TURN_END,
                 TurnEventData(entity=entity, round_num=round_num, turn_num=1))

    def test_grants_extra_action_on_the_ally_after_refill(self):
        caster, ally = _cleric(), _cleric()
        bus, engine, resolver = self._setup(caster, ally)
        resolver.resolve(caster, [ally], _spell("haste"))

        # Runs on the new engine: the caster concentrates, targeting the ally.
        assert caster.concentration_scope is not None
        assert caster.concentration_target is ally

        base = ally.resources.actions
        ally.spend_resources(ACTION_COST)  # actions -> 0
        self._turn_start(bus, ally)
        # Refilled to base, then the rider adds +1 (it fires at -10, after refill).
        assert ally.resources.actions == base + 1

    def test_breaking_concentration_stops_the_bonus(self):
        from unittest.mock import patch

        caster, ally = _cleric(), _cleric()
        bus, engine, resolver = self._setup(caster, ally)
        resolver.resolve(caster, [ally], _spell("haste"))

        # A failed CON save from damage to the caster breaks concentration.
        with patch("src.rules.effects.roll_d20", return_value=1):
            bus.emit(EventType.DAMAGE_DEALT, defender=caster, damage_list=[], total=20)
        assert not caster.has_concentration

        ally.spend_resources(ACTION_COST)
        self._turn_start(bus, ally)
        assert ally.resources.actions == 1  # only the refill; the rider is revoked

    def test_duration_expires_on_the_casters_turns(self):
        """Accepted deviation: the 10-round clock lives on the caster's concentration
        scope, so it ticks on the *caster's* turns, not the ally's (see fold.py)."""
        caster, ally = _cleric(), _cleric()
        bus, engine, resolver = self._setup(caster, ally)
        resolver.resolve(caster, [ally], _spell("haste"))

        for r in range(1, 11):
            assert caster.has_concentration, f"round {r}: still concentrating"
            self._turn_end(bus, caster, round_num=r)
        assert not caster.has_concentration  # expired after 10 caster turns

        ally.spend_resources(ACTION_COST)
        self._turn_start(bus, ally, round_num=11)
        assert ally.resources.actions == 1  # the bonus is gone
