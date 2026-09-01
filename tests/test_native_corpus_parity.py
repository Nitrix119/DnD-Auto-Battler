"""Corpus parity: each migrated native spell == its pre-migration legacy shape.

The regression net for the bulk `effects` → `program` migration (Phase 3 §5, slice 2).
`tests/legacy_snapshots/<name>.json` freezes each spell's legacy shape (its `effects`,
plus the referenced entity-effect `rule` for persistent spells) captured *before*
migration. For every snapshot whose spell has since been migrated to a native
`program`, this resolves both the native program and the folded legacy shape under
several seeds and asserts the per-defender `InvocationResult` fields are identical.

A snapshot whose spell is not yet native is skipped (parity self-activates on
migration). The `test_all_spells_are_native` sentinel guards against a spell being
left un-migrated (or a snapshot going permanently skipped) once the slice is done.

Note: charm_person's native form uses `apply_condition` directly (a different
mechanism than the legacy `add_entity_effect`→charmed fold); its result-field parity is
trivial (a save, no damage), so its real behaviour is covered by
`tests/test_entity_effect_fold.py`, not here.
"""

import glob
import json
import os

import pytest

from src.models import AbilityScores, StatBlock, Entity
from src.models.spell_properties import TargetingType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.loaders import StatBlockLoader
from src.rules.rule_loader import RuleLoader
from src.spells.block import parse_program
from src.spells.adapter import to_program
from src.spells.evaluator import resolve_program
from src.utils import dice

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")
SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "legacy_snapshots")

_SNAPSHOTS = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, "*.json")))
_SNAPSHOT_NAMES = [os.path.splitext(os.path.basename(p))[0] for p in _SNAPSHOTS]


def _caster() -> Entity:
    sb = StatBlock(
        name="Wizard",
        ability_scores=AbilityScores(10, 10, 10, 16, 10, 10),  # INT +3
        hit_points_max=40, armor_class=12,
        proficiency_bonus=2, spellcasting_ability="intelligence",
    )
    e = Entity(sb)
    e.refill_resources()
    return e


def _target(hp: int = 80, ac: int = 12) -> Entity:
    sb = StatBlock(name="Target", ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
                   hit_points_max=hp, armor_class=ac)
    e = Entity(sb)
    e.refill_resources()
    return e


def _fields(result):
    return (result.hit, result.damage_dealt, result.healing_total,
            result.save_success, result.attack_roll)


def _rule_lookup(snapshot):
    """A ``name -> Rule`` lookup for folding the legacy shape, or None."""
    rule = snapshot.get("rule")
    if rule is None:
        return None
    parsed = RuleLoader.from_dict(rule)
    name = snapshot.get("rule_name", "")
    return lambda n: parsed if n == name else None


def _resolve(program, spell, n_targets, seed):
    dice.seed_rng(seed)
    caster = _caster()
    targets = [_target() for _ in range(n_targets)]
    bus = EventBus()
    return resolve_program(caster, targets, spell, program,
                           event_bus=bus, damage_processor=DamageProcessor(bus),
                           slot_level=spell.spell_level), caster, targets


@pytest.mark.parametrize("name", _SNAPSHOT_NAMES)
@pytest.mark.parametrize("seed", [1, 7, 13, 29])
def test_native_matches_legacy_snapshot(name, seed):
    spell = StatBlockLoader.load_spell_from_json(
        os.path.join(SPELLS_DIR, f"{name}.json"))
    if not spell.program:
        pytest.skip(f"{name} not yet migrated to a native program")

    snapshot = json.load(open(os.path.join(SNAPSHOT_DIR, f"{name}.json"),
                              encoding="utf-8"))
    n_targets = 1 if spell.targeting_type == TargetingType.SINGLE_TARGET else 4

    native, _, _ = _resolve(parse_program(spell.program), spell, n_targets, seed)
    legacy_program = to_program(snapshot["effects"], spell.targeting_type,
                                _rule_lookup(snapshot))
    legacy, _, _ = _resolve(legacy_program, spell, n_targets, seed)

    assert [_fields(r) for r in native] == [_fields(r) for r in legacy], (
        f"{name}: native program diverged from the legacy snapshot")


def test_all_spells_are_native():
    """Once slice 2 is done, every shipped spell resolves via a native program.

    Guards against a spell left on the legacy `effects` path, or a parity case that
    silently skips forever. Xfail until the migration completes."""
    files = sorted(glob.glob(os.path.join(SPELLS_DIR, "*.json")))
    legacy = []
    for f in files:
        spell = StatBlockLoader.load_spell_from_json(f)
        if not spell.program:
            legacy.append(os.path.splitext(os.path.basename(f))[0])
    if legacy:
        pytest.xfail(f"still on legacy effects (migration in progress): {legacy}")
    assert not legacy
