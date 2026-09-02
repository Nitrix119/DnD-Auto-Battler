"""Loader-boundary validation for native block programs.

Elevates the runtime arity linter (:mod:`.lint`) to a **load-time** gate and adds
the checks a hand- or LLM-authored ``program`` needs to fail loudly at load rather
than silently at cast: every ``block`` names a registered type, the target-arity
rule holds, and every ``context.X`` reference names a key some block actually
writes.

It also carries the rule-side half of E6: a ``trigger`` block declares the ``event``
it fires on, so every ``event.<field>`` reference beneath it is checked against that
event's declared fields. At fire time a missing attribute is swallowed
(``triggers._passes`` returns False), which makes a typo indistinguishable from a
legitimately-absent field — so it must be caught here.

This is the ``program`` counterpart of
:func:`src.rules.step_schema.validate_effects`, which validates the legacy
``effects`` shape. Both are called at the ``StatBlockLoader`` boundary as spells
migrate; the legacy validator stays until the last spell is native (Phase 3 §5).
"""

from __future__ import annotations

import ast
import re
from typing import Any, Iterator, List, Optional, Sequence

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .block import Block, parse_program
from .contract import TargetArity
from .lint import lint_program
from .registry import REGISTRY, BlockRegistry

# ``context.<name>`` references inside any expression string must name a key the
# engine seeds. The canonical set lives in ``src.rules.step_schema.CONTEXT_KEYS``
# (kept in sync with ``src.spells.context.seed_context``); imported lazily in the
# check below to avoid the loader import cycle the legacy validator also dodges.
_CONTEXT_REF_RE = re.compile(r"\bcontext\.([A-Za-z_][A-Za-z0-9_]*)")


class ProgramValidationError(ValueError):
    """A native ``program`` is malformed (unknown block, bad context ref, …)."""


def _check_registered(
    program: Sequence[Block], registry: BlockRegistry, spell_name: str
) -> None:
    for block in program:
        if not registry.is_registered(block.type):
            raise ProgramValidationError(
                f"spell {spell_name!r}: unknown block type {block.type!r}; "
                f"registered: {', '.join(sorted(registry.types())) or '(none)'}"
            )
        missing = [
            arg for arg in registry.get(block.type).contract.required_args
            if arg not in block.args
        ]
        if missing:
            raise ProgramValidationError(
                f"spell {spell_name!r}: block {block.type!r} is missing required "
                f"arg(s): {', '.join(missing)}."
            )
        _check_registered(block.then, registry, spell_name)


def _iter_context_refs(value: Any) -> Iterator[str]:
    """Yield every ``context.<name>`` reference found anywhere in *value*."""
    if isinstance(value, str):
        yield from _CONTEXT_REF_RE.findall(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_context_refs(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_context_refs(v)


def _iter_event_refs(value: Any) -> Iterator[str]:
    """Yield every top-level ``event.<attr>`` name referenced anywhere in *value*.

    Strings that are not valid Python expressions carry no references (a plain
    literal such as ``"COLD"`` or ``"Armor of Agathys"`` is not an expression).
    """
    if isinstance(value, str):
        try:
            tree = ast.parse(value, mode="eval")
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "event"
            ):
                yield node.attr
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_event_refs(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_event_refs(v)


def _check_event_refs(
    program: Sequence[Block], spell_name: str, event_name: Optional[str] = None
) -> None:
    """Check ``event.<field>`` references against the enclosing trigger's event.

    Blocks outside any trigger have no event in scope and are skipped; a nested
    trigger rebinds the event for its own subtree.
    """
    from src.combat.events import EventType
    from src.combat.event_data import event_fields

    for block in program:
        scope = event_name
        if block.type == "trigger":
            declared = block.args.get("event")
            scope = str(declared) if isinstance(declared, str) else None

        if scope is not None:
            try:
                available = event_fields(EventType[scope.upper()])
            except KeyError:
                raise ProgramValidationError(
                    f"spell {spell_name!r}: trigger names unknown event {scope!r}; "
                    f"valid events: {', '.join(e.name for e in EventType)}."
                ) from None
            for value in block.args.values():
                for ref in _iter_event_refs(value):
                    if ref not in available:
                        raise ProgramValidationError(
                            f"spell {spell_name!r}: references unknown event field "
                            f"event.{ref} not carried by {scope.upper()}; valid "
                            f"fields: {', '.join(sorted(available)) or '(none)'}."
                        )
        _check_event_refs(block.then, spell_name, scope)


def _check_context_refs(program: Sequence[Block], spell_name: str) -> None:
    from src.rules.step_schema import CONTEXT_KEYS

    for block in program:
        for value in block.args.values():
            for ref in _iter_context_refs(value):
                if ref not in CONTEXT_KEYS:
                    raise ProgramValidationError(
                        f"spell {spell_name!r}: block {block.type!r} references "
                        f"context.{ref}, which no block writes; valid keys: "
                        f"{', '.join(sorted(CONTEXT_KEYS))}."
                    )
        _check_context_refs(block.then, spell_name)


def validate_program(
    program_dicts: Any,
    *,
    spell_name: str = "",
    registry: BlockRegistry = REGISTRY,
) -> List[Block]:
    """Validate a native ``program`` (a list of block dicts) at the loader boundary.

    Checks, in order: the program parses (a list of well-formed blocks with a
    string ``block`` key and list ``then``); every block type is registered; the
    target-arity rule holds (the same :func:`.lint_program` the evaluator asserts at
    run time, seeded from whether the top level consumes a target set); no expression
    references a ``context.X`` key nothing writes; and no expression under a
    ``trigger`` references an ``event.<field>`` that trigger's event does not carry.

    Returns the parsed program on success.

    Raises:
        ProgramValidationError: on any of the above.
    """
    try:
        program = parse_program(program_dicts)
    except ValueError as exc:
        raise ProgramValidationError(f"spell {spell_name!r}: {exc}") from exc

    _check_registered(program, registry, spell_name)

    # Mirror the evaluator's fan-out detection: a top-level set-consuming block
    # (an iterator) means the current target is a set at the program root.
    set_consumer = any(
        registry.get(b.type).contract.target_arity is TargetArity.SET for b in program
    )
    try:
        lint_program(program, target_is_set=set_consumer, registry=registry)
    except ValueError as exc:  # ProgramArityError is a ValueError
        raise ProgramValidationError(f"spell {spell_name!r}: {exc}") from exc

    _check_context_refs(program, spell_name)
    _check_event_refs(program, spell_name)
    return program
