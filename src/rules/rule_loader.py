import ast
import json
from typing import Any, Dict, List

from src.combat.events import EventType
from src.combat.event_data import event_fields
from .rule import Rule


def _event_refs(expr: Any) -> List[str]:
    """Top-level ``event.<attr>`` names referenced in an expression string.

    Non-strings and strings that are not valid Python expressions yield nothing
    (plain literals such as ``"COLD"`` or ``"Armor of Agathys"`` are not
    expressions and carry no event references).
    """
    if not isinstance(expr, str):
        return []
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    refs: List[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "event"
        ):
            refs.append(node.attr)
    return refs


def _validate_event_field_refs(rule: Rule) -> None:
    """Raise ValueError if a rule references an ``event.<field>`` no trigger carries.

    Validates the condition and every string-valued effect field (including a
    per-effect ``when``) against the union of the rule's trigger events' declared
    fields. A field present on *no* trigger is a typo (E6); a field on *some*
    triggers is the legitimate multi-trigger case and is allowed.
    """
    available: set = set()
    for trigger in rule.triggers:
        available |= event_fields(trigger)

    exprs: List[str] = []
    if rule.condition:
        exprs.append(rule.condition)
    for effect in rule.effects:
        if isinstance(effect, dict):
            exprs.extend(v for v in effect.values() if isinstance(v, str))

    bad: List[str] = []
    for expr in exprs:
        for attr in _event_refs(expr):
            if attr not in available and attr not in bad:
                bad.append(attr)

    if bad:
        valid = ", ".join(sorted(available)) or "(none)"
        triggers = ", ".join(t.name for t in rule.triggers)
        raise ValueError(
            f"Rule {rule.name!r}: references unknown event field(s) "
            f"{', '.join('event.' + b for b in bad)} not carried by its "
            f"trigger(s) [{triggers}]; valid fields: {valid}"
        )


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

        rule = Rule(
            name=data["name"],
            triggers=triggers,
            effects=data["effects"],
            condition=data.get("condition"),
            enabled=data.get("enabled", True),
            duration_rounds=data.get("duration_rounds"),
            source=data.get("source", ""),
        )
        # Boundary check: catch typo'd event.<field> references at load time so a
        # bad rule fails loudly here instead of being silently skipped at run
        # time (retires E6). See src.combat.event_data.event_fields.
        _validate_event_field_refs(rule)
        return rule
