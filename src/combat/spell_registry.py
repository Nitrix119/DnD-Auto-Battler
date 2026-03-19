"""Registry that indexes SpellAction objects by name for fast lookup."""

from pathlib import Path
from typing import Dict

from src.models.action import SpellAction
from src.loaders.stat_block_loader import StatBlockLoader


class SpellRegistry:
    """Scans directories of spell JSON files and indexes them by name.

    Each file must contain a single spell action object (``"type": "spell"``).
    Spell names are stored and looked up case-sensitively, matching the names
    used in ``StatBlock.known_spells``.
    """

    def __init__(self) -> None:
        self._spells: Dict[str, SpellAction] = {}

    def scan_directory(self, directory: str) -> None:
        """Recursively scan *directory* for .json spell files and register them.

        Raises:
            ValueError: If a duplicate spell name is found across files.
        """
        for path in sorted(Path(directory).rglob("*.json")):
            spell = StatBlockLoader.load_spell_from_json(str(path))
            if spell.name in self._spells:
                raise ValueError(
                    f"Duplicate spell name '{spell.name}' found in {path}"
                )
            self._spells[spell.name] = spell

    def register(self, spell: SpellAction) -> None:
        """Register a single spell, overwriting any previous entry with the same name."""
        self._spells[spell.name] = spell

    def get(self, name: str) -> SpellAction:
        """Return the SpellAction for *name*.

        Raises:
            KeyError: If the spell is not registered.
        """
        return self._spells[name]

    def __contains__(self, name: str) -> bool:
        return name in self._spells

    def __len__(self) -> int:
        return len(self._spells)
