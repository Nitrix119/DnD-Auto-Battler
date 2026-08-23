"""Load-time validation of event-field references in rules (retires E6).

E6: RuleEngine's condition eval catches AttributeError and silently skips, so a
genuine typo (``event.targett``) was indistinguishable from a legitimately-absent
field on a wrong event type. With a per-event field schema we now validate every
``event.<field>`` reference at load time against the union of the rule's trigger
events: a field present on *no* trigger is a typo and raises; a field present on
*some* triggers (the legitimate multi-trigger case) still loads and relies on the
runtime skip. See docs/SPELL_SYSTEM_DESIGN.md §6.9.
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


# ── Typos are caught at load ────────────────────────────────────────────────────

class TestEventFieldValidation:

    def test_condition_typo_on_no_trigger_raises(self):
        data = {
            "name": "typo_rule",
            "triggers": ["DAMAGE_DEALT"],
            "condition": "event.defenderr == entity",
            "effects": [],
        }
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(data)
        msg = str(exc.value)
        assert "defenderr" in msg and "typo_rule" in msg

    def test_valid_condition_loads(self):
        data = {
            "name": "ok_rule",
            "triggers": ["DAMAGE_DEALT"],
            "condition": "event.defender == entity and event.total > 0",
            "effects": [],
        }
        RuleLoader.from_dict(data)  # no raise

    def test_field_on_some_but_not_all_triggers_is_allowed(self):
        # 'attacker' exists on ATTACK_HIT but not DAMAGE_DEALT — the legitimate
        # multi-trigger case must still load (runtime skip handles the gap).
        data = {
            "name": "multi_trigger",
            "triggers": ["ATTACK_HIT", "DAMAGE_DEALT"],
            "condition": "event.attacker == entity",
            "effects": [],
        }
        RuleLoader.from_dict(data)  # no raise

    def test_effect_field_typo_raises(self):
        data = {
            "name": "bad_effect_target",
            "triggers": ["ATTACK_HIT"],
            "effects": [
                {"action": "DealDamage", "target": "event.attackerr",
                 "formula": "1d6", "damage_type": "COLD"}
            ],
        }
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(data)
        assert "attackerr" in str(exc.value)

    def test_error_names_valid_fields(self):
        data = {
            "name": "helpful_error",
            "triggers": ["HEALING_APPLIED"],
            "condition": "event.healed == entity",
            "effects": [],
        }
        with pytest.raises(ValueError) as exc:
            RuleLoader.from_dict(data)
        # HEALING_APPLIED carries target/amount — the error should list them.
        assert "target" in str(exc.value)
