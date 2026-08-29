"""Per-invocation state for running a block program.

One :class:`Invocation` holds everything a single program run needs: the caster,
the current (single) target, the shared mutable ``context`` dict, the combat
collaborators, and the bookkeeping the result is derived from. Sub-programs
(an iterator per element, a trigger per firing) spawn a child via
:meth:`Invocation.child`, which reuses the caster/action/collaborators and gives
the child its own seeded context — so the collaborators are threaded in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.models.entity import Entity
from src.models.damage import Damage
from src.models.lifetime import LifetimeScope
from src.rules.expressions import build_context

if TYPE_CHECKING:
    from src.combat.event_bus import CombatEvent


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


@dataclass(frozen=True)
class CastEnv:
    """The constant cast environment — the collaborators for one whole cast.

    These never vary across a cast and all its child sub-runs (each iterator
    element, each trigger firing), so a child reuses its parent's ``CastEnv`` by
    reference rather than re-threading five arguments. Frozen because nothing
    should mutate the environment mid-cast; the per-run *state* lives on
    :class:`Invocation`, which holds a reference to one of these.
    """

    action: Any  # SpellAction-like: .name, .spell_level
    event_bus: Any
    damage_processor: Any
    rule_engine: Any = None
    slot_level: Optional[int] = None


@dataclass
class Invocation:
    """Mutable state for one run of a block program over one target.

    Holds a reference to the immutable :class:`CastEnv` (the collaborators) plus
    the per-run state that varies. Two roles:

    - A **per-target** invocation (the common case): ``target`` is the single
      current target and the run writes into ``context``. Iterator ``then`` bodies
      and the flat single-target path both use this.
    - A **root** invocation for a set-consuming program: ``targets`` holds the whole
      set an iterator (``for_each_target``) fans over, appending each element's
      :class:`InvocationResult` to ``results``. Its ``target`` is a placeholder
      (the caster) that no block reads — the arity lint guarantees only a
      set-consuming block runs at the root, and those read ``targets``, never
      ``target``.

    The collaborators are exposed as read-only properties delegating to ``env``,
    so ``inv.event_bus`` / ``inv.action`` / … keep working unchanged.
    """

    env: CastEnv
    caster: Entity
    target: Entity  # the current single target (caster placeholder at an iterator root)
    context: Dict[str, Any] = field(default_factory=dict)

    # -- Collaborators (delegated to the immutable environment) ----------------
    @property
    def action(self) -> Any:
        return self.env.action

    @property
    def event_bus(self) -> Any:
        return self.env.event_bus

    @property
    def damage_processor(self) -> Any:
        return self.env.damage_processor

    @property
    def rule_engine(self) -> Any:
        return self.env.rule_engine

    @property
    def slot_level(self) -> Optional[int]:
        return self.env.slot_level

    # The target *set* an iterator consumes, and the per-element results it
    # collects. Empty on a per-target invocation.
    targets: List[Entity] = field(default_factory=list)
    results: List["InvocationResult"] = field(default_factory=list)

    # The lifetime scope currently open (set by a `lifetime` block for its `then`
    # body): grants made under it register their revoke handle here so teardown
    # revokes exactly what the spell granted. None outside a lifetime — grants
    # are then instantaneous/permanent, as before.
    active_scope: Optional[LifetimeScope] = None

    # When a trigger fires, the data of the event that fired it — exposed as
    # ``event.<field>`` to the ``then`` body's expressions (e.g. a rider healing
    # for ``event.total // 2``). None during an ordinary cast.
    event_data: Optional[Dict[str, Any]] = None

    # The lifetime scope that owns the currently-firing trigger, so a rider can end
    # its own effect (an ``end_lifetime`` block disposes it — e.g. Armor of Agathys
    # ending when its temp HP is gone). None outside a trigger firing.
    owning_scope: Optional[LifetimeScope] = None

    # The **live** ``CombatEvent`` a trigger is firing on, so an event-modifier
    # block (``modify_damage`` and its siblings) can write back onto the in-flight
    # event the resolver is mid-way through emitting — resistance multipliers,
    # advantage/critical flags, ``cancelled``. This is the one handle that lets a
    # block reach a live event; ``event_data`` above is a *copy* for forward reads,
    # whereas this is the real object. None during an ordinary cast (an
    # event-modifier block run outside a trigger has nothing to mutate).
    live_event: Optional["CombatEvent"] = None

    # Bookkeeping the result is derived from.
    dealt_damages: List[Damage] = field(default_factory=list)
    healing_total: int = 0
    healed_entity: Optional[Entity] = None
    spell_hit_emitted: bool = False
    damage_dealt_emitted: bool = False

    def child(
        self,
        *,
        caster: Optional[Entity] = None,
        target: Optional[Entity] = None,
        event_data: Optional[Dict[str, Any]] = None,
        shared_rolls: Optional[Dict[int, int]] = None,
        live_event: Optional["CombatEvent"] = None,
    ) -> "Invocation":
        """A fresh invocation sharing this one's action/collaborators.

        The single place a sub-run is spawned — an iterator per element, a trigger
        per firing — so the combat collaborators are threaded in exactly one spot
        rather than re-passed at every call site. Gets its own seeded ``context``;
        ``caster``/``target`` default to this invocation's. A trigger overrides
        ``caster`` with the effect-**holder** so the rider's ``entity``/``caster``
        resolves to it (the holder, not necessarily the spell's caster), and passes
        ``live_event`` so an event-modifier block in the ``then`` body can write
        back onto the in-flight event.
        """
        inv = Invocation(
            env=self.env,
            caster=self.caster if caster is None else caster,
            target=self.target if target is None else target,
            context=seed_context(self.env.slot_level or 0),
            event_data=event_data,
            live_event=live_event,
        )
        if shared_rolls:
            inv.context["_shared_rolls"] = shared_rolls
        return inv


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
    def from_invocation(cls, inv: "Invocation") -> "InvocationResult":
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


def eval_context(inv: "Invocation") -> Dict[str, Any]:
    """Build the sandboxed namespace for a block's expression fields.

    Exposes ``event.caster`` / ``event.defender`` / ``event.action``, the pipeline
    ``context`` (public keys only, as a namespace), and ``save_success`` /
    ``save_roll`` — matching the legacy pipeline's expression namespace so
    expressions evaluate identically on both engines.
    """
    public = {k: v for k, v in inv.context.items() if not k.startswith("_")}
    # A fired trigger carries the real event's data; expose it as event.<field>,
    # keeping caster/defender/action as fallbacks so both cast and trigger
    # expressions resolve. During an ordinary cast event_data is None.
    event_data: Dict[str, Any] = dict(inv.event_data) if inv.event_data else {}
    event_data.setdefault("caster", inv.caster)
    event_data.setdefault("defender", inv.target)
    if inv.action is not None:
        event_data.setdefault("action", inv.action)
    return build_context(
        event_data,
        save_success=inv.context["save_success"],
        save_roll=inv.context["save_roll"],
        context=SimpleNamespace(**public),
        entity=inv.caster,
    )
