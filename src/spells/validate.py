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

It is called at the ``StatBlockLoader`` and ``RuleLoader`` boundaries — every spell,
weapon program and rule passes through it.
"""

from __future__ import annotations

import ast
import difflib
import re
from typing import Any, Iterator, List, Optional, Sequence, Tuple

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .block import Block, parse_program
from .contract import UNIVERSAL_FIELDS, Field, TargetArity
from .lint import lint_program
from .registry import REGISTRY, BlockRegistry

# ``context.<name>`` references inside any expression string must name a key the
# engine seeds. The canonical set is ``src.spells.context.CONTEXT_KEYS``, derived
# from ``seed_context`` itself so the two cannot drift.
_CONTEXT_REF_RE = re.compile(r"\bcontext\.([A-Za-z_][A-Za-z0-9_]*)")

# A dice formula: one or more terms (NdM or a flat integer) joined by + / -.
# Mirrors ``src.loaders.stat_block_loader._FORMULA_RE`` — kept in sync deliberately.
_FORMULA_RE = re.compile(r"^[+-]?\d+(?:d\d+)?(?:[+-]\d+(?:d\d+)?)*$")

# ``scaling`` is the one block arg with an internal shape, so it carries a schema of
# its own until the fuller per-field block schema lands (REMAINING §4). A malformed
# one silently scales nothing at cast time, so it must fail at load.
_SCALING_FIELDS = {"per_slot_above": int, "add_dice": str}


class ProgramValidationError(ValueError):
    """A native ``program`` is malformed (unknown block, bad context ref, …)."""


def _allowed_fields(contract) -> Tuple[Field, ...]:
    """Every field a block accepts: its own, plus the ones every block takes."""
    return tuple(contract.fields) + UNIVERSAL_FIELDS


def _check_registered(
    program: Sequence[Block], registry: BlockRegistry, spell_name: str
) -> None:
    for block in program:
        if not registry.is_registered(block.type):
            raise ProgramValidationError(
                f"spell {spell_name!r}: unknown block type {block.type!r}; "
                f"registered: {', '.join(sorted(registry.types())) or '(none)'}"
            )
        contract = registry.get(block.type).contract
        # Unknown args first: a misspelled *required* arg is both "unknown" and
        # "missing", and "unknown arg 'fomula' — did you mean 'formula'?" is the far
        # more useful of the two messages.
        _check_unknown_args(block, contract, spell_name)
        missing = [a for a in contract.required_args if a not in block.args]
        if missing:
            raise ProgramValidationError(
                f"spell {spell_name!r}: block {block.type!r} is missing required "
                f"arg(s): {', '.join(missing)}."
            )
        _check_registered(block.then, registry, spell_name)


def _check_unknown_args(block: Block, contract, spell_name: str) -> None:
    """Reject any arg the block does not declare.

    An undeclared arg is silently ignored at run time — a typo'd ``fomula`` simply
    deals no damage — so it has to fail here. Keys starting with ``_`` are authoring
    commentary (``_note``) and are ignored by both the engine and this check.
    """
    valid = sorted(f.name for f in _allowed_fields(contract))
    for key in block.args:
        if key.startswith("_") or key in valid:
            continue
        suggestion = difflib.get_close_matches(key, valid, n=1, cutoff=0.6)
        hint = f" — did you mean {suggestion[0]!r}?" if suggestion else ""
        raise ProgramValidationError(
            f"spell {spell_name!r}: block {block.type!r} has unknown arg "
            f"{key!r}{hint} Valid args: {', '.join(valid)}."
        )


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
    from .context import CONTEXT_KEYS

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


def _check_scaling(program: Sequence[Block], spell_name: str) -> None:
    """Validate a block's ``scaling`` object: required subfields, types, formula."""
    for block in program:
        scaling = block.args.get("scaling")
        if scaling is not None:
            _check_one_scaling(scaling, block.type, spell_name)
        _check_scaling(block.then, spell_name)


def _check_one_scaling(scaling: Any, block_type: str, spell_name: str) -> None:
    where = f"spell {spell_name!r}: block {block_type!r}"
    valid = ", ".join(sorted(_SCALING_FIELDS))
    if not isinstance(scaling, dict):
        raise ProgramValidationError(
            f"{where} has a 'scaling' that is not an object; expected "
            f"an object with {valid}."
        )
    for name, expected in _SCALING_FIELDS.items():
        if name not in scaling:
            raise ProgramValidationError(
                f"{where} 'scaling' is missing required subfield {name!r}; "
                f"required: {valid}."
            )
        value = scaling[name]
        if isinstance(value, bool) or not isinstance(value, expected):
            raise ProgramValidationError(
                f"{where} 'scaling.{name}' must be {expected.__name__}, got "
                f"{type(value).__name__} ({value!r})."
            )
    unknown = sorted(set(scaling) - set(_SCALING_FIELDS))
    if unknown:
        raise ProgramValidationError(
            f"{where} 'scaling' has unknown subfield(s) {', '.join(unknown)}; "
            f"valid: {valid}."
        )
    if not _FORMULA_RE.match(scaling["add_dice"]):
        raise ProgramValidationError(
            f"{where} 'scaling.add_dice' is not a dice formula: "
            f"{scaling['add_dice']!r}."
        )


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
    references a ``context.X`` key nothing writes; no expression under a ``trigger``
    references an ``event.<field>`` that trigger's event does not carry; and any
    ``scaling`` object is well formed.

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
    _check_scaling(program, spell_name)
    return program
