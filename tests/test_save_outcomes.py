"""Tests for saving throw outcomes in the spell pipeline.

Covers:
  - JSON loading: save_result in pipeline damage steps
  - half_damage: floor-halves damage when the target saves successfully
  - no_damage: zeroes all damage when the target saves successfully
  - Per-target independence: AoE targets each get their own save outcome
  - Fireball end-to-end integration using the real JSON file

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
from src.models import Entity
from src.models.action import SpellAction
from src.models.spell_properties import (
    CastingTime, CastingTimeType,
    Duration, DurationUnit,
    RangeType, SpellComponents, SpellRange,
    TargetingType,
)
from src.models.stat_block import StatBlock
from src.models.ability import AbilityScores

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
    on_save_success: str = None,  # "half_damage" or "no_damage"
) -> SpellAction:
    """Single-target spell that uses the caster's spell save DC.

    Uses a fixed damage formula equal to the literal amount so results are
    deterministic (roll_formula("20") == 20).
    """
    damage_step = {
        "type": "damage",
        "target": "defender",
        "damage_type": "FIRE",
        "formula": str(damage_amount),
    }
    if on_save_success:
        damage_step["save_result"] = {"on_success": on_save_success}

    return SpellAction(
        name="Test Spell",
        description="",
        spell_range=SpellRange(RangeType.FEET, distance_ft=60),
        targeting_type=TargetingType.SINGLE_TARGET,
        casting_time=CastingTime(CastingTimeType.ACTION),
        duration=Duration(DurationUnit.INSTANTANEOUS),
        components=SpellComponents(verbal=True, somatic=False),
        pipeline_effects=[
            {"type": "saving_throw", "attribute": save_ability, "dc": "use_caster_dc", "target": "defender"},
            damage_step,
        ],
    )


def _plain_resolver(caster, *targets) -> SpellResolver:
    """SpellResolver with no rule engine (damage tests only)."""
    bus = EventBus()
    dp = DamageProcessor(bus)
    return SpellResolver(bus, dp)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestSaveOutcomeLoading:
    """save_result is parsed correctly from spell JSON files."""

    def test_fireball_has_half_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))
        damage_steps = [s for s in spell.pipeline_effects if s.get("type") == "damage"]
        assert len(damage_steps) >= 1
        assert damage_steps[0].get("save_result", {}).get("on_success") == "half_damage"

    def test_burning_hands_has_half_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "burning_hands.json"))
        damage_steps = [s for s in spell.pipeline_effects if s.get("type") == "damage"]
        assert damage_steps[0].get("save_result", {}).get("on_success") == "half_damage"

    def test_thunderwave_has_half_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "thunderwave.json"))
        damage_steps = [s for s in spell.pipeline_effects if s.get("type") == "damage"]
        assert damage_steps[0].get("save_result", {}).get("on_success") == "half_damage"

    def test_acid_splash_has_no_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "acid_splash.json"))
        damage_steps = [s for s in spell.pipeline_effects if s.get("type") == "damage"]
        assert damage_steps[0].get("save_result", {}).get("on_success") == "no_damage"

    def test_sacred_flame_has_no_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "sacred_flame.json"))
        damage_steps = [s for s in spell.pipeline_effects if s.get("type") == "damage"]
        assert damage_steps[0].get("save_result", {}).get("on_success") == "no_damage"

    def test_poison_spray_has_no_damage_on_success(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "poison_spray.json"))
        damage_steps = [s for s in spell.pipeline_effects if s.get("type") == "damage"]
        assert damage_steps[0].get("save_result", {}).get("on_success") == "no_damage"

    def test_firebolt_has_no_save_step(self):
        """Attack-roll spells have no saving throw step in the pipeline."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        save_steps = [s for s in spell.pipeline_effects if s.get("type") == "saving_throw"]
        assert len(save_steps) == 0

    def test_magic_missile_has_no_save_step(self):
        """Auto-hit spells with no save have no saving throw step in the pipeline."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "magic_missile.json"))
        save_steps = [s for s in spell.pipeline_effects if s.get("type") == "saving_throw"]
        assert len(save_steps) == 0


# ---------------------------------------------------------------------------
# HalfDamage
# ---------------------------------------------------------------------------

class TestHalfDamage:
    """half_damage save_result floor-halves damage when the target saves."""

    def test_half_damage_on_successful_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_save_success="half_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=15):  # 15 >= 15 → succeed
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 10  # 20 // 2

    def test_full_damage_on_failed_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_save_success="half_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=14):  # 14 < 15 → fail
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 20  # no modification

    def test_half_damage_uses_floor_division_odd(self):
        """Halving an odd number rounds down (7 → 3, not 4)."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=7, on_save_success="half_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp - 3  # 7 // 2

    def test_half_of_one_is_zero(self):
        """1 // 2 = 0 — a saved target takes no damage."""
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=1, on_save_success="half_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp


# ---------------------------------------------------------------------------
# NoDamage
# ---------------------------------------------------------------------------

class TestNoDamage:
    """no_damage save_result zeroes all damage when the target saves."""

    def test_no_damage_on_successful_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_save_success="no_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=15):
            resolver.resolve(caster, [target], spell)

        assert target.hp == target.max_hp

    def test_full_damage_on_failed_save(self):
        caster, target = _make_caster(), _make_target()
        resolver = _plain_resolver(caster, target)
        spell = _make_save_spell(damage_amount=20, on_save_success="no_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=14):
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

        spell = _make_save_spell(damage_amount=20, on_save_success="half_damage")

        # d20 called once per target; 15 → succeed, 14 → fail
        rolls = iter([15, 14])
        with patch("src.utils.saving_throw.roll_d20", side_effect=lambda: next(rolls)):
            resolver.resolve(caster, [saver, failer], spell)

        assert saver.hp == saver.max_hp - 10   # 20 // 2
        assert failer.hp == failer.max_hp - 20  # full damage

    def test_all_targets_save_no_damage_spell(self):
        """When every target saves, no_damage protects them all."""
        caster = _make_caster()
        targets = [_make_target() for _ in range(3)]
        resolver = _plain_resolver(caster, *targets)

        spell = _make_save_spell(damage_amount=20, on_save_success="no_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=20):
            resolver.resolve(caster, targets, spell)

        for t in targets:
            assert t.hp == t.max_hp

    def test_all_targets_fail_full_damage(self):
        """When every target fails, full damage lands on all."""
        caster = _make_caster()
        targets = [_make_target() for _ in range(3)]
        resolver = _plain_resolver(caster, *targets)

        spell = _make_save_spell(damage_amount=20, on_save_success="half_damage")

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(caster, targets, spell)

        for t in targets:
            assert t.hp == t.max_hp - 20


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
        resolver = SpellResolver(bus, dp)

        hit_events = []
        bus.subscribe(EventType.SPELL_HIT, lambda e: hit_events.append(e))

        with patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [target], fireball)

        assert len(hit_events) == 1
        assert hit_events[0].data.get("save_roll") is not None
        assert hit_events[0].data.get("save_success") is False

    def test_fireball_half_damage_on_successful_save(self, wizard, fireball):
        """Target takes floor(rolled / 2) damage when the Dex save succeeds."""
        target = _make_target(hp=500)
        bus = EventBus()
        dp = DamageProcessor(bus)
        resolver = SpellResolver(bus, dp)

        # Patch roll_formula so the 8d6 roll is deterministic (returns 24).
        # Fireball uses roll_once, so the shared pre-roll now happens in the
        # for_each_target iterator (the new block engine); patch it there.
        # AND roll_d20 so the save succeeds (20 >= wizard DC 15)
        with patch("src.spells.blocks.iterators.roll_formula", return_value=24), \
             patch("src.utils.saving_throw.roll_d20", return_value=20):
            resolver.resolve(wizard, [target], fireball)

        damage_taken = target.max_hp - target.hp
        assert damage_taken == 12  # 24 // 2

    def test_fireball_full_damage_on_failed_save(self, wizard, fireball):
        """Target takes the full rolled damage when the Dex save fails."""
        target = _make_target(hp=500)
        bus = EventBus()
        dp = DamageProcessor(bus)
        resolver = SpellResolver(bus, dp)

        with patch("src.spells.blocks.iterators.roll_formula", return_value=24), \
             patch("src.utils.saving_throw.roll_d20", return_value=1):
            resolver.resolve(wizard, [target], fireball)

        damage_taken = target.max_hp - target.hp
        assert damage_taken == 24

    def test_fireball_independent_saves_per_target(self, wizard, fireball):
        """Each target in an AoE resolves its own save and takes damage independently."""
        saver = _make_target(hp=500)
        failer = _make_target(hp=500)
        bus = EventBus()
        dp = DamageProcessor(bus)
        resolver = SpellResolver(bus, dp)

        rolls = iter([20, 1])  # saver succeeds, failer fails
        with patch("src.spells.blocks.iterators.roll_formula", return_value=24), \
             patch("src.utils.saving_throw.roll_d20", side_effect=lambda: next(rolls)):
            resolver.resolve(wizard, [saver, failer], fireball)

        assert saver.max_hp - saver.hp == 12   # 24 // 2
        assert failer.max_hp - failer.hp == 24  # full
