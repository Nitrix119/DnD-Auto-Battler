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

# A bare Python identifier. Used to stop an `allow_expr` field treating a misspelled
# enum name ("FIREE") as an expression — it parses as one, but is never meant as one.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _is_expression(value: Any) -> bool:
    """True if *value* parses as a Python expression (so it could be one)."""
    if not isinstance(value, str):
        return False
    try:
        ast.parse(value, mode="eval")
    except SyntaxError:
        return False
    return True


def _check_value(value: Any, spec: Field, where: str) -> None:
    """Validate one arg value against its declared :class:`Field`.

    *where* names the block (and, inside a nested object, the path to the value) so
    the message points at the exact key that is wrong.
    """
    # A declared sentinel is accepted verbatim in place of the kind — the literal
    # special values the engine reads directly ("use_caster_bonus", "caster").
    if spec.sentinels and isinstance(value, str) and value in spec.sentinels:
        return

    kind = spec.kind
    if kind == "any":
        return

    if kind == "bool":
        if not isinstance(value, bool):
            raise ProgramValidationError(
                f"{where} must be true or false, got "
                f"{type(value).__name__} ({value!r})."
            )
    elif kind in ("int", "number"):
        # bool is an int in Python; a `true` where a number belongs is an error.
        ok = (not isinstance(value, bool)) and isinstance(
            value, int if kind == "int" else (int, float)
        )
        if not ok:
            extra = (
                f" (or one of: {', '.join(spec.sentinels)})" if spec.sentinels else ""
            )
            raise ProgramValidationError(
                f"{where} must be {'an integer' if kind == 'int' else 'a number'}"
                f"{extra}, got {type(value).__name__} ({value!r})."
            )
    elif kind == "str":
        if not isinstance(value, str):
            raise ProgramValidationError(
                f"{where} must be a string, got {type(value).__name__} ({value!r})."
            )
    elif kind == "formula":
        if not isinstance(value, str) or not _FORMULA_RE.match(value):
            raise ProgramValidationError(
                f"{where} is not a dice formula ('2d6', '1d8+3', '20'): {value!r}."
            )
    elif kind == "expr":
        if not _is_expression(value) and not isinstance(value, (int, float, bool)):
            raise ProgramValidationError(
                f"{where} must be an expression or a number, got "
                f"{type(value).__name__} ({value!r})."
            )
    elif kind == "enum":
        assert spec.enum is not None  # guaranteed by Field.__post_init__
        names = [m.name for m in spec.enum]
        if not isinstance(value, str) or value.upper() not in names:
            # The one hybrid: `damage.damage_type` also takes an expression yielding
            # a type (a rider dealing the weapon's own). A *bare identifier* does not
            # count — "FIREE" parses as an expression but is plainly a misspelled
            # enum name, and nothing in the expression namespace is a bare word.
            if spec.allow_expr and _is_expression(value) and not _IDENT_RE.match(value):
                return
            suggestion = difflib.get_close_matches(
                str(value).upper(), names, n=1, cutoff=0.6
            )
            hint = f" — did you mean {suggestion[0]!r}?" if suggestion else ""
            raise ProgramValidationError(
                f"{where} is not a {spec.enum.__name__}: {value!r}{hint} "
                f"Valid: {', '.join(sorted(names))}."
            )
    elif kind == "choice":
        if value not in spec.choices:
            suggestion = difflib.get_close_matches(
                str(value), list(spec.choices), n=1, cutoff=0.6
            )
            hint = f" — did you mean {suggestion[0]!r}?" if suggestion else ""
            raise ProgramValidationError(
                f"{where} is {value!r}{hint} Valid: {', '.join(spec.choices)}."
            )
    elif kind == "map_expr":
        if not isinstance(value, dict):
            raise ProgramValidationError(
                f"{where} must be an object of name -> expression, got "
                f"{type(value).__name__}."
            )
    elif kind == "object":
        _check_object(value, spec, where)
    elif kind == "list":
        if not isinstance(value, list):
            raise ProgramValidationError(
                f"{where} must be a list, got {type(value).__name__} ({value!r})."
            )
        for i, entry in enumerate(value):
            _check_object(entry, spec, f"{where}[{i}]")


def _check_object(value: Any, spec: Field, where: str) -> None:
    """Validate a nested object against ``spec.subfields``."""
    valid = sorted(f.name for f in spec.subfields)
    if not isinstance(value, dict):
        raise ProgramValidationError(
            f"{where} must be an object with {', '.join(valid)}, got "
            f"{type(value).__name__} ({value!r})."
        )
    for required in spec.subfields:
        if required.required and required.name not in value:
            raise ProgramValidationError(
                f"{where} is missing required subfield {required.name!r}; "
                f"required: {', '.join(f.name for f in spec.subfields if f.required)}."
            )
    for key, sub_value in value.items():
        if key.startswith("_"):
            continue
        sub: Optional[Field] = next(
            (f for f in spec.subfields if f.name == key), None)
        if sub is None:
            suggestion = difflib.get_close_matches(key, valid, n=1, cutoff=0.6)
            hint = f" — did you mean {suggestion[0]!r}?" if suggestion else ""
            raise ProgramValidationError(
                f"{where} has unknown subfield {key!r}{hint} "
                f"Valid: {', '.join(valid)}."
            )
        _check_value(sub_value, sub, f"{where}.{key}")


def _check_field_kinds(
    program: Sequence[Block], registry: BlockRegistry, spell_name: str
) -> None:
    """Validate every present arg against its declared field."""
    for block in program:
        contract = registry.get(block.type).contract
        for spec in _allowed_fields(contract):
            if spec.name in block.args:
                _check_value(
                    block.args[spec.name], spec,
                    f"spell {spell_name!r}: block {block.type!r} arg {spec.name!r}",
                )
        _check_field_kinds(block.then, registry, spell_name)


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
    references an ``event.<field>`` that trigger's event does not carry; every arg
    is declared by the block and matches its declared kind and domain.

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
    _check_field_kinds(program, registry, spell_name)
    return program
