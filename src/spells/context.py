"""Per-invocation state for running a block program.

One :class:`Invocation` holds everything a single program run needs: the caster,
the current (single) target, the shared mutable ``context`` dict, the combat
collaborators, and the bookkeeping the result is derived from. Sub-programs
(iterators, triggers — later slices) get a child invocation with a rebound
target, keeping each run's context its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.entity import Entity
from src.models.damage import Damage


def seed_context(slot_level: int) -> Dict[str, Any]:
    """Return a fresh context dict with every key a block may read initialised.

    Mirrors the keys the legacy pipeline seeds (plus ``slot_level`` from stage 2),
    so a block never reads an uninitialised value and the two engines agree.
    """
    return {
        "hit": True,
        "critical_hit": False,
        "critical_miss": False,
        "attack_cancelled": False,
        "had_advantage": False,
        "had_disadvantage": False,
        "save_success": True,
        "save_roll": None,
        "save_dc": None,
        "attack_roll": None,
        "attack_total": None,
        "damage_dealt": 0,
        "damage_rolled": 0,
        "healing_amount": 0,
        "temp_hp_granted": 0,
        "slot_level": slot_level,
    }


@dataclass
class Invocation:
    """Mutable state for one run of a block program over one target."""

    caster: Entity
    target: Entity
    action: Any                      # SpellAction-like: .name, .spell_level
    event_bus: Any
    damage_processor: Any
    rule_engine: Any = None
    slot_level: Optional[int] = None
    context: Dict[str, Any] = field(default_factory=dict)

    # Bookkeeping the result is derived from.
    dealt_damages: List[Damage] = field(default_factory=list)
    healing_total: int = 0
    healed_entity: Optional[Entity] = None
    spell_hit_emitted: bool = False
    damage_dealt_emitted: bool = False


@dataclass
class InvocationResult:
    """Outcome of resolving a block program for one caster/target pair.

    Field-compatible with the legacy ``PipelineResult`` so the two can be
    compared directly by the parity harness.
    """

    hit: bool = True
    damage_dealt: int = 0
    healing_total: int = 0
    healed_entity: Optional[Entity] = None
    save_roll: Optional[int] = None
    save_dc: Optional[int] = None
    save_success: bool = True
    attack_roll: Optional[int] = None
    attack_total: Optional[int] = None
    critical_hit: bool = False
    critical_miss: bool = False
    attack_cancelled: bool = False
    had_advantage: bool = False
    had_disadvantage: bool = False

    @classmethod
    def from_invocation(cls, inv: Invocation) -> "InvocationResult":
        c = inv.context
        return cls(
            hit=c["hit"],
            damage_dealt=c["damage_dealt"],
            healing_total=inv.healing_total,
            healed_entity=inv.healed_entity,
            save_roll=c["save_roll"],
            save_dc=c["save_dc"],
            save_success=c["save_success"],
            attack_roll=c["attack_roll"],
            attack_total=c["attack_total"],
            critical_hit=c["critical_hit"],
            critical_miss=c["critical_miss"],
            attack_cancelled=c.get("attack_cancelled", False),
            had_advantage=c.get("had_advantage", False),
            had_disadvantage=c.get("had_disadvantage", False),
        )
