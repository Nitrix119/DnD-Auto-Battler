import json
from typing import Any, Dict, List

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
            KeyError: If required fields (name, triggers/trigger, effects) are missing.
            ValueError: If a trigger string is not a valid EventType.
        """
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)

        return RuleLoader.from_dict(data)

    @staticmethod
    def _parse_trigger(trigger_str: str) -> EventType:
        """Convert a trigger string to an EventType enum value."""
        try:
            return EventType[trigger_str.upper()]
        except KeyError:
            valid = [e.name for e in EventType]
            raise ValueError(
                f"Unknown trigger '{trigger_str}'. Valid values: {valid}"
            )

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Rule:
        """Build a Rule from a plain dict (e.g. already-parsed JSON).

        Accepts either ``"trigger"`` (single string) or ``"triggers"`` (list of
        strings).  Both are normalized to a list of :class:`EventType` values.

        Args:
            data: Dict with keys: name, trigger/triggers, effects, and optionally
                condition and enabled.

        Returns:
            A Rule instance.
        """
        triggers: List[EventType]
        if "triggers" in data:
            triggers = [RuleLoader._parse_trigger(t) for t in data["triggers"]]
        else:
            raise KeyError("Rule must have a 'triggers' field")

        return Rule(
            name=data["name"],
            triggers=triggers,
            effects=data["effects"],
            condition=data.get("condition"),
            enabled=data.get("enabled", True),
            duration_rounds=data.get("duration_rounds"),
            source=data.get("source", ""),
        )
