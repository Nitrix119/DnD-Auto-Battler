"""Declarative schema + linter for spell pipeline steps (design stage 1).

A spell's ``effects`` array is an ordered list of typed steps, translated into a
block program and run by the block evaluator (``src/spells/``). Historically the only
validation was "does it parse as JSON" — an unknown step type, a typo'd field,
a bad enum, or a ``context.X`` reference to a key nothing writes all failed
silently (a warning-and-skip at run time, or a no-op) rather than at authoring
time.

This module makes the step vocabulary a **contract**:

* :data:`STEP_SCHEMAS` declares, for every step type the pipeline dispatches,
  its required/optional fields, each field's value domain, and the context keys
  it reads and writes. It is the single source of truth the linter checks
  against and the authoring guide is generated from.
* :func:`lint_effects` validates an ``effects`` list and returns a list of
  human-readable problems (empty when clean).
* :func:`validate_effects` raises :class:`ValueError` if there are any problems
  — this is what the loader calls at the boundary so bad content fails loudly.

Design intent and the decisions behind this live in
``docs/SPELL_SYSTEM_DESIGN.md`` (§6.9, §7 stage 1). This validates the *current*
``effects`` shape; it deliberately keeps every shipped spell (the conformance
corpus) passing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.models.damage import DamageType
from src.models.condition import ConditionType

# Mirrors src.loaders.stat_block_loader._FORMULA_RE — a dice formula is one or
# more terms (NdM or a flat integer) joined by + / -, e.g. "3d6", "2d6+1d8+5",
# "1d20-2", or "20". Kept in sync deliberately (see that module's comment).
_FORMULA_RE = re.compile(r"^[+-]?\d+(?:d\d+)?(?:[+-]\d+(?:d\d+)?)*$")

_ABILITIES = (
    "strength", "dexterity", "constitution",
    "intelligence", "wisdom", "charisma",
)

# The keys the block engine seeds into its per-invocation context. A ``context.X``
# reference in any expression must name one of these; anything else is a typo.
# Keep in sync with ``src.spells.context.seed_context``.
CONTEXT_KEYS = frozenset({
    "hit", "critical_hit", "critical_miss",
    "save_success", "save_roll", "save_dc",
    "attack_roll", "attack_total",
    "damage_dealt", "damage_rolled",
    "healing_amount", "temp_hp_granted",
    "slot_level",
})


# ---------------------------------------------------------------------------
# Field / step schema types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    """One field on a step type.

    kind drives validation:
      - "int"            : an integer
      - "bool"           : a boolean
      - "str"            : any string
      - "expr"           : an expression string (scanned for context.X refs)
      - "formula"        : a dice-formula string (validated against _FORMULA_RE)
      - "formula_or_int" : a formula string or an integer
      - "int_or_keyword" : an integer or the exact ``keyword`` string
      - "enum"           : a case-insensitive member name of ``enum``
      - "choice"         : one of ``choices``
      - "target"         : one of "caster" / "defender"
      - "object"         : a nested dict (optionally validated by ``subfields``)
      - "list"           : a list (elements not deep-linted at stage 1)
      - "any"            : accepted as-is
    """
    name: str
    required: bool = False
    kind: str = "any"
    enum: Optional[type] = None
    choices: Tuple[str, ...] = ()
    keyword: Optional[str] = None
    subfields: Tuple["Field", ...] = ()
    description: str = ""


@dataclass(frozen=True)
class StepSchema:
    """Contract for one step type."""
    type: str
    summary: str
    fields: Tuple[Field, ...]
    reads: Tuple[str, ...] = ()
    writes: Tuple[str, ...] = ()

    def field_map(self) -> Dict[str, Field]:
        return {f.name: f for f in self.fields}


# A ``condition`` (skip-guard expression) is accepted on every step type.
_CONDITION = Field("condition", kind="expr",
                   description="Expression; step is skipped if it evaluates falsy.")
# ``target`` appears on legacy content for several steps; it is honoured by some
# handlers (healing, grant_temporary_hp, apply_condition, add_modifier,
# add_entity_effect) and inert on others (attack_roll, damage, saving_throw —
# which always act on the current defender). Accepted everywhere to keep the
# corpus clean; the guide notes where it is meaningful.
_TARGET = Field("target", kind="target",
                description='"caster" or "defender".')


STEP_SCHEMAS: Dict[str, StepSchema] = {
    "attack_roll": StepSchema(
        type="attack_roll",
        summary="Emit ATTACK_DECLARED, roll a d20, and write the hit result.",
        fields=(
            Field("attack_bonus", kind="int_or_keyword", keyword="use_caster_bonus",
                  description="Flat bonus, or 'use_caster_bonus' for the caster's spell attack bonus."),
            _TARGET,
            _CONDITION,
        ),
        writes=("hit", "attack_roll", "attack_total",
                "critical_hit", "critical_miss"),
    ),
    "saving_throw": StepSchema(
        type="saving_throw",
        summary="Roll a saving throw for the defender and write the outcome.",
        fields=(
            Field("attribute", required=True, kind="choice", choices=_ABILITIES,
                  description="The saving-throw ability."),
            Field("dc", required=True, kind="int_or_keyword", keyword="use_caster_dc",
                  description="A DC integer, or 'use_caster_dc' for the caster's spell save DC."),
            _TARGET,
            _CONDITION,
        ),
        writes=("save_roll", "save_dc", "save_success"),
    ),
    "damage": StepSchema(
        type="damage",
        summary="Deal typed damage to the defender.",
        fields=(
            Field("damage_type", required=True, kind="enum", enum=DamageType,
                  description="Damage type."),
            Field("formula", required=True, kind="formula",
                  description="Dice formula, e.g. '8d6' or '2d6+1d8+5', or a flat integer string."),
            Field("requires_hit", kind="bool",
                  description="Skip this step when context.hit is False."),
            Field("roll_once", kind="bool",
                  description="Roll once and share the total across all AoE targets."),
            Field("save_result", kind="object",
                  subfields=(
                      Field("on_success", required=True, kind="choice",
                            choices=("half_damage", "no_damage"),
                            description="How a passed save reduces the damage."),
                  ),
                  description="Modify damage based on a preceding saving_throw."),
            Field("scaling", kind="object",
                  subfields=(
                      Field("per_slot_above", required=True, kind="int",
                            description="Threshold slot level; scaling adds dice per level above it."),
                      Field("add_dice", required=True, kind="formula",
                            description="Dice added per slot level above the threshold, e.g. '1d6'."),
                  ),
                  description="Upcasting: add dice as the spell is cast with a higher slot."),
            _TARGET,
            _CONDITION,
        ),
        reads=("hit", "save_success", "save_roll", "critical_hit", "slot_level"),
        writes=("damage_dealt", "damage_rolled"),
    ),
    "healing": StepSchema(
        type="healing",
        summary="Heal a target by an expression amount or a formula+bonus.",
        fields=(
            _TARGET,
            Field("amount", kind="expr",
                  description="Expression for a computed amount; takes precedence over formula."),
            Field("formula", kind="formula",
                  description="Dice formula rolled at cast time."),
            Field("bonus", kind="expr",
                  description="Added to the formula roll (int or expression)."),
            _CONDITION,
        ),
        writes=("healing_amount",),
    ),
    "add_entity_effect": StepSchema(
        type="add_entity_effect",
        summary="Apply a named entity effect from the rule registry.",
        fields=(
            Field("entity_effect_name", required=True, kind="str",
                  description="Name of the effect in rules/entity_effects/."),
            _TARGET,
            Field("on_caster", kind="bool",
                  description="Target the caster (equivalent to target='caster')."),
            Field("concentration", kind="bool",
                  description="Track as the caster's concentration; drops any prior one."),
            Field("instance_fields", kind="object",
                  description="Per-instance data; values are expressions evaluated at cast time."),
            Field("on_apply", kind="list",
                  description="Sub-actions dispatched to the rule-engine handler registry."),
            _CONDITION,
        ),
    ),
    "grant_temporary_hp": StepSchema(
        type="grant_temporary_hp",
        summary="Grant temporary hit points directly.",
        fields=(
            _TARGET,
            Field("amount", required=True, kind="expr",
                  description="Amount of temp HP (int or expression)."),
            _CONDITION,
        ),
        writes=("temp_hp_granted",),
    ),
    "apply_condition": StepSchema(
        type="apply_condition",
        summary="Apply a status condition via the rule engine.",
        fields=(
            Field("condition_type", required=True, kind="enum", enum=ConditionType,
                  description="The condition to apply."),
            _TARGET,
            Field("duration", kind="object",
                  description="Duration object (same shape as a spell duration)."),
            Field("source", kind="str", description="Human-readable source label."),
            Field("instance_fields", kind="object",
                  description="Per-instance data; values are expressions."),
            _CONDITION,
        ),
    ),
    "add_modifier": StepSchema(
        type="add_modifier",
        summary="Add a persistent stat modifier via the rule engine.",
        fields=(
            _TARGET,
            Field("stat", required=True, kind="str",
                  description="Stat to modify, e.g. 'ac' or 'saving_throw.wisdom'."),
            Field("value", required=True, kind="expr",
                  description="Modifier amount (int or expression)."),
            Field("source", kind="str", description="Human-readable source label."),
            Field("effect_name", kind="str",
                  description="Links the modifier to a named effect for removal."),
            _CONDITION,
        ),
    ),
}


# ---------------------------------------------------------------------------
# Expression context-reference extraction
# ---------------------------------------------------------------------------

def context_refs(expr: str) -> List[str]:
    """Return the attribute names referenced as ``context.<attr>`` in *expr*.

    Best-effort: a syntactically invalid expression yields no refs here (the
    field-level validators surface it separately). Only direct ``context.X``
    attribute access is extracted — that is where a typo'd context key hides.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    refs: List[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "context"
        ):
            refs.append(node.attr)
    return refs


# ---------------------------------------------------------------------------
# The linter
# ---------------------------------------------------------------------------

def _fmt(index: int, step_type: str, msg: str) -> str:
    return f"step {index} ({step_type}): {msg}"


def _check_value(f: Field, value: Any) -> Optional[str]:
    """Return an error message for *value* against field spec *f*, or None."""
    kind = f.kind

    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"field {f.name!r} must be an integer, got {value!r}"

    elif kind == "bool":
        if not isinstance(value, bool):
            return f"field {f.name!r} must be true/false, got {value!r}"

    elif kind == "str":
        if not isinstance(value, str):
            return f"field {f.name!r} must be a string, got {value!r}"

    elif kind == "formula":
        if not isinstance(value, str) or not _FORMULA_RE.match(value.replace(" ", "")):
            return f"field {f.name!r} is not a valid dice formula: {value!r}"

    elif kind == "formula_or_int":
        if isinstance(value, bool) or isinstance(value, int):
            pass
        elif isinstance(value, str) and _FORMULA_RE.match(value.replace(" ", "")):
            pass
        else:
            return f"field {f.name!r} must be a dice formula or integer, got {value!r}"

    elif kind == "int_or_keyword":
        if isinstance(value, bool):
            return f"field {f.name!r} must be an integer or {f.keyword!r}, got {value!r}"
        if isinstance(value, int):
            pass
        elif value == f.keyword:
            pass
        else:
            return f"field {f.name!r} must be an integer or {f.keyword!r}, got {value!r}"

    elif kind == "enum":
        assert f.enum is not None
        try:
            f.enum[str(value).upper()]
        except KeyError:
            valid = ", ".join(m.name for m in f.enum)
            return f"field {f.name!r} has unknown value {value!r}; valid: {valid}"

    elif kind == "choice":
        if value not in f.choices:
            return (f"field {f.name!r} has unknown value {value!r}; "
                    f"valid: {', '.join(f.choices)}")

    elif kind == "target":
        if value not in ("caster", "defender"):
            return f"field {f.name!r} must be 'caster' or 'defender', got {value!r}"

    elif kind == "object":
        if not isinstance(value, dict):
            return f"field {f.name!r} must be an object, got {value!r}"

    elif kind == "list":
        if not isinstance(value, list):
            return f"field {f.name!r} must be a list, got {value!r}"

    # "expr" and "any" accept any scalar/shape here; expr refs are checked
    # separately for context.X typos.
    return None


def _check_subfields(f: Field, value: dict, index: int, step_type: str,
                     errors: List[str]) -> None:
    allowed = {sf.name for sf in f.subfields}
    if not allowed:
        return
    sub_map = {sf.name: sf for sf in f.subfields}
    for sf in f.subfields:
        if sf.required and sf.name not in value:
            errors.append(_fmt(index, step_type,
                               f"{f.name}.{sf.name} is required"))
    for key, val in value.items():
        sf = sub_map.get(key)
        if sf is None:
            errors.append(_fmt(index, step_type,
                               f"unknown field {f.name}.{key!r}; "
                               f"valid: {', '.join(sorted(allowed))}"))
            continue
        msg = _check_value(sf, val)
        if msg:
            errors.append(_fmt(index, step_type, f"{f.name}.{msg}"))


def lint_effects(effects: Any) -> List[str]:
    """Validate a pipeline ``effects`` list; return a list of problems (empty = clean)."""
    errors: List[str] = []

    if effects is None:
        return errors
    if not isinstance(effects, list):
        return [f"'effects' must be a list, got {type(effects).__name__}"]

    for i, step in enumerate(effects):
        if not isinstance(step, dict):
            errors.append(f"step {i}: must be an object, got {step!r}")
            continue

        step_type = step.get("type")
        if not step_type:
            errors.append(f"step {i}: missing 'type'; valid: {', '.join(sorted(STEP_SCHEMAS))}")
            continue

        schema = STEP_SCHEMAS.get(step_type)
        if schema is None:
            errors.append(
                f"step {i}: unknown step type {step_type!r}; "
                f"valid: {', '.join(sorted(STEP_SCHEMAS))}"
            )
            continue

        fmap = schema.field_map()

        # Required fields present?
        for fname, fspec in fmap.items():
            if fspec.required and fname not in step:
                errors.append(_fmt(i, step_type, f"missing required field {fname!r}"))

        # Each present field known + well-typed?
        for key, value in step.items():
            if key == "type":
                continue
            fspec = fmap.get(key)
            if fspec is None:
                valid = ", ".join(sorted(k for k in fmap))
                errors.append(_fmt(i, step_type,
                                   f"unknown field {key!r}; valid: {valid}"))
                continue
            msg = _check_value(fspec, value)
            if msg:
                errors.append(_fmt(i, step_type, msg))
                continue
            if fspec.kind == "object" and fspec.subfields and isinstance(value, dict):
                _check_subfields(fspec, value, i, step_type, errors)
            if fspec.kind == "expr" and isinstance(value, str):
                for ref in context_refs(value):
                    if ref not in CONTEXT_KEYS:
                        errors.append(_fmt(i, step_type,
                                           f"field {key!r} references unknown context key "
                                           f"'context.{ref}'; valid: "
                                           f"{', '.join(sorted(CONTEXT_KEYS))}"))

    return errors


def validate_effects(effects: Any, spell_name: str = "") -> None:
    """Raise :class:`ValueError` if *effects* has any lint problems.

    Called at the loader boundary so malformed spell content fails loudly with a
    message that names the spell and every problem found.
    """
    errors = lint_effects(effects)
    if errors:
        label = f" in spell {spell_name!r}" if spell_name else ""
        joined = "\n  - ".join(errors)
        raise ValueError(f"Invalid spell effects{label}:\n  - {joined}")


# ---------------------------------------------------------------------------
# Reference-doc generation (the schema is the single source of truth)
# ---------------------------------------------------------------------------

# Path of the generated step reference, relative to the repo root.
STEP_REFERENCE_PATH = "examples/spells/STEP_REFERENCE.md"

_GENERATED_HEADER = (
    "<!-- GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "     Regenerate with:  python -m src.rules.step_schema\n"
    "     Source of truth:  src/rules/step_schema.py (STEP_SCHEMAS).\n"
    "     A drift test (tests/test_step_reference_doc.py) fails if this is stale. -->\n"
)


def _render_type(f: Field) -> str:
    """Render a field's value domain for the reference table."""
    kind = f.kind
    if kind == "int_or_keyword":
        return f"int or `{f.keyword}`"
    if kind == "enum" and f.enum is not None:
        return "one of: " + ", ".join(f"`{m.name}`" for m in f.enum)
    if kind == "choice":
        return "one of: " + ", ".join(f"`{c}`" for c in f.choices)
    if kind == "target":
        return "`caster` / `defender`"
    return {
        "int": "int",
        "bool": "true / false",
        "str": "string",
        "expr": "expression",
        "formula": "dice formula",
        "formula_or_int": "dice formula or int",
        "object": "object",
        "list": "list",
        "any": "any",
    }.get(kind, kind)


def generate_step_reference() -> str:
    """Render the full per-step reference as Markdown from :data:`STEP_SCHEMAS`."""
    lines: List[str] = [_GENERATED_HEADER, "# Spell Pipeline Step Reference", ""]
    lines.append(
        "The authoritative list of pipeline step types and their fields, generated "
        "from the schema the loader validates against. Every context key an "
        "expression may read is listed under **Writes context** on the step that "
        "produces it."
    )
    lines.append("")
    lines.append("Step types: " + ", ".join(f"[`{t}`](#{t})" for t in STEP_SCHEMAS) + ".")
    lines.append("")

    for step_type, schema in STEP_SCHEMAS.items():
        lines.append(f"## `{step_type}`")
        lines.append("")
        lines.append(schema.summary)
        lines.append("")
        lines.append("| Field | Required | Type | Description |")
        lines.append("|---|---|---|---|")
        for f in schema.fields:
            req = "yes" if f.required else "no"
            desc = f.description or ""
            lines.append(f"| `{f.name}` | {req} | {_render_type(f)} | {desc} |")
            for sf in f.subfields:
                sreq = "yes" if sf.required else "no"
                lines.append(
                    f"| `{f.name}.{sf.name}` | {sreq} | {_render_type(sf)} | "
                    f"{sf.description or ''} |"
                )
        lines.append("")
        reads = ", ".join(f"`{k}`" for k in schema.reads) or "_(none)_"
        writes = ", ".join(f"`{k}`" for k in schema.writes) or "_(none)_"
        lines.append(f"**Reads context:** {reads}")
        lines.append("")
        lines.append(f"**Writes context:** {writes}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    from pathlib import Path

    out = Path(__file__).resolve().parents[2] / STEP_REFERENCE_PATH
    out.write_text(generate_step_reference(), encoding="utf-8")
    print(f"wrote {out}")
