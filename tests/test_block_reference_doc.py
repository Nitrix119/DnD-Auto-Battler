"""The block reference doc is generated from the registry and must not drift.

docs/BLOCK_REFERENCE.md is rendered from the live block REGISTRY (each handler's
docstring + its BlockContract), so the authoring docs cannot fall behind the code
the loader validates against. If this fails, regenerate with:

    python -m src.spells.reference
"""

import os

from src.spells.reference import generate_block_reference, BLOCK_REFERENCE_PATH
from src.spells.registry import REGISTRY

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _checked_in() -> str:
    path = os.path.join(REPO_ROOT, BLOCK_REFERENCE_PATH)
    assert os.path.exists(path), (
        f"{BLOCK_REFERENCE_PATH} is missing; generate it with "
        f"'python -m src.spells.reference'"
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_block_reference_is_up_to_date():
    assert _checked_in() == generate_block_reference(), (
        "BLOCK_REFERENCE.md is out of date with the registry; regenerate with "
        "'python -m src.spells.reference'"
    )


def test_every_registered_block_is_documented():
    doc = _checked_in()
    for block_type in REGISTRY.types():
        assert f"## `{block_type}`" in doc, f"{block_type} missing from the reference"


def test_every_block_has_a_summary():
    """A block with no docstring would render '(undocumented)' — catch it here
    rather than shipping a reference with a hole in it."""
    assert "_(undocumented)_" not in _checked_in()
