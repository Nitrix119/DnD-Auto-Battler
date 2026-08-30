"""The router's injection guard — shared by the spell and attack resolvers.

The block engine reproduces every reactive effect the legacy engine does **except**
one: a handler that mutates the *running* action's ``pipeline_effects`` mid-run
(Colossus Slayer's bonus die on ``ATTACK_HIT``, via ``InjectPipelineDamageStep``).
That injection depends on the legacy ``EffectPipeline``'s drain loop, which the
block engine has no equivalent for. So a cast/attack by an entity carrying such an
effect stays on the legacy engine; everything else rides the EventBus identically on
both engines and can run on either.

This is transitional: once Colossus becomes an ``ATTACK_HIT`` trigger on the block
engine (Phase 3), the injection disappears and this guard — and the whole legacy
pipeline — can be deleted.
"""

from __future__ import annotations

from src.models.entity import Entity

# Effect actions the new engine can't reproduce: they mutate the running attack's
# step list. Everything else an active effect does rides the EventBus.
_INJECTION_ACTIONS = frozenset({"InjectPipelineDamageStep", "AddDamageToAttackHit"})


def caster_has_injection_effect(caster: Entity) -> bool:
    """True when *caster* carries a pipeline-injecting reactive effect.

    The single condition that keeps a cast or weapon attack on the legacy engine.
    """
    for bucket in caster.active_effects.values():
        for instance in bucket:
            rule = getattr(instance, "rule", None)
            effects = getattr(rule, "effects", None) or []
            if any(e.get("action") in _INJECTION_ACTIONS for e in effects):
                return True
    return False
