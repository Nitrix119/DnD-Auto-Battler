"""Block contracts — a block's fields, what it reads and writes, how it targets.

Every block type registers a :class:`BlockContract` alongside its handler. The
contract is the single source of truth used by (a) the validator, to reject a bad
program at load, (b) the evaluator, to know each block's shape, and (c) the
generated ``docs/BLOCK_REFERENCE.md``.

The :class:`Field` declarations are the per-arg half: they name every arg a block
accepts, its kind and domain, and whether it is required. Anything not declared is
rejected at load — an unknown arg is silently ignored at run time, which is the worst
outcome for an author (see CLAUDE.md §2.5). Because the declarations are hand-written
they are drift-guarded by ``tests/test_block_schema_drift.py``, which reads the
handlers' actual ``block.get(...)`` calls and compares the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Type


#: The closed set of field kinds. Keep it closed: a kind per block would be a second
#: vocabulary, which is the thing this engine exists to avoid.
KINDS = frozenset({
    "expr",      # an expression string, evaluated against the block's context
    "formula",   # a dice formula literal ("2d6+1", "20")
    "int",       # an integer literal
    "number",    # an int or float literal
    "str",       # a plain string literal
    "bool",      # a JSON boolean
    "enum",      # a member *name* of ``Field.enum``
    "choice",    # one of ``Field.choices``
    "object",    # a nested object shaped by ``Field.subfields``
    "list",      # a list of objects, each shaped by ``Field.subfields``
    "map_expr",  # an object whose values are expressions (``bindings``)
    "any",       # deliberately unconstrained
})


@dataclass(frozen=True)
class Field:
    """One argument a block accepts.

    Args:
        name: the JSON key.
        kind: one of :data:`KINDS` — how the value is validated.
        required: the load-time validator rejects a block that omits it.
        enum: the Enum class a ``kind="enum"`` value must name a member of.
        choices: the permitted values for ``kind="choice"``.
        sentinels: literal strings accepted *in place of* the kind — the odd
            special values the engine reads directly (``"use_caster_bonus"``,
            ``"caster"``), which would otherwise fail their own kind check.
        subfields: the shape of a ``kind="object"`` or ``kind="list"`` value.
        allow_expr: also accept an expression string. For the one genuinely hybrid
            arg, ``damage.damage_type``, which takes either a ``DamageType`` name or
            an expression yielding one (a rider dealing the weapon's own type).
        description: one line, for the generated reference.
    """

    name: str
    kind: str = "any"
    required: bool = False
    enum: Optional[Type[Enum]] = None
    choices: Tuple[str, ...] = ()
    sentinels: Tuple[str, ...] = ()
    subfields: Tuple["Field", ...] = ()
    allow_expr: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(
                f"field {self.name!r}: unknown kind {self.kind!r}; "
                f"valid: {', '.join(sorted(KINDS))}"
            )
        if self.kind == "enum" and self.enum is None:
            raise ValueError(f"field {self.name!r}: kind='enum' needs an enum class")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"field {self.name!r}: kind='choice' needs choices")
        if self.kind in ("object", "list") and not self.subfields:
            raise ValueError(f"field {self.name!r}: kind={self.kind!r} needs subfields")


class TargetArity(Enum):
    """How a block relates to the evaluator's *current target*.

    - ``SINGLE``: acts on the current target, which must be exactly one entity
      (``damage``, ``attack_roll``, ``saving_throw``, ``apply_condition``, …).
      Reaching a SINGLE block while the current target is a *set* is an error.
    - ``CASTER``: acts on the caster regardless of the current target
      (heal-self, grant-temp-HP-to-caster).
    - ``SET``: consumes a target set — iterator blocks (``for_each_target``) that
      rebind the current target per element for their ``then`` sub-program, or a
      rare aggregate that genuinely operates over the whole set.
    """

    SINGLE = "single"
    CASTER = "caster"
    SET = "set"


#: Args every block accepts, whatever its type. ``condition`` is read by
#: ``runner._condition_passes`` before dispatch, not by any handler — so it belongs
#: here rather than being repeated in all twenty contracts.
UNIVERSAL_FIELDS: Tuple[Field, ...] = (
    Field("condition", "expr",
          description="Expression; the block is skipped when it evaluates falsy."),
)


@dataclass(frozen=True)
class BlockContract:
    """The declared contract for one block type.

    Args:
        fields: every arg this block accepts (see :class:`Field`). An arg absent
            from here is rejected at load. ``required_args`` is derived from it, so
            requiredness has exactly one declaration site.
        reads: context keys the block may read (for the linter's flow check).
        writes: context keys the block writes.
        target_arity: how the block addresses targets (see :class:`TargetArity`).
        is_gate: True for pre-effect roll/gate blocks (``attack_roll``,
            ``saving_throw``). The evaluator emits ``SPELL_HIT`` just before the
            first non-gate block, matching the legacy pipeline's ordering.
        installs_reactions: True for blocks that subscribe handlers to future
            events (``lifetime``, ``trigger``). The evaluator flushes the pending
            ``DAMAGE_DEALT`` just before the first such block so a rider does not
            fire on its own cast's damage — matching where the legacy pipeline
            emitted ``DAMAGE_DEALT`` (before the first ``add_entity_effect``).
        mutates_event: True for **event-modifier** blocks (``modify_damage`` and
            its siblings) that reach back onto the in-flight ``CombatEvent`` via
            ``Invocation.live_event`` — resistance multipliers, advantage/critical
            flags, ``cancelled``. They are meaningful only when fired inside a
            ``trigger`` (which supplies the live event); run standalone they have
            nothing to mutate and no-op. The distinguishing mark of the one block
            category that changes a live event rather than writing forward state.
        consumes_then: True for the blocks that actually run a ``then`` sub-program
            (``for_each_target``, ``lifetime``, ``trigger``). On any other block a
            ``then`` is silently dead, so the validator rejects it.
    """

    fields: Tuple[Field, ...] = ()
    reads: Tuple[str, ...] = ()
    writes: Tuple[str, ...] = ()
    target_arity: TargetArity = TargetArity.SINGLE
    is_gate: bool = False
    installs_reactions: bool = False
    mutates_event: bool = False
    consumes_then: bool = False

    @property
    def required_args(self) -> Tuple[str, ...]:
        """Arg names that must be present — derived from ``fields``."""
        return tuple(f.name for f in self.fields if f.required)

    @property
    def field_names(self) -> Tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def field(self, name: str) -> Optional[Field]:
        for f in self.fields:
            if f.name == name:
                return f
        return None
