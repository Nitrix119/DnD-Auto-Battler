"""Tests for the spell pipeline step schema + linter (design stage 1).

The linter validates a spell's ``effects`` (pipeline steps) against a declarative
schema at the loader boundary, turning today's silent no-ops (unknown step type,
typo'd field, bad enum, a ``context.X`` reference to a key nothing writes) into
precise, named load-time errors — without changing runtime behaviour, and without
rejecting any of the shipped spell content (the conformance corpus).
"""

import glob
import os

import pytest

from src.rules.step_schema import (
    STEP_SCHEMAS,
    CONTEXT_KEYS,
    lint_effects,
    validate_effects,
)
from src.loaders import StatBlockLoader

SPELLS_DIR = os.path.join(os.path.dirname(__file__), "..", "examples", "spells")


# ── The schema covers exactly the step types the pipeline dispatches ────────────

def test_schema_covers_all_dispatched_step_types():
    expected = {
        "attack_roll", "saving_throw", "damage", "healing",
        "add_entity_effect", "grant_temporary_hp", "apply_condition", "add_modifier",
    }
    assert set(STEP_SCHEMAS) == expected


def test_context_keys_match_pipeline_seed_defaults():
    # These are the keys the block engine seeds into context; a context.X ref
    # outside this set is a typo the linter should catch.
    assert {"hit", "damage_dealt", "save_success", "attack_total"} <= CONTEXT_KEYS


# ── The conformance corpus: every shipped spell must lint clean ─────────────────

def test_all_shipped_spells_lint_clean():
    files = glob.glob(os.path.join(SPELLS_DIR, "*.json"))
    assert files, "no spell files found"
    problems = {}
    for f in files:
        spell = StatBlockLoader.load_spell_from_json(f)
        errors = lint_effects(spell.pipeline_effects)
        if errors:
            problems[os.path.basename(f)] = errors
    assert not problems, f"shipped spells failed lint: {problems}"


# ── Unhappy paths: each becomes a named error ───────────────────────────────────

class TestLintErrors:

    def test_unknown_step_type_is_named(self):
        errors = lint_effects([{"type": "smite"}])
        assert any("smite" in e for e in errors)

    def test_missing_type_is_reported(self):
        errors = lint_effects([{"formula": "1d6"}])
        assert errors

    def test_missing_required_field(self):
        # damage requires formula + damage_type
        errors = lint_effects([{"type": "damage", "damage_type": "FIRE"}])
        assert any("formula" in e for e in errors)

    def test_unknown_field_typo_is_named(self):
        errors = lint_effects([
            {"type": "damage", "damage_type": "FIRE", "formula": "1d6", "requires_hitt": True}
        ])
        assert any("requires_hitt" in e for e in errors)

    def test_bad_damage_type_enum(self):
        errors = lint_effects([{"type": "damage", "damage_type": "FIREE", "formula": "1d6"}])
        assert any("FIREE" in e for e in errors)

    def test_bad_save_attribute(self):
        errors = lint_effects([{"type": "saving_throw", "attribute": "wisdumb", "dc": 15}])
        assert any("wisdumb" in e for e in errors)

    def test_bad_formula(self):
        errors = lint_effects([{"type": "damage", "damage_type": "FIRE", "formula": "1d"}])
        assert errors

    def test_bad_context_reference_is_named(self):
        errors = lint_effects([
            {"type": "attack_roll", "attack_bonus": "use_caster_bonus"},
            {"type": "healing", "target": "caster", "amount": "context.dmage_dealt // 2"},
        ])
        assert any("dmage_dealt" in e for e in errors)

    def test_good_context_reference_is_accepted(self):
        errors = lint_effects([
            {"type": "attack_roll", "attack_bonus": "use_caster_bonus"},
            {"type": "healing", "target": "caster", "amount": "context.damage_dealt // 2"},
        ])
        assert errors == []

    def test_bad_save_result_option(self):
        errors = lint_effects([
            {"type": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc"},
            {"type": "damage", "damage_type": "FIRE", "formula": "8d6",
             "save_result": {"on_success": "quarter_damage"}},
        ])
        assert any("quarter_damage" in e for e in errors)


# ── Loader integration: bad content fails loudly at the boundary ────────────────

class TestLoaderIntegration:

    def test_validate_effects_raises_with_spell_name(self):
        with pytest.raises(ValueError) as exc:
            validate_effects([{"type": "smite"}], spell_name="Bogus")
        assert "Bogus" in str(exc.value)

    def test_parse_action_rejects_bad_effects(self, tmp_path):
        import json
        bad = {
            "name": "Bad Spell", "description": "x", "type": "spell",
            "effects": [{"type": "damage", "damage_type": "FIRE", "formula": "1d6",
                         "requires_hitt": True}],
        }
        p = tmp_path / "bad_spell.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            StatBlockLoader.load_spell_from_json(str(p))
        assert "requires_hitt" in str(exc.value)
