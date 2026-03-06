"""Unified expression evaluation for the rule engine.

This module is the single source of truth for sandboxed ``eval()`` in rule
conditions and effect fields.  Both ``RuleEngine`` and the built-in effect
handlers import from here.
"""

from types import SimpleNamespace
from typing import Any, Dict


SAFE_BUILTINS: Dict[str, Any] = {
    "max": max, "min": min, "abs": abs, "int": int,
    "round": round, "bool": bool, "len": len, "hasattr": hasattr,
}


def build_context(event_data: dict, **extras) -> dict:
    """Build a standard expression evaluation namespace.

    Args:
        event_data: Dict of fields exposed as ``event.<field>`` in expressions.
        **extras: Additional top-level names merged into the context
            (e.g. ``save_success=True``).

    Returns:
        A dict suitable for :func:`evaluate`, containing ``event``
        (SimpleNamespace), all ``SAFE_BUILTINS``, and any extras.
    """
    return {
        **SAFE_BUILTINS,
        "event": SimpleNamespace(**event_data),
        **extras,
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
