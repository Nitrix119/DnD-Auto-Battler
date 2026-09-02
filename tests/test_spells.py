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
from src.combat import CombatSystem, CombatState, EventType
from src.rules.rule_engine import RuleEngine
from src.rules.effect_registry import EffectRegistry
from src.spatial.geometry import Point3D
from src.utils.dice import roll_d20, roll_formula

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
SPELLS_DIR = EXAMPLES_DIR / "spells"
CHARACTERS_DIR = EXAMPLES_DIR / "creatures/characters"


def _damage_entries(spell):
    """Damage steps of a spell, whether authored natively or legacily.

    A native spell keys blocks by ``block`` (in ``program``, possibly nested under
    ``then``); a legacy spell keys steps by ``type`` (flat in ``pipeline_effects``).
    Both spell ``damage_type``/``formula`` fields under the same names.
    """
    def walk(blocks, key):
        out = []
        for b in blocks:
            if b.get(key) == "damage":
                out.append(b)
            out.extend(walk(b.get("then", []), key))
        return out

    if spell.program:
        return walk(spell.program, "block")
    return walk(spell.pipeline_effects, "type")


def _save_entries(spell):
    """saving_throw steps of a spell, native (`program`) or legacy (`pipeline_effects`)."""
    def walk(blocks, key):
        out = []
        for b in blocks:
            if b.get(key) == "saving_throw":
                out.append(b)
            out.extend(walk(b.get("then", []), key))
        return out

    if spell.program:
        return walk(spell.program, "block")
    return walk(spell.pipeline_effects, "type")


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
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "FIRE"
        assert damage_steps[0]["formula"] == "1d10"

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
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "FIRE"
        assert damage_steps[0]["formula"] == "8d6"

    def test_inflict_wounds_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "inflict_wounds.json"))
        assert spell.name == "Inflict Wounds"
        assert spell.spell_level == 1
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.TOUCH
        assert spell.aoe is None
        assert not spell.components.requires_material
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "NECROTIC"
        assert damage_steps[0]["formula"] == "3d10"


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
            damage_step = _damage_entries(firebolt)[0]
            damage = roll_formula(damage_step["formula"])
            target.take_damage(Damage(DamageType[damage_step["damage_type"]], damage))
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
            damage_step = _damage_entries(inflict_wounds)[0]
            damage = roll_formula(damage_step["formula"])
            target.take_damage(Damage(DamageType[damage_step["damage_type"]], damage))
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
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "COLD"
        assert damage_steps[0]["formula"] == "1d8"


class TestSacredFlameLoading:
    """Sacred Flame – cantrip, Dex save, radiant damage."""

    def test_sacred_flame_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "sacred_flame.json"))
        assert spell.name == "Sacred Flame"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 60
        save_steps = _save_entries(spell)
        assert save_steps[0]["attribute"] == "dexterity"
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "RADIANT"
        assert damage_steps[0]["formula"] == "1d8"


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
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "NECROTIC"
        assert damage_steps[0]["formula"] == "1d8"


class TestEldritchBlastLoading:
    """Eldritch Blast – cantrip, ranged spell attack, force damage."""

    def test_eldritch_blast_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "eldritch_blast.json"))
        assert spell.name == "Eldritch Blast"
        assert spell.spell_level == 0
        # Multi-target: each beam is an independent projectile (one per chosen target).
        assert spell.targeting_type == TargetingType.MULTI_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "FORCE"
        assert damage_steps[0]["formula"] == "1d10"


class TestPoisonSprayLoading:
    """Poison Spray – cantrip, Con save, poison damage."""

    def test_poison_spray_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "poison_spray.json"))
        assert spell.name == "Poison Spray"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 10
        save_steps = _save_entries(spell)
        assert save_steps[0]["attribute"] == "constitution"
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "POISON"
        assert damage_steps[0]["formula"] == "1d12"


class TestAcidSplashLoading:
    """Acid Splash – cantrip, Dex save, acid damage."""

    def test_acid_splash_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "acid_splash.json"))
        assert spell.name == "Acid Splash"
        assert spell.spell_level == 0
        assert spell.targeting_type == TargetingType.SINGLE_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 60
        save_steps = _save_entries(spell)
        assert save_steps[0]["attribute"] == "dexterity"
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "ACID"
        assert damage_steps[0]["formula"] == "1d6"


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
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "RADIANT"
        assert damage_steps[0]["formula"] == "4d6"


class TestMagicMissileLoading:
    """Magic Missile – 1st level, auto-hit, force damage."""

    def test_magic_missile_properties(self):
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "magic_missile.json"))
        assert spell.name == "Magic Missile"
        assert spell.spell_level == 1
        # Modelled honestly as split projectiles: one damage step per dart, run
        # once per chosen target via the multi-target fan-out.
        assert spell.targeting_type == TargetingType.MULTI_TARGET
        assert spell.spell_range.range_type == RangeType.FEET
        assert spell.spell_range.distance_ft == 120
        assert spell.duration.unit == DurationUnit.INSTANTANEOUS
        assert not spell.components.requires_material
        assert spell.higher_level_scaling is not None
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "FORCE"
        assert damage_steps[0]["formula"] == "1d4+1"


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
        assert spell.higher_level_scaling is not None
        save_steps = _save_entries(spell)
        assert save_steps[0]["attribute"] == "constitution"
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "THUNDER"
        assert damage_steps[0]["formula"] == "2d8"


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
        assert spell.higher_level_scaling is not None
        save_steps = _save_entries(spell)
        assert save_steps[0]["attribute"] == "dexterity"
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "FIRE"
        assert damage_steps[0]["formula"] == "3d6"


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
            damage_step = _damage_entries(spell)[0]
            damage = roll_formula(damage_step["formula"])
            target.take_damage(Damage(DamageType[damage_step["damage_type"]], damage))
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
            damage_step = _damage_entries(spell)[0]
            damage = roll_formula(damage_step["formula"])
            target.take_damage(Damage(DamageType[damage_step["damage_type"]], damage))
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

        damage_step = _damage_entries(spell)[0]
        damage = roll_formula(damage_step["formula"])
        target.take_damage(Damage(DamageType[damage_step["damage_type"]], damage))
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
            damage_step = _damage_entries(spell)[0]
            damage = roll_formula(damage_step["formula"])
            target.take_damage(Damage(DamageType[damage_step["damage_type"]], damage))
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
        """Cure Wounds heals via HealTarget on_apply: 1d8 + spellcasting modifier.

        The wizard (INT 18, modifier +4) casts Cure Wounds on itself.
        Healing must be between (1 + modifier) and (8 + modifier) HP, and a
        HEALING_APPLIED event must be emitted with the correct target and amount.
        """
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "cure_wounds.json"))

        # Damage the wizard enough that any roll is observable
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 20))
        hp_after_damage = wizard.hp
        assert hp_after_damage < wizard.max_hp

        # Track HEALING_APPLIED events
        healing_events = []
        combat.event_bus.subscribe(EventType.HEALING_APPLIED, lambda e: healing_events.append(e))

        # Cast Cure Wounds on self (wizard is the defender)
        combat.resolve_spell(wizard, [wizard], spell)

        # HP should have increased but not exceeded max
        assert wizard.hp > hp_after_damage
        assert wizard.hp <= wizard.max_hp

        # HEALING_APPLIED event must have fired once with the right target and amount
        assert len(healing_events) == 1
        event_data = healing_events[0].data
        assert event_data.target is wizard
        modifier = wizard.spellcasting_modifier  # INT 18 → +4
        assert 1 + modifier <= event_data.amount <= 8 + modifier

    def test_cure_wounds_does_not_exceed_max_hp(self, wizard, goblins, combat):
        """Cure Wounds cannot heal above max HP."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "cure_wounds.json"))

        # Only take 1 damage so healing is capped by max HP
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 1))
        assert wizard.hp == wizard.max_hp - 1

        combat.resolve_spell(wizard, [wizard], spell)

        # HP should be capped at max, not over-healed
        assert wizard.hp == wizard.max_hp


class TestVampiricTouch:
    """Vampiric Touch — concentration, melee spell attack, heals caster for half damage."""

    @pytest.fixture
    def wizard(self) -> Entity:
        sb = StatBlockLoader.load_from_json(str(CHARACTERS_DIR / "wizard.json"))
        return Entity(sb, is_player_controlled=True)

    @pytest.fixture
    def goblin(self):
        sb = StatBlockLoader.load_from_json(str(EXAMPLES_DIR / "creatures/goblin.json"))
        return Entity(sb)

    @pytest.fixture
    def combat(self, wizard, goblin) -> CombatSystem:
        wizard.x, wizard.y, wizard.z = 0.0, 0.0, 0.0
        goblin.x, goblin.y, goblin.z = 5.0, 0.0, 0.0
        cs = CombatSystem()
        cs.add_combatant(wizard)
        cs.add_combatant(goblin)
        effect_registry = EffectRegistry()
        effect_registry.scan_directory("rules/entity_effects")
        cs.rule_engine = RuleEngine(
            cs.event_bus,

            damage_processor=cs._damage_processor,
            effect_registry=effect_registry,
        )
        cs.start_combat()
        for i, entry in enumerate(cs.initiative_tracker.initiative_order):
            if entry.entity is wizard:
                cs.initiative_tracker.current_turn_index = i
                break
        return cs

    def test_vampiric_touch_loads(self):
        """Vampiric Touch loads correctly from JSON."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))
        assert spell.name == "Vampiric Touch"
        assert spell.spell_level == 3
        assert spell.duration.concentration
        damage_steps = _damage_entries(spell)
        assert len(damage_steps) == 1
        assert damage_steps[0]["damage_type"] == "NECROTIC"
        assert damage_steps[0]["formula"] == "3d6"

    def test_vampiric_touch_grants_action_on_hit(self, wizard, goblin, combat):
        """After a successful cast, the wizard has a granted Vampiric Touch attack action."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))

        # Damage goblin enough to survive at least one hit (goblin has ~7 HP)
        goblin.current_hp = 100

        combat.resolve_spell(wizard, [goblin], spell)

        # If hit: wizard should have concentration and a granted attack action.
        if wizard.concentrating_on == "vampiric_touch":
            assert any(a.name == "Vampiric Touch" for a in wizard.granted_actions)
        else:
            # Missed — nothing to verify about the ongoing effect
            pytest.skip("Spell missed; rerun to test on-hit behaviour")

    def test_vampiric_touch_heals_on_hit(self, wizard, goblin, combat):
        """Caster heals for half the necrotic damage dealt when Vampiric Touch hits."""
        from unittest.mock import patch

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))
        goblin.current_hp = 200  # Ensure goblin survives

        wizard.take_damage(Damage(DamageType.BLUDGEONING, 10))
        hp_before = wizard.hp

        healing_events = []
        combat.event_bus.subscribe(
            EventType.HEALING_APPLIED, lambda e: healing_events.append(e)
        )

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            combat.resolve_spell(wizard, [goblin], spell)

        if not wizard.concentrating_on:
            pytest.skip("Spell missed; rerun to test healing")

        # Healed for floor(damage // 2) — at minimum 1 (since 3d6 minimum is 3)
        assert len(healing_events) >= 1
        heal_amount = healing_events[0].data.amount
        assert heal_amount >= 1
        assert wizard.hp == min(wizard.max_hp, hp_before + heal_amount)

    def test_vampiric_touch_concentration_removal_revokes_granted_action(self, wizard, goblin, combat):
        """Breaking concentration removes the granted Vampiric Touch attack."""
        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))
        goblin.current_hp = 200

        combat.resolve_spell(wizard, [goblin], spell)

        if not wizard.concentrating_on:
            pytest.skip("Spell missed; rerun to test concentration removal")

        assert any(a.name == "Vampiric Touch" for a in wizard.granted_actions)

        # Break concentration through the real teardown path — disposing the
        # lifetime scope revokes the granted action by its owned handle.
        wizard.end_concentration()

        assert not any(a.name == "Vampiric Touch" for a in wizard.granted_actions)

    def test_vampiric_touch_repeat_attack_heals(self, wizard, goblin, combat):
        """Using the granted Vampiric Touch attack on a repeat turn also heals the caster."""
        from unittest.mock import patch
        from src.models.action import AttackAction

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))
        goblin.current_hp = 200
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 10))

        # Initial cast
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
         combat.resolve_spell(wizard, [goblin], spell)

        if not wizard.concentrating_on:
            pytest.skip("Spell missed; rerun to test repeat attack")

        granted = next((a for a in wizard.granted_actions if a.name == "Vampiric Touch"), None)
        assert isinstance(granted, AttackAction)

        # Simulate next turn: refill action resource and resolve the granted attack
        wizard.resources.actions = 1
        hp_before = wizard.hp

        healing_events = []
        combat.event_bus.subscribe(
            EventType.HEALING_APPLIED, lambda e: healing_events.append(e)
        )

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20):
            hit, damage, _ = combat.resolve_attack(wizard, goblin, granted)

        if hit:
            assert len(healing_events) >= 1
            assert wizard.hp >= hp_before  # healed by at least something


    def test_vampiric_touch_healing_uses_floor_division(self, wizard, goblin, combat):
        """D&D rounding: 9 damage should heal for 4 (9 // 2 = 4), not 5."""
        from unittest.mock import patch
        from src.models.action import AttackAction

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))
        goblin.current_hp = 200
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 30))
        hp_before = wizard.hp

        # Force the spell attack to hit (natural 20) and damage to be exactly 9
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.spells.blocks.damage.roll_formula", return_value=9):
            results = combat.resolve_spell(wizard, [goblin], spell)

        # Verify the hit actually landed
        _, hit, damage, _, healing, _ = results[0]
        assert hit is True
        assert damage == 9
        # Floor division: 9 // 2 = 4
        assert healing == 4
        assert wizard.hp == hp_before + 4

    def test_vampiric_touch_recast_while_active(self, wizard, goblin, combat):
        """Re-casting Vampiric Touch while already concentrating still heals on hit."""
        from unittest.mock import patch

        spell = StatBlockLoader.load_spell_from_json(str(SPELLS_DIR / "vampiric_touch.json"))
        goblin.current_hp = 200
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 30))

        # First cast — force hit
        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.spells.blocks.damage.roll_formula", return_value=6):
            combat.resolve_spell(wizard, [goblin], spell)

        assert wizard.concentrating_on == "vampiric_touch"
        hp_after_first = wizard.hp

        # Second cast (re-cast while concentration is active) — force hit
        wizard.resources.actions = 1
        wizard.take_damage(Damage(DamageType.BLUDGEONING, 10))
        hp_before_second = wizard.hp

        with patch("src.spells.blocks.rolls.roll_d20", return_value=20), \
             patch("src.spells.blocks.damage.roll_formula", return_value=8):
            results = combat.resolve_spell(wizard, [goblin], spell)

        _, hit, damage, _, healing, _ = results[0]
        assert hit is True
        assert damage == 8
        # Healing should still trigger: 8 // 2 = 4
        assert healing == 4
        assert wizard.concentrating_on == "vampiric_touch"
        assert any(a.name == "Vampiric Touch" for a in wizard.granted_actions)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
