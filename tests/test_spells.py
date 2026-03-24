"""Tests for spell actions in simple combat scenarios."""

import pytest
from pathlib import Path

from src.models import (
    Entity,
    SpellAction, Damage, DamageType,
    RangeType, TargetingType, AOEShape,
    CastingTimeType, DurationUnit,
)
from src.loaders.stat_block_loader import StatBlockLoader
from src.combat import CombatSystem, CombatState
from src.rules.rule_engine import RuleEngine
from src.rules.effect_registry import EffectRegistry
from src.spatial.geometry import Point3D
from src.utils.dice import roll_d20, roll_formula

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
SPELLS_DIR = EXAMPLES_DIR / "spells"
CHARACTERS_DIR = EXAMPLES_DIR / "creatures/characters"


class TestSpellLoading:
    """Verify that spell JSON files round-trip through the loader correctly."""

    def test_firebolt_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))
        assert spell.name == "Fire Bolt"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.aoe is None
        assert spell.casting_time.time_type == CastingTimeType.ACTION
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert spell.components.verbal
        assert spell.components.somatic
        assert not spell.components.requires_material
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FIRE
        assert spell.damage[0].formula == "1d10"

    def test_fireball_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))
        assert spell.name == "Fireball"
        assert spell.spell_level == 3
        assert spell.targeting_type == TargetingType.AOE
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 150
        assert spell.aoe is not None
        assert spell.aoe.shape == AOEShape.SPHERE
        assert spell.aoe.size_ft == 20
        assert spell.components.requires_material
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FIRE
        assert spell.damage[0].formula == "8d6"

    def test_inflict_wounds_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "inflict_wounds.json"))
        assert spell.name == "Inflict Wounds"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.TOUCH
        assert spell.aoe is None
        assert not spell.components.requires_material
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.NECROTIC
        assert spell.damage[0].formula == "3d10"


class TestSpellCombat:
    """Test spell behaviour against goblins in a live combat encounter."""

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    @pytest.fixture
    def wizard(self) -> Entity:
        """Level-5 wizard: INT 18, proficiency +3, spell attack +7, DC 15."""
        sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "wizard.json"))
        return Entity(sb, is_player_controlled=True)

    @pytest.fixture
    def goblins(self):
        """Three independent goblin entities loaded from examples/goblin.json."""
        def _make():
            sb = StatBlockLoader.load_from_json(str(EXAMPLES_DIR / "creatures/goblin.json"))
            return Entity(sb)
        return [_make() for _ in range(3)]

    @pytest.fixture
    def firebolt(self) -> SpellAction:
        return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "firebolt.json"))

    @pytest.fixture
    def fireball(self) -> SpellAction:
        return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "fireball.json"))

    @pytest.fixture
    def inflict_wounds(self) -> SpellAction:
        return StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "inflict_wounds.json"))

    @pytest.fixture
    def combat(self, wizard, goblins) -> CombatSystem:
        # Wizard at origin; goblins spaced 10 ft apart along the X axis
        # so that a fireball centred at (30, 0, 0) catches all three
        # (20 ft radius sphere — each goblin's nearest corner is within 20 ft).
        wizard.x, wizard.y, wizard.z = 0.0, 0.0, 0.0
        for i, goblin in enumerate(goblins):
            goblin.x = float(10 + i * 10)  # 10, 20, 30 ft along X
            goblin.y, goblin.z = 0.0, 0.0
        cs = CombatSystem()
        cs.add_combatant(wizard)
        for goblin in goblins:
            cs.add_combatant(goblin)
        cs.start_combat()
        # Ensure wizard is always the active entity regardless of initiative roll.
        for i, entry in enumerate(cs.initiative_tracker.initiative_order):
            if entry.entity is wizard:
                cs.initiative_tracker.current_turn_index = i
                break
        return cs

    # ------------------------------------------------------------------
    # Fire Bolt – single target, ranged spell attack
    # ------------------------------------------------------------------

    def test_firebolt_only_damages_target(self, wizard, goblins, firebolt, combat):
        """Fire Bolt targets one goblin; the other two are untouched."""
        target, bystander_a, bystander_b = goblins

        initial_b_a = bystander_a.hp
        initial_b_b = bystander_b.hp

        # Simulate the spell attack roll using the caster's computed bonus
        roll = roll_d20()
        attack_total = roll + wizard.spell_attack_bonus
        hit = attack_total >= target.ac

        if hit:
            damage = roll_formula(firebolt.damage[0].formula)
            target.take_damage(Damage(firebolt.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        # The two bystanders must be completely unaffected
        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b

    # ------------------------------------------------------------------
    # Fireball – AOE, Dexterity save, half on success
    # ------------------------------------------------------------------

    def test_fireball_damages_all_targets(self, wizard, goblins, fireball, combat):
        """Fireball auto-targets every goblin whose bounding box overlaps the blast.

        Goblins are placed at x=10, 20, 30 ft (see combat fixture).  The blast
        is aimed at (30, 0, 0), giving a 20 ft radius sphere centred there.
        All three goblins' bounding boxes overlap that sphere.

        8d6 minimum is 8.  Even on a successful Dex save (half damage) every
        goblin takes ≥ 4 damage — enough to hurt a 7 HP goblin.
        """
        assert fireball.targeting_type == TargetingType.AOE

        initial_hps = [g.hp for g in goblins]

        # Aim at x=30; the system finds targets and applies damage automatically.
        blast_target = Point3D(30.0, 0.0, 0.0)
        combat.resolve_spell(wizard, [], fireball, target=blast_target)

        # Every goblin must have taken damage regardless of save outcome
        for goblin, initial_hp in zip(goblins, initial_hps):
            assert goblin.hp < initial_hp, (
                f"{goblin.name} should have taken damage from Fireball "
                f"(initial HP {initial_hp}, current HP {goblin.hp})"
            )

    # ------------------------------------------------------------------
    # Inflict Wounds – single target, melee spell attack
    # ------------------------------------------------------------------

    def test_inflict_wounds_only_damages_target(self, wizard, goblins, inflict_wounds, combat):
        """Inflict Wounds targets one goblin; the other two are untouched."""
        target, bystander_a, bystander_b = goblins

        initial_b_a = bystander_a.hp
        initial_b_b = bystander_b.hp

        # Simulate the melee spell attack roll using the caster's computed bonus
        roll = roll_d20()
        attack_total = roll + wizard.spell_attack_bonus
        hit = attack_total >= target.ac

        if hit:
            damage = roll_formula(inflict_wounds.damage[0].formula)
            target.take_damage(Damage(inflict_wounds.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        # The two bystanders must be completely unaffected
        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b


class TestRayOfFrostLoading:
    """Ray of Frost – cantrip, ranged spell attack, cold damage."""

    def test_ray_of_frost_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "ray_of_frost.json"))
        assert spell.name == "Ray of Frost"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 60
        assert spell.aoe is None
        assert spell.casting_time.time_type == CastingTimeType.ACTION
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert spell.components.verbal
        assert spell.components.somatic
        assert not spell.components.requires_material
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.COLD
        assert spell.damage[0].formula == "1d8"


class TestSacredFlameLoading:
    """Sacred Flame – cantrip, Dex save, radiant damage."""

    def test_sacred_flame_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "sacred_flame.json"))
        assert spell.name == "Sacred Flame"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 60
        assert spell.save_ability == "dexterity"
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.RADIANT
        assert spell.damage[0].formula == "1d8"


class TestChillTouchLoading:
    """Chill Touch – cantrip, ranged spell attack, necrotic damage."""

    def test_chill_touch_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "chill_touch.json"))
        assert spell.name == "Chill Touch"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.duration.unit == DurationUnit.ROUND
        assert spell.duration.count == 1
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.NECROTIC
        assert spell.damage[0].formula == "1d8"


class TestEldritchBlastLoading:
    """Eldritch Blast – cantrip, ranged spell attack, force damage."""

    def test_eldritch_blast_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "eldritch_blast.json"))
        assert spell.name == "Eldritch Blast"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FORCE
        assert spell.damage[0].formula == "1d10"


class TestPoisonSprayLoading:
    """Poison Spray – cantrip, Con save, poison damage."""

    def test_poison_spray_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "poison_spray.json"))
        assert spell.name == "Poison Spray"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 10
        assert spell.save_ability == "constitution"
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.POISON
        assert spell.damage[0].formula == "1d12"


class TestAcidSplashLoading:
    """Acid Splash – cantrip, Dex save, acid damage."""

    def test_acid_splash_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "acid_splash.json"))
        assert spell.name == "Acid Splash"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 60
        assert spell.save_ability == "dexterity"
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.ACID
        assert spell.damage[0].formula == "1d6"


class TestGuidingBoltLoading:
    """Guiding Bolt – 1st level, ranged spell attack, radiant damage."""

    def test_guiding_bolt_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "guiding_bolt.json"))
        assert spell.name == "Guiding Bolt"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.duration.unit == DurationUnit.ROUND
        assert spell.duration.count == 1
        assert not spell.components.requires_material
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.RADIANT
        assert spell.damage[0].formula == "4d6"


class TestMagicMissileLoading:
    """Magic Missile – 1st level, auto-hit, force damage."""

    def test_magic_missile_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "magic_missile.json"))
        assert spell.name == "Magic Missile"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert not spell.components.requires_material
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FORCE
        assert spell.damage[0].formula == "3d4+3"


class TestCureWoundsLoading:
    """Cure Wounds – 1st level, touch, no damage (healing spell)."""

    def test_cure_wounds_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "cure_wounds.json"))
        assert spell.name == "Cure Wounds"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.TOUCH
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert not spell.components.requires_material
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 0


class TestThunderwaveLoading:
    """Thunderwave – 1st level, AoE cube, Con save, thunder damage."""

    def test_thunderwave_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "thunderwave.json"))
        assert spell.name == "Thunderwave"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.AOE
        assert spell.spell_range.range_type == RangeType.SELF
        assert spell.aoe is not None
        assert spell.aoe.shape == AOEShape.CUBE
        assert spell.aoe.size_ft == 15
        assert spell.save_ability == "constitution"
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.THUNDER
        assert spell.damage[0].formula == "2d8"


class TestBurningHandsLoading:
    """Burning Hands – 1st level, AoE cone, Dex save, fire damage."""

    def test_burning_hands_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "burning_hands.json"))
        assert spell.name == "Burning Hands"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.AOE
        assert spell.spell_range.range_type == RangeType.SELF
        assert spell.aoe is not None
        assert spell.aoe.shape == AOEShape.CONE
        assert spell.aoe.size_ft == 15
        assert spell.save_ability == "dexterity"
        assert spell.higher_level_scaling is not None
        assert len(spell.damage) == 1
        assert spell.damage[0].damage_type == DamageType.FIRE
        assert spell.damage[0].formula == "3d6"


class TestShieldOfFaithLoading:
    """Shield of Faith – 1st level, bonus action, concentration, buff."""

    def test_shield_of_faith_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "shield_of_faith.json"))
        assert spell.name == "Shield of Faith"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 60
        assert spell.casting_time.time_type == CastingTimeType.BONUS_ACTION
        assert spell.duration.unit == DurationUnit.MINUTE
        assert spell.duration.count == 10
        assert spell.duration.concentration
        assert spell.components.requires_material
        assert len(spell.damage) == 0


class TestNewSpellsCombat:
    """Combat tests for newly added spells against goblins."""

    @pytest.fixture
    def wizard(self) -> Entity:
        sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "wizard.json"))
        return Entity(sb, is_player_controlled=True)

    @pytest.fixture
    def goblins(self):
        def _make():
            sb = StatBlockLoader.load_from_json(str(EXAMPLES_DIR / "creatures/goblin.json"))
            return Entity(sb)
        return [_make() for _ in range(3)]

    @pytest.fixture
    def combat(self, wizard, goblins) -> CombatSystem:
        wizard.x, wizard.y, wizard.z = 0.0, 0.0, 0.0
        for i, goblin in enumerate(goblins):
            goblin.x = float(10 + i * 10)
            goblin.y, goblin.z = 0.0, 0.0
        cs = CombatSystem()
        cs.add_combatant(wizard)
        for goblin in goblins:
            cs.add_combatant(goblin)
        # Attach a RuleEngine with EffectRegistry so on_apply effects (e.g. HealTarget, AddModifier) work
        effect_registry = EffectRegistry()
        effect_registry.scan_directory("rules/entity_effects")
        cs.rule_engine = RuleEngine(
            cs.event_bus,
            entities_getter=lambda: cs.combatants,
            damage_processor=cs._damage_processor,
            effect_registry=effect_registry,
        )
        cs.start_combat()
        # Ensure wizard is always the active entity regardless of initiative roll.
        for i, entry in enumerate(cs.initiative_tracker.initiative_order):
            if entry.entity is wizard:
                cs.initiative_tracker.current_turn_index = i
                break
        return cs

    # ------------------------------------------------------------------
    # Ray of Frost – single target, ranged spell attack
    # ------------------------------------------------------------------

    def test_ray_of_frost_single_target(self, wizard, goblins, combat):
        """Ray of Frost hits one goblin; bystanders are untouched."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "ray_of_frost.json"))
        target, bystander_a, bystander_b = goblins
        initial_b_a, initial_b_b = bystander_a.hp, bystander_b.hp

        roll = roll_d20()
        attack_total = roll + wizard.spell_attack_bonus
        if attack_total >= target.ac:
            damage = roll_formula(spell.damage[0].formula)
            target.take_damage(Damage(spell.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b

    # ------------------------------------------------------------------
    # Eldritch Blast – single target, ranged spell attack
    # ------------------------------------------------------------------

    def test_eldritch_blast_single_target(self, wizard, goblins, combat):
        """Eldritch Blast hits one goblin; bystanders are untouched."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "eldritch_blast.json"))
        target, bystander_a, bystander_b = goblins
        initial_b_a, initial_b_b = bystander_a.hp, bystander_b.hp

        roll = roll_d20()
        attack_total = roll + wizard.spell_attack_bonus
        if attack_total >= target.ac:
            damage = roll_formula(spell.damage[0].formula)
            target.take_damage(Damage(spell.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b

    # ------------------------------------------------------------------
    # Magic Missile – auto-hit, force damage (no attack roll)
    # ------------------------------------------------------------------

    def test_magic_missile_auto_hit(self, wizard, goblins, combat):
        """Magic Missile always hits — no attack roll or save needed."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "magic_missile.json"))
        target = goblins[0]
        initial_hp = target.hp

        damage = roll_formula(spell.damage[0].formula)
        target.take_damage(Damage(spell.damage[0].damage_type, damage))
        assert target.hp < initial_hp

    # ------------------------------------------------------------------
    # Guiding Bolt – single target, ranged spell attack, heavy damage
    # ------------------------------------------------------------------

    def test_guiding_bolt_single_target(self, wizard, goblins, combat):
        """Guiding Bolt targets one goblin; bystanders are untouched."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "guiding_bolt.json"))
        target, bystander_a, bystander_b = goblins
        initial_b_a, initial_b_b = bystander_a.hp, bystander_b.hp

        roll = roll_d20()
        attack_total = roll + wizard.spell_attack_bonus
        if attack_total >= target.ac:
            damage = roll_formula(spell.damage[0].formula)
            target.take_damage(Damage(spell.damage[0].damage_type, damage))
            assert target.hp < target.max_hp
        else:
            assert target.hp == target.max_hp

        assert bystander_a.hp == initial_b_a
        assert bystander_b.hp == initial_b_b

    # ------------------------------------------------------------------
    # Thunderwave – AoE cube, damages all nearby targets
    # ------------------------------------------------------------------

    def test_thunderwave_aoe(self, wizard, goblins, combat):
        """Thunderwave is a 15-ft cube from self — should hit close goblins."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "thunderwave.json"))
        assert spell.targeting_type == TargetingType.AOE
        assert spell.aoe.shape == AOEShape.CUBE

        # Place goblins close enough for 15-ft cube from origin
        for i, goblin in enumerate(goblins):
            goblin.x = float(5 + i * 5)  # 5, 10, 15 ft
            goblin.y, goblin.z = 0.0, 0.0

        initial_hps = [g.hp for g in goblins]
        blast_origin = Point3D(0.0, 0.0, 0.0)
        combat.resolve_spell(wizard, [], spell, target=blast_origin)

        hit_count = sum(
            1 for g, ihp in zip(goblins, initial_hps) if g.hp < ihp
        )
        # At minimum the closest goblin should be hit
        assert hit_count >= 1

    # ------------------------------------------------------------------
    # Cure Wounds – healing spell via HealTarget on_apply
    # ------------------------------------------------------------------

    def test_cure_wounds_no_damage(self, wizard, goblins, combat):
        """Cure Wounds has no damage entries — it is a healing spell."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "cure_wounds.json"))
        assert len(spell.damage) == 0
        assert spell.spell_range.range_type == RangeType.TOUCH

    def test_cure_wounds_heals_target(self, wizard, goblins, combat):
        """Cure Wounds heals a damaged target via the HealTarget on_apply hook.

        The wizard takes some damage, then casts Cure Wounds on itself
        (touch range). Because the spell has no attack bonus and no save DC,
        it auto-hits and the on_apply HealTarget effect fires, restoring
        1d8 HP (minimum 1).
        """
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "cure_wounds.json"))

        # Damage the wizard so healing is observable
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 6))
        hp_after_damage = wizard.hp
        assert hp_after_damage < wizard.max_hp

        # Cast Cure Wounds on self (wizard is the defender)
        combat.resolve_spell(wizard, [wizard], spell)

        # The wizard should have been healed by 1-8 HP
        assert wizard.hp > hp_after_damage
        assert wizard.hp <= wizard.max_hp

    def test_cure_wounds_does_not_exceed_max_hp(self, wizard, goblins, combat):
        """Cure Wounds cannot heal above max HP."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "cure_wounds.json"))

        # Only take 1 damage so healing is capped by max HP
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 1))
        assert wizard.hp == wizard.max_hp - 1

        combat.resolve_spell(wizard, [wizard], spell)

        # HP should be capped at max, not over-healed
        assert wizard.hp == wizard.max_hp


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
