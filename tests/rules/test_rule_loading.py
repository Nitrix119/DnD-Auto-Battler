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


# ── E6: a typo'd event.<field> in a trigger is caught at load ───────────────────

class TestTriggerEventFieldValidation:
    """A trigger's `when`/args are evaluated against the fired event, and a missing
    attribute is swallowed there (triggers._passes returns False) — so a typo is
    indistinguishable from a legitimately-absent field at run time. It has to be
    caught at load, against the trigger's declared event."""

    def _rule(self, **trigger):
        base = {"block": "trigger", "event": "DAMAGE_DEALT", "then": []}
        base.update(trigger)
        return {"name": "typo_rule", "program": [base]}

    def test_typo_in_when_raises(self):
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(self._rule(when="event.defenderr == entity"))
        msg = str(exc.value)
        assert "defenderr" in msg and "typo_rule" in msg

    def test_valid_when_loads(self):
        RuleLoader.from_dict(self._rule(when="event.defender == entity and event.total > 0"))

    def test_typo_in_a_nested_block_arg_raises(self):
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(self._rule(then=[
                {"block": "damage", "target": "event.attackerr",
                 "formula": "1d6", "damage_type": "COLD"},
            ]))
        assert "attackerr" in str(exc.value)

    def test_typo_in_a_binding_raises(self):
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(self._rule(bindings={"charmer": "event.casterr"}))
        assert "casterr" in str(exc.value)

    def test_error_names_the_valid_fields(self):
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(self._rule(event="HEALING_APPLIED",
                                            when="event.healed == entity"))
        assert "target" in str(exc.value)  # HEALING_APPLIED carries target/amount

    def test_field_from_an_outer_trigger_is_allowed(self):
        """A nested trigger's `then` may reference the *inner* event's fields."""
        RuleLoader.from_dict({"name": "nested", "program": [{
            "block": "trigger", "event": "TURN_START", "then": [
                {"block": "trigger", "event": "ATTACK_HIT",
                 "when": "event.attacker == entity", "then": []},
            ],
        }]})
