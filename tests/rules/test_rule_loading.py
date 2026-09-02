"""The rule loader boundary: what loads, what is rejected, and the event schema.

A rule is authored as a block ``program``; the loader validates it and rejects
anything else by name, so a malformed or retired-shape rule fails loudly here rather
than loading into a silent no-op.

The per-event field schema (``EVENT_DATA_CLASSES`` / ``event_fields``) is what a rule
author's ``event.<field>`` references are checked against. Its load-time check for the
retired ``triggers``/``effects`` shape is gone with that shape; the schema itself
stays, and is the primitive the block-level version of that check (E6, still open for
nested attributes) will build on. See docs/SPELL_SYSTEM_DESIGN.md §6.9.
"""

import glob
import os

import pytest

from src.combat.events import EventType
from src.combat.event_data import EVENT_DATA_CLASSES, event_fields
from src.rules.rule_loader import RuleLoader

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "rules")


# ── The event-field schema is complete ──────────────────────────────────────────

def test_event_data_classes_cover_every_event_type():
    missing = [et for et in EventType if et not in EVENT_DATA_CLASSES]
    assert not missing, f"EVENT_DATA_CLASSES missing entries for: {missing}"


def test_event_fields_reports_declared_fields():
    fields = event_fields(EventType.DAMAGE_DEALT)
    assert {"defender", "total", "source", "action_name"} <= fields


def test_dynamic_crit_fields_are_declared_on_attack_events():
    # critical_hit/critical_miss are set by handlers; declaring them keeps the
    # schema honest so a rule may reference them without a false-positive typo.
    assert "critical_hit" in event_fields(EventType.ATTACK_ROLLED)
    assert "critical_miss" in event_fields(EventType.ATTACK_ROLLED)


# ── Conformance: every shipped rule loads clean ─────────────────────────────────

def test_all_shipped_rules_load_clean():
    files = glob.glob(os.path.join(RULES_DIR, "**", "*.json"), recursive=True)
    assert files, "no rule files found"
    for f in files:
        RuleLoader.load(f)  # must not raise


# ── A non-program rule is rejected by name ──────────────────────────────────────

class TestNonProgramRulesAreRejected:

    def test_retired_triggers_effects_shape_is_rejected(self):
        """The pre-block authoring form must not load as a silent no-op."""
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict({
                "name": "old_shape",
                "triggers": ["DAMAGE_DEALT"],
                "effects": [{"action": "DealDamage", "formula": "1d6"}],
            })
        msg = str(exc.value)
        assert "old_shape" in msg          # names the offender
        assert "program" in msg            # names what is required
        assert "triggers" in msg and "effects" in msg  # names what it found

    def test_rule_with_no_program_is_rejected(self):
        with pytest.raises(ValueError, match="bare"):
            RuleLoader.from_dict({"name": "bare"})

    def test_load_error_names_the_file(self, tmp_path):
        path = tmp_path / "legacy_rule.json"
        path.write_text('{"name": "on_disk", "triggers": ["TURN_END"], "effects": []}')
        with pytest.raises(ValueError) as exc:
            RuleLoader.load(str(path))
        assert "legacy_rule.json" in str(exc.value)
        assert "on_disk" in str(exc.value)
