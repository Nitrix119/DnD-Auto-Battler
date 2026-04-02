"""Unified expression evaluation for the rule engine.

This module is the single source of truth for sandboxed ``eval()`` in rule
conditions and effect fields.  Both ``RuleEngine`` and the built-in effect
handlers import from here.
"""

import ast
import types
from types import SimpleNamespace
from typing import Any, Dict, Set


SAFE_BUILTINS: Dict[str, Any] = {
    "max": max, "min": min, "abs": abs, "int": int,
    "round": round, "bool": bool, "len": len, "hasattr": hasattr,
}


ALLOWED_NODES: frozenset = frozenset({
    ast.Expression,
    ast.Name, ast.Attribute, ast.Subscript,
    ast.Index,    # Python 3.8 compat; never emitted by 3.9+ parser, but harmless
    ast.Load,     # context node on every Name/Attribute/Subscript in read position
    ast.Constant,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not,
    ast.BinOp, ast.FloorDiv, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.Call,
    ast.Tuple,
})

_validated_cache: Set[str] = set()
_compiled_cache: Dict[str, types.CodeType] = {}


def _validate_ast(expr: str) -> None:
    """Validate a rule expression string against the AST whitelist.

    Raises ValueError with a descriptive message if the expression contains any
    disallowed construct (dangerous node type, dunder attribute, or non-whitelisted
    function call).  Results are cached by expression string so repeated validation
    of the same expression (very common in combat) incurs only one parse.
    """
    if expr in _validated_cache:
        return

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression {expr!r}: syntax error: {exc}") from exc

    for node in ast.walk(tree):
        node_type = type(node)

        if node_type not in ALLOWED_NODES:
            raise ValueError(
                f"Invalid expression {expr!r}: disallowed node type '{node_type.__name__}'"
            )

        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError(
                f"Invalid expression {expr!r}: attribute access to private/dunder "
                f"name {node.attr!r} is not allowed"
            )

        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError(
                f"Invalid expression {expr!r}: use of private/dunder name "
                f"{node.id!r} is not allowed"
            )

        if isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Name):
                raise ValueError(
                    f"Invalid expression {expr!r}: only direct calls to SAFE_BUILTINS "
                    f"are allowed, not method calls or computed callables"
                )
            if func.id not in SAFE_BUILTINS:
                raise ValueError(
                    f"Invalid expression {expr!r}: call to {func.id!r} is not allowed; "
                    f"permitted functions: {sorted(SAFE_BUILTINS)}"
                )

    _validated_cache.add(expr)


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


def evaluate(expr: Any, ctx: dict) -> Any:
    """Evaluate a Python expression in a sandboxed namespace.

    Accepts either a string (validated via AST whitelist before eval) or a
    pre-compiled code object (e.g. from Rule._compiled_condition, which was
    validated as a string at Rule creation time in __post_init__).

    String expressions are compiled once and cached as bytecode so that
    repeated evaluations of the same expression (very common inside combat
    loops) skip repeated parsing and AST validation.
    """
    if isinstance(expr, str):
        if expr not in _compiled_cache:
            _validate_ast(expr)  # security boundary: validated once at first use
            _compiled_cache[expr] = compile(expr, "<rule-expr>", "eval")
        expr = _compiled_cache[expr]
    return eval(expr, {"__builtins__": {}}, ctx)


def resolve(value: Any, ctx: dict) -> Any:
    """Resolve a value that may be a Python expression string.

    If *value* is a string it is evaluated via :func:`evaluate`; otherwise it
    is returned unchanged (int, bool, None, etc.).
    """
    if isinstance(value, str):
        return evaluate(value, ctx)
    return value
