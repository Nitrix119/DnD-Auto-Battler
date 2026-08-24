"""The block-based spell system (the rewrite).

A spell is a ``program``: an ordered, nestable list of typed **blocks** run by a
single evaluator over a per-invocation context. This package is the clean-slate
home for that system (see docs/SPELL_SYSTEM_BUILD_PLAN.md); the legacy flat
``EffectPipeline`` in ``src/combat`` stays untouched until it is retired.

Phase 1 foundations (this slice): the ``Block`` value type, the ``BlockContract``
(reads/writes/target arity), and the ``BlockRegistry`` that replaces the old
``if/elif`` dispatch and the second ``BUILTIN_EFFECTS`` vocabulary with one
catalogue.
"""

from .block import Block
from .contract import BlockContract, TargetArity
from .registry import BlockRegistry, RegisteredBlock, REGISTRY

__all__ = [
    "Block",
    "BlockContract",
    "TargetArity",
    "BlockRegistry",
    "RegisteredBlock",
    "REGISTRY",
]
