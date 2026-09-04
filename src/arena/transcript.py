"""Structured, replay-ready logging of a match.

A :class:`Transcript` is an ordered list of JSON records — the RNG seed, turn
boundaries, every action (the agent's :class:`~src.arena.tools.ToolCall` and the
result), and ground-truth state snapshots. It logs *everything useful* so metrics are
computed from the data rather than by re-running the agents (E2), and so a match can be
**replayed** deterministically from the seed and recorded outcomes (E5).

The records are plain dicts and serialize to JSONL (one record per line).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.arena.tools import ToolCall


@dataclass
class Transcript:
    """An append-only log of a single match.

    Attributes:
        seed: The RNG seed the match was run with (``None`` if unseeded).
        records: The ordered records; each carries an ``i`` index and a ``kind``.
    """

    seed: Optional[int] = None
    records: List[Dict[str, Any]] = field(default_factory=list)

    def log(self, kind: str, **data: Any) -> None:
        """Append one record of *kind* with arbitrary JSON-serializable *data*."""
        self.records.append({"i": len(self.records), "kind": kind, **data})

    def match_start(self, teams: Dict[Optional[str], List[str]], **meta: Any) -> None:
        self.log("match_start", seed=self.seed, teams=teams, **meta)

    def turn_start(self, entity_id: str, round_num: int, turn_num: int) -> None:
        self.log("turn_start", entity_id=entity_id, round=round_num, turn=turn_num)

    def action(self, actor_id: str, call: ToolCall, result: Dict[str, Any]) -> None:
        self.log(
            "action",
            actor_id=actor_id,
            call={"name": call.name, "arguments": call.arguments},
            result=result,
        )

    def turn_end(self, entity_id: str, state: Dict[str, Any]) -> None:
        self.log("turn_end", entity_id=entity_id, state=state)

    def match_end(self, winner: Optional[str], reason: str, rounds: int) -> None:
        self.log("match_end", winner=winner, reason=reason, rounds=rounds)

    def records_of(self, kind: str) -> List[Dict[str, Any]]:
        """All records of a given *kind* (handy for tests and quick metrics)."""
        return [r for r in self.records if r["kind"] == kind]

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(r) for r in self.records)

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_jsonl(), encoding="utf-8")
