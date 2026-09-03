"""The two-value target selector shared by every entity-acting block.

A block that acts on an entity (``damage``'s siblings: ``healing``, ``add_modifier``,
``apply_condition``, ``refill_resources``, …) chooses *which* entity with a single
``target`` arg holding one of two values:

- ``"self"`` — the block's **owner**: the invocation's caster, which for a spell is
  the caster and for a rider is the effect-holder.
- ``"current"`` — the **current target slot** (``inv.target``): the defender on a
  combat cast, or whatever an enclosing ``trigger`` rebound the slot to (e.g. a global
  rule's event entity). The default when ``target`` is omitted.

This is deliberately *not* an expression (unlike ``trigger.target``): retargeting to an
arbitrary entity is the enclosing ``trigger``'s job. The selector only picks between the
two entities an invocation already carries — so it reads honestly inside a global rule,
where there is no attacker/defender, only "the current slot".
"""

from __future__ import annotations

from src.models.entity import Entity

from ..contract import Field
from ..context import Invocation
from ..block import Block

#: The one declaration of the selector, shared by every block that accepts it, so the
#: schema, the validator, and the generated reference have a single source of truth.
TARGET_FIELD = Field(
    "target", "choice", choices=("self", "current"),
    description="'self' acts on the block's owner (caster/holder); "
                "'current' acts on the current target slot (the default).",
)


def select_target(block: Block, inv: Invocation) -> Entity:
    """Resolve the block's ``target`` selector to an entity (see module docstring)."""
    return inv.caster if block.get("target") == "self" else inv.target
