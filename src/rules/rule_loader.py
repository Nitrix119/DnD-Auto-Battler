import json
from typing import Any, Dict

from .rule import Rule


class RuleLoader:
    """Deserializes JSON rule files into Rule objects."""

    @staticmethod
    def load(path: str) -> Rule:
        """Load a single rule from a JSON file.

        Args:
            path: Path to the JSON rule file.

        Returns:
            A Rule instance ready to be installed by RuleEngine.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the rule is not a native block ``program``.
        """
        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)

        try:
            return RuleLoader.from_dict(data)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Rule:
        """Build a Rule from a plain dict (e.g. already-parsed JSON).

        A rule authors its reactive behaviour as a block ``program`` keyed by
        ``block``; its events live inside its ``trigger`` blocks. The program is
        validated here, at the loader boundary, so a malformed rule fails loudly on
        load rather than silently doing nothing at install.

        Args:
            data: Dict with keys: name, program, and optionally duration_rounds
                and source.

        Returns:
            A Rule instance.

        Raises:
            ValueError: If ``program`` is missing — including when the retired
                ``triggers``/``effects`` shape is used instead.
        """
        name = data.get("name", "<unnamed>")
        if "program" not in data:
            legacy = sorted(k for k in ("triggers", "trigger", "effects") if k in data)
            hint = (
                f" It uses the retired {'/'.join(legacy)} form; rewrite it as a "
                f"program of trigger blocks."
                if legacy else ""
            )
            raise ValueError(
                f"Rule {name!r} has no 'program'. A rule must be authored as a "
                f"native block program (a list of blocks keyed by 'block').{hint}"
            )

        rule = Rule(
            name=data["name"],
            program=data["program"],
            duration_rounds=data.get("duration_rounds"),
            source=data.get("source", ""),
        )
        # Lazy import: the block validator pulls in the block catalogue (which
        # reaches into src.combat), so import at call time to dodge a load-time
        # rules -> spells -> combat cycle — the same dodge validate.py uses.
        from src.spells.validate import validate_program

        validate_program(data["program"], spell_name=data["name"])
        return rule
