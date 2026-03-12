"""Registry that indexes entity effect Rules by name for fast lookup."""

import json
from pathlib import Path
from typing import Dict

from .rule import Rule
from .rule_loader import RuleLoader


class EffectRegistry:
    """Scans directories of effect JSON files and indexes them by name."""

    def __init__(self):
        self._effects: Dict[str, Rule] = {}

    def scan_directory(self, directory: str) -> None:
        """Recursively scan a directory for .json effect files and register them."""
        for path in sorted(Path(directory).rglob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rule = RuleLoader.from_dict(data)
            if rule.name in self._effects:
                raise ValueError(
                    f"Duplicate effect name '{rule.name}' found in {path}"
                )
            self._effects[rule.name] = rule

    def get(self, name: str) -> Rule:
        """Look up an effect by name. Raises KeyError if not found."""
        return self._effects[name]

    def __contains__(self, name: str) -> bool:
        return name in self._effects
