"""Build an agent's view of the battle — its sensory input for one turn.

``build_observation`` produces a plain ``dict`` (JSON-serializable) from *one entity's*
point of view: itself and its allies in full, each enemy filtered through the
:class:`~src.arena.information_policy.InformationPolicy`, the battle's round/turn state, and
the entity's legal-action menu (:func:`~src.arena.action_space.legal_actions`).

Positions are reported in **backend feet** ``(x, y, z)`` — the engine's own coordinates — so
the observation is honest to the model the engine runs. The web layer's cell-coordinate swap
is a presentation concern that a future web spectator bridge applies; it does not belong in
the agent's view.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

from src.arena.action_space import legal_actions
from src.arena.information_policy import (
    FULL_INFORMATION,
    HP_EXACT,
    InformationPolicy,
    bucket_hp,
)
from src.models.entity import Entity

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem


def _position(entity: Entity) -> dict:
    return {"x": entity.x, "y": entity.y, "z": entity.z}


def _resources(entity: Entity) -> dict:
    r = entity.resources
    return {
        "actions": r.actions,
        "bonus_actions": r.bonus_actions,
        "reactions": r.reactions,
        "movement": r.movement,
    }


def _spell_slots(entity: Entity) -> Optional[dict]:
    if entity.spell_slots is None:
        return None
    return {
        str(level): remaining
        for level, remaining in entity.spell_slots.remaining.items()
    }


def _conditions(entity: Entity) -> list:
    return [c.condition_type.value for c in entity.conditions]


def _serialize_ally(entity: Entity) -> Dict[str, Any]:
    """Full view of a friendly entity (self or ally) — nothing is hidden."""
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "team": entity.team,
        "position": _position(entity),
        "alive": entity.is_alive(),
        "hp": entity.current_hp,
        "max_hp": entity.max_hp,
        "temp_hp": entity.temporary_hp,
        "ac": entity.ac,
        "conditions": _conditions(entity),
        "resources": _resources(entity),
        "spell_slots": _spell_slots(entity),
    }


def _serialize_enemy(entity: Entity, policy: InformationPolicy) -> Dict[str, Any]:
    """View of an enemy, with fields hidden or coarsened per *policy*.

    Identity, team, position, and liveness are always shown — the battlefield is
    shared and the engine needs positions. Everything else is gated by the policy.
    """
    view: Dict[str, Any] = {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "team": entity.team,
        "position": _position(entity),
        "alive": entity.is_alive(),
    }

    if policy.shows_hp:
        if policy.hp_display == HP_EXACT:
            view["hp"] = entity.current_hp
            view["max_hp"] = entity.max_hp
            view["temp_hp"] = entity.temporary_hp
        else:  # bucketed
            view["hp_bucket"] = bucket_hp(entity.current_hp, entity.max_hp)

    if policy.reveal_enemy_ac:
        view["ac"] = entity.ac
    if policy.reveal_enemy_conditions:
        view["conditions"] = _conditions(entity)
    if policy.reveal_enemy_resources:
        view["resources"] = _resources(entity)
    if policy.reveal_enemy_spell_slots:
        view["spell_slots"] = _spell_slots(entity)

    return view


def build_observation(
    combat: "CombatSystem",
    entity: Entity,
    policy: InformationPolicy = FULL_INFORMATION,
) -> dict:
    """Return *entity*'s observation of *combat* as a JSON-serializable dict.

    Args:
        combat: The battle to observe.
        entity: The entity whose viewpoint this observation is from.
        policy: What this agent may learn about its enemies. Defaults to
            :data:`~src.arena.information_policy.FULL_INFORMATION`.

    The returned dict has: ``round``/``turn``/``state``/``is_my_turn``, ``self`` (full),
    ``allies`` (full), ``enemies`` (policy-filtered), and ``legal_actions`` (the menu of
    what *entity* may do now).
    """
    current = combat.get_current_entity()
    return {
        "state": combat.state.name,
        "round": combat.round,
        "turn": combat.turn,
        "is_my_turn": current is not None and current.entity_id == entity.entity_id,
        "self": _serialize_ally(entity),
        "allies": [_serialize_ally(a) for a in combat.get_allies(entity)],
        "enemies": [
            _serialize_enemy(e, policy) for e in combat.get_enemies(entity)
        ],
        "legal_actions": legal_actions(combat, entity).to_dict(),
    }
