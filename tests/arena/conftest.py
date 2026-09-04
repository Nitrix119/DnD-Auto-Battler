"""Shared factories for arena tests.

These build small combats out of hand-made entities so tests can place tokens at
known positions and hand them specific attacks/spells, then exercise the arena's
read-only helpers (observation, legal-action assembly) against the real engine.
"""

from pathlib import Path

import pytest

from src.combat import CombatSystem
from src.combat.spell_registry import SpellRegistry
from src.loaders import StatBlockLoader
from src.models import AbilityScores, AttackAction, Damage, DamageType, Entity, StatBlock
from src.models.action import SpellAction
from src.models.spell_properties import RangeType, SpellRange, TargetingType
from src.utils import dice

_SPELLS_DIR = Path(__file__).resolve().parents[2] / "examples" / "spells"


@pytest.fixture(autouse=True)
def _seed_rng():
    """Seed the shared RNG so any dice rolled in a test are reproducible."""
    dice.seed_rng(1234)


def force_turn(combat: CombatSystem, entity: Entity) -> None:
    """Point the initiative tracker at *entity*'s slot (make it their turn)."""
    for i, entry in enumerate(combat.initiative_tracker.initiative_order):
        if entry.entity is entity:
            combat.initiative_tracker.current_turn_index = i
            return
    raise AssertionError(f"{entity.name} is not in the initiative order")


def load_spell(filename: str) -> SpellAction:
    """Load a real spell from ``examples/spells`` (a valid block program)."""
    return StatBlockLoader.load_spell_from_json(str(_SPELLS_DIR / filename))


def melee_attack(name: str = "Longsword") -> AttackAction:
    """A 5-ft melee attack for one action."""
    return AttackAction(
        name=name,
        description="",
        bonus_to_hit=5,
        damage=[Damage(DamageType.SLASHING, formula="1d8")],
        range_ft=5.0,
    )


def single_target_spell(
    name: str = "Firebolt", *, spell_level: int = 0, distance_ft: int = 120
) -> SpellAction:
    """A single-target ranged spell (cantrip by default)."""
    return SpellAction(
        name=name,
        description="",
        spell_level=spell_level,
        spell_range=SpellRange(RangeType.FEET, distance_ft=distance_ft),
        targeting_type=TargetingType.SINGLE_TARGET,
        program=[],
    )


@pytest.fixture
def make_entity():
    """Return a factory: ``make_entity(name, ...) -> Entity`` placed at a position."""

    def _make(
        name,
        *,
        hp=30,
        ac=15,
        team=None,
        pos=(0.0, 0.0, 0.0),
        attacks=None,
        known_spells=None,
        spell_slot_defaults=None,
        spellcasting_ability="",
    ):
        block = StatBlock(
            name=name,
            ability_scores=AbilityScores(15, 14, 13, 12, 11, 10),
            hit_points_max=hp,
            armor_class=ac,
            proficiency_bonus=2,
            known_spells=list(known_spells or []),
            spellcasting_ability=spellcasting_ability,
            spell_slot_defaults=dict(spell_slot_defaults or {}),
        )
        for action in attacks or []:
            block.add_action(action)
        entity = Entity(block, team=team)
        entity.x, entity.y, entity.z = pos
        return entity

    return _make


@pytest.fixture
def make_combat():
    """Return a factory: ``make_combat(entities, registry=None) -> CombatSystem``.

    The combat is left in SETUP — the arena's read-only helpers do not require an
    active turn, and leaving it unstarted keeps positions and resources pristine.
    """

    def _make(entities, registry=None):
        combat = CombatSystem()
        for entity in entities:
            combat.add_combatant(entity)
        if registry is not None:
            combat.spell_registry = registry
        return combat

    return _make


@pytest.fixture
def registry_with():
    """Return a factory: ``registry_with(*spells) -> SpellRegistry``."""

    def _make(*spells):
        registry = SpellRegistry()
        for spell in spells:
            registry.register(spell)
        return registry

    return _make
