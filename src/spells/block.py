"""The Block value type — one instruction in a spell program.

A block is an immutable value: a registered ``type``, its ``args`` (the remaining
fields), and an optional ``then`` sub-program (a tuple of child blocks) that
iterator and trigger blocks run. Programs nest only through ``then`` (decided:
one nesting mechanism — see the design doc §0 / build plan).

The program shape uses ``"block"`` as the type key::

    { "block": "damage", "damage_type": "FIRE", "formula": "8d6" }
    { "block": "for_each_target", "then": [ { "block": "damage", ... } ] }

Legacy ``effects`` step-dicts (which use ``"type"``) are converted to blocks by
the transitional adapter, not by this type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

_TYPE_KEY = "block"
_THEN_KEY = "then"


@dataclass(frozen=True)
class Block:
    """One instruction in a spell program (immutable)."""

    type: str
    args: Dict[str, Any] = field(default_factory=dict)
    then: Tuple["Block", ...] = ()

    @classmethod
    def from_dict(cls, data: Any) -> "Block":
        """Parse one block dict (recursively parsing its ``then`` sub-program).

        Raises:
            ValueError: if *data* is not an object or has no ``block`` type key.
        """
        if not isinstance(data, dict):
            raise ValueError(f"block must be an object, got {data!r}")
        btype = data.get(_TYPE_KEY)
        if not btype or not isinstance(btype, str):
            raise ValueError(
                f"block must have a string {_TYPE_KEY!r} field, got {data!r}"
            )
        raw_then = data.get(_THEN_KEY, [])
        if not isinstance(raw_then, list):
            raise ValueError(
                f"block {btype!r}: {_THEN_KEY!r} must be a list, got {raw_then!r}"
            )
        then = tuple(cls.from_dict(child) for child in raw_then)
        args = {
            k: v for k, v in data.items() if k not in (_TYPE_KEY, _THEN_KEY)
        }
        return cls(type=btype, args=args, then=then)

    def get(self, key: str, default: Any = None) -> Any:
        """Read one of the block's args."""
        return self.args.get(key, default)


def parse_program(program: Any) -> List[Block]:
    """Parse a ``program`` (a list of block dicts) into a list of Blocks."""
    if program is None:
        return []
    if not isinstance(program, list):
        raise ValueError(f"program must be a list of blocks, got {program!r}")
    return [Block.from_dict(b) for b in program]
