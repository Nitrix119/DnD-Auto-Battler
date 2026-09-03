"""The declared field schemas must match the args the handlers actually read.

`BlockContract.fields` is hand-written, and a hand-written schema rots: someone adds
`block.get("new_arg")` to a handler, forgets the declaration, and the validator then
*rejects* the arg they just added — or declares a field nothing reads and the
generated reference documents something that does not exist.

So this reads the code. It AST-parses every module that reads block args and collects
each literal key passed to `block.get(...)` / `block.args[...]`, then compares that set
against the union of declared field names, in both directions.

This is sound because every arg read in `src/spells/` uses a **literal string
constant** — there are no dynamic key lookups. If that ever stops being true this test
becomes incomplete rather than wrong, so `test_no_dynamic_arg_reads` guards it.

**What it is not:** a per-block check. It compares *sets of names*, because three args
are read outside their own handler (see `_CROSS_READS`). It is a drift alarm, not a
proof that block X declares exactly the args handler X reads.
"""

import ast
import pathlib

from src.spells.contract import UNIVERSAL_FIELDS, Field
from src.spells.registry import REGISTRY
import src.spells.blocks  # noqa: F401  (registers the catalogue)

_SRC = pathlib.Path(__file__).parent.parent / "src" / "spells"

# Modules that read block args: the handlers, plus the two places that read args off a
# block they do not own.
_MODULES = sorted((_SRC / "blocks").glob("*.py")) + [
    _SRC / "runner.py",     # reads `condition` on every block before dispatch
    _SRC / "iterators.py" if (_SRC / "iterators.py").exists() else _SRC / "blocks" / "iterators.py",
]

# Receiver names that denote a block whose args are being read.
_BLOCK_RECEIVERS = {"block", "b", "tb", "child"}

# Args read somewhere other than their own block's handler. Each is a real cross-read,
# listed here so it is documented rather than silently tolerated by the set comparison.
_CROSS_READS = {
    # `condition` — read by runner._condition_passes for *every* block, not by any
    # handler. Declared once in UNIVERSAL_FIELDS.
    "condition",
    # `target` — read via the shared `select_target` helper in blocks/targeting.py
    # rather than in each handler body.
    "target",
    # `roll_once` / `formula` / `scaling` — re-read off child `damage` blocks by
    # for_each_target, to share one roll across the target set. Declared on `damage`.
    "roll_once", "formula", "scaling",
}


def _declared_field_names() -> set:
    names = {f.name for f in UNIVERSAL_FIELDS}
    for block_type in REGISTRY.types():
        for f in REGISTRY.get(block_type).contract.fields:
            names.add(f.name)
            names |= _subfield_names(f)
    return names


def _subfield_names(f: Field) -> set:
    out = set()
    for sub in f.subfields:
        out.add(sub.name)
        out |= _subfield_names(sub)
    return out


def _read_arg_names():
    """Every literal arg key the source reads off a block, with where it was read."""
    found = {}
    for path in _MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            key = None
            # block.get("name") / block.get("name", default)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in _BLOCK_RECEIVERS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key = node.args[0].value
            # block.args["name"]
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "args"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                key = node.slice.value
            if key is not None:
                found.setdefault(key, set()).add(path.name)
    return found


def test_every_arg_the_code_reads_is_declared():
    """Added `block.get("x")` to a handler? Declare it, or authors cannot use it."""
    read = _read_arg_names()
    declared = _declared_field_names()
    undeclared = {k: sorted(v) for k, v in read.items() if k not in declared}
    assert not undeclared, (
        "these block args are read by the code but declared by no BlockContract, so "
        "the validator will reject them as unknown: "
        f"{undeclared}"
    )


def test_every_declared_field_is_read_somewhere():
    """A field nothing reads is a lie in BLOCK_REFERENCE.md."""
    read = set(_read_arg_names())
    # Subfields are read off the nested dict, not off `block`, so exclude them here.
    top_level = {f.name for f in UNIVERSAL_FIELDS}
    for block_type in REGISTRY.types():
        top_level |= {f.name for f in REGISTRY.get(block_type).contract.fields}
    unread = sorted(top_level - read)
    assert not unread, (
        "these fields are declared but no handler reads them — either the arg was "
        f"removed and the schema is stale, or the name is misspelled: {unread}"
    )


def test_cross_reads_are_still_cross_reads():
    """The documented exceptions must stay true, or the note above is misleading."""
    read = _read_arg_names()
    for name in _CROSS_READS:
        assert name in read, f"{name!r} is listed as a cross-read but nothing reads it"


def test_no_dynamic_arg_reads():
    """The set comparison above is only complete while every key is a literal.

    A `block.get(some_variable)` would read an arg this test cannot see, quietly
    weakening the guard — so fail loudly and make the author think about it.
    """
    offenders = []
    for path in _MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in _BLOCK_RECEIVERS
                and node.args
                and not isinstance(node.args[0], ast.Constant)
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "block args must be read with a literal key so the schema drift guard can "
        f"see them; dynamic reads at: {offenders}"
    )
