"""Tests for spell-applied entity effects.

Verifies that spells can declare entity effects via the ``effects`` field,
that saving throws gate their application via ``condition``, and that
``instance_fields`` expressions are evaluated correctly at spell-hit time.
"""

from pathlib import Path
from unittest.mock import patch


from src.models import Entity, SpellAction
from src.combat import EventBus, EventType
from src.combat.event_data import TurnEventData
from src.combat.spell_resolver import SpellResolver
from src.combat.damage_processor import DamageProcessor
from src.loaders.stat_block_loader import StatBlockLoader
from src.rules import EffectRegistry, RuleEngine

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
SPELLS_DIR = EXAMPLES_DIR / "spells"
CHARACTERS_DIR = EXAMPLES_DIR / "creatures/characters"
CREATURES_DIR = EXAMPLES_DIR / "creatures"
CONDITIONS_DIR = Path(__file__).parent.parent / "rules" / "entity_effects" / "conditions"


# ── Fixtures ──────────────────────────────────────────────────────────────────

def load_wizard() -> Entity:
    sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "wizard.json"))
    return Entity(sb)


def load_goblin() -> Entity:
    sb = StatBlockLoader.load_from_json(str(CREATURES_DIR / "goblin.json"))
    return Entity(sb)


def setup_engine_and_resolver(*entities):
    """Return (bus, rule_engine, spell_resolver) wired together."""
    bus = EventBus()
    damage_proc = DamageProcessor(bus)
    registry = EffectRegistry()
    registry.scan_directory("rules/entity_effects")
    engine = RuleEngine(bus, damage_processor=damage_proc,
                        effect_registry=registry)
    resolver = SpellResolver(bus, damage_proc, rule_engine=engine)
    return bus, engine, resolver


def charm_person_spell(save_dc: int = 13) -> SpellAction:
    """Load Charm Person from the example spell file, overriding the save DC.

    Charm Person is a native ``program`` (Phase 3 §5); its saving-throw block lives
    in ``program``, so the DC override targets that.
    """
    spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "charm_person.json"))
    for block in spell.program:
        if block.get("block") == "saving_throw":
            block["dc"] = save_dc
    return spell


# ── Loading ───────────────────────────────────────────────────────────────────

class TestSpellEffectLoading:

    def test_charm_person_loads_program(self):
        """charm_person.json parses into a native program: a save then an
        apply_condition for ``charmed``, gated on a failed save, binding the charmer."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "charm_person.json"))
        assert spell.program and not spell.pipeline_effects
        cond = [b for b in spell.program if b.get("block") == "apply_condition"]
        assert len(cond) == 1
        block = cond[0]
        assert block.get("condition_type") == "charmed"
        assert block.get("condition") == "not context.save_success"
        assert block.get("bindings", {}).get("charmer") == "event.caster"

    def test_charm_person_save_ability(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "charm_person.json"))
        save_steps = [b for b in spell.program if b.get("block") == "saving_throw"]
        assert save_steps[0]["attribute"] == "wisdom"
        assert save_steps[0]["dc"] == "use_caster_dc"

    def test_spell_without_effects_has_no_entity_effect_steps(self):
        """Firebolt has no add_entity_effect steps in the pipeline."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        effect_steps = [s for s in spell.pipeline_effects if s.get("type") == "add_entity_effect"]
        assert effect_steps == []

    def test_spell_without_save_has_no_saving_throw_step(self):
        """Firebolt has no saving_throw step in the pipeline."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        save_steps = [s for s in spell.pipeline_effects if s.get("type") == "saving_throw"]
        assert save_steps == []


# ── Saving throws ─────────────────────────────────────────────────────────────

class TestSavingThrows:

    def test_save_roll_available_on_spell_hit_event(self):
        """SPELL_HIT event should carry save_success and save_roll when save_dc > 0."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell_hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: spell_hit_events.append(e))

        spell = charm_person_spell(save_dc=30)  # DC 30 — goblin always fails
        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        assert len(spell_hit_events) == 1
        event = spell_hit_events[0]
        assert event.data.get("save_roll") is not None
        assert event.data.get("save_success") is False

    def test_spell_hit_save_success_when_roll_beats_dc(self):
        """save_success should be True when the save roll exceeds the DC."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell_hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: spell_hit_events.append(e))

        spell = charm_person_spell(save_dc=1)  # DC 1 — goblin always succeeds
        with patch("src.utils.saving_throw.roll_d20", return_value=20):
            resolver.resolve(wizard, [goblin], spell)

        assert spell_hit_events[0].data.get("save_success") is True

    def test_no_save_roll_when_save_dc_is_zero(self):
        """Spells with save_dc=0 should not roll a save (save_roll stays None).

        Magic Missile has no save at all (save_dc=0, save_ability=""), so it is
        used here. Fireball now carries save_dc="use_caster_dc" and correctly
        triggers a Dex save — that behaviour is tested in test_save_outcomes.py.
        """
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell_hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: spell_hit_events.append(e))

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "magic_missile.json"))
        resolver.resolve(wizard, [goblin], spell)

        assert spell_hit_events[0].data.get("save_roll") is None
        assert spell_hit_events[0].data.get("save_success") is True


# ── Effect application on failed save ─────────────────────────────────────────

class TestSpellEffectApplicationOnFailedSave:

    def test_charmed_applied_when_save_fails(self):
        """Charm Person applies charmed (on the new engine) when the defender fails."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = charm_person_spell(save_dc=30)  # DC 30 — goblin always fails

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        # Folded onto the new engine: a lifetime on the goblin holds the charmed
        # rider, and the captured charmer (the wizard) blocks the goblin's attack
        # on the wizard (the instance_fields closure took effect).
        assert len(goblin.lifetimes) == 1
        action = next(a for a in goblin.stat_block.actions if a.name == "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=wizard, action=action)
        assert event.cancelled is True

    def test_charmed_not_applied_when_save_succeeds(self):
        """Charm Person should NOT apply the charmed effect when the defender succeeds."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = charm_person_spell(save_dc=1)  # DC 1 — goblin always succeeds

        with patch("src.utils.saving_throw.roll_d20", return_value=20):
            resolver.resolve(wizard, [goblin], spell)

        assert goblin.lifetimes == []  # no charmed rider installed

    def test_charmed_attack_is_blocked_after_spell(self):
        """After a successful Charm Person cast, the charmed goblin cannot attack the wizard."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = charm_person_spell(save_dc=30)  # goblin always fails

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        # Now try the goblin attacking the wizard — should be cancelled
        action = next(a for a in goblin.stat_block.actions if a.name == "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=wizard, action=action)
        assert event.cancelled is True

    def test_charmed_goblin_can_still_attack_others(self):
        """The charmed goblin can still attack non-charmer entities."""
        wizard = load_wizard()
        goblin = load_goblin()
        bystander = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin, bystander)

        spell = charm_person_spell(save_dc=30)

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin], spell)

        action = next(a for a in goblin.stat_block.actions if a.name == "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=bystander, action=action)
        assert event.cancelled is False


# ── No rule_engine — effects silently skipped ─────────────────────────────────

class TestSpellEffectsWithoutRuleEngine:

    def test_native_condition_degrades_without_rule_engine(self):
        """Without a rule engine (no effect registry), a native ``apply_condition``
        still adds the condition *marker* but installs no reactive rider — a graceful
        degrade, not a crash. (Loud-fail for unexpressable native content is at load,
        via ``validate_program``; see tests/test_validate_program.py.)"""
        wizard = load_wizard()
        goblin = load_goblin()
        bus = EventBus()
        resolver = SpellResolver(bus, DamageProcessor(bus), rule_engine=None)

        spell = charm_person_spell(save_dc=30)  # save auto-fails → charm applies
        resolver.resolve(wizard, [goblin], spell)

        charmed = [c for c in goblin.get_active_conditions()
                   if c.condition_type.value == "charmed"]
        assert len(charmed) == 1          # marker applied

        # No rider installed without a registry: the charmed mechanics (a charmed
        # creature cannot attack its charmer) do not fire. The one lifetime present
        # is the marker's own duration clock, which every condition carries.
        assert bus.emit(EventType.ATTACK_DECLARED, attacker=goblin,
                        defender=wizard, action=None).cancelled is False
        assert goblin.lifetimes == [charmed[0].owning_scope]


# ── Rule caching ──────────────────────────────────────────────────────────────

class TestRuleCaching:

    def test_registry_returns_same_rule_object(self):
        """The charmed Rule template is cached (not re-parsed per cast), while each
        cast installs its own independent rider."""
        wizard = load_wizard()
        goblin_a = load_goblin()
        goblin_b = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin_a, goblin_b)

        spell = charm_person_spell(save_dc=30)

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [goblin_a], spell)
            resolver.resolve(wizard, [goblin_b], spell)

        # The rule template is the same cached object across lookups (not re-parsed).
        assert engine.effect_registry.get("charmed") is engine.effect_registry.get("charmed")
        # But each cast installed its own independent rider (a lifetime per goblin).
        assert len(goblin_a.lifetimes) == 1
        assert len(goblin_b.lifetimes) == 1
        assert goblin_a.lifetimes[0] is not goblin_b.lifetimes[0]


# ── CombatSystem integration ──────────────────────────────────────────────────

class TestCombatSystemIntegration:

    def test_rule_engine_wired_via_combat_system(self):
        """Setting combat.rule_engine should wire the rule_engine to SpellResolver."""
        from src.combat import CombatSystem

        bus = EventBus()
        engine = RuleEngine(bus)

        cs = CombatSystem()
        cs.event_bus = bus
        cs.rule_engine = engine

        assert cs._spell_resolver.rule_engine is engine

    def test_charm_person_via_combat_system_resolve_spell(self):
        """Calling CombatSystem.resolve_spell with Charm Person should apply charmed."""
        from src.combat import CombatSystem

        wizard = load_wizard()
        goblin = load_goblin()

        bus = EventBus()
        registry = EffectRegistry()
        registry.scan_directory("rules/entity_effects")
        engine = RuleEngine(bus,
                            effect_registry=registry)

        cs = CombatSystem()
        cs.event_bus = bus
        cs.rule_engine = engine
        cs.add_combatant(wizard, initiative_modifier=100)
        cs.add_combatant(goblin, initiative_modifier=0)

        spell = charm_person_spell(save_dc=30)  # goblin always fails

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            cs.resolve_spell(wizard, [goblin], spell)

        # Folded onto the new engine: the goblin holds a charmed lifetime and cannot
        # attack the wizard (its captured charmer).
        assert len(goblin.lifetimes) == 1
        action = next(a for a in goblin.stat_block.actions if a.name == "Scimitar")
        event = bus.emit(EventType.ATTACK_DECLARED,
                         attacker=goblin, defender=wizard, action=action)
        assert event.cancelled is True


# ── Longstrider spell integration ────────────────────────────────────────────

def load_cleric() -> Entity:
    sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "cleric.json"))
    return Entity(sb)


# ── Shield of Faith ───────────────────────────────────────────────────────────

class TestShieldOfFaithEffect:
    """Shield of Faith adds +2 AC via AddModifier on_apply and tracks concentration."""

    def test_ac_increases_by_two_on_cast(self):
        """Casting Shield of Faith on an entity raises its AC by 2."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.ac

        resolver.resolve(cleric, [cleric], spell)

        assert cleric.ac == base_ac + 2

    def test_stat_modifier_is_recorded(self):
        """A StatModifier with the correct fields is added to the target."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        resolver.resolve(cleric, [cleric], spell)

        ac_mods = cleric.get_stat_modifiers("ac")
        assert len(ac_mods) == 1
        mod = ac_mods[0]
        assert mod.value == 2
        assert mod.source == "Shield of Faith"
        assert mod.effect_name == "shield_of_faith"

    def test_stat_breakdown_contains_base_and_modifier(self):
        """get_stat_breakdown returns the base AC line followed by the spell modifier."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.stat_block.armor_class
        resolver.resolve(cleric, [cleric], spell)

        breakdown = cleric.get_stat_breakdown("ac")
        assert len(breakdown) == 2
        assert breakdown[0] == {"source": "Base", "value": base_ac}
        assert breakdown[1] == {"source": "Shield of Faith", "value": 2}

    def test_concentration_tracked_on_caster(self):
        """After casting, the caster's concentrating_on and concentration_target are set."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        resolver.resolve(cleric, [cleric], spell)

        assert cleric.concentrating_on == "shield_of_faith"
        assert cleric.concentration_target is cleric

    def test_ac_restored_when_effect_removed(self):
        """Removing the shield_of_faith effect strips the modifier and restores base AC."""
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.ac
        resolver.resolve(cleric, [cleric], spell)

        assert cleric.ac == base_ac + 2

        cleric.remove_effect("shield_of_faith")

        assert cleric.ac == base_ac
        assert cleric.get_stat_modifiers("ac") == []

    def test_zero_damage_cast_does_not_break_concentration(self):
        """Casting a zero-damage buff spell must not trigger a concentration check.

        apply_damage always emits DAMAGE_DEALT (even with total=0), so the
        concentration rule must guard on event.total > 0 — otherwise the cleric
        risks losing concentration on a spell it just cast.
        """
        cleric = load_cleric()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(cleric, goblin)

        # Load concentration rule so the engine enforces it
        engine.load_from_file("rules/global/concentration.json")

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        base_ac = cleric.ac

        # Cast 20 times — if 0-damage DAMAGE_DEALT could strip concentration,
        # a failed DC-10 Con save would occasionally drop the AC back to base.
        for _ in range(20):
            cleric.remove_effect("shield_of_faith")
            cleric.concentrating_on = None
            cleric.concentration_target = None
            resolver.resolve(cleric, [cleric], spell)
            assert cleric.ac == base_ac + 2, (
                "AC should be base+2 immediately after casting Shield of Faith"
            )


def longstrider_spell() -> SpellAction:
    """Load Longstrider from the example spell file."""
    return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "longstrider.json"))


class TestLongstriderSpellEffects:

    def test_longstrider_loads_program(self):
        """longstrider.json parses into a native program: a rounds lifetime whose
        TURN_START rider grants movement (its effect is inline, not a second file)."""
        spell = longstrider_spell()
        assert spell.program and not spell.pipeline_effects
        life = spell.program[0]
        assert life["block"] == "lifetime" and life.get("kind") == "rounds"
        assert life["then"][0]["block"] == "trigger"

    def test_longstrider_no_save(self):
        """Longstrider has no saving throw block in the program."""
        spell = longstrider_spell()

        def walk(blocks):
            for b in blocks:
                yield b.get("block")
                yield from walk(b.get("then", []))

        assert "saving_throw" not in set(walk(spell.program))

    def test_longstrider_applies_effect_on_cast(self):
        """Casting Longstrider installs the movement effect on the target.

        The effect is a lifetime + TURN_START rider on the target. Assert the
        observable install: a duration lifetime now sits on the goblin.
        """
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)

        spell = longstrider_spell()
        resolver.resolve(wizard, [goblin], spell)

        assert len(goblin.lifetimes) == 1

    def test_longstrider_grants_movement_on_turn(self):
        """After casting, the affected entity gets +10 movement on TURN_START."""
        wizard = load_wizard()
        goblin = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin)
        engine.load_from_file("rules/global/action_economy_refill.json")

        spell = longstrider_spell()
        resolver.resolve(wizard, [goblin], spell)

        # Emit TURN_START for the goblin
        bus.emit(EventType.TURN_START, TurnEventData(
            entity=goblin, round_num=2, turn_num=1,
        ))

        # Base speed (30) + longstrider (+10) = 40
        assert goblin.resources.movement == 40

    def test_longstrider_on_multiple_targets(self):
        """Longstrider can be applied to multiple targets (for future upcast)."""
        wizard = load_wizard()
        goblin_a = load_goblin()
        goblin_b = load_goblin()
        bus, engine, resolver = setup_engine_and_resolver(wizard, goblin_a, goblin_b)
        engine.load_from_file("rules/global/action_economy_refill.json")

        spell = longstrider_spell()
        resolver.resolve(wizard, [goblin_a, goblin_b], spell)

        # Both goblins should have the effect installed (a duration lifetime each).
        assert len(goblin_a.lifetimes) == 1
        assert len(goblin_b.lifetimes) == 1

        bus.emit(EventType.TURN_START, TurnEventData(
            entity=goblin_a, round_num=2, turn_num=1,
        ))
        assert goblin_a.resources.movement == 40

        bus.emit(EventType.TURN_START, TurnEventData(
            entity=goblin_b, round_num=2, turn_num=2,
        ))
        assert goblin_b.resources.movement == 40
