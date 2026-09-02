"""Generate the block authoring reference from the registry itself.

``BLOCK_REFERENCE.md`` is rendered from the live block ``REGISTRY`` — each block's
handler docstring plus its :class:`BlockContract` — so the authoring docs cannot
drift from the code the loader validates against. A drift test
(``tests/test_block_reference_doc.py``) fails if the checked-in file is stale.

Regenerate with::

    python -m src.spells.reference

What it can and cannot say
--------------------------
The contract knows a block's *required* args, the context keys it reads and writes,
its target arity, and its category flags — so those are authoritative here. It does
**not** yet carry a per-field type/domain/description for optional args; that is the
fuller per-field block schema (docs/SPELL_SYSTEM_REMAINING.md §4), and when it lands
this generator grows a field table per block. Until then the handler docstring
carries that detail in prose.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .contract import TargetArity
from .registry import REGISTRY, BlockRegistry

BLOCK_REFERENCE_PATH = "docs/BLOCK_REFERENCE.md"

_HEADER = (
    "<!-- GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "     Regenerate with:  python -m src.spells.reference\n"
    "     Source of truth:  the block REGISTRY (src/spells/blocks/*.py).\n"
    "     A drift test (tests/test_block_reference_doc.py) fails if this is stale. -->\n"
)

_ARITY_BLURB = {
    TargetArity.SINGLE: "acts on the current target, which must be exactly one entity",
    TargetArity.CASTER: "acts on the caster, whatever the current target is",
    TargetArity.SET: "consumes the target set (an iterator, or a genuine aggregate)",
}


def _summary(handler) -> str:
    """The first paragraph of a handler's docstring, as one line."""
    doc = (handler.__doc__ or "").strip()
    if not doc:
        return "_(undocumented)_"
    para: List[str] = []
    for line in doc.splitlines():
        if not line.strip():
            break
        para.append(line.strip())
    return " ".join(para)


def _detail(handler) -> str:
    """The remainder of the docstring after the summary paragraph, dedented."""
    doc = (handler.__doc__ or "").strip()
    lines = doc.splitlines()
    rest: List[str] = []
    seen_blank = False
    for line in lines:
        if not seen_blank:
            if not line.strip():
                seen_blank = True
            continue
        rest.append(line.strip())
    while rest and not rest[-1]:
        rest.pop()
    return "\n".join(rest)


def generate_block_reference(registry: BlockRegistry = REGISTRY) -> str:
    """Render the block reference as Markdown from *registry*."""
    types = sorted(registry.types())
    out: List[str] = [_HEADER, "", "# Block Reference", ""]
    out.append(
        "The authoritative list of block types, generated from the registry the "
        "loader validates against. A spell, a weapon and a rule are all programs "
        "built from these blocks."
    )
    out.append("")
    out.append("Block types: " + ", ".join(f"[`{t}`](#{t})" for t in types) + ".")
    out.append("")
    out.append(
        "**Reading this.** *Required args* are the ones the load-time validator "
        "rejects a program for omitting; a block may accept further optional args "
        "documented in its notes. *Reads*/*Writes context* are the `context.X` keys "
        "a block consumes and produces — a later block may read what an earlier one "
        "wrote. *Target* is how the block addresses the current target."
    )
    out.append("")

    for type_name in types:
        entry = registry.get(type_name)
        c = entry.contract
        out.append(f"## `{type_name}`")
        out.append("")
        out.append(_summary(entry.handler))
        out.append("")

        rows = [
            ("Required args", ", ".join(f"`{a}`" for a in c.required_args)),
            ("Reads context", ", ".join(f"`{k}`" for k in c.reads)),
            ("Writes context", ", ".join(f"`{k}`" for k in c.writes)),
            ("Target", _ARITY_BLURB[c.target_arity]),
        ]
        flags = []
        if c.is_gate:
            flags.append("gate (a roll that later blocks are conditioned on)")
        if c.installs_reactions:
            flags.append("installs reactions (subscribes handlers to future events)")
        if c.mutates_event:
            flags.append("event modifier (mutates the in-flight event; only meaningful inside a `trigger`)")
        if flags:
            rows.append(("Category", "; ".join(flags)))

        out.append("| | |")
        out.append("|---|---|")
        for label, value in rows:
            out.append(f"| **{label}** | {value or '_(none)_'} |")
        out.append("")

        detail = _detail(entry.handler)
        if detail:
            out.append(detail)
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    out = Path(__file__).resolve().parents[2] / BLOCK_REFERENCE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate_block_reference(), encoding="utf-8", newline="\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
