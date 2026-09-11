"""Structured, replay-ready logging of a match.

A :class:`Transcript` is an ordered list of JSON records — the RNG seed, turn
boundaries, every action (the agent's :class:`~src.arena.tools.ToolCall` and the
result), and ground-truth state snapshots. It logs *everything useful* so metrics are
computed from the data rather than by re-running the agents (E2), and so a match can be
**replayed** deterministically from the seed and recorded outcomes (E5).

The records are plain dicts and serialize to JSONL (one record per line).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.arena.tools import ToolCall

DEFAULT_MATCH_DIR = "matches"


def _slugify(label: str) -> str:
    """Reduce *label* to a filename-safe token (letters, digits, dot, dash, underscore)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-")


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

    def match_start(
        self,
        teams: Dict[Optional[str], List[str]],
        *,
        combatants: Optional[List[Dict[str, Any]]] = None,
        initial_state: Optional[Dict[str, Any]] = None,
        **meta: Any,
    ) -> None:
        """Log the opening record.

        ``combatants`` are static stat blocks (see
        :func:`~src.arena.observation.serialize_stat_block`) and ``initial_state`` is a
        pre-combat full snapshot (see :func:`~src.arena.observation.snapshot_state`).
        Both are optional so a bare match still logs; they let a replay start from an
        exact frame 0 and show every combatant's options. Absent keys are omitted, not
        logged as ``null``.
        """
        extra: Dict[str, Any] = {}
        if combatants is not None:
            extra["combatants"] = combatants
        if initial_state is not None:
            extra["initial_state"] = initial_state
        self.log("match_start", seed=self.seed, teams=teams, **extra, **meta)

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

    def save_auto(self, directory: str = DEFAULT_MATCH_DIR, label: str = "") -> Path:
        """Write the transcript under *directory* with a unique, sortable filename.

        Names are ``YYYYMMDD_HHMMSS_<label>_seed<seed>.jsonl`` (Windows-safe — no colons),
        so runs sort chronologically and never overwrite each other. A same-second collision
        gets a ``_2``/``_3`` suffix. Returns the path written. The directory is created if
        needed; ``matches/`` is git-ignored, so logs stay out of Git. Open any of them in the
        ``/playback`` page via its file picker.
        """
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        seed_part = f"seed{self.seed}" if self.seed is not None else "noseed"
        base = "_".join(p for p in (stamp, _slugify(label), seed_part) if p)

        path = target / f"{base}.jsonl"
        n = 2
        while path.exists():
            path = target / f"{base}_{n}.jsonl"
            n += 1

        self.save(str(path))
        return path
