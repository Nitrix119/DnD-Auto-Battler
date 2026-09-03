"""Native-rule invariant — the rule corpus is fully native, with no exceptions.

Every shipped ``rules/global/*`` and ``rules/entity_effects/**`` rule is authored as a
block ``program``. This guards that invariant: each rule file is native and its program
passes the load-time block validator, so a regression that re-introduces a legacy-shaped
rule (or a malformed program) fails here.
"""

import json
import os

import pytest

from src.rules.rule_loader import RuleLoader
from src.spells.validate import validate_program

_HERE = os.path.dirname(__file__)
_GLOBAL = os.path.join(_HERE, "..", "rules", "global")
_ENTITY = os.path.join(_HERE, "..", "rules", "entity_effects")


def _rule_files():
    files = []
    for root, _dirs, names in os.walk(_ENTITY):
        files += [os.path.join(root, n) for n in names if n.endswith(".json")]
    files += [os.path.join(_GLOBAL, n) for n in os.listdir(_GLOBAL) if n.endswith(".json")]
    return sorted(files)


_FILES = _rule_files()
_IDS = [os.path.relpath(f, os.path.join(_HERE, "..")) for f in _FILES]


@pytest.mark.parametrize("path", _FILES, ids=_IDS)
def test_rule_is_native_and_valid(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    name = data.get("name", "")
    # Native shape: a block ``program``, and none of the legacy ``triggers``/``effects``.
    assert "program" in data, f"{path} is not native (no program)"
    assert "effects" not in data and "triggers" not in data, f"{path} has legacy keys"
    # The program parses and passes the load-time validator (also exercised by the loader).
    rule = RuleLoader.load(path)
    assert rule.program is not None
    validate_program(rule.program, spell_name=name)
