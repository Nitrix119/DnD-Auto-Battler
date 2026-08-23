"""Drift guard: the generated step reference must match the schema.

The per-step reference doc (examples/spells/STEP_REFERENCE.md) is generated from
STEP_SCHEMAS so the authoring docs cannot drift from the code the loader
validates against (design decision E3 / SPELL_SYSTEM_DESIGN.md §7 stage 1). If
this test fails, regenerate with:  python -m src.rules.step_schema
"""

import os

from src.rules.step_schema import generate_step_reference, STEP_REFERENCE_PATH

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_step_reference_doc_is_up_to_date():
    path = os.path.join(REPO_ROOT, STEP_REFERENCE_PATH)
    assert os.path.exists(path), (
        f"{STEP_REFERENCE_PATH} is missing; generate it with "
        f"'python -m src.rules.step_schema'"
    )
    with open(path, encoding="utf-8") as f:
        on_disk = f.read()
    expected = generate_step_reference()
    assert on_disk == expected, (
        "STEP_REFERENCE.md is out of date with the schema; regenerate with "
        "'python -m src.rules.step_schema'"
    )


def test_every_step_type_appears_in_reference():
    from src.rules.step_schema import STEP_SCHEMAS
    doc = generate_step_reference()
    for step_type in STEP_SCHEMAS:
        assert f"## `{step_type}`" in doc
