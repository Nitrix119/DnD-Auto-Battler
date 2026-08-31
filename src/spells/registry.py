"""The block registry — one catalogue, dict dispatch, no ``if/elif``.

This replaced the old ``EffectPipeline`` ``if/elif`` ladder (now deleted) — and
supersedes the separate ``BUILTIN_EFFECTS`` vocabulary — with one registry of block
types.
A block type is registered once with its handler and :class:`BlockContract`;
the evaluator dispatches by name and the linter validates against the same
contract.

The block *type* catalogue is process-global by design — it is code (the
language's vocabulary), immutable after import, and shared across all battles,
unlike per-battle spell content and mutable state. Tests may still construct an
isolated :class:`BlockRegistry` instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet

from .block import Block
from .contract import BlockContract

# Handler signature: (block, invocation) -> None. The invocation context type is
# introduced in the next slice (the evaluator); typed loosely here to avoid a
# forward dependency.
BlockHandler = Callable[[Block, Any], None]


@dataclass(frozen=True)
class RegisteredBlock:
    """A registered block type: its handler paired with its contract."""

    handler: BlockHandler
    contract: BlockContract


class BlockRegistry:
    """A catalogue of block types, dispatched by name."""

    def __init__(self) -> None:
        self._blocks: Dict[str, RegisteredBlock] = {}

    def register(
        self,
        type_name: str,
        handler: BlockHandler,
        contract: BlockContract,
    ) -> None:
        """Register a block type. Raises if the name is already registered."""
        if type_name in self._blocks:
            raise ValueError(f"block type {type_name!r} is already registered")
        self._blocks[type_name] = RegisteredBlock(handler, contract)

    def get(self, type_name: str) -> RegisteredBlock:
        """Look up a registered block. Raises KeyError naming valid types."""
        try:
            return self._blocks[type_name]
        except KeyError:
            raise KeyError(
                f"unknown block type {type_name!r}; "
                f"registered: {', '.join(sorted(self._blocks)) or '(none)'}"
            )

    def is_registered(self, type_name: str) -> bool:
        return type_name in self._blocks

    def types(self) -> FrozenSet[str]:
        return frozenset(self._blocks)


# The default, process-global catalogue that block modules register into.
REGISTRY = BlockRegistry()
