"""Unified expression evaluation for the rule engine.

This module is the single source of truth for sandboxed ``eval()`` in rule
conditions and effect fields.  Both ``RuleEngine`` and the built-in effect
handlers import from here.
"""

from typing import Any, Dict


SAFE_BUILTINS: Dict[str, Any] = {
    "max": max, "min": min, "abs": abs, "int": int,
    "round": round, "bool": bool, "len": len, "hasattr": hasattr,
}


def evaluate(expr: str, ctx: dict) -> Any:
    """Evaluate a Python expression string in a sandboxed namespace."""
    return eval(expr, {"__builtins__": {}}, ctx)


def resolve(value: Any, ctx: dict) -> Any:
    """Resolve a value that may be a Python expression string.

    If *value* is a string it is evaluated via :func:`evaluate`; otherwise it
    is returned unchanged (int, bool, None, etc.).
    """
    if isinstance(value, str):
        return evaluate(value, ctx)
    return value
