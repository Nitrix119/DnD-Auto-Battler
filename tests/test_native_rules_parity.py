"""Parity net for the native-rule migration (Phase 3 §5d — foundation + pilot).

Each ``rules/global/*`` / ``rules/entity_effects/*`` file is migrating off the legacy
``action``-verb ``Rule`` shape (``triggers``/``effects``, translated at install time by
``fold.rule_to_trigger_blocks``) onto a native block ``program`` authored directly in the
file. This harness freezes each migrated rule's *pre-migration* legacy shape under
``tests/legacy_snapshots_rules/`` and asserts the live native ``program`` parses to exactly
the block program the fold produced from that snapshot — the same guardrail the spell
migration used (``test_native_corpus_parity``).

The fold args below are the ones each install seam actually passes, so the frozen fold
output is the real oracle:

- global rules → ``rule_to_trigger_blocks(rule, priority=0)`` (``global_rules``)
- Colossus (an entity-effect rider) → ``rule_to_trigger_blocks(rule, holder="caster")``
  (``entity_effects.install_entity_effect``, run on caster == holder)
- conditions → ``rule_to_trigger_blocks(rule, holder="defender")`` (``apply_condition`` when
  the condition is applied to the target — the shipped usage)

A sentinel (:func:`test_every_pilot_rule_is_native`) fails until every pilot file is native,
so the follow-on corpus slice cannot silently stall.
"""

import json
import os

import pytest

from src.rules.rule_loader import RuleLoader
from src.spells.block import parse_program
from src.spells.fold import rule_to_trigger_blocks

_HERE = os.path.dirname(__file__)
_SNAPSHOTS = os.path.join(_HERE, "legacy_snapshots_rules")
_GLOBAL = os.path.join(_HERE, "..", "rules", "global")
_ENTITY = os.path.join(_HERE, "..", "rules", "entity_effects")
_CONDITIONS = os.path.join(_ENTITY, "conditions")

# (snapshot filename, live native file path, fold kwargs the install seam uses)
PILOT = [
    ("damage_resistance_rule.json",
     os.path.join(_GLOBAL, "damage_resistance_rule.json"), {"priority": 0}),
    ("damage_immunity_rule.json",
     os.path.join(_GLOBAL, "damage_immunity_rule.json"), {"priority": 0}),
    ("damage_vulnerability_rule.json",
     os.path.join(_GLOBAL, "damage_vulnerability_rule.json"), {"priority": 0}),
    ("colossus_slayer.json",
     os.path.join(_ENTITY, "colossus_slayer.json"), {"holder": "caster"}),
    ("restrained.json",
     os.path.join(_CONDITIONS, "restrained.json"), {"holder": "defender"}),
]

_IDS = [p[0] for p in PILOT]


def _folded_from_snapshot(snapshot_name, **fold_kwargs):
    with open(os.path.join(_SNAPSHOTS, snapshot_name), "r", encoding="utf-8") as f:
        legacy = RuleLoader.from_dict(json.load(f))
    return parse_program(rule_to_trigger_blocks(legacy, **fold_kwargs))


@pytest.mark.parametrize("snapshot, native_path, fold_kwargs", PILOT, ids=_IDS)
def test_native_program_matches_folded_legacy(snapshot, native_path, fold_kwargs):
    """The live native ``program`` parses to exactly the fold's output for its snapshot."""
    native_rule = RuleLoader.load(native_path)
    assert native_rule.program, f"{native_path} is not native yet (no program)"
    native = parse_program(native_rule.program)
    expected = _folded_from_snapshot(snapshot, **fold_kwargs)
    assert native == expected


def test_every_pilot_rule_is_native():
    """Sentinel: every pilot rule file is native (block ``program``, no legacy ``effects``).

    Fails until the whole pilot has migrated; the follow-on corpus slice extends PILOT and
    keeps this honest.
    """
    for _snapshot, native_path, _kwargs in PILOT:
        with open(native_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "program" in data and "effects" not in data, native_path
