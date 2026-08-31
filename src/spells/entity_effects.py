"""Install a per-entity reactive rule (a creature feature) as block triggers.

The entity-effect sibling of :func:`src.spells.global_rules.install_global_rules`.
``RuleEngine.apply_effect`` routes a cleanly-foldable reactive rule here instead of
filing an ``EffectInstance`` in ``entity.active_effects`` for legacy dispatch: the
rule's ``triggers``/``effects`` fold to holder-scoped ``trigger`` blocks
(:func:`fold.rule_to_trigger_blocks`) subscribed on the shared event bus, with the
holder bound to the entity the effect is applied to. Colossus Slayer — a permanent
``ATTACK_HIT`` bonus-damage rider — is the first user (Phase 3 §2).

Eligibility is conservative, mirroring the global-rules install: every effect must
have a block translator. Anything with an untranslatable effect stays on the legacy
engine.

The installed triggers are owned by a :class:`LifetimeScope` on the entity (§3): a
``duration_rounds`` rule expires through ``Entity.tick_lifetimes`` on the holder's
turn, and ``RuleEngine.remove_effect`` / ``Entity.remove_effect`` disposes the scope
by name to tear the rider down. A rider with no duration is a permanent scope (never
auto-expires) that removal can still dispose — Colossus Slayer is such a rider.
"""

from __future__ import annotations

from typing import Any, Optional

from src.models.lifetime import LifetimeScope, LifetimeKind

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .block import parse_program
from .context import CastEnv, Invocation, seed_context
from .fold import rule_to_trigger_blocks
from .runner import run_program


def install_entity_effect(
    entity: Any,
    rule: Any,
    *,
    event_bus: Any,
    damage_processor: Optional[Any] = None,
    instance_fields: Optional[dict] = None,
) -> bool:
    """Install *rule* as holder-scoped block triggers on *entity*, owned by a scope.

    Returns ``True`` when the rule was installed on the block engine, ``False`` when
    it has an effect with no block translator (the caller then keeps it on the legacy
    path). The rider's holder is *entity*, so its ``entity``/``event.caster`` resolves
    to it; ``instance_fields`` ride each trigger as captured ``bindings``. The triggers
    are owned by a lifetime scope on ``entity.lifetimes`` keyed to ``rule.name``, so a
    ``duration_rounds`` rule expires on the holder's turn and ``remove_effect`` can
    dispose it by name.
    """
    try:
        blocks = rule_to_trigger_blocks(rule, holder="caster")
    except KeyError:
        # An effect action with no block translator — not foldable; stay on legacy.
        return False
    if not blocks:
        return False
    if instance_fields:
        for tb in blocks:
            tb["bindings"] = instance_fields
    program = parse_program(blocks)
    env = CastEnv(action=None, event_bus=event_bus, damage_processor=damage_processor)
    scope = LifetimeScope(
        kind=LifetimeKind.ROUNDS,
        source=getattr(rule, "name", "") or "",
        rounds_remaining=getattr(rule, "duration_rounds", None),
    )
    inv = Invocation(
        env=env,
        caster=entity,
        target=entity,
        context=seed_context(0),
    )
    inv.active_scope = scope  # the triggers register their unsubscribe into it
    run_program(program, inv)
    entity.lifetimes.append(scope)
    return True
