import json
from typing import Any, Dict

from src.combat.events import EventType
from .rule import Rule


class RuleLoader:
    """Deserializes JSON rule files into Rule objects."""

    @staticmethod
    def load(path: str) -> Rule:
        """Load a single rule from a JSON file.

        Args:
            path: Path to the JSON rule file.

        Returns:
            A Rule instance ready to be registered with RuleEngine.

        Raises:
            FileNotFoundError: If the file does not exist.
            KeyError: If required fields (name, trigger, effects) are missing.
            ValueError: If the trigger string is not a valid EventType.
        """
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)

        return RuleLoader.from_dict(data)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Rule:
        """Build a Rule from a plain dict (e.g. already-parsed JSON).

        Args:
            data: Dict with keys: name, trigger, effects, and optionally
                condition and enabled.

        Returns:
            A Rule instance.
        """
        trigger_str: str = data["trigger"]
        try:
            trigger = EventType[trigger_str.upper()]
        except KeyError:
            valid = [e.name for e in EventType]
            raise ValueError(
                f"Unknown trigger '{trigger_str}'. Valid values: {valid}"
            )

        return Rule(
            name=data["name"],
            trigger=trigger,
            effects=data["effects"],
            condition=data.get("condition"),
            enabled=data.get("enabled", True),
        )
