"""Tests for on_successful_save / on_failed_save spell outcome processing.

Covers:
  - JSON loading (on_successful_save / on_failed_save parsed from spell files)
  - HalfDamage: floor-halves damage when the target saves successfully
  - NoDamage: zeroes all damage when the target saves successfully
  - on_failed_save: damage/effects applied only when the save is failed
  - No save rolled: outcome lists are ignored when no saving throw is triggered
  - Per-target independence: AoE targets each get their own save outcome
  - Entity effects via on_failed_save / on_successful_save
  - Fireball end-to-end integration using the real JSON file
  - Backwards compatibility: the existing ``condition`` key on spell_effects still works

Caster setup for deterministic saves
--------------------------------------
_make_caster()  →  INT 18 (+4), proficiency +3, spellcasting_ability="intelligence"
                   spell_save_dc = 8 + 3 + 4 = 15

_make_target()  →  all stats 10 (+0), no save proficiencies
                   save total = d20 + 0
                   roll 14 → 14 < 15 → FAIL
                   roll 15 → 15 >= 15 → SUCCEED
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.combat.attack_resolver import AttackResolver
from src.combat.damage_processor import DamageProcessor
from src.combat.event_bus import EventBus
from src.combat.spell_resolver import SpellResolver
from src.loaders.stat_block_loader import StatBlockLoader
from src.models import Entity, DamageType
from src.models.ability import AbilityScores
from src.models.damage import Damage
from src.models.action import SpellAction
from src.models.spell_properties import (
    CastingTime, CastingTimeType,
    Duration, DurationUnit,
    RangeType, SpellComponents, SpellRange,
    TargetingType,
)
from src.models.stat_block import StatBlock
from src.rules import EffectRegistry, RuleEngine

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
SPELLS_DIR = EXAMPLES_DIR / "spells"
CHARACTERS_DIR = EXAMPLES_DIR / "creatures/characters"

_DC = 15  # wizard's spell_save_dc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_caster() -> Entity:
    """Caster with spell_save_dc = 15 (INT 18 +4, proficiency +3, ability=intelligence)."""
    sb = StatBlock(
        name="Caster",
        ability_scores=AbilityScores(
            strength=10, dexterity=10, constitution=10,
            intelligence=18, wisdom=10, charisma=10,
        ),
        hit_points_max=30,
        armor_class=12,
        proficiency_bonus=3,
        spellcasting_ability="intelligence",
    )
    return Entity(sb)


def _make_target(hp: int = 100) -> Entity:
    """Target with all saves at +0 (stats 10, no proficiencies)."""
    sb = StatBlock(
        name="Target",
        ability_scores=AbilityScores(
            strength=10, dexterity=10, constitution=10,
            intelligence=10, wisdom=10, charisma=10,
        ),
        hit_points_max=hp,
        armor_class=10,
    )
    return Entity(sb)


def _make_save_spell(
    *,
    damage_amount: int = 20,
    save_ability: str = "dexterity",
    on_successful_save=None,
    on_failed_save=None,
) -> SpellAction:
    """Single-target auto-hit spell that uses the caster's spell save DC.

    Uses a fixed damage amount (no formula) so results are deterministic.
    """
    return SpellAction(
        name="Test Spell",
        description="",
        save_dc="use_caster_dc",
        save_ability=save_ability,
        damage=[Damage(DamageType.FIRE, damage_amount)],
        spell_range=SpellRange(RangeType.FEET, distance_ft=60),
        targeting_type=TargetingType.SINGLE_TARGET,
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=False),
        on_successful_save=on_successful_save or [],
        on_failed_save=on_failed_save or [],
    )


def _plain_resolver(caster, *targets) -> SpellResolver:
    """SpellResolver with no rule engine (damage tests only)."""
    bus = EventBus()
    dp = DamageProcessor(bus)
    ar = AttackResolver(bus, dp)
    return SpellResolver(bus, dp, ar)


def _engine_resolver(caster, *targets):
    """SpellResolver wired to a RuleEngine (for entity-effect tests)."""
    entity_list = [caster, *targets]
    bus = EventBus()
    dp = DamageProcessor(bus)
    ar = AttackResolver(bus, dp)
    registry = EffectRegistry()
    registry.scan_directory("rules/entity_effects")
    engine = RuleEngine(
        bus,
        entities_getter=lambda: entity_list,
        damage_processor=dp,
        effect_registry=registry,
    )
    resolver = SpellResolver(bus, dp, ar, rule_engine=engine)
    return resolver, engine


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestSaveOutcomeLoading:
    """on_successful_save / on_failed_save are parsed from spell JSON files."""

    def test_fireball_has_half_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))
        assert len(spell.on_successful_save) == 1
        assert spell.on_successful_save[0]["action"] == "HalfDamage"
        assert spell.on_failed_save == []

    def test_burning_hands_has_half_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "burning_hands.json"))
        assert len(spell.on_successful_save) == 1
        assert spell.on_successful_save[0]["action"] == "HalfDamage"

    def test_thunderwave_has_half_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "thunderwave.json"))
        assert len(spell.on_successful_save) == 1
        assert spell.on_successful_save[0]["action"] == "HalfDamage"

    def test_acid_splash_has_no_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "acid_splash.json"))
        assert len(spell.on_successful_save) == 1
        assert spell.on_successful_save[0]["action"] == "NoDamage"

    def test_sacred_flame_has_no_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "sacred_flame.json"))
        assert len(spell.on_successful_save) == 1
        assert spell.on_successful_save[0]["action"] == "NoDamage"

    def test_poison_spray_has_no_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "poison_spray.json"))
        assert len(spell.on_successful_save) == 1
        assert spell.on_successful_save[0]["action"] == "NoDamage"

    def test_firebolt_has_no_save_outcomes(self):
        """Attack-roll spells have no save outcome entries."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        assert spell.on_successful_save == []
        assert spell.on_failed_save == []

    def test_magic_missile_has_no_save_outcomes(self):
        """Auto-hit spells with no save have no save outcome entries."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "magic_missile.json"))
        assert spell.on_successful_save == []
        assert spell.on_failed_save == []


# ---------------------------------------------------------------------------
# HalfDamage
# ---------------------------------------------------------------------------

class TestHalfDamage:
    """HalfDamage in on_successful_save floor-halves all damage amounts."""

    def test_half_damage_on_successful_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_successful_save=[{"action": "HalfDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):  # 15 >= 15 → succeed
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 10  # 20 // 2

    def test_full_damage_on_failed_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_successful_save=[{"action": "HalfDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # 14 < 15 → fail
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 20  # no modification

    def test_half_damage_uses_floor_division_odd(self):
        """Halving an odd number rounds down (7 → 3, not 4)."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=7, on_successful_save=[{"action": "HalfDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 3  # 7 // 2

    def test_half_of_one_is_zero(self):
        """1 // 2 = 0 — a saved target takes no damage."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=1, on_successful_save=[{"action": "HalfDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp


# ---------------------------------------------------------------------------
# NoDamage
# ---------------------------------------------------------------------------

class TestNoDamage:
    """NoDamage in on_successful_save zeroes all damage when the target saves."""

    def test_no_damage_on_successful_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_successful_save=[{"action": "NoDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp

    def test_full_damage_on_failed_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_successful_save=[{"action": "NoDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 20

    def test_no_damage_applies_to_all_damage_entries(self):
        """NoDamage zeroes every damage entry, not just the first."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_successful_save=[{"action": "NoDamage"}])
        spell.damage.append(Damage(DamageType.COLD, 10))  # second damage type

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp  # both entries zeroed


# ---------------------------------------------------------------------------
# on_failed_save
# ---------------------------------------------------------------------------

class TestOnFailedSave:
    """Entries in on_failed_save apply only when the saving throw is failed."""

    def test_no_damage_on_failed_save(self):
        """NoDamage in on_failed_save zeroes damage when the target fails."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_failed_save=[{"action": "NoDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp

    def test_full_damage_when_save_succeeds_with_on_failed_save(self):
        """on_failed_save entries are skipped entirely when the save is passed."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_failed_save=[{"action": "NoDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):  # succeed
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 20

    def test_half_damage_on_failed_save(self):
        """HalfDamage can live in on_failed_save (unusual but valid)."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_failed_save=[{"action": "HalfDamage"}])

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 10  # halved on fail


# ---------------------------------------------------------------------------
# No save rolled → outcomes not applied
# ---------------------------------------------------------------------------

class TestOutcomesRequireSaveRoll:
    """Save outcome lists have no effect when no saving throw is triggered."""

    def test_outcomes_ignored_when_no_save_ability(self):
        """A spell with on_successful_save but no save_ability auto-hits at full damage."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)

        # save_ability="" → resolver won't roll a save → save_roll stays None
        spell = SpellAction(
            name="No-Save Spell",
            description="",
            save_dc=15,
            save_ability="",
            damage=[Damage(DamageType.FIRE, 20)],
            spell_range=SpellRange(RangeType.FEET, distance_ft=60),
            targeting_type=TargetingType.SINGLE_TARGET,
            casting_time=CastingTime(CastingTimeType.ACTION),
            duration=Duration(DurationUnit.INSTANTANEOUS),
            components=SpellComponents(verbal=True, somatic=False),
            on_successful_save=[{"action": "NoDamage"}],
        )

        resolver.resolve(caster, [target], spell)

        # NoDamage must NOT apply since no save was rolled
        assert target.hp == target.max_hp - 20

    def test_outcomes_ignored_for_zero_dc_spell(self):
        """A spell with save_dc=0 never rolls a save; outcomes are ignored."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)

        spell = SpellAction(
            name="Auto-Hit Spell",
            description="",
            save_dc=0,
            save_ability="dexterity",
            damage=[Damage(DamageType.FIRE, 20)],
            spell_range=SpellRange(RangeType.FEET, distance_ft=60),
            targeting_type=TargetingType.SINGLE_TARGET,
            casting_time=CastingTime(CastingTimeType.ACTION),
            duration=Duration(DurationUnit.INSTANTANEOUS),
            components=SpellComponents(verbal=True, somatic=False),
            on_successful_save=[{"action": "NoDamage"}],
        )

        resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 20


# ---------------------------------------------------------------------------
# Per-target independence (AoE)
# ---------------------------------------------------------------------------

class TestPerTargetIndependence:
    """In AoE resolution, each target rolls its own save and gets its own outcome."""

    def test_one_saves_one_fails_half_damage(self):
        """First target saves (half damage); second fails (full damage)."""
        caster = _make_caster()
        saver = _make_target()
        failer = _make_target()
        resolver = _plain_resolver(caster, saver, failer)

        spell = _make_save_spell(
            damage_amount=20,
            on_successful_save=[{"action": "HalfDamage"}],
        )

        # d20 called once per target; 15 → succeed, 14 → fail
        rolls = iter([15, 14])
        with patch("src.combat.spell_resolver.roll_d20", side_effect=lambda: next(rolls)):
            resolver.resolve(caster, [saver, failer], spell)

        assert saver.hp == saver.max_hp - 10   # 20 // 2
        assert failer.hp == failer.max_hp - 20  # full damage

    def test_all_targets_save_no_damage_spell(self):
        """When every target saves, NoDamage protects them all."""
        caster = _make_caster()
        targets = [_make_target() for _ in range(3)]
        resolver = _plain_resolver(caster, *targets)

        spell = _make_save_spell(
            damage_amount=20,
            on_successful_save=[{"action": "NoDamage"}],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=20):
            resolver.resolve(caster, targets, spell)

        for t in targets:
            assert t.hp == t.max_hp

    def test_all_targets_fail_full_damage(self):
        """When every target fails, full damage lands on all."""
        caster = _make_caster()
        targets = [_make_target() for _ in range(3)]
        resolver = _plain_resolver(caster, *targets)

        spell = _make_save_spell(
            damage_amount=20,
            on_successful_save=[{"action": "HalfDamage"}],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(caster, targets, spell)

        for t in targets:
            assert t.hp == t.max_hp - 20


# ---------------------------------------------------------------------------
# Entity effects via save outcomes
# ---------------------------------------------------------------------------

class TestSaveOutcomeEffects:
    """Entity effects declared in on_failed_save / on_successful_save are applied."""

    def test_effect_applied_on_failed_save(self):
        """charmed effect in on_failed_save is applied when the save is failed."""
        caster, target = _make_caster(), _make_target()
        resolver, _ = _engine_resolver(caster, target)

        spell = _make_save_spell(
            damage_amount=0,
            on_failed_save=[{
                "effect": "charmed",
                "instance_fields": {"charmer": "event.caster"},
            }],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target], spell)

        assert "attack_declared" in target.active_effects
        instance = target.active_effects["attack_declared"][0]
        assert instance.name == "charmed"
        assert instance.instance_fields.get("charmer") is caster

    def test_effect_not_applied_when_save_succeeds(self):
        """Effect in on_failed_save is skipped when the save is passed."""
        caster, target = _make_caster(), _make_target()
        resolver, _ = _engine_resolver(caster, target)

        spell = _make_save_spell(
            damage_amount=0,
            on_failed_save=[{
                "effect": "charmed",
                "instance_fields": {"charmer": "event.caster"},
            }],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):  # succeed
            resolver.resolve(caster, [target], spell)

        assert target.active_effects.get("attack_declared", []) == []

    def test_effect_applied_on_successful_save(self):
        """An effect in on_successful_save fires when the target saves."""
        caster, target = _make_caster(), _make_target()
        resolver, _ = _engine_resolver(caster, target)

        spell = _make_save_spell(
            damage_amount=0,
            on_successful_save=[{
                "effect": "charmed",
                "instance_fields": {"charmer": "event.caster"},
            }],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=15):  # succeed
            resolver.resolve(caster, [target], spell)

        assert "attack_declared" in target.active_effects

    def test_effect_not_applied_on_failed_save_when_in_success_list(self):
        """Effect in on_successful_save is skipped when the target fails the save."""
        caster, target = _make_caster(), _make_target()
        resolver, _ = _engine_resolver(caster, target)

        spell = _make_save_spell(
            damage_amount=0,
            on_successful_save=[{
                "effect": "charmed",
                "instance_fields": {"charmer": "event.caster"},
            }],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target], spell)

        assert target.active_effects.get("attack_declared", []) == []

    def test_damage_mod_and_effect_in_same_list(self):
        """Both HalfDamage and an entity effect can live in the same outcome list."""
        caster, target = _make_caster(), _make_target()
        resolver, _ = _engine_resolver(caster, target)

        spell = _make_save_spell(
            damage_amount=20,
            on_failed_save=[
                {"action": "HalfDamage"},
                {"effect": "charmed", "instance_fields": {"charmer": "event.caster"}},
            ],
        )

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 10  # halved
        assert "attack_declared" in target.active_effects  # charmed applied


# ---------------------------------------------------------------------------
# Condition key backwards compatibility
# ---------------------------------------------------------------------------

class TestConditionKeyBackwardsCompat:
    """The existing ``condition`` key on spell_effects entries still gates effects.

    The new on_successful_save / on_failed_save keys are an alternative — both
    approaches should coexist without interference.
    """

    def test_condition_not_save_success_still_works(self):
        """spell_effects with condition='not save_success' applies on failed save."""
        caster, target = _make_caster(), _make_target()
        resolver, engine = _engine_resolver(caster, target)

        # Spell using the old condition-based approach
        spell = _make_save_spell(damage_amount=0)
        spell.spell_effects = [{
            "effect": "charmed",
            "condition": "not save_success",
            "instance_fields": {"charmer": "event.caster"},
        }]

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target], spell)

        assert "attack_declared" in target.active_effects

    def test_condition_save_success_still_works(self):
        """condition='save_success' gates an effect to successful saves."""
        caster, target = _make_caster(), _make_target()
        resolver, engine = _engine_resolver(caster, target)

        spell = _make_save_spell(damage_amount=0)
        spell.spell_effects = [{
            "effect": "charmed",
            "condition": "save_success",
            "instance_fields": {"charmer": "event.caster"},
        }]

        # fail — effect should NOT apply
        with patch("src.combat.spell_resolver.roll_d20", return_value=14):
            resolver.resolve(caster, [target], spell)

        assert target.active_effects.get("attack_declared", []) == []

        # succeed — effect SHOULD apply
        with patch("src.combat.spell_resolver.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert "attack_declared" in target.active_effects

    def test_condition_and_save_outcomes_coexist(self):
        """Both condition-based effects and on_failed_save entries apply independently."""
        caster = _make_caster()
        target_a = _make_target()  # will receive condition-based effect
        target_b = _make_target()  # same spell, same targets — just one entity
        resolver, engine = _engine_resolver(caster, target_a)

        # Spell with BOTH approaches: condition-based charmed + on_failed_save HalfDamage
        spell = _make_save_spell(
            damage_amount=20,
            on_failed_save=[{"action": "HalfDamage"}],
        )
        spell.spell_effects = [{
            "effect": "charmed",
            "condition": "not save_success",
            "instance_fields": {"charmer": "event.caster"},
        }]

        with patch("src.combat.spell_resolver.roll_d20", return_value=14):  # fail
            resolver.resolve(caster, [target_a], spell)

        # Damage is halved by on_failed_save
        assert target_a.hp == target_a.max_hp - 10
        # Effect is applied by condition
        assert "attack_declared" in target_a.active_effects


# ---------------------------------------------------------------------------
# Fireball integration (real JSON)
# ---------------------------------------------------------------------------

class TestFireballIntegration:
    """End-to-end tests using the real fireball.json spell file."""

    @pytest.fixture
    def wizard(self) -> Entity:
        sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "wizard.json"))
        return Entity(sb)

    @pytest.fixture
    def fireball(self):
        return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))

    def test_fireball_rolls_dex_save(self, wizard, fireball):
        """Fireball triggers a Dexterity saving throw for each target."""
        from src.combat.events import EventType

        target = _make_target(hp=200)
        bus = EventBus()
        dp = DamageProcessor(bus)
        ar = AttackResolver(bus, dp)
        resolver = SpellResolver(bus, dp, ar)

        hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: hit_events.append(e))

        with patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [target], fireball)

        assert len(hit_events) == 1
        assert hit_events[0].data.get("save_roll") is not None
        assert hit_events[0].data.get("save_success") is False

    def test_fireball_half_damage_on_successful_save(self, wizard, fireball):
        """Target takes floor(rolled / 2) damage when the Dex save succeeds."""
        target = _make_target(hp=500)
        bus = EventBus()
        dp = DamageProcessor(bus)
        ar = AttackResolver(bus, dp)
        resolver = SpellResolver(bus, dp, ar)

        # Patch roll_formula so the 8d6 roll is deterministic (returns 24)
        # AND roll_d20 so the save succeeds (20 >= wizard DC 15)
        with patch("src.models.action.roll_formula", return_value=24), \
             patch("src.combat.spell_resolver.roll_d20", return_value=20):
            resolver.resolve(wizard, [target], fireball)

        damage_taken = target.max_hp - target.hp
        assert damage_taken == 12  # 24 // 2

    def test_fireball_full_damage_on_failed_save(self, wizard, fireball):
        """Target takes the full rolled damage when the Dex save fails."""
        target = _make_target(hp=500)
        bus = EventBus()
        dp = DamageProcessor(bus)
        ar = AttackResolver(bus, dp)
        resolver = SpellResolver(bus, dp, ar)

        with patch("src.models.action.roll_formula", return_value=24), \
             patch("src.combat.spell_resolver.roll_d20", return_value=1):
            resolver.resolve(wizard, [target], fireball)

        damage_taken = target.max_hp - target.hp
        assert damage_taken == 24

    def test_fireball_independent_saves_per_target(self, wizard, fireball):
        """Each target in an AoE resolves its own save and takes damage independently."""
        saver = _make_target(hp=500)
        failer = _make_target(hp=500)
        bus = EventBus()
        dp = DamageProcessor(bus)
        ar = AttackResolver(bus, dp)
        resolver = SpellResolver(bus, dp, ar)

        rolls = iter([20, 1])  # saver succeeds, failer fails
        with patch("src.models.action.roll_formula", return_value=24), \
             patch("src.combat.spell_resolver.roll_d20", side_effect=lambda: next(rolls)):
            resolver.resolve(wizard, [saver, failer], fireball)

        assert saver.max_hp - saver.hp == 12   # 24 // 2
        assert failer.max_hp - failer.hp == 24  # full
